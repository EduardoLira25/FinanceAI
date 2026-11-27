import json

from datetime import timedelta

import pytest

from backend.app.services.financial_prompt import (
    FinancialContext,
    synthetic_context
)

from backend.app.services.llm_decision import (
    LLMDecision,
    DecisionError,
    validate_decision,
    request_decision
)


def respuesta(action="BUY", **cambios):

    datos = {
        "action": action,
        "symbol": "BTCUSDT",
        "candle_date": "2024-01-01",
        "rationale": "Propuesta financiera simulada."
    }

    datos.update(cambios)

    return json.dumps(datos)


def contexto(**cambios):

    datos = synthetic_context().model_dump()

    datos.update(cambios)

    return FinancialContext.model_validate(
        datos
    )


@pytest.mark.parametrize("accion", [
    "BUY", "HOLD", "SELL"
])
def test_acciones_validas(accion):

    ctx = contexto(quantity_sats=1000000)

    resultado = validate_decision(
        respuesta(accion),
        ctx
    )

    assert resultado.action == accion


@pytest.mark.parametrize("raw, codigo", [
    (
        "No es JSON",
        "INVALID_DECISION_JSON"
    ),
    (
        "```json\n" + respuesta() + "\n```",
        "INVALID_DECISION_JSON"
    ),
    (
        "[]",
        "INVALID_DECISION_SCHEMA"
    ),
    (
        '{"action":"BUY","action":"SELL"}',
        "DUPLICATE_JSON_KEY"
    ),
    (
        respuesta(quantity=10),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        '{"action":"BUY"}',
        "INVALID_DECISION_SCHEMA"
    ),
    (
        respuesta("buy"),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        respuesta(symbol="ETHUSDT"),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        respuesta(candle_date="2024-01-02"),
        "CANDLE_DATE_MISMATCH"
    ),
    (
        respuesta(rationale="   "),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        respuesta(rationale="a" * 241),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        respuesta(rationale="Linea 1\nLinea 2"),
        "INVALID_DECISION_SCHEMA"
    ),
    (
        '{"action":NaN}',
        "INVALID_JSON_CONSTANT"
    )
])
def test_respuestas_invalidas(raw, codigo):

    with pytest.raises(DecisionError) as error:

        validate_decision(
            raw,
            synthetic_context()
        )

    assert error.value.code == codigo


@pytest.mark.parametrize(
    "accion, cambios, codigo",
    [
        (
            "BUY",
            {"portfolio_status": "PAUSED"},
            "PORTFOLIO_NOT_ACTIVE"
        ),
        (
            "BUY",
            {"portfolio_status": "STOPPED"},
            "PORTFOLIO_NOT_ACTIVE"
        ),
        (
            "BUY",
            {"emergency_stop": True},
            "EMERGENCY_STOP"
        ),
        (
            "BUY",
            {
                "as_of_utc": (
                    synthetic_context().candle_close
                    + timedelta(hours=2)
                )
            },
            "STALE_CANDLE"
        ),
        (
            "BUY",
            {"cash_micros": 0},
            "INSUFFICIENT_CASH"
        ),
        (
            "SELL",
            {"quantity_sats": 0},
            "NO_POSITION_TO_SELL"
        )
    ]
)
def test_restricciones_financieras(
    accion,
    cambios,
    codigo
):

    with pytest.raises(DecisionError) as error:

        validate_decision(
            respuesta(accion),
            contexto(**cambios)
        )

    assert error.value.code == codigo


class FakeClient:

    def __init__(self, raw):

        self.raw = raw

    def chat(self, messages, schema):

        assert len(messages) == 2

        assert schema == (
            LLMDecision.model_json_schema()
        )

        return {
            "content": self.raw,
            "model": "qwen3:8b",
            "digest": "a" * 64,
            "ollama_version": "0.40.18",
            "latency_ms": 100,
            "prompt_tokens": 100,
            "output_tokens": 25
        }


def test_solicitud_valida():

    resultado = request_decision(
        synthetic_context(),
        FakeClient(respuesta())
    )

    assert resultado["decision"]["action"] == "BUY"

    assert resultado["validation_status"] == "VALID"

    assert resultado["risk_authorized"] is False

    assert resultado["executed"] is False

    assert resultado["real_trading"] is False


def test_solicitud_invalida_bloqueada():

    with pytest.raises(DecisionError):

        request_decision(
            synthetic_context(),
            FakeClient("JSON incorrecto")
        )
