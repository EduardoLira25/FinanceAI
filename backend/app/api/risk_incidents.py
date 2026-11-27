from datetime import datetime, timezone
from typing import Literal

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
    tags=["Risk and Incidents"]
)


def utc(value):

    if value is None:
        return None

    return datetime.fromtimestamp(
        value, timezone.utc
    ).isoformat()


def serialize_config(r):

    return {
        "version": r["version"],
        "max_exposure_pct": r["max_exposure_bps"] / 100,
        "max_daily_loss_pct": r["max_daily_loss_bps"] / 100,
        "max_data_age_seconds": r["max_data_age_seconds"],
        "min_order_usdt": r["min_order_micros"] / MICROS,
        "fee_pct": r["fee_bps"] / 100,
        "slippage_pct": r["slippage_bps"] / 100,
        "prediction_threshold_pct": (
            r["prediction_threshold"] * 100
        ),
        "emergency_stop": bool(r["emergency_stop"]),
        "created_at_utc": utc(r["created_at"])
    }


def risk_overview(path=DATABASE_PATH, now=None):

    if now is None:
        now = int(datetime.now(timezone.utc).timestamp())

    with read_connection(path) as c:

        p = c.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
              AND strategy = 'LLM'
              AND currency = 'USDT'
        """).fetchone()

        if p is None:

            raise RuntimeError("Cartera no disponible.")

        configs = c.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
        """, (p["id"],)).fetchall()

        if not configs:

            raise RuntimeError("Configuracion ausente.")

        position = c.execute("""
            SELECT pos.quantity_sats, a.id AS asset_id
            FROM positions pos
            JOIN assets a ON a.id = pos.asset_id
            WHERE pos.portfolio_id = ?
              AND a.symbol = 'BTCUSDT'
              AND a.exchange = 'MEXC'
        """, (p["id"],)).fetchone()

        if position is None:

            raise RuntimeError("Posicion no disponible.")

        candle = c.execute("""
            SELECT close, close_time, open_time
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = 86400
              AND close_time <= ?
            ORDER BY open_time DESC
            LIMIT 1
        """, (
            position["asset_id"], now
        )).fetchone()

        current = serialize_config(configs[0])

        exposure = None
        position_value = None
        equity = None
        age = None

        if candle is not None:

            position_value = (
                position["quantity_sats"]
                * price_to_micros(candle["close"])
                // SATOSHIS
            )

            equity = p["cash_micros"] + position_value

            exposure = (
                position_value / equity * 100
                if equity else 0
            )

            age = now - candle["close_time"]

        pending = c.execute("""
            SELECT COUNT(*)
            FROM error_logs
            WHERE resolved = 0
        """).fetchone()[0]

    blockers = []

    if p["status"] != "ACTIVE":
        blockers.append("PORTFOLIO_NOT_ACTIVE")

    if current["emergency_stop"]:
        blockers.append("EMERGENCY_STOP")

    if pending:
        blockers.append("RECOVERY_REQUIRED")

    if candle is None:
        blockers.append("MISSING_CANDLE")

    elif age > current["max_data_age_seconds"]:
        blockers.append("STALE_CANDLE")

    return {
        "portfolio_status": p["status"],
        "current": current,
        "versions": [
            serialize_config(r) for r in configs
        ],
        "exposure_pct": exposure,
        "position_value_usdt": (
            position_value / MICROS
            if position_value is not None else None
        ),
        "equity_usdt": (
            equity / MICROS
            if equity is not None else None
        ),
        "reference_date": (
            utc(candle["open_time"])[:10]
            if candle is not None else None
        ),
        "reference_close_utc": (
            utc(candle["close_time"])
            if candle is not None else None
        ),
        "data_age_seconds": age,
        "known_blockers": blockers,
        "pending_incidents": pending,
        "checked_at_utc": utc(now),
        "valuation_type": "LAST_STORED_CLOSED_CANDLE",
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


def incident_history(
    path=DATABASE_PATH,
    *,
    limit=20,
    offset=0,
    status="ALL"
):

    if status not in ("ALL", "PENDING", "RESOLVED"):

        raise ValueError("Estado incompatible.")

    with read_connection(path) as c:

        stats = c.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(resolved = 0), 0) AS pending,
                COALESCE(SUM(resolved = 1), 0) AS resolved
            FROM error_logs
        """).fetchone()

        filtro = ""
        parametros = []

        if status != "ALL":

            filtro = " WHERE resolved = ?"

            parametros.append(
                1 if status == "RESOLVED" else 0
            )

        filtered_total = c.execute(
            "SELECT COUNT(*) FROM error_logs" + filtro,
            parametros
        ).fetchone()[0]

        filas = c.execute("""
            SELECT
                id, cycle_id, component, error_type,
                message, cause, corrective_action,
                retry_count, resolved,
                created_at, resolved_at
            FROM error_logs
        """ + filtro + """
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (
            *parametros, limit, offset
        )).fetchall()

        logs = c.execute("""
            SELECT
                id, cycle_id, level, component,
                message, created_at
            FROM system_logs
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    return {
        "total": stats["total"],
        "pending": stats["pending"],
        "resolved": stats["resolved"],
        "filtered_total": filtered_total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(filas) < filtered_total,
        "incidents": [
            {
                "id": r["id"],
                "cycle_id": r["cycle_id"],
                "component": r["component"],
                "error_type": r["error_type"],
                "message": r["message"],
                "cause": r["cause"],
                "corrective_action": r["corrective_action"],
                "retry_count": r["retry_count"],
                "resolved": bool(r["resolved"]),
                "created_at_utc": utc(r["created_at"]),
                "resolved_at_utc": utc(r["resolved_at"])
            }
            for r in filas
        ],
        "system_logs": [
            {
                "id": r["id"],
                "cycle_id": r["cycle_id"],
                "level": r["level"],
                "component": r["component"],
                "message": r["message"],
                "created_at_utc": utc(r["created_at"])
            }
            for r in logs
        ],
        "recovery_required": stats["pending"] > 0,
        "scope": "SYSTEM_DATABASE",
        "real_trading": False
    }


@router.get("/risk/overview")
def risk_endpoint():

    return risk_overview(DATABASE_PATH)


@router.get("/incidents/history")
def incidents_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    status: Literal[
        "ALL", "PENDING", "RESOLVED"
    ] = "ALL"
):

    return incident_history(
        DATABASE_PATH,
        limit=limit,
        offset=offset,
        status=status
    )
