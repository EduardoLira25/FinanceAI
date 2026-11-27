import json

from datetime import timedelta, timezone

import pytest

from pydantic import ValidationError

from backend.app.services.financial_prompt import (
    FinancialContext,
    SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_messages,
    build_context_data,
    synthetic_context,
    prompt_sha256
)


def reconstruir(**cambios):

    datos = synthetic_context().model_dump()

    datos.update(cambios)

    return FinancialContext.model_validate(datos)


def test_contexto_financiero():

    datos = build_context_data(
        synthetic_context()
    )

    assert datos["symbol"] == "BTCUSDT"

    assert datos["portfolio"]["cash_usdt"] == 50000

    assert datos["portfolio"]["equity_at_close_usdt"] == 50000

    assert datos["portfolio"]["bitcoin_quantity"] == 0

    assert datos["forecast"]["predicted_return_pct"] == pytest.approx(0.4)

    assert datos["forecast"]["predicted_close_usdt"] == pytest.approx(50200)

    assert datos["risk"]["max_exposure_pct"] == 25

    assert datos["data_age_seconds"] == 600

    assert datos["risk"]["data_is_stale"] is False

    assert datos["real_trading"] is False


def test_estructura_mensajes():

    contexto = synthetic_context()

    mensajes = build_messages(contexto)

    assert len(mensajes) == 2

    assert mensajes[0]["role"] == "system"

    assert mensajes[1]["role"] == "user"

    assert mensajes[0]["content"] == SYSTEM_PROMPT

    contenido = mensajes[1]["content"].split(
        "\n\n", 1
    )[1]

    datos = json.loads(contenido)

    assert datos == build_context_data(contexto)

    assert len(prompt_sha256()) == 64

    assert datos["prompt_version"] == PROMPT_VERSION

    assert "No utilices informacion posterior" in SYSTEM_PROMPT


def test_cartera_pausada_y_datos_antiguos():

    original = synthetic_context()

    contexto = reconstruir(
        portfolio_status="PAUSED",
        emergency_stop=True,
        as_of_utc=(
            original.candle_close
            + timedelta(hours=14)
        )
    )

    datos = build_context_data(contexto)

    assert datos["portfolio"]["status"] == "PAUSED"

    assert datos["risk"]["emergency_stop"] is True

    assert datos["risk"]["data_is_stale"] is True


def test_control_temporal_replay():

    original = synthetic_context()

    contexto = reconstruir(
        mode="REPLAY",
        as_of_utc=original.candle_close
    )

    datos = build_context_data(contexto)

    assert datos["data_age_seconds"] == 0

    with pytest.raises(ValidationError):

        reconstruir(mode="REPLAY")


def test_horizonte_objetivo():

    original = synthetic_context()

    with pytest.raises(ValidationError):

        reconstruir(
            as_of_utc=(
                original.candle_close
                - timedelta(seconds=1)
            )
        )

    with pytest.raises(ValidationError):

        reconstruir(
            as_of_utc=(
                original.candle_close
                + timedelta(days=1)
            )
        )


def test_zona_horaria_no_utc():

    original = synthetic_context()

    otra_zona = timezone(
        timedelta(hours=1)
    )

    with pytest.raises(ValidationError):

        reconstruir(
            as_of_utc=(
                original.as_of_utc.astimezone(
                    otra_zona
                )
            )
        )


@pytest.mark.parametrize("cambios", [
    {"symbol": "ETHUSDT"},
    {"returns_20": (0.01,) * 19},
    {"returns_20": (float("nan"),) * 20},
    {"cash_micros": -1},
    {"reference_close": 0.0},
    {"volatility_20": -0.01},
    {"prediction_threshold": 0.0},
    {"portfolio_status": "INVALIDO"},
    {"predicted_return": -1.0}
])
def test_contexto_invalido(cambios):

    with pytest.raises(ValidationError):

        reconstruir(**cambios)
