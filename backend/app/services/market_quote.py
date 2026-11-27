import json
import time

from dataclasses import dataclass, asdict

from datetime import datetime, timezone

from decimal import Decimal, InvalidOperation

import requests

from backend.app.core.config import BASE_DIR

from backend.app.services.risk import (
    price_to_micros,
    MICROS,
    MAX_QUOTE_AGE_SECONDS
)

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)


BASE_URL = "https://api.mexc.com"

SYMBOL = "BTCUSDT"

SOURCE = "MEXC_RECENT_TRADE"

MAX_ATTEMPTS = 3

MAX_CLOCK_SKEW_MS = 5000

MAX_REQUEST_DURATION_MS = 15000

MAX_AGE_MS = MAX_QUOTE_AGE_SECONDS * 1000

SQLITE_MAX_INTEGER = 2**63 - 1


class QuoteError(RuntimeError):

    def __init__(self, code, message):

        self.code = code

        super().__init__(message)


@dataclass(frozen=True)
class MarketQuote:

    symbol: str

    price_micros: int

    trade_time_ms: int

    server_time_ms: int

    received_at_ms: int

    latency_ms: float

    source: str = SOURCE

    @property
    def price_usdt(self):

        return self.price_micros / MICROS

    @property
    def trade_time(self):

        return self.trade_time_ms // 1000


# 2. Cliente HTTP exclusivamente de lectura

def request_json(path, params=None):

    if path not in (
        "/api/v3/time",
        "/api/v3/trades"
    ):

        raise QuoteError(
            "INVALID_ENDPOINT",
            "Endpoint de mercado no autorizado."
        )

    with requests.Session() as sesion:

        sesion.trust_env = False

        for intento in range(MAX_ATTEMPTS):

            try:

                respuesta = sesion.get(
                    BASE_URL + path,
                    params=params,
                    timeout=(3, 5),
                    allow_redirects=False
                )

            except requests.RequestException:

                if intento + 1 < MAX_ATTEMPTS:

                    time.sleep(2 ** intento)

                    continue

                raise QuoteError(
                    "QUOTE_UNAVAILABLE",
                    "MEXC no responde."
                ) from None

            if respuesta.status_code in (418, 429):

                raise QuoteError(
                    "QUOTE_RATE_LIMIT",
                    "Limite de solicitudes MEXC."
                )

            if (
                respuesta.status_code >= 500
                and intento + 1 < MAX_ATTEMPTS
            ):

                time.sleep(2 ** intento)

                continue

            if respuesta.status_code != 200:

                raise QuoteError(
                    "QUOTE_HTTP_ERROR",
                    f"MEXC HTTP {respuesta.status_code}"
                )

            try:

                return respuesta.json()

            except ValueError:

                raise QuoteError(
                    "INVALID_QUOTE_JSON",
                    "Respuesta MEXC no valida."
                ) from None

    raise QuoteError(
        "QUOTE_UNAVAILABLE",
        "Solicitudes agotadas."
    )


# 3. Validar cotizacion

def validate_quote(quote, now_ms):

    if not isinstance(quote, MarketQuote):

        raise QuoteError(
            "INVALID_QUOTE",
            "Cotizacion incompatible."
        )

    if (
        quote.symbol != SYMBOL
        or quote.source != SOURCE
    ):

        raise QuoteError(
            "INVALID_QUOTE_SOURCE",
            "Fuente o simbolo incompatible."
        )

    if (
        type(quote.price_micros) is not int
        or not 0 < quote.price_micros
            <= SQLITE_MAX_INTEGER
    ):

        raise QuoteError(
            "INVALID_QUOTE_PRICE",
            "Precio de mercado invalido."
        )

    tiempos = (
        quote.trade_time_ms,
        quote.server_time_ms,
        quote.received_at_ms,
        now_ms
    )

    if any(
        type(t) is not int or t <= 0
        for t in tiempos
    ):

        raise QuoteError(
            "INVALID_QUOTE_TIME",
            "Timestamp de mercado invalido."
        )

    if abs(
        quote.server_time_ms
        - quote.received_at_ms
    ) > MAX_CLOCK_SKEW_MS:

        raise QuoteError(
            "CLOCK_SKEW",
            "Diferencia excesiva entre reloj local y MEXC."
        )

    if (
        quote.trade_time_ms > quote.server_time_ms
        or quote.trade_time_ms > quote.received_at_ms
        or quote.received_at_ms > now_ms
    ):

        raise QuoteError(
            "FUTURE_QUOTE",
            "Cotizacion posterior al instante permitido."
        )

    if (
        quote.server_time_ms - quote.trade_time_ms
            > MAX_AGE_MS
        or now_ms - quote.trade_time_ms
            > MAX_AGE_MS
    ):

        raise QuoteError(
            "STALE_QUOTE",
            "Cotizacion demasiado antigua."
        )

    return quote


# 4. Obtener una transaccion reciente

def get_latest_quote(
    fetch=request_json,
    clock=time.time
):

    inicio = time.perf_counter()

    trades = fetch(
        "/api/v3/trades",
        {
            "symbol": SYMBOL,
            "limit": 1
        }
    )

    if (
        not isinstance(trades, list)
        or len(trades) != 1
        or not isinstance(trades[0], dict)
    ):

        raise QuoteError(
            "INVALID_TRADE_DATA",
            "Respuesta de transacciones invalida."
        )

    trade = trades[0]

    timestamp = trade.get("time")

    if type(timestamp) is not int or timestamp <= 0:

        raise QuoteError(
            "INVALID_QUOTE_TIME",
            "Hora de transaccion invalida."
        )

    try:

        raw_price = trade["price"]

        raw_qty = trade["qty"]

        if (
            not isinstance(raw_price, str)
            or not isinstance(raw_qty, str)
        ):

            raise ValueError()

        precio = Decimal(raw_price)

        cantidad = Decimal(raw_qty)

        if (
            not precio.is_finite()
            or not cantidad.is_finite()
            or precio <= 0
            or cantidad <= 0
        ):

            raise ValueError()

        precio_micros = price_to_micros(precio)

        if precio_micros > SQLITE_MAX_INTEGER:

            raise ValueError()

    except (
        InvalidOperation,
        KeyError,
        ValueError,
        TypeError,
        OverflowError,
        RuntimeError
    ):

        raise QuoteError(
            "INVALID_QUOTE_PRICE",
            "Precio o cantidad de mercado invalida."
        ) from None

    # Consultar hora del servidor despues de
    # recibir la transaccion.

    servidor = fetch("/api/v3/time")

    if (
        not isinstance(servidor, dict)
        or type(servidor.get("serverTime")) is not int
    ):

        raise QuoteError(
            "INVALID_SERVER_TIME",
            "Hora del servidor invalida."
        )

    received_at = int(clock() * 1000)

    latency = (
        time.perf_counter() - inicio
    ) * 1000

    if latency > MAX_REQUEST_DURATION_MS:

        raise QuoteError(
            "QUOTE_REQUEST_TOO_SLOW",
            "Consulta de precio demasiado lenta."
        )

    quote = MarketQuote(
        symbol=SYMBOL,
        price_micros=precio_micros,
        trade_time_ms=timestamp,
        server_time_ms=servidor["serverTime"],
        received_at_ms=received_at,
        latency_ms=round(latency, 3)
    )

    return validate_quote(
        quote,
        received_at
    )


# 5. Serializar informacion para futuras
#    operaciones y evidencias

def serialize_quote(quote):

    def fecha(timestamp_ms):

        return datetime.fromtimestamp(
            timestamp_ms / 1000,
            timezone.utc
        ).isoformat()

    return {
        **asdict(quote),
        "price_usdt": quote.price_usdt,
        "trade_time_utc": fecha(
            quote.trade_time_ms
        ),
        "server_time_utc": fecha(
            quote.server_time_ms
        ),
        "received_at_utc": fecha(
            quote.received_at_ms
        ),
        "age_seconds_at_receipt": (
            quote.received_at_ms
            - quote.trade_time_ms
        ) / 1000,
        "price_type": "RECENT_PUBLIC_TRADE",
        "paper_reference_only": True,
        "real_trading": False
    }


# 6. Diagnostico real

def main():

    print("=" * 60)
    print("FINANCEAI - COTIZACION ACTUAL MEXC")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.8.1",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Operaciones_financieras": False
    }

    try:

        quote = get_latest_quote()

        datos = serialize_quote(quote)

        evidencia["Resultado"] = "APROBADO"

        evidencia["Cotizacion"] = datos

        print(json.dumps(
            datos,
            indent=4,
            ensure_ascii=False
        ))

        print("\nPrecio actual de referencia:",
              quote.price_usdt, "USDT")

        print("Antiguedad de transaccion:",
              datos["age_seconds_at_receipt"],
              "segundos")

        print("Latencia de consulta:",
              quote.latency_ms, "ms")

    except QuoteError as error:

        evidencia["Resultado"] = "REVISAR"

        evidencia["Error"] = {
            "code": error.code,
            "message": str(error)
        }

        print("Cotizacion bloqueada:", error.code)

        print(str(error))

    finally:

        assert database_hash() == db_antes

        assert model_hashes() == modelo_antes

        evidencia["Base_datos_intacta"] = True

        evidencia["Modelo_LSTM_intacto"] = True

        ruta = (
            BASE_DIR /
            "results/control_market_quote.json"
        )

        ruta.write_text(
            json.dumps(
                evidencia,
                indent=4,
                ensure_ascii=False,
                allow_nan=False
            ),
            encoding="utf-8"
        )

    print("\nBase de datos intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Credenciales MEXC utilizadas: NO")
    print("Ordenes ejecutadas: NO")
    print("Dinero real utilizado: NO")
    print("Evidencia:", ruta.name)

    if evidencia["Resultado"] != "APROBADO":

        raise SystemExit(1)

    print("\nCotizacion reciente: APROBADA")
    print("Control temporal: APROBADO")
    print("Fuente publica MEXC: VERIFICADA")

    print("\nPASO 12.8.1 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
