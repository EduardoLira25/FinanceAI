import time

from typing import Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from backend.app.core.config import DATABASE_PATH
from backend.app.core.database import read_connection
from backend.app.core.security import verify_api_key

from backend.app.services.risk import (
    MICROS,
    SATOSHIS,
    price_to_micros
)


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
    tags=["Portfolio History"]
)


def utc(value):

    if value is None:
        return None

    return datetime.fromtimestamp(
        value, timezone.utc
    ).isoformat()


def principal(conexion):

    cartera = conexion.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
          AND mode = 'PAPER_LIVE'
          AND strategy = 'LLM'
          AND currency = 'USDT'
    """).fetchone()

    if cartera is None:

        raise RuntimeError(
            "Cartera principal no disponible."
        )

    return cartera


def portfolio_overview(path=DATABASE_PATH, now=None):

    now = int(time.time()) if now is None else int(now)

    with read_connection(path) as conexion:

        cartera = principal(conexion)

        posicion = conexion.execute("""
            SELECT
                pos.quantity_sats,
                pos.cost_basis_micros,
                a.id AS asset_id
            FROM positions pos
            JOIN assets a ON a.id = pos.asset_id
            WHERE pos.portfolio_id = ?
              AND a.symbol = 'BTCUSDT'
              AND a.exchange = 'MEXC'
        """, (cartera["id"],)).fetchone()

        if posicion is None:

            raise RuntimeError(
                "Posicion BTC no disponible."
            )

        vela = conexion.execute("""
            SELECT open_time, close_time, close
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = 86400
              AND close_time <= ?
            ORDER BY open_time DESC
            LIMIT 1
        """, (
            posicion["asset_id"], now
        )).fetchone()

        if vela is None:

            raise RuntimeError(
                "Precio de valoracion no disponible."
            )

        cash = cartera["cash_micros"]

        quantity = posicion["quantity_sats"]

        mark = price_to_micros(vela["close"])

        position_value = (
            quantity * mark // SATOSHIS
        )

        equity = cash + position_value

        initial = cartera["initial_cash_micros"]

        cost_basis = posicion["cost_basis_micros"]

        snapshots = conexion.execute("""
            SELECT
                e.id,
                e.snapshot_type,
                e.recorded_at,
                e.cash_micros,
                e.position_value_micros,
                e.equity_micros,
                e.drawdown
            FROM equity_history e
            JOIN agent_cycles c ON c.id = e.cycle_id
            WHERE c.portfolio_id = ?
              AND e.snapshot_type = 'VALUATION'
              AND e.recorded_at <= ?
            ORDER BY e.recorded_at DESC, e.id DESC
            LIMIT 365
        """, (cartera["id"], now)).fetchall()

        stats = conexion.execute("""
            SELECT
                COUNT(*) AS total,
                MAX(e.drawdown) AS max_drawdown
            FROM equity_history e
            JOIN agent_cycles c ON c.id = e.cycle_id
            WHERE c.portfolio_id = ?
              AND e.recorded_at <= ?
        """, (cartera["id"], now)).fetchone()

        total_valuations = conexion.execute("""
            SELECT COUNT(*)
            FROM equity_history e
            JOIN agent_cycles c ON c.id = e.cycle_id
            WHERE c.portfolio_id = ?
              AND e.snapshot_type = 'VALUATION'
              AND e.recorded_at <= ?
        """, (cartera["id"], now)).fetchone()[0]

        orders = conexion.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(
                    CASE WHEN o.side = 'BUY'
                    THEN 1 ELSE 0 END
                ), 0) AS buys,
                COALESCE(SUM(
                    CASE WHEN o.side = 'SELL'
                    THEN 1 ELSE 0 END
                ), 0) AS sells,
                COALESCE(SUM(o.fee_micros), 0) AS fees,
                COALESCE(SUM(o.slippage_micros), 0)
                    AS slippage
            FROM orders o
            JOIN agent_decisions d ON d.id = o.decision_id
            JOIN agent_cycles c ON c.id = d.cycle_id
            WHERE c.portfolio_id = ?
              AND o.status = 'FILLED'
        """, (cartera["id"],)).fetchone()

    return {
        "name": cartera["name"],
        "status": cartera["status"],
        "currency": "USDT",
        "initial_cash": initial / MICROS,
        "cash": cash / MICROS,
        "bitcoin_quantity": quantity / SATOSHIS,
        "position_value": position_value / MICROS,
        "cost_basis": cost_basis / MICROS,
        "unrealized_pnl": (
            position_value - cost_basis
        ) / MICROS,
        "equity": equity / MICROS,
        "return_pct": (equity / initial - 1) * 100,
        "exposure_pct": (
            position_value / equity * 100
            if equity else 0
        ),
        "reference_price": vela["close"],
        "reference_date": utc(vela["open_time"])[:10],
        "reference_close_utc": utc(vela["close_time"]),
        "valuation_type": "LAST_STORED_CLOSED_CANDLE",
        "max_recorded_drawdown_pct": (
            stats["max_drawdown"] * 100
            if stats["max_drawdown"] is not None
            else None
        ),
        "total_snapshots": stats["total"],
        "total_valuations": total_valuations,
        "valuations": [
            {
                "id": fila["id"],
                "date": utc(fila["recorded_at"]),
                "cash": fila["cash_micros"] / MICROS,
                "position_value": (
                    fila["position_value_micros"] / MICROS
                ),
                "equity": fila["equity_micros"] / MICROS,
                "drawdown_pct": fila["drawdown"] * 100
            }
            for fila in reversed(snapshots)
        ],
        "filled_orders": orders["total"],
        "buys": orders["buys"],
        "sells": orders["sells"],
        "fees_usdt": orders["fees"] / MICROS,
        "slippage_usdt": orders["slippage"] / MICROS,
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


def order_history(
    path=DATABASE_PATH,
    *,
    limit=20,
    offset=0,
    side=None,
    status=None
):

    with read_connection(path) as conexion:

        cartera = principal(conexion)

        filtro = """
            FROM orders o
            JOIN agent_decisions d ON d.id = o.decision_id
            JOIN agent_cycles c ON c.id = d.cycle_id
            JOIN candles v ON v.id = c.candle_id
            JOIN assets a ON a.id = v.asset_id
            WHERE c.portfolio_id = ?
        """

        parametros = [cartera["id"]]

        if side is not None:

            filtro += " AND o.side = ?"
            parametros.append(side)

        if status is not None:

            filtro += " AND o.status = ?"
            parametros.append(status)

        total = conexion.execute(
            "SELECT COUNT(*) " + filtro,
            parametros
        ).fetchone()[0]

        filas = conexion.execute("""
            SELECT
                o.*,
                c.id AS cycle_id,
                a.symbol,
                v.open_time
        """ + filtro + """
            ORDER BY o.id DESC
            LIMIT ? OFFSET ?
        """, (
            *parametros, limit, offset
        )).fetchall()

    ordenes = []

    for fila in filas:

        ordenes.append({
            "id": fila["id"],
            "cycle_id": fila["cycle_id"],
            "symbol": fila["symbol"],
            "side": fila["side"],
            "status": fila["status"],
            "quantity_btc": (
                fila["quantity_sats"] / SATOSHIS
            ),
            "price_usdt": (
                fila["price_micros"] / MICROS
                if fila["price_micros"] is not None
                else None
            ),
            "notional_usdt": (
                fila["notional_micros"] / MICROS
                if fila["notional_micros"] is not None
                else None
            ),
            "fee_usdt": fila["fee_micros"] / MICROS,
            "slippage_usdt": (
                fila["slippage_micros"] / MICROS
            ),
            "reference_date": utc(fila["open_time"])[:10],
            "created_at_utc": utc(fila["created_at"]),
            "filled_at_utc": utc(fila["filled_at"]),
            "execution_source": fila["execution_source"]
        })

    return {
        "orders": ordenes,
        "total": total,
        "returned": len(ordenes),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(ordenes) < total,
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


@router.get("/portfolio/overview")
def overview_endpoint():

    return portfolio_overview(DATABASE_PATH)


@router.get("/orders/history")
def orders_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    side: Literal["BUY", "SELL"] | None = None,
    status: Literal[
        "FILLED", "PENDING", "REJECTED", "CANCELLED"
    ] | None = None
):

    return order_history(
        DATABASE_PATH,
        limit=limit,
        offset=offset,
        side=side,
        status=status
    )
