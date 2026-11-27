import runpy
import pytest

from pathlib import Path
from dataclasses import replace

from backend.app.services.risk import evaluate

original = runpy.run_path(
    str(Path(__file__).with_name("test_risk.py"))
)

PORTFOLIO = original["PORTFOLIO"]
MARKET = original["MARKET"]
CONFIG = original["CONFIG"]


def preparar_cartera(accion):

    return replace(
        PORTFOLIO,
        status="ACTIVE",
        cash_micros=50000000000,
        quantity_sats=(
            100000000 if accion == "SELL" else 0
        ),
        day_start_equity_micros=50000000000
    )


def verificar_bloqueo(resultado):

    assert not resultado.approved
    assert resultado.authorized_action == "HOLD"
    assert resultado.quantity_sats == 0


@pytest.mark.parametrize("accion", ["BUY", "SELL"])
def test_bloqueo_vela_obsoleta(accion):

    cartera = preparar_cartera(accion)

    control = evaluate(
        accion,
        cartera,
        MARKET,
        CONFIG
    )

    assert control.approved

    mercado = replace(
        MARKET,
        candle_close_time=(
            MARKET.now
            - CONFIG.max_data_age_seconds
            - 1
        )
    )

    resultado = evaluate(
        accion,
        cartera,
        mercado,
        CONFIG
    )

    verificar_bloqueo(resultado)


def test_saldo_positivo_insuficiente():

    cartera = replace(
        preparar_cartera("BUY"),
        cash_micros=1,
        day_start_equity_micros=1
    )

    resultado = evaluate(
        "BUY",
        cartera,
        MARKET,
        CONFIG
    )

    verificar_bloqueo(resultado)


@pytest.mark.parametrize("accion", ["BUY", "SELL"])
def test_paro_emergencia_bloquea_operacion(accion):

    cartera = preparar_cartera(accion)

    control = evaluate(
        accion,
        cartera,
        MARKET,
        CONFIG
    )

    assert control.approved

    riesgo = replace(
        CONFIG,
        emergency_stop=True
    )

    resultado = evaluate(
        accion,
        cartera,
        MARKET,
        riesgo
    )

    verificar_bloqueo(resultado)

