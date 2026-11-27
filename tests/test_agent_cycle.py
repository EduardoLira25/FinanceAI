import json
import sqlite3

import pytest

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.agent_cycle import (
    run_once,
    cycle_lock,
    finalize_previous_valuation,
    AgentCycleError
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION,
    OllamaError
)

from backend.app.services.market_quote import (
    MarketQuote,
    QuoteError
)

from backend.app.services.risk import (
    DAY,
    MICROS
)

from backend.app.services.prediction import (
    generate_prediction
)

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)


@pytest.fixture(scope="module", autouse=True)
def proteger_originales():

    db_antes = database_hash()

    modelo_antes = model_hashes()

    yield

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes


@pytest.fixture
def escenario(tmp_path):

    ruta = tmp_path / "cycle.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:

            original.backup(copia)

        finally:

            copia.close()

    with write_transaction(ruta) as conexion:

        prediccion = conexion.execute("""
            SELECT *
            FROM predictions
            ORDER BY target_open_time DESC
            LIMIT 1
        """).fetchone()

        cierre = prediccion["target_open_time"]

        conexion.execute("""
            UPDATE predictions
            SET created_at = ?
            WHERE id = ?
        """, (
            cierre + 1,
            prediccion["id"]
        ))

        conexion.execute("""
            UPDATE portfolio
            SET status = 'ACTIVE'
            WHERE name = 'FinanceAI_Paper'
        """)

    return ruta, cierre + 100


class FakeClient:

    def __init__(self, action, llamadas):

        self.action = action

        self.llamadas = llamadas

    def chat(self, messages, schema):

        self.llamadas.append("LLM")

        contexto = json.loads(
            messages[1]["content"].split(
                "\n\n", 1
            )[1]
        )

        return {
            "content": json.dumps({
                "action": self.action,
                "symbol": "BTCUSDT",
                "candle_date": contexto["candle_date"],
                "rationale": "Prueba integrada."
            }),
            "model": MODEL,
            "digest": MODEL_DIGEST,
            "ollama_version": OLLAMA_VERSION,
            "latency_ms": 100.0,
            "prompt_tokens": 500,
            "output_tokens": 30
        }


def ejecutar(
    escenario,
    action="BUY",
    llamadas=None,
    now=None,
    cliente=None,
    quote_fn=None
):

    db, instante = escenario

    if now is None:

        now = instante

    if llamadas is None:

        llamadas = []

    def sincronizar(path):

        llamadas.append("MEXC")

        return {
            "status": "ok",
            "new_candles": 0
        }

    def predecir(path, clock):

        llamadas.append("LSTM")

        return generate_prediction(
            path,
            clock=clock
        )

    def cotizar():

        llamadas.append("QUOTE")

        return MarketQuote(
            symbol="BTCUSDT",
            price_micros=50000 * MICROS,
            trade_time_ms=now * 1000 - 500,
            server_time_ms=now * 1000,
            received_at_ms=now * 1000,
            latency_ms=100.0
        )

    return run_once(
        cliente or FakeClient(
            action,
            llamadas
        ),
        path=db,
        clock=lambda: now,
        sync_fn=sincronizar,
        prediction_fn=predecir,
        quote_fn=quote_fn or cotizar
    )


def contar(db, tabla):

    with read_connection(db) as conexion:

        return conexion.execute(
            f"SELECT COUNT(*) FROM {tabla}"
        ).fetchone()[0]


def test_ciclo_completo(escenario):

    db, _ = escenario

    llamadas = []

    resultado = ejecutar(
        escenario,
        llamadas=llamadas
    )

    assert llamadas == [
        "MEXC", "LSTM", "LLM", "QUOTE"
    ]

    assert resultado["status"] == "COMPLETED"

    assert resultado["executed"]

    assert resultado["cycle"]["order_side"] == "BUY"

    assert resultado["cycle"]["cash_micros"] == (
        37500 * MICROS
    )

    assert contar(db, "orders") == 1


@pytest.mark.parametrize("estado", [
    "PAUSED", "STOPPED"
])
def test_cartera_inactiva(escenario, estado):

    db, _ = escenario

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET status = ?
        """, (estado,))

    llamadas = []

    resultado = ejecutar(
        escenario,
        llamadas=llamadas
    )

    assert resultado["status"] == estado

    assert llamadas == []

    assert contar(db, "orders") == 0


def test_paro_emergencia(escenario):

    db, _ = escenario

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET emergency_stop = 1
        """)

    llamadas = []

    resultado = ejecutar(
        escenario,
        llamadas=llamadas
    )

    assert resultado["status"] == "EMERGENCY_STOP"

    assert llamadas == []

    assert contar(db, "orders") == 0


def test_duplicados(escenario):

    db, _ = escenario

    primero = ejecutar(escenario)

    llamadas = []

    segundo = ejecutar(
        escenario,
        llamadas=llamadas
    )

    assert llamadas == ["MEXC"]

    assert segundo["status"] == (
        "WAITING_NEXT_CANDLE"
    )

    assert segundo["executed"] is False

    assert primero["cycle"]["order_id"] == (
        segundo["cycle"]["order_id"]
    )

    assert contar(db, "orders") == 1

    assert contar(db, "agent_cycles") == 1


def test_ciclo_simultaneo_bloqueado(escenario):

    db, _ = escenario

    llamadas = []

    with cycle_lock(db) as adquirido:

        assert adquirido

        resultado = ejecutar(
            escenario,
            llamadas=llamadas
        )

    assert resultado["status"] == (
        "CYCLE_ALREADY_RUNNING"
    )

    assert llamadas == []


def test_datos_antiguos_hold(escenario):

    db, now = escenario

    resultado = ejecutar(
        escenario,
        action="HOLD",
        now=now + 4000
    )

    assert resultado["status"] == "COMPLETED"

    assert resultado["executed"] is False

    assert contar(db, "orders") == 0

    assert contar(db, "agent_decisions") == 1


def test_error_ollama_no_ejecuta(escenario):

    db, _ = escenario

    class ClienteFallido:

        def chat(self, messages, schema):

            raise OllamaError(
                "OLLAMA_UNAVAILABLE",
                "Prueba de servidor detenido."
            )

    with pytest.raises(OllamaError):

        ejecutar(
            escenario,
            cliente=ClienteFallido()
        )

    assert contar(db, "orders") == 0

    assert contar(db, "agent_cycles") == 0


def test_error_cotizacion_no_ejecuta(escenario):

    db, _ = escenario

    def fallar():

        raise QuoteError(
            "QUOTE_UNAVAILABLE",
            "Prueba de fallo de mercado."
        )

    with pytest.raises(QuoteError):

        ejecutar(
            escenario,
            quote_fn=fallar
        )

    assert contar(db, "orders") == 0

    assert contar(db, "agent_cycles") == 0


def preparar_cierre(escenario):

    db, now = escenario

    ejecutar(escenario)

    with write_transaction(db) as conexion:

        prediccion = conexion.execute("""
            SELECT p.*, c.asset_id
            FROM predictions p
            JOIN candles c
                ON c.id = p.candle_id
            ORDER BY p.target_open_time DESC
            LIMIT 1
        """).fetchone()

        t = prediccion["target_open_time"]

        conexion.execute("""
            INSERT INTO candles (
                asset_id,
                interval_seconds,
                open_time,
                close_time,
                open,
                high,
                low,
                close,
                volume,
                quote_volume,
                source
            )
            VALUES (
                ?, 86400, ?, ?,
                50000, 55000, 49000, 55000,
                100, 5000000, 'TEST'
            )
        """, (
            prediccion["asset_id"],
            t,
            t + DAY
        ))

    return db, t + DAY


def test_valoracion_diaria(escenario):

    db, cierre = preparar_cierre(escenario)

    # No utilizar la vela antes de que cierre.

    assert finalize_previous_valuation(
        db,
        clock=lambda: cierre - 1
    ) is False

    assert finalize_previous_valuation(
        db,
        clock=lambda: cierre
    ) is True

    # No duplicar valoraciones.

    assert finalize_previous_valuation(
        db,
        clock=lambda: cierre + 1
    ) is False

    with read_connection(db) as conexion:

        fila = conexion.execute("""
            SELECT *
            FROM equity_history
            WHERE snapshot_type = 'VALUATION'
        """).fetchone()

        assert fila["equity_micros"] == (
            51250 * MICROS
        )

        assert fila["recorded_at"] == cierre

    assert contar(db, "equity_history") == 2


def test_valoracion_saldo_inconsistente(escenario):

    db, cierre = preparar_cierre(escenario)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET cash_micros = cash_micros + 1000000
        """)

    with pytest.raises(AgentCycleError):

        finalize_previous_valuation(
            db,
            clock=lambda: cierre
        )

    assert contar(db, "equity_history") == 1
