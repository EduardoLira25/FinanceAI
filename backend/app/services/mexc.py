import json
import math
import time
import requests

from datetime import datetime, timezone

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

BASE_URL = "https://api.mexc.com"
SYMBOL = "BTCUSDT"
INTERVAL = "1d"
DAY = 86400
DAY_MS = DAY * 1000

MAX_ATTEMPTS = 3
MAX_BATCH = 100
MAX_BATCHES = 10


class MarketDataError(RuntimeError):
    pass


def request_json(path, params=None):

    if path not in (
        "/api/v3/time",
        "/api/v3/klines"
    ):
        raise MarketDataError(
            "Endpoint no autorizado."
        )

    for intento in range(MAX_ATTEMPTS):

        try:

            respuesta = requests.get(
                BASE_URL + path,
                params=params,
                timeout=(5, 15),
                allow_redirects=False
            )

        except (
            requests.Timeout,
            requests.ConnectionError
        ):

            if intento == MAX_ATTEMPTS - 1:
                raise MarketDataError(
                    "MEXC no responde."
                ) from None

            time.sleep(2 ** intento)
            continue

        if respuesta.status_code in (418, 429):

            raise MarketDataError(
                "Limite de solicitudes MEXC. "
                "Sincronizacion pausada."
            )

        if respuesta.status_code >= 500:

            if intento == MAX_ATTEMPTS - 1:
                raise MarketDataError(
                    "Servidor MEXC no disponible."
                )

            time.sleep(2 ** intento)
            continue

        if respuesta.status_code != 200:

            raise MarketDataError(
                f"MEXC HTTP {respuesta.status_code}"
            )

        try:
            return respuesta.json()

        except ValueError:

            raise MarketDataError(
                "Respuesta JSON invalida."
            ) from None

    raise MarketDataError(
        "Solicitudes agotadas."
    )


def get_server_time(fetch=request_json):

    datos = fetch("/api/v3/time")

    if not isinstance(datos, dict):

        raise MarketDataError(
            "Hora del servidor invalida."
        )

    valor = datos.get("serverTime")

    if type(valor) is not int or valor <= 0:

        raise MarketDataError(
            "Timestamp MEXC invalido."
        )

    return valor


def normalize_candles(payload, server_ms):

    if not isinstance(payload, list):

        raise MarketDataError(
            "Formato de velas invalido."
        )

    velas = {}

    for fila in payload:

        if not isinstance(fila, list) or len(fila) != 8:

            raise MarketDataError(
                "Estructura OHLCV invalida."
            )

        try:

            if type(fila[0]) is not int:
                raise ValueError()

            if type(fila[6]) is not int:
                raise ValueError()

            apertura_ms = fila[0]
            cierre_original = fila[6]

            cierre_ms = apertura_ms + DAY_MS

            if apertura_ms < 0:
                raise ValueError()

            if apertura_ms % DAY_MS != 0:
                raise ValueError()

            if cierre_original not in (
                cierre_ms,
                cierre_ms - 1
            ):
                raise ValueError()

            valores = tuple(
                float(fila[i])
                for i in (1, 2, 3, 4, 5, 7)
            )

            if not all(
                math.isfinite(v) for v in valores
            ):
                raise ValueError()

            apertura, high, low, close, volume, quote = valores

            if min(apertura, high, low, close) <= 0:
                raise ValueError()

            if high < max(apertura, close, low):
                raise ValueError()

            if low > min(apertura, close, high):
                raise ValueError()

            if volume < 0 or quote < 0:
                raise ValueError()

        except (ValueError, TypeError, OverflowError):

            raise MarketDataError(
                "Vela financiera invalida."
            ) from None

        # Descartar velas aun abiertas

        if cierre_ms > server_ms:
            continue

        registro = (
            apertura_ms // 1000,
            cierre_ms // 1000,
            *valores
        )

        identificador = registro[0]

        if identificador in velas:

            if velas[identificador] != registro:

                raise MarketDataError(
                    "Velas duplicadas inconsistentes."
                )

        velas[identificador] = registro

    return [
        velas[k] for k in sorted(velas)
    ]


def latest_stored(path=DATABASE_PATH):

    with read_connection(path) as conexion:

        fila = conexion.execute("""
            SELECT a.id AS asset_id,
                   c.open_time,
                   c.close_time,
                   c.close
            FROM candles c
            JOIN assets a ON a.id = c.asset_id
            WHERE a.symbol = ?
              AND a.active = 1
              AND a.exchange = 'MEXC'
              AND c.interval_seconds = ?
            ORDER BY c.open_time DESC
            LIMIT 1
        """, (SYMBOL, DAY)).fetchone()

    if fila is None:

        raise MarketDataError(
            "Historial inicial no disponible."
        )

    return dict(fila)


def synchronize(path=DATABASE_PATH, fetch=request_json):

    inicio = time.perf_counter()

    anterior = latest_stored(path)

    asset_id = anterior["asset_id"]

    inicio_ms = anterior["close_time"] * 1000

    server_ms = get_server_time(fetch)

    limite_cerrado = (
        server_ms // DAY_MS
    ) * DAY_MS

    if inicio_ms > limite_cerrado:

        raise MarketDataError(
            "Historial posterior a la hora MEXC."
        )

    pendientes = (
        limite_cerrado - inicio_ms
    ) // DAY_MS

    if pendientes > MAX_BATCH * MAX_BATCHES:

        raise MarketDataError(
            "Historial pendiente excede el limite."
        )

    nuevas = []
    cursor = inicio_ms

    # Descargar sin mantener bloqueada SQLite

    while cursor < limite_cerrado:

        fin = min(
            cursor + MAX_BATCH * DAY_MS,
            limite_cerrado
        )

        payload = fetch(
            "/api/v3/klines",
            {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": cursor,
                "endTime": fin - 1,
                "limit": MAX_BATCH
            }
        )

        lote = normalize_candles(
            payload,
            server_ms
        )

        lote = [
            v for v in lote
            if cursor <= v[0] * 1000 < fin
        ]

        esperadas = list(
            range(
                cursor // 1000,
                fin // 1000,
                DAY
            )
        )

        if [v[0] for v in lote] != esperadas:

            raise MarketDataError(
                "Historial incompleto o discontinuo."
            )

        nuevas.extend(lote)

        cursor = fin

    # Guardar todo dentro de una transaccion atomica

    with write_transaction(path) as conexion:

        ultima = conexion.execute("""
            SELECT MAX(close_time)
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
        """, (asset_id, DAY)).fetchone()[0]

        if ultima != anterior["close_time"]:

            raise MarketDataError(
                "Historial actualizado por otro proceso. "
                "Repetir sincronizacion."
            )

        if nuevas:

            conexion.executemany("""
                INSERT INTO candles (
                    asset_id,
                    interval_seconds,
                    open_time,
                    close_time,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                    source
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MEXC'
                )
            """, [
                (asset_id, DAY, *vela)
                for vela in nuevas
            ])

            conexion.execute("""
                INSERT INTO system_logs (
                    level,
                    component,
                    message
                )
                VALUES ('INFO', 'MEXC', ?)
            """, (
                f"Sincronizacion: {len(nuevas)} velas nuevas",
            ))

        total = conexion.execute("""
            SELECT COUNT(*)
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
        """, (asset_id, DAY)).fetchone()[0]

        ultima = conexion.execute("""
            SELECT open_time, close_time, close
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
            ORDER BY open_time DESC
            LIMIT 1
        """, (asset_id, DAY)).fetchone()

        edad = (
            server_ms / 1000
            - ultima["close_time"]
        )

        resultado = {
            "status": "ok",
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "new_candles": len(nuevas),
            "total_candles": total,
            "latest_candle_date": datetime.fromtimestamp(
                ultima["open_time"],
                timezone.utc
            ).date().isoformat(),
            "latest_close": ultima["close"],
            "data_age_seconds": edad,
            "closed_candles_only": True,
            "real_trading": False,
            "latency_ms": round(
                (time.perf_counter() - inicio) * 1000,
                3
            )
        }

    return resultado


def main():

    print("=" * 60)
    print("FINANCEAI - CONEXION PUBLICA MEXC")
    print("=" * 60)

    try:

        resultado = synchronize()

    except MarketDataError as error:

        print("SINCRONIZACION NO COMPLETADA:", error)
        print("No se habilitaron operaciones financieras.")

        with write_transaction() as conexion:

            conexion.execute("""
                INSERT INTO error_logs (
                    component,
                    error_type,
                    message,
                    corrective_action
                )
                VALUES (
                    'MEXC',
                    'MARKET_DATA_ERROR',
                    ?,
                    'Revision y nuevo intento manual'
                )
            """, (str(error),))

        raise SystemExit(1)

    print(json.dumps(resultado, indent=4))

    # Repetir para verificar que no existan duplicados

    repeticion = synchronize()

    assert repeticion["new_candles"] == 0
    assert (
        repeticion["total_candles"]
        == resultado["total_candles"]
    )

    evidencia = {
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": resultado,
        "Segunda_sincronizacion": repeticion,
        "Idempotencia": True
    }

    (
        BASE_DIR /
        "results/control_integracion_mexc.json"
    ).write_text(
        json.dumps(evidencia, indent=4),
        encoding="utf-8"
    )

    print("\nConexion MEXC: APROBADA")
    print("Velas abiertas almacenadas: NO")
    print("Registros duplicados: NO")
    print("Credenciales MEXC utilizadas: NO")
    print("Operaciones financieras: NO")
    print("Reentrenamiento: NO")
    print("TE reevaluado: NO")
    print("\nPASO 11.6 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
