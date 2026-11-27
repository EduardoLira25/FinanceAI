import time

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import read_connection

from backend.app.core.security import verify_api_key


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
    tags=["Predictions"]
)


def utc(timestamp):

    return datetime.fromtimestamp(
        timestamp,
        timezone.utc
    ).isoformat()


def prediction_history(
    path=DATABASE_PATH,
    *,
    limit=100,
    offset=0,
    now=None
):

    now = int(time.time()) if now is None else int(now)

    with read_connection(path) as conexion:

        condiciones = """
            a.symbol = 'BTCUSDT'
            AND a.exchange = 'MEXC'
            AND c.interval_seconds = 86400
            AND p.model_version = '1.0.0'
            AND p.created_at <= ?
            AND p.created_at >= c.close_time
            AND p.created_at < p.target_close_time
            AND p.target_open_time = c.close_time
            AND p.target_close_time = c.close_time + 86400
        """

        total = conexion.execute("""
            SELECT COUNT(*)
            FROM predictions p
            JOIN candles c ON c.id = p.candle_id
            JOIN assets a ON a.id = c.asset_id
            WHERE
        """ + condiciones, (now,)).fetchone()[0]

        filas = conexion.execute("""
            SELECT
                p.id,
                p.candle_id,
                p.model_version,
                p.predicted_return,
                p.predicted_price,
                p.target_open_time,
                p.target_close_time,
                p.created_at,
                p.inference_ms,
                c.open_time AS reference_open_time,
                c.close AS reference_close,
                t.close AS observed_close
            FROM predictions p
            JOIN candles c ON c.id = p.candle_id
            JOIN assets a ON a.id = c.asset_id
            LEFT JOIN candles t
                ON t.asset_id = c.asset_id
                AND t.interval_seconds = c.interval_seconds
                AND t.open_time = p.target_open_time
                AND t.close_time = p.target_close_time
                AND t.close_time <= ?
            WHERE
        """ + condiciones + """
            ORDER BY c.open_time DESC, p.id DESC
            LIMIT ? OFFSET ?
        """, (
            now,
            now,
            limit,
            offset
        )).fetchall()

        resultados = []

        for fila in filas:

            observado = fila["observed_close"]

            retorno_real = (
                (observado / fila["reference_close"] - 1) * 100
                if observado is not None
                else None
            )

            retorno_predicho = (
                fila["predicted_return"] * 100
            )

            if observado is not None:

                estado = "OBSERVED"

            elif now < fila["target_close_time"]:

                estado = "PENDING"

            else:

                estado = "WAITING_SYNC"

            resultados.append({
                "id": fila["id"],
                "symbol": "BTCUSDT",
                "model_version": fila["model_version"],
                "reference_date": utc(
                    fila["reference_open_time"]
                )[:10],
                "reference_close": fila["reference_close"],
                "predicted_price": fila["predicted_price"],
                "predicted_return_pct": retorno_predicho,
                "generated_at_utc": utc(fila["created_at"]),
                "target_open_utc": utc(
                    fila["target_open_time"]
                ),
                "target_close_utc": utc(
                    fila["target_close_time"]
                ),
                "inference_ms": fila["inference_ms"],
                "observed_close": observado,
                "observed_return_pct": retorno_real,
                "absolute_error_pp": (
                    abs(retorno_real - retorno_predicho)
                    if retorno_real is not None
                    else None
                ),
                "observation_status": estado
            })

    return {
        "symbol": "BTCUSDT",
        "total": total,
        "returned": len(resultados),
        "offset": offset,
        "has_more": offset + len(resultados) < total,
        "predictions": resultados,
        "as_of_utc": utc(now),
        "data_type": "stored_application_predictions",
        "real_trading": False
    }


@router.get("/predictions/history")
def history_endpoint(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1000000)
):

    return prediction_history(
        limit=limit,
        offset=offset
    )
