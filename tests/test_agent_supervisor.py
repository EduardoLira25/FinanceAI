import sqlite3

import pytest

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services import agent_supervisor

from backend.app.services.agent_supervisor import (
    run_guarded,
    recovery_status,
    resume_after_review,
    supervisor_lock_path,
    RecoveryError,
    SupervisorPersistenceError
)

from backend.app.services.agent_cycle import cycle_lock

from backend.app.services.mexc import MarketDataError

from backend.app.services.prediction import PredictionError

from backend.app.services.ollama_client import OllamaError

from backend.app.services.llm_decision import (
    DecisionError,
    database_hash,
    model_hashes
)

from backend.app.services.market_quote import QuoteError

from backend.app.services.agent_risk import AgentRiskError


@pytest.fixture(scope="module", autouse=True)
def proteger_originales():

    db_antes = database_hash()

    modelo_antes = model_hashes()

    yield

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "supervisor.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:

            original.backup(copia)

        finally:

            copia.close()

    with write_transaction(ruta) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET status = 'ACTIVE'
            WHERE name = 'FinanceAI_Paper'
        """)

    return ruta


def runner_fallido(error):

    def ejecutar(*args, **kwargs):

        raise error

    return ejecutar


def fallar(db):

    return run_guarded(
        None,
        path=db,
        runner=runner_fallido(
            MarketDataError("MEXC no responde.")
        )
    )


@pytest.mark.parametrize("error, codigo", [
    (
        MarketDataError("MEXC no responde."),
        "MARKET_DATA_ERROR"
    ),
    (
        MarketDataError("Limite de solicitudes MEXC."),
        "MARKET_RATE_LIMIT"
    ),
    (
        QuoteError("STALE_QUOTE", "Cotizacion antigua."),
        "STALE_QUOTE"
    ),
    (
        OllamaError("OLLAMA_UNAVAILABLE", "Ollama detenido."),
        "OLLAMA_UNAVAILABLE"
    ),
    (
        DecisionError("INVALID_DECISION_JSON", "JSON invalido."),
        "INVALID_DECISION_JSON"
    ),
    (
        AgentRiskError("CONTEXT_CHANGED", "Contexto diferente."),
        "CONTEXT_CHANGED"
    ),
    (
        PredictionError("Prediccion invalida."),
        "PREDICTION_ERROR"
    ),
    (
        RuntimeError("Error inesperado controlado."),
        "UNEXPECTED_ERROR"
    )
])
def test_clasificacion_y_pausa(db, error, codigo):

    resultado = run_guarded(
        None,
        path=db,
        runner=runner_fallido(error)
    )

    assert resultado["status"] == "PAUSED_ERROR"

    assert resultado["error_code"] == codigo

    assert resultado["automatic_retry"] is False

    estado = recovery_status(db)

    assert estado["portfolio_status"] == "PAUSED"

    assert estado["recovery_required"]

    assert len(estado["pending_incidents"]) == 1

    with read_connection(db) as conexion:

        assert conexion.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_fallo_real_del_orquestador(db):

    def sincronizar(path):

        raise MarketDataError(
            "MEXC no responde."
        )

    resultado = run_guarded(
        None,
        path=db,
        sync_fn=sincronizar
    )

    assert resultado["status"] == "PAUSED_ERROR"


def test_reinicio_sin_duplicar_incidentes(db):

    primero = fallar(db)

    segundo = run_guarded(
        None,
        path=db
    )

    assert segundo["status"] == "RECOVERY_REQUIRED"

    assert segundo["pending_incident_ids"] == [
        primero["incident_id"]
    ]

    assert len(
        recovery_status(db)["pending_incidents"]
    ) == 1


def test_recuperacion_manual(db):

    incidente = fallar(db)

    resultado = resume_after_review(
        [incidente["incident_id"]],
        "Incidente revisado.",
        path=db
    )

    assert resultado["status"] == "ACTIVE"

    assert resultado["execution_started"] is False

    assert recovery_status(db)[
        "recovery_required"
    ] is False


def test_confirmacion_incorrecta(db):

    incidente = fallar(db)

    with pytest.raises(RecoveryError):

        resume_after_review(
            [incidente["incident_id"] + 1],
            "Revision incorrecta.",
            path=db
        )

    assert recovery_status(db)[
        "portfolio_status"
    ] == "PAUSED"


@pytest.mark.parametrize("bloqueo", [
    "STOPPED",
    "EMERGENCY_STOP"
])
def test_recuperacion_bloqueada(db, bloqueo):

    incidente = fallar(db)

    with write_transaction(db) as conexion:

        if bloqueo == "STOPPED":

            conexion.execute("""
                UPDATE portfolio
                SET status = 'STOPPED'
            """)

        else:

            conexion.execute("""
                UPDATE risk_config
                SET emergency_stop = 1
            """)

    with pytest.raises(RecoveryError):

        resume_after_review(
            [incidente["incident_id"]],
            "Intento de recuperacion.",
            path=db
        )


def test_ciclo_incompleto_bloquea_recuperacion(db):

    incidente = fallar(db)

    with write_transaction(db) as conexion:

        cartera = conexion.execute("""
            SELECT id
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()

        prediccion = conexion.execute("""
            SELECT id, candle_id
            FROM predictions
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        riesgo = conexion.execute("""
            SELECT id
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        conexion.execute("""
            INSERT INTO agent_cycles (
                portfolio_id,
                candle_id,
                prediction_id,
                risk_config_id,
                status
            )
            VALUES (?, ?, ?, ?, 'RUNNING')
        """, (
            cartera["id"],
            prediccion["candle_id"],
            prediccion["id"],
            riesgo["id"]
        ))

    with pytest.raises(RecoveryError):

        resume_after_review(
            [incidente["incident_id"]],
            "Revision controlada.",
            path=db
        )


def test_otro_incidente_sin_resolver(db):

    incidente = fallar(db)

    with write_transaction(db) as conexion:

        conexion.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES (
                'MEXC',
                'TEST_ERROR',
                'Incidente adicional.'
            )
        """)

    with pytest.raises(RecoveryError):

        resume_after_review(
            [incidente["incident_id"]],
            "Revision controlada.",
            path=db
        )


def test_supervisores_simultaneos(db):

    with cycle_lock(
        supervisor_lock_path(db)
    ) as adquirido:

        assert adquirido

        resultado = run_guarded(
            None,
            path=db
        )

    assert resultado["status"] == "SUPERVISOR_BUSY"


def test_fallo_de_persistencia(db, monkeypatch):

    def persistencia_fallida(*args, **kwargs):

        raise sqlite3.OperationalError(
            "Fallo controlado de SQLite."
        )

    monkeypatch.setattr(
        agent_supervisor,
        "write_transaction",
        persistencia_fallida
    )

    with pytest.raises(SupervisorPersistenceError):

        run_guarded(
            None,
            path=db
        )


def test_resultado_normal_no_genera_incidente(db):

    def normal(*args, **kwargs):

        return {
            "status": "WAITING_NEXT_CANDLE",
            "executed": False
        }

    resultado = run_guarded(
        None,
        path=db,
        runner=normal
    )

    assert resultado["status"] == "WAITING_NEXT_CANDLE"

    assert recovery_status(db)[
        "pending_incidents"
    ] == []


def test_activacion_sin_resolver_incidentes(db):

    fallar(db)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET status = 'ACTIVE'
        """)

    resultado = run_guarded(
        None,
        path=db
    )

    assert resultado["status"] == "RECOVERY_REQUIRED"

    assert recovery_status(db)[
        "portfolio_status"
    ] == "PAUSED"
