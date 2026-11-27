import json
import sqlite3

import pytest

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.agent_context import (
    load_live_context,
    propose_live_decision,
    AgentContextError
)

from backend.app.services.financial_prompt import (
    build_context_data
)

from backend.app.services.llm_decision import (
    DecisionError
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "agent_context.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:

            original.backup(copia)

        finally:

            copia.close()

    return ruta


def obtener_referencia(db):

    with read_connection(db) as conexion:

        fila = conexion.execute("""
            SELECT p.*, c.close AS reference_close
            FROM predictions p
            JOIN candles c
                ON c.id = p.candle_id
            ORDER BY c.open_time DESC
            LIMIT 1
        """).fetchone()

        return dict(fila)


def reloj(db):

    return obtener_referencia(db)["created_at"]


def test_contexto_real(db):

    prediccion = obtener_referencia(db)

    contexto, metadata = load_live_context(
        db,
        clock=lambda: reloj(db)
    )

    assert contexto.symbol == "BTCUSDT"

    assert contexto.mode == "PAPER_LIVE"

    assert len(contexto.returns_20) == 20

    assert metadata["historical_closes_used"] == 40

    assert metadata["prediction_id"] == prediccion["id"]

    assert contexto.predicted_return == (
        prediccion["predicted_return"]
    )

    assert contexto.reference_close == (
        prediccion["reference_close"]
    )

    datos = build_context_data(contexto)

    assert datos["real_trading"] is False

    assert datos["portfolio"]["status"] == "PAUSED"

    assert datos["market"][
        "execution_quote_available"
    ] is False


def test_prediccion_ausente(db):

    now = reloj(db)

    with write_transaction(db) as conexion:

        conexion.execute("""
            DELETE FROM predictions
        """)

    with pytest.raises(AgentContextError):

        load_live_context(
            db,
            clock=lambda: now
        )


@pytest.mark.parametrize("instante", [
    "antes_generacion",
    "objetivo_vencido"
])
def test_control_temporal(db, instante):

    prediccion = obtener_referencia(db)

    if instante == "antes_generacion":

        now = prediccion["created_at"] - 1

    else:

        now = prediccion["target_close_time"]

    with pytest.raises(AgentContextError):

        load_live_context(
            db,
            clock=lambda: now
        )


def test_historial_discontinuo(db):

    now = reloj(db)

    with write_transaction(db) as conexion:

        fila = conexion.execute("""
            SELECT id
            FROM candles
            ORDER BY open_time DESC
            LIMIT 1 OFFSET 10
        """).fetchone()

        conexion.execute("""
            DELETE FROM candles
            WHERE id = ?
        """, (fila["id"],))

    with pytest.raises(AgentContextError):

        load_live_context(
            db,
            clock=lambda: now
        )


def test_precio_inconsistente(db):

    now = reloj(db)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE predictions
            SET predicted_price = predicted_price + 100
        """)

    with pytest.raises(AgentContextError):

        load_live_context(
            db,
            clock=lambda: now
        )


def test_modelo_incompatible(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE model_versions
            SET model_sha256 = ?
        """, ("0" * 64,))

    with pytest.raises(AgentContextError):

        load_live_context(
            db,
            clock=lambda: reloj(db)
        )


class FakeClient:

    def __init__(self, candle_date, action):

        self.candle_date = candle_date

        self.action = action

    def chat(self, messages, schema):

        assert len(messages) == 2

        return {
            "content": json.dumps({
                "action": self.action,
                "symbol": "BTCUSDT",
                "candle_date": self.candle_date,
                "rationale": "Prueba controlada."
            }),
            "model": MODEL,
            "digest": MODEL_DIGEST,
            "ollama_version": OLLAMA_VERSION,
            "latency_ms": 100.0,
            "prompt_tokens": 500,
            "output_tokens": 35
        }


def test_integracion_hold(db):

    contexto, _ = load_live_context(
        db,
        clock=lambda: reloj(db)
    )

    cliente = FakeClient(
        contexto.candle_date.isoformat(),
        "HOLD"
    )

    resultado = propose_live_decision(
        cliente,
        db,
        clock=lambda: reloj(db)
    )

    assert resultado["llm_result"][
        "decision"
    ]["action"] == "HOLD"

    assert resultado["risk_evaluation_pending"]

    assert resultado["executed"] is False

    assert resultado["real_trading"] is False


def test_compra_invalida_bloqueada(db):

    contexto, _ = load_live_context(
        db,
        clock=lambda: reloj(db)
    )

    cliente = FakeClient(
        contexto.candle_date.isoformat(),
        "BUY"
    )

    with pytest.raises(DecisionError) as error:

        propose_live_decision(
            cliente,
            db,
            clock=lambda: reloj(db)
        )

    assert error.value.code == "PORTFOLIO_NOT_ACTIVE"


def test_base_datos_intacta(db):

    with read_connection(db) as conexion:

        antes = list(conexion.iterdump())

    contexto, _ = load_live_context(
        db,
        clock=lambda: reloj(db)
    )

    cliente = FakeClient(
        contexto.candle_date.isoformat(),
        "HOLD"
    )

    propose_live_decision(
        cliente,
        db,
        clock=lambda: reloj(db)
    )

    with read_connection(db) as conexion:

        despues = list(conexion.iterdump())

    assert antes == despues
