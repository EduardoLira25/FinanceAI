import json

from datetime import timedelta

import pytest

from backend.app.services import agent_risk

from backend.app.services.agent_risk import (
    preview_action,
    operational_blockers,
    preview_live_decision,
    verify_unchanged_context,
    AgentRiskError
)

from backend.app.services.financial_prompt import (
    FinancialContext,
    synthetic_context
)

from backend.app.services.llm_decision import (
    DecisionError
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)


def contexto(**cambios):

    datos = synthetic_context().model_dump()

    datos.update(cambios)

    return FinancialContext.model_validate(
        datos
    )


def test_hold_autorizado_sin_orden():

    resultado = preview_action(
        "HOLD",
        synthetic_context()
    )

    assert resultado["approved"]

    assert resultado["authorized_action"] == "HOLD"

    assert resultado["quantity_sats"] == 0

    assert resultado["order_authorized"] is False


def test_compra_cartera_pausada():

    resultado = preview_action(
        "BUY",
        contexto(portfolio_status="PAUSED")
    )

    assert resultado["approved"] is False

    assert resultado["authorized_action"] == "HOLD"

    assert (
        "PORTFOLIO_NOT_ACTIVE"
        in resultado["reasons"]
    )


def test_compra_sin_cotizacion_verificada():

    original = synthetic_context()

    resultado = preview_action(
        "BUY",
        contexto(
            as_of_utc=original.candle_close
        )
    )

    assert resultado["approved"] is False

    assert resultado["quantity_sats"] == 0

    assert (
        "NO_VERIFIED_EXECUTION_QUOTE"
        in resultado["reasons"]
    )


def test_venta_sin_cotizacion_verificada():

    original = synthetic_context()

    resultado = preview_action(
        "SELL",
        contexto(
            quantity_sats=25000000,
            as_of_utc=original.candle_close
        )
    )

    assert resultado["approved"] is False

    assert (
        "NO_VERIFIED_EXECUTION_QUOTE"
        in resultado["reasons"]
    )


def test_datos_antiguos():

    original = synthetic_context()

    resultado = preview_action(
        "BUY",
        contexto(
            as_of_utc=(
                original.candle_close
                + timedelta(hours=2)
            )
        )
    )

    assert resultado["approved"] is False

    assert "STALE_CANDLE" in resultado["reasons"]


def test_paro_emergencia():

    resultado = preview_action(
        "BUY",
        contexto(emergency_stop=True)
    )

    assert resultado["approved"] is False

    assert "EMERGENCY_STOP" in resultado["reasons"]


def test_patrimonio_diario_ausente():

    resultado = preview_action(
        "BUY",
        contexto(
            day_start_equity_micros=None
        )
    )

    assert (
        "MISSING_DAILY_EQUITY_BASELINE"
        in resultado["reasons"]
    )


def test_restricciones_operativas():

    original = synthetic_context()

    ctx = contexto(
        portfolio_status="PAUSED",
        emergency_stop=True,
        day_start_equity_micros=None,
        as_of_utc=(
            original.candle_close
            + timedelta(hours=14)
        )
    )

    motivos = operational_blockers(ctx)

    assert "PORTFOLIO_NOT_ACTIVE" in motivos

    assert "EMERGENCY_STOP" in motivos

    assert "STALE_CANDLE" in motivos

    assert "NO_VERIFIED_EXECUTION_QUOTE" in motivos

    assert (
        "MISSING_DAILY_EQUITY_BASELINE_FOR_BUY"
        in motivos
    )


def test_cambio_de_cartera():

    with pytest.raises(AgentRiskError) as error:

        verify_unchanged_context(
            synthetic_context(),
            contexto(cash_micros=1000000),
            {"prediction_id": 1},
            {"prediction_id": 1}
        )

    assert error.value.code == "CONTEXT_CHANGED"


def test_cambio_configuracion_riesgo():

    with pytest.raises(AgentRiskError) as error:

        verify_unchanged_context(
            synthetic_context(),
            contexto(max_exposure_bps=1000),
            {"risk_config_id": 1},
            {"risk_config_id": 2}
        )

    assert error.value.code == "CONTEXT_CHANGED"


def test_cambio_prediccion():

    ctx = synthetic_context()

    with pytest.raises(AgentRiskError) as error:

        verify_unchanged_context(
            ctx,
            ctx,
            {"prediction_id": 1},
            {"prediction_id": 2}
        )

    assert error.value.code == "CONTEXT_CHANGED"


def test_reloj_retrocede():

    original = synthetic_context()

    anterior = contexto(
        as_of_utc=(
            original.as_of_utc
            - timedelta(seconds=1)
        )
    )

    with pytest.raises(AgentRiskError) as error:

        verify_unchanged_context(
            original,
            anterior,
            {},
            {}
        )

    assert error.value.code == "CLOCK_MOVED_BACKWARD"


class FakeClient:

    def __init__(self, action="HOLD", raw=None):

        self.action = action

        self.raw = raw

    def chat(self, messages, schema):

        contenido = self.raw

        if contenido is None:

            contenido = json.dumps({
                "action": self.action,
                "symbol": "BTCUSDT",
                "candle_date": "2024-01-01",
                "rationale": "Prueba controlada."
            })

        return {
            "content": contenido,
            "model": MODEL,
            "digest": MODEL_DIGEST,
            "ollama_version": OLLAMA_VERSION,
            "latency_ms": 100.0,
            "prompt_tokens": 500,
            "output_tokens": 35
        }


def preparar_contextos(
    monkeypatch,
    primero,
    segundo
):

    iterador = iter([primero, segundo])

    def cargar(path, clock):

        ctx = next(iterador)

        return ctx, {
            "prediction_id": 1,
            "candle_id": 1,
            "portfolio_id": 1,
            "risk_config_id": 1,
            "context_created_at_utc": (
                ctx.as_of_utc.isoformat()
            )
        }

    monkeypatch.setattr(
        agent_risk,
        "load_live_context",
        cargar
    )


def test_integracion_completa(monkeypatch):

    primero = synthetic_context()

    segundo = contexto(
        as_of_utc=(
            primero.as_of_utc
            + timedelta(seconds=10)
        )
    )

    preparar_contextos(
        monkeypatch,
        primero,
        segundo
    )

    resultado = preview_live_decision(
        FakeClient()
    )

    assert resultado["context_revalidated"]

    assert resultado["llm_risk"]["approved"]

    assert (
        resultado["llm_risk"]["authorized_action"]
        == "HOLD"
    )

    assert (
        resultado["model_only_risk"]["proposed_action"]
        == "BUY"
    )

    assert resultado["executed"] is False

    assert resultado["order_authorized"] is False


def test_datos_vencen_durante_inferencia(monkeypatch):

    original = synthetic_context()

    primero = contexto(
        as_of_utc=(
            original.candle_close
            + timedelta(seconds=3599)
        )
    )

    segundo = contexto(
        as_of_utc=(
            original.candle_close
            + timedelta(seconds=3601)
        )
    )

    preparar_contextos(
        monkeypatch,
        primero,
        segundo
    )

    resultado = preview_live_decision(
        FakeClient("BUY")
    )

    assert resultado["llm_risk"]["approved"] is False

    assert (
        "STALE_CANDLE"
        in resultado["llm_risk"]["reasons"]
    )

    assert resultado["executed"] is False


def test_json_invalido_bloqueado(monkeypatch):

    preparar_contextos(
        monkeypatch,
        synthetic_context(),
        synthetic_context()
    )

    with pytest.raises(DecisionError):

        preview_live_decision(
            FakeClient(raw="JSON incorrecto")
        )


def test_accion_invalida():

    with pytest.raises(AgentRiskError):

        preview_action(
            "SHORT",
            synthetic_context()
        )
