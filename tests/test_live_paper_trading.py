import json
import sqlite3

from dataclasses import replace

import pytest

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services import live_paper_trading

from backend.app.services.live_paper_trading import (
    execute_live_cycle,
    LivePaperError
)

from backend.app.services.agent_context import (
    load_live_context
)

from backend.app.services.agent_risk import (
    AgentRiskError
)

from backend.app.services.llm_decision import (
    request_decision,
    DecisionError,
    database_hash,
    model_hashes
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)

from backend.app.services.market_quote import (
    MarketQuote,
    QuoteError
)

from backend.app.services.risk import MICROS


@pytest.fixture(scope="module", autouse=True)
def proteger_originales():

    db_antes = database_hash()

    modelo_antes = model_hashes()

    yield

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes


@pytest.fixture
def escenario(tmp_path):

    ruta = tmp_path / "live_paper_test.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:

            original.backup(copia)

        finally:

            copia.close()

    # Reloj sintetico dentro de la ventana
    # permitida. No se modifica la base principal.

    with write_transaction(ruta) as conexion:

        prediccion = conexion.execute("""
            SELECT id, target_open_time
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

    now = cierre + 100

    quote = MarketQuote(
        symbol="BTCUSDT",
        price_micros=50000 * MICROS,
        trade_time_ms=now * 1000 - 500,
        server_time_ms=now * 1000,
        received_at_ms=now * 1000,
        latency_ms=100.0
    )

    return ruta, now, quote


class FakeClient:

    def __init__(self, context, action):

        self.context = context

        self.action = action

    def chat(self, messages, schema):

        return {
            "content": json.dumps({
                "action": self.action,
                "symbol": "BTCUSDT",
                "candle_date": (
                    self.context.candle_date.isoformat()
                ),
                "rationale": "Prueba financiera controlada."
            }),
            "model": MODEL,
            "digest": MODEL_DIGEST,
            "ollama_version": OLLAMA_VERSION,
            "latency_ms": 100.0,
            "prompt_tokens": 500,
            "output_tokens": 30
        }


def preparar(escenario, action="BUY"):

    db, now, quote = escenario

    context, metadata = load_live_context(
        db,
        clock=lambda: now
    )

    proposal = request_decision(
        context,
        FakeClient(context, action)
    )

    return context, metadata, proposal, quote


def ejecutar(escenario, action="BUY"):

    db, now, _ = escenario

    return execute_live_cycle(
        *preparar(escenario, action),
        path=db,
        clock=lambda: now
    )


def contar(db, tabla):

    with read_connection(db) as conexion:

        return conexion.execute(
            f"SELECT COUNT(*) FROM {tabla}"
        ).fetchone()[0]


def test_compra_virtual(escenario):

    db, _, _ = escenario

    resultado = ejecutar(escenario)

    assert resultado["executed"]

    assert resultado["order_side"] == "BUY"

    assert resultado["quantity_sats"] == 25000000

    assert (
        resultado["notional_micros"]
        == 12500 * MICROS
    )

    assert (
        resultado["cash_micros"]
        == 37500 * MICROS
    )

    assert (
        resultado["equity_micros"]
        == 50000 * MICROS
    )

    assert resultado["fee_micros"] == 0

    assert resultado["real_trading"] is False

    assert contar(db, "orders") == 1


def test_venta_virtual(escenario):

    db, _, _ = escenario

    # Posicion sintetica inicial para probar venta.

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET cash_micros = ?
        """, (37500 * MICROS,))

        conexion.execute("""
            UPDATE positions
            SET quantity_sats = 25000000,
                cost_basis_micros = ?
        """, (12500 * MICROS,))

    resultado = ejecutar(
        escenario,
        "SELL"
    )

    assert resultado["executed"]

    assert resultado["order_side"] == "SELL"

    assert (
        resultado["cash_micros"]
        == 50000 * MICROS
    )

    assert resultado["position_value_micros"] == 0

    with read_connection(db) as conexion:

        posicion = conexion.execute("""
            SELECT quantity_sats, cost_basis_micros
            FROM positions
        """).fetchone()

        assert tuple(posicion) == (0, 0)


def test_hold_cartera_pausada(escenario):

    db, _, _ = escenario

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET status = 'PAUSED'
        """)

    resultado = ejecutar(
        escenario,
        "HOLD"
    )

    assert resultado["risk_approved"]

    assert resultado["executed"] is False

    assert resultado["order_id"] is None

    assert contar(db, "orders") == 0


def test_idempotencia(escenario):

    db, now, _ = escenario

    argumentos = preparar(escenario)

    primero = execute_live_cycle(
        *argumentos,
        path=db,
        clock=lambda: now
    )

    segundo = execute_live_cycle(
        *argumentos,
        path=db,
        clock=lambda: now
    )

    assert primero["created"] is True

    assert segundo["created"] is False

    assert (
        primero["order_id"]
        == segundo["order_id"]
    )

    assert contar(db, "orders") == 1

    assert contar(db, "agent_cycles") == 1

    assert contar(db, "agent_decisions") == 1


def test_cotizacion_vencida(escenario):

    db, now, _ = escenario

    argumentos = preparar(escenario)

    with pytest.raises(QuoteError) as error:

        execute_live_cycle(
            *argumentos,
            path=db,
            clock=lambda: now + 61
        )

    assert error.value.code == "STALE_QUOTE"

    assert contar(db, "orders") == 0


def test_sin_cotizacion(escenario):

    db, now, _ = escenario

    context, metadata, proposal, _ = (
        preparar(escenario)
    )

    with pytest.raises(QuoteError):

        execute_live_cycle(
            context,
            metadata,
            proposal,
            None,
            path=db,
            clock=lambda: now
        )

    assert contar(db, "orders") == 0


def test_cambio_riesgo(escenario):

    db, now, _ = escenario

    argumentos = preparar(escenario)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET max_exposure_bps = 1000
        """)

    with pytest.raises(AgentRiskError):

        execute_live_cycle(
            *argumentos,
            path=db,
            clock=lambda: now
        )

    assert contar(db, "orders") == 0


def test_cambio_saldo(escenario):

    db, now, _ = escenario

    argumentos = preparar(escenario)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET cash_micros = cash_micros - 1000000
        """)

    with pytest.raises(AgentRiskError):

        execute_live_cycle(
            *argumentos,
            path=db,
            clock=lambda: now
        )

    assert contar(db, "orders") == 0


def test_datos_vencen_durante_decision(escenario):

    db, now, quote = escenario

    cierre = now - 100

    inicio = cierre + 3599

    final = cierre + 3601

    context, metadata = load_live_context(
        db,
        clock=lambda: inicio
    )

    proposal = request_decision(
        context,
        FakeClient(context, "BUY")
    )

    quote = replace(
        quote,
        trade_time_ms=final * 1000,
        server_time_ms=final * 1000,
        received_at_ms=final * 1000
    )

    resultado = execute_live_cycle(
        context,
        metadata,
        proposal,
        quote,
        path=db,
        clock=lambda: final
    )

    assert resultado["risk_approved"] is False

    assert resultado["executed"] is False

    assert (
        "STALE_CANDLE"
        in resultado["risk_reason"]
    )


def test_propuesta_manipulada(escenario):

    db, now, _ = escenario

    context, metadata, proposal, quote = (
        preparar(escenario)
    )

    proposal["llm_digest"] = "0" * 64

    with pytest.raises(LivePaperError):

        execute_live_cycle(
            context,
            metadata,
            proposal,
            quote,
            path=db,
            clock=lambda: now
        )

    assert contar(db, "orders") == 0


def test_reversion_atomica(escenario, monkeypatch):

    db, _, _ = escenario

    with read_connection(db) as conexion:

        antes = list(conexion.iterdump())

    def fallar(*args, **kwargs):

        raise RuntimeError(
            "Fallo controlado durante ejecucion."
        )

    monkeypatch.setattr(
        live_paper_trading,
        "_record_snapshot",
        fallar
    )

    with pytest.raises(RuntimeError):

        ejecutar(escenario)

    with read_connection(db) as conexion:

        assert list(conexion.iterdump()) == antes


def test_patrimonio_diario_ausente(escenario):

    db, _, _ = escenario

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET cash_micros = ?
        """, (45000 * MICROS,))

        conexion.execute("""
            UPDATE positions
            SET quantity_sats = 10000000,
                cost_basis_micros = ?
        """, (5000 * MICROS,))

    resultado = ejecutar(escenario)

    assert resultado["risk_approved"] is False

    assert (
        "MISSING_DAILY_EQUITY_BASELINE"
        in resultado["risk_reason"]
    )

    assert contar(db, "orders") == 0


def test_paro_durante_inferencia(escenario):

    db, now, _ = escenario

    argumentos = preparar(escenario)

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET emergency_stop = 1
        """)

    with pytest.raises(AgentRiskError):

        execute_live_cycle(
            *argumentos,
            path=db,
            clock=lambda: now
        )

    assert contar(db, "orders") == 0
