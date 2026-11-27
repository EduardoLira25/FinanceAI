import json
import math
import time

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP

from backend.app.core.database import read_connection

MICROS = 1_000_000
SATOSHIS = 100_000_000
BPS = 10_000
DAY = 86400

MAX_QUOTE_AGE_SECONDS = 60


class RiskError(RuntimeError):
    pass


def ceil_div(a, b):

    return (a + b - 1) // b


def price_to_micros(price):

    valor = Decimal(str(price))

    if not valor.is_finite() or valor <= 0:
        raise RiskError("Precio invalido.")

    resultado = int(
        (valor * MICROS).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )

    if resultado <= 0:
        raise RiskError("Precio inferior a la precision.")

    return resultado


@dataclass(frozen=True)
class RiskConfig:

    max_exposure_bps: int = 2500
    max_daily_loss_bps: int = 200
    max_data_age_seconds: int = 3600
    min_order_micros: int = 10 * MICROS
    fee_bps: int = 0
    slippage_bps: int = 0
    emergency_stop: bool = False


@dataclass(frozen=True)
class PortfolioState:

    cash_micros: int
    quantity_sats: int
    status: str
    day_start_equity_micros: int | None


@dataclass(frozen=True)
class MarketContext:

    symbol: str
    candle_close_time: int
    quote_time: int
    now: int
    price_micros: int


@dataclass(frozen=True)
class RiskDecision:

    proposed_action: str
    authorized_action: str
    approved: bool
    reasons: tuple
    quantity_sats: int = 0
    execution_price_micros: int = 0
    notional_micros: int = 0
    fee_micros: int = 0


def reject(action, *reasons):

    return RiskDecision(
        proposed_action=action,
        authorized_action="HOLD",
        approved=False,
        reasons=tuple(reasons)
    )


def model_only_action(predicted_return, threshold=0.001):

    if (
        not math.isfinite(predicted_return)
        or not math.isfinite(threshold)
        or threshold <= 0
        or predicted_return <= -1
    ):
        raise RiskError("Pronostico o umbral invalido.")

    # Estrategia experimental: BTC si supera umbral,
    # efectivo en caso contrario.

    return (
        "BUY"
        if predicted_return > threshold
        else "SELL"
    )


def validate_config(config):

    for valor in (
        config.max_exposure_bps,
        config.max_daily_loss_bps,
        config.fee_bps,
        config.slippage_bps
    ):

        if type(valor) is not int:
            raise RiskError("Configuracion invalida.")

        if not 0 <= valor <= BPS:
            raise RiskError("Configuracion invalida.")

    for valor in (
        config.max_data_age_seconds,
        config.min_order_micros
    ):

        if type(valor) is not int or valor <= 0:
            raise RiskError("Configuracion invalida.")

    if type(config.emergency_stop) is not bool:
        raise RiskError("Paro de emergencia invalido.")


def evaluate(action, portfolio, market, config):

    validate_config(config)

    if action not in ("BUY", "HOLD", "SELL"):

        return reject(
            action,
            "INVALID_ACTION"
        )

    for valor in (
        portfolio.cash_micros,
        portfolio.quantity_sats,
        market.price_micros,
        market.now,
        market.candle_close_time,
        market.quote_time
    ):

        if type(valor) is not int:

            return reject(
                action,
                "INVALID_NUMERIC_DATA"
            )

    if (
        portfolio.cash_micros < 0
        or portfolio.quantity_sats < 0
    ):

        return reject(action, "INVALID_BALANCE")

    if market.price_micros <= 0:

        return reject(action, "INVALID_PRICE")

    if market.symbol != "BTCUSDT":

        return reject(action, "INVALID_SYMBOL")

    if action == "HOLD":

        return RiskDecision(
            "HOLD", "HOLD", True,
            ("NO_TRADE_REQUESTED",)
        )

    reasons = []

    # 2. Estado de la cartera y paro de emergencia

    if portfolio.status != "ACTIVE":

        reasons.append("PORTFOLIO_NOT_ACTIVE")

    if config.emergency_stop:

        reasons.append("EMERGENCY_STOP")

    # 3. Validar fechas y antiguedad

    age = market.now - market.candle_close_time

    if (
        market.candle_close_time <= 0
        or market.candle_close_time % DAY != 0
        or age < 0
    ):

        reasons.append("INVALID_CANDLE_TIME")

    elif age > config.max_data_age_seconds:

        reasons.append("STALE_CANDLE")

    quote_age = market.now - market.quote_time

    if (
        market.quote_time < market.candle_close_time
        or quote_age < 0
    ):

        reasons.append("INVALID_QUOTE_TIME")

    elif quote_age > MAX_QUOTE_AGE_SECONDS:

        reasons.append("STALE_QUOTE")

    # 4. Valorar cartera

    current_value = (
        portfolio.quantity_sats
        * market.price_micros
        // SATOSHIS
    )

    equity = (
        portfolio.cash_micros
        + current_value
    )

    if equity <= 0:

        reasons.append("INVALID_EQUITY")

    # 5. Limite de perdida diaria
    # Bloquea nuevas compras, pero permite reducir
    # posiciones si los demas controles son validos.

    if action == "BUY":

        baseline = portfolio.day_start_equity_micros

        if type(baseline) is not int or baseline <= 0:

            reasons.append(
                "MISSING_DAILY_EQUITY_BASELINE"
            )

        elif (
            equity < baseline
            and (baseline - equity) * BPS
            >= baseline * config.max_daily_loss_bps
        ):

            reasons.append("DAILY_LOSS_LIMIT")

    if reasons:

        return reject(action, *reasons)

    # 6. Determinar precio de ejecucion simulado

    if action == "BUY":

        execution_price = ceil_div(
            market.price_micros
            * (BPS + config.slippage_bps),
            BPS
        )

    else:

        execution_price = (
            market.price_micros
            * (BPS - config.slippage_bps)
            // BPS
        )

    if execution_price <= 0:

        return reject(
            action,
            "INVALID_EXECUTION_PRICE"
        )

    def costs(quantity):

        if action == "BUY":

            notional = ceil_div(
                quantity * execution_price,
                SATOSHIS
            )

        else:

            notional = (
                quantity * execution_price
                // SATOSHIS
            )

        fee = ceil_div(
            notional * config.fee_bps,
            BPS
        )

        return notional, fee

    # 7. Calcular cantidad autorizada

    if action == "BUY":

        if portfolio.cash_micros <= 0:

            return reject(
                action,
                "INSUFFICIENT_CASH"
            )

        if (
            current_value * BPS
            >= equity * config.max_exposure_bps
        ):

            return reject(
                action,
                "MAX_EXPOSURE_REACHED"
            )

        # Encontrar cantidad maxima que cumple
        # efectivo y exposicion despues de costos.

        def fits(quantity):

            notional, fee = costs(quantity)

            remaining_cash = (
                portfolio.cash_micros
                - notional
                - fee
            )

            position_value = (
                (portfolio.quantity_sats + quantity)
                * market.price_micros
                // SATOSHIS
            )

            new_equity = (
                remaining_cash + position_value
            )

            return (
                remaining_cash >= 0
                and new_equity > 0
                and position_value * BPS
                <= new_equity * config.max_exposure_bps
            )

        low = 0

        high = (
            portfolio.cash_micros
            * SATOSHIS
            // execution_price
        )

        while low < high:

            middle = (low + high + 1) // 2

            if fits(middle):

                low = middle

            else:

                high = middle - 1

        quantity = low

        if quantity <= 0:

            return reject(
                action,
                "INSUFFICIENT_CAPACITY"
            )

    else:

        quantity = portfolio.quantity_sats

        if quantity <= 0:

            return reject(
                action,
                "NO_POSITION_TO_SELL"
            )

    notional, fee = costs(quantity)

    if notional < config.min_order_micros:

        return reject(
            action,
            "BELOW_MINIMUM_ORDER"
        )

    if action == "BUY":

        if not fits(quantity):

            return reject(
                action,
                "FINAL_EXPOSURE_CHECK_FAILED"
            )

    if action == "SELL" and fee > notional:

        return reject(
            action,
            "INVALID_EXECUTION_COST"
        )

    return RiskDecision(
        proposed_action=action,
        authorized_action=action,
        approved=True,
        reasons=("RISK_APPROVED",),
        quantity_sats=quantity,
        execution_price_micros=execution_price,
        notional_micros=notional,
        fee_micros=fee
    )


# 8. Diagnostico con informacion real de SQLite

def main():

    print("=" * 60)
    print("FINANCEAI - MOTOR DE RIESGO")
    print("=" * 60)

    with read_connection() as conexion:

        cartera = conexion.execute("""
            SELECT
                p.id,
                p.status,
                p.cash_micros,
                pos.quantity_sats
            FROM portfolio p
            JOIN positions pos
                ON pos.portfolio_id = p.id
            JOIN assets a
                ON a.id = pos.asset_id
            WHERE p.name = 'FinanceAI_Paper'
              AND a.symbol = 'BTCUSDT'
        """).fetchone()

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        prediccion = conexion.execute("""
            SELECT
                p.predicted_return,
                c.close,
                c.close_time
            FROM predictions p
            JOIN candles c
                ON c.id = p.candle_id
            JOIN assets a
                ON a.id = c.asset_id
            WHERE a.symbol = 'BTCUSDT'
              AND p.model_version = '1.0.0'
            ORDER BY c.open_time DESC
            LIMIT 1
        """).fetchone()

        ordenes = conexion.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

    assert prediccion is not None

    config = RiskConfig(
        max_exposure_bps=riesgo["max_exposure_bps"],
        max_daily_loss_bps=riesgo["max_daily_loss_bps"],
        max_data_age_seconds=riesgo["max_data_age_seconds"],
        min_order_micros=riesgo["min_order_micros"],
        fee_bps=riesgo["fee_bps"],
        slippage_bps=riesgo["slippage_bps"],
        emergency_stop=bool(riesgo["emergency_stop"])
    )

    estado = PortfolioState(
        cash_micros=cartera["cash_micros"],
        quantity_sats=cartera["quantity_sats"],
        status=cartera["status"],
        day_start_equity_micros=None
    )

    # El cierre historico NO es una cotizacion
    # ejecutable actual. Usarlo solo para comprobar
    # que el motor rechaza datos antiguos.

    mercado = MarketContext(
        symbol="BTCUSDT",
        candle_close_time=prediccion["close_time"],
        quote_time=prediccion["close_time"],
        now=int(time.time()),
        price_micros=price_to_micros(
            prediccion["close"]
        )
    )

    propuesta = model_only_action(
        prediccion["predicted_return"],
        riesgo["prediction_threshold"]
    )

    decision = evaluate(
        propuesta,
        estado,
        mercado,
        config
    )

    assert decision.approved is False
    assert decision.authorized_action == "HOLD"
    assert "PORTFOLIO_NOT_ACTIVE" in decision.reasons
    assert ordenes == 0

    print("\nRendimiento pronosticado:",
          prediccion["predicted_return"] * 100, "%")

    print("Accion propuesta:", propuesta)

    print("\nRESULTADO DEL CONTROL DE RIESGO:\n")

    print(json.dumps(
        asdict(decision),
        indent=4
    ))

    print("\nCapital virtual:",
          estado.cash_micros / MICROS,
          "USDT")

    print("Ordenes realizadas:", ordenes)
    print("Motor de riesgo: FUNCIONAL")
    print("Cartera modificada: NO")
    print("Operaciones ejecutadas: NO")
    print("Dinero real utilizado: NO")
    print("\nPASO 11.8 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
