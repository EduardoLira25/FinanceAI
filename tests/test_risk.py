from dataclasses import replace

import pytest

from backend.app.services.risk import (
    MICROS,
    SATOSHIS,
    RiskConfig,
    RiskError,
    PortfolioState,
    MarketContext,
    evaluate,
    model_only_action,
    price_to_micros
)

CONFIG = RiskConfig()

CIERRE = 86400 * 20000

PORTFOLIO = PortfolioState(
    cash_micros=50000 * MICROS,
    quantity_sats=0,
    status="ACTIVE",
    day_start_equity_micros=50000 * MICROS
)

MARKET = MarketContext(
    symbol="BTCUSDT",
    candle_close_time=CIERRE,
    quote_time=CIERRE + 100,
    now=CIERRE + 100,
    price_micros=50000 * MICROS
)


def test_compra_autorizada():

    resultado = evaluate(
        "BUY", PORTFOLIO, MARKET, CONFIG
    )

    assert resultado.approved
    assert resultado.authorized_action == "BUY"
    assert resultado.notional_micros == 12500 * MICROS
    assert resultado.quantity_sats == 25000000
    assert resultado.fee_micros == 0


def test_compra_con_exposicion_existente():

    cartera = replace(
        PORTFOLIO,
        cash_micros=45000 * MICROS,
        quantity_sats=10000000
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert resultado.approved
    assert resultado.notional_micros == 7500 * MICROS


def test_venta_autorizada():

    cartera = replace(
        PORTFOLIO,
        cash_micros=37500 * MICROS,
        quantity_sats=25000000
    )

    resultado = evaluate(
        "SELL", cartera, MARKET, CONFIG
    )

    assert resultado.approved
    assert resultado.quantity_sats == 25000000
    assert resultado.notional_micros == 12500 * MICROS


def test_hold():

    resultado = evaluate(
        "HOLD", PORTFOLIO, MARKET, CONFIG
    )

    assert resultado.approved
    assert resultado.quantity_sats == 0
    assert resultado.authorized_action == "HOLD"


@pytest.mark.parametrize("estado", [
    "PAUSED", "STOPPED"
])
def test_cartera_inactiva(estado):

    cartera = replace(
        PORTFOLIO,
        status=estado
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "PORTFOLIO_NOT_ACTIVE" in resultado.reasons


def test_paro_emergencia():

    resultado = evaluate(
        "BUY", PORTFOLIO, MARKET,
        replace(CONFIG, emergency_stop=True)
    )

    assert not resultado.approved
    assert "EMERGENCY_STOP" in resultado.reasons


def test_vela_antigua():

    mercado = replace(
        MARKET,
        now=CIERRE + 3601,
        quote_time=CIERRE + 3601
    )

    resultado = evaluate(
        "BUY", PORTFOLIO, mercado, CONFIG
    )

    assert not resultado.approved
    assert "STALE_CANDLE" in resultado.reasons


def test_cotizacion_antigua():

    mercado = replace(
        MARKET,
        quote_time=CIERRE
    )

    resultado = evaluate(
        "BUY", PORTFOLIO, mercado, CONFIG
    )

    assert not resultado.approved
    assert "STALE_QUOTE" in resultado.reasons


def test_vela_futura():

    mercado = replace(
        MARKET,
        now=CIERRE - 1
    )

    resultado = evaluate(
        "BUY", PORTFOLIO, mercado, CONFIG
    )

    assert not resultado.approved
    assert "INVALID_CANDLE_TIME" in resultado.reasons


def test_cotizacion_futura():

    mercado = replace(
        MARKET,
        quote_time=MARKET.now + 1
    )

    resultado = evaluate(
        "BUY", PORTFOLIO, mercado, CONFIG
    )

    assert not resultado.approved
    assert "INVALID_QUOTE_TIME" in resultado.reasons


def test_simbolo_invalido():

    resultado = evaluate(
        "BUY", PORTFOLIO,
        replace(MARKET, symbol="INVALIDO"),
        CONFIG
    )

    assert not resultado.approved
    assert "INVALID_SYMBOL" in resultado.reasons


def test_perdida_diaria():

    cartera = replace(
        PORTFOLIO,
        cash_micros=49000 * MICROS
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "DAILY_LOSS_LIMIT" in resultado.reasons


def test_venta_permitida_con_perdida_diaria():

    cartera = replace(
        PORTFOLIO,
        cash_micros=35000 * MICROS,
        quantity_sats=25000000
    )

    resultado = evaluate(
        "SELL", cartera, MARKET, CONFIG
    )

    assert resultado.approved


def test_sin_patrimonio_diario_inicial():

    cartera = replace(
        PORTFOLIO,
        day_start_equity_micros=None
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved

    assert (
        "MISSING_DAILY_EQUITY_BASELINE"
        in resultado.reasons
    )


def test_exposicion_alcanzada():

    cartera = replace(
        PORTFOLIO,
        cash_micros=37500 * MICROS,
        quantity_sats=25000000
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "MAX_EXPOSURE_REACHED" in resultado.reasons


def test_efectivo_insuficiente():

    cartera = replace(
        PORTFOLIO,
        cash_micros=0,
        quantity_sats=SATOSHIS
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "INSUFFICIENT_CASH" in resultado.reasons


def test_sin_btc_para_vender():

    resultado = evaluate(
        "SELL", PORTFOLIO, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "NO_POSITION_TO_SELL" in resultado.reasons


def test_orden_inferior_al_minimo():

    cartera = replace(
        PORTFOLIO,
        cash_micros=20 * MICROS,
        day_start_equity_micros=20 * MICROS
    )

    resultado = evaluate(
        "BUY", cartera, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "BELOW_MINIMUM_ORDER" in resultado.reasons


def test_accion_invalida():

    resultado = evaluate(
        "SHORT", PORTFOLIO, MARKET, CONFIG
    )

    assert not resultado.approved
    assert "INVALID_ACTION" in resultado.reasons


def test_saldo_negativo():

    resultado = evaluate(
        "BUY",
        replace(PORTFOLIO, cash_micros=-1),
        MARKET,
        CONFIG
    )

    assert not resultado.approved
    assert "INVALID_BALANCE" in resultado.reasons


def test_precio_invalido():

    resultado = evaluate(
        "BUY", PORTFOLIO,
        replace(MARKET, price_micros=0),
        CONFIG
    )

    assert not resultado.approved


def test_configuracion_invalida():

    with pytest.raises(RiskError):

        evaluate(
            "BUY", PORTFOLIO, MARKET,
            replace(CONFIG, max_exposure_bps=10001)
        )


def test_comision_y_deslizamiento():

    configuracion = replace(
        CONFIG,
        fee_bps=10,
        slippage_bps=10
    )

    resultado = evaluate(
        "BUY", PORTFOLIO, MARKET,
        configuracion
    )

    assert resultado.approved
    assert resultado.fee_micros > 0

    assert (
        resultado.execution_price_micros
        > MARKET.price_micros
    )

    restante = (
        PORTFOLIO.cash_micros
        - resultado.notional_micros
        - resultado.fee_micros
    )

    posicion = (
        resultado.quantity_sats
        * MARKET.price_micros
        // SATOSHIS
    )

    patrimonio = restante + posicion

    assert restante >= 0
    assert posicion * 10000 <= patrimonio * 2500


@pytest.mark.parametrize("retorno, esperado", [
    (0.004861526, "BUY"),
    (0.001, "SELL"),
    (-0.01, "SELL")
])
def test_estrategia_modelo(retorno, esperado):

    assert model_only_action(retorno) == esperado


def test_pronostico_invalido():

    with pytest.raises(RiskError):

        model_only_action(float("nan"))


def test_precision_monetaria():

    assert price_to_micros(
        60454.44
    ) == 60454440000
