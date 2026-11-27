from datetime import datetime, date, time, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)

from backend.app.core.security import verify_api_key

from backend.app.core.database import read_connection


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)]
)


def timestamp_fecha(fecha):

    return int(
        datetime.combine(
            fecha,
            time.min,
            tzinfo=timezone.utc
        ).timestamp()
    )


def buscar_activo(conexion, symbol):

    fila = conexion.execute("""
        SELECT id, symbol
        FROM assets
        WHERE symbol = ?
          AND active = 1
    """, (symbol,)).fetchone()

    if fila is None:

        raise HTTPException(
            status_code=404,
            detail="Activo no disponible."
        )

    return fila


def serializar_vela(fila):

    return {
        "id": fila["id"],
        "date": datetime.fromtimestamp(
            fila["open_time"],
            tz=timezone.utc
        ).date().isoformat(),
        "open_time": fila["open_time"],
        "close_time": fila["close_time"],
        "open": fila["open"],
        "high": fila["high"],
        "low": fila["low"],
        "close": fila["close"],
        "volume": fila["volume"],
        "quote_volume": fila["quote_volume"],
        "source": fila["source"]
    }


@router.get("/market/assets", tags=["Mercado"])
def get_assets():

    with read_connection() as conexion:

        filas = conexion.execute("""
            SELECT
                symbol,
                base_currency,
                quote_currency,
                exchange,
                active
            FROM assets
            ORDER BY symbol
        """).fetchall()

    return {
        "total": len(filas),
        "assets": [
            {
                **dict(fila),
                "active": bool(fila["active"])
            }
            for fila in filas
        ]
    }


@router.get("/market/candles", tags=["Mercado"])
def get_candles(
    symbol: str = "BTCUSDT",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=1000000),
    start_date: date | None = None,
    end_date: date | None = None
):

    if (
        start_date is not None
        and end_date is not None
        and start_date > end_date
    ):

        raise HTTPException(
            status_code=422,
            detail="Rango de fechas invalido."
        )

    with read_connection() as conexion:

        activo = buscar_activo(
            conexion,
            symbol.upper()
        )

        condiciones = [
            "asset_id = ?",
            "interval_seconds = ?"
        ]

        parametros = [
            activo["id"],
            86400
        ]

        if start_date is not None:

            condiciones.append("open_time >= ?")

            parametros.append(
                timestamp_fecha(start_date)
            )

        if end_date is not None:

            condiciones.append("open_time <= ?")

            parametros.append(
                timestamp_fecha(end_date)
            )

        where = " AND ".join(condiciones)

        total = conexion.execute(
            f"""
            SELECT COUNT(*)
            FROM candles
            WHERE {where}
            """,
            parametros
        ).fetchone()[0]

        filas = conexion.execute(
            f"""
            SELECT *
            FROM candles
            WHERE {where}
            ORDER BY open_time DESC
            LIMIT ? OFFSET ?
            """,
            [*parametros, limit, offset]
        ).fetchall()

    return {
        "symbol": activo["symbol"],
        "interval": "1d",
        "timezone": "UTC",
        "data_type": "stored_history",
        "order": "descending",
        "total": total,
        "limit": limit,
        "offset": offset,
        "returned": len(filas),
        "has_more": offset + len(filas) < total,
        "candles": [
            serializar_vela(fila)
            for fila in filas
        ]
    }


@router.get("/market/latest", tags=["Mercado"])
def get_latest(symbol: str = "BTCUSDT"):

    with read_connection() as conexion:

        activo = buscar_activo(
            conexion,
            symbol.upper()
        )

        fila = conexion.execute("""
            SELECT *
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = 86400
            ORDER BY open_time DESC
            LIMIT 1
        """, (activo["id"],)).fetchone()

    if fila is None:

        raise HTTPException(
            status_code=404,
            detail="No existen velas almacenadas."
        )

    return {
        "symbol": activo["symbol"],
        "interval": "1d",
        "timezone": "UTC",
        "data_type": "stored_history",
        "candle": serializar_vela(fila)
    }


@router.get("/risk/config", tags=["Riesgo"])
def get_risk_config():

    with read_connection() as conexion:

        fila = conexion.execute("""
            SELECT
                r.*,
                p.name AS portfolio_name,
                p.status AS portfolio_status
            FROM risk_config r
            JOIN portfolio p
                ON p.id = r.portfolio_id
            WHERE p.name = ?
            ORDER BY r.version DESC
            LIMIT 1
        """, ("FinanceAI_Paper",)).fetchone()

    if fila is None:

        raise HTTPException(
            status_code=404,
            detail="Configuracion de riesgo no disponible."
        )

    return {
        "portfolio": fila["portfolio_name"],
        "portfolio_status": fila["portfolio_status"],
        "version": fila["version"],
        "max_exposure_pct": (
            fila["max_exposure_bps"] / 100
        ),
        "max_daily_loss_pct": (
            fila["max_daily_loss_bps"] / 100
        ),
        "max_data_age_seconds": (
            fila["max_data_age_seconds"]
        ),
        "min_order_usdt": (
            fila["min_order_micros"] / 1000000
        ),
        "fee_pct": fila["fee_bps"] / 100,
        "slippage_pct": fila["slippage_bps"] / 100,
        "prediction_threshold": (
            fila["prediction_threshold"]
        ),
        "emergency_stop": bool(
            fila["emergency_stop"]
        ),
        "risk_engine_ready": False,
        "real_trading": False
    }
