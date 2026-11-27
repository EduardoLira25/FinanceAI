from dataclasses import replace

import pytest
import requests

from backend.app.services import market_quote

from backend.app.services.market_quote import (
    MarketQuote,
    QuoteError,
    get_latest_quote,
    validate_quote,
    serialize_quote,
    request_json,
    SOURCE
)

NOW = 1700000000000


def fetch_mock(
    trade=None,
    server_time=NOW
):

    if trade is None:

        trade = [{
            "price": "60454.44",
            "qty": "0.01",
            "time": NOW - 500
        }]

    def fetch(path, params=None):

        if path == "/api/v3/time":

            return {
                "serverTime": server_time
            }

        assert path == "/api/v3/trades"

        assert params == {
            "symbol": "BTCUSDT",
            "limit": 1
        }

        return trade

    return fetch


def obtener(**cambios):

    return get_latest_quote(
        fetch=fetch_mock(**cambios),
        clock=lambda: NOW / 1000
    )


def test_cotizacion_valida():

    quote = obtener()

    assert quote.symbol == "BTCUSDT"

    assert quote.price_micros == 60454440000

    assert quote.price_usdt == 60454.44

    assert quote.source == SOURCE

    datos = serialize_quote(quote)

    assert datos["age_seconds_at_receipt"] == 0.5

    assert datos["real_trading"] is False


def test_cotizacion_antigua():

    quote = obtener()

    with pytest.raises(QuoteError) as error:

        validate_quote(
            quote,
            NOW + 60000
        )

    assert error.value.code == "STALE_QUOTE"


def test_cotizacion_futura():

    with pytest.raises(QuoteError) as error:

        obtener(trade=[{
            "price": "60000",
            "qty": "0.01",
            "time": NOW + 1
        }])

    assert error.value.code == "FUTURE_QUOTE"


def test_relojes_desincronizados():

    with pytest.raises(QuoteError) as error:

        obtener(server_time=NOW + 5001)

    assert error.value.code == "CLOCK_SKEW"


@pytest.mark.parametrize("price", [
    "-1", "0", "NaN", "Infinity", "invalido"
])
def test_precio_invalido(price):

    with pytest.raises(QuoteError) as error:

        obtener(trade=[{
            "price": price,
            "qty": "0.01",
            "time": NOW
        }])

    assert error.value.code == "INVALID_QUOTE_PRICE"


def test_cantidad_invalida():

    with pytest.raises(QuoteError):

        obtener(trade=[{
            "price": "60000",
            "qty": "-1",
            "time": NOW
        }])


def test_transaccion_ausente():

    with pytest.raises(QuoteError) as error:

        obtener(trade=[])

    assert error.value.code == "INVALID_TRADE_DATA"


def test_timestamp_invalido():

    with pytest.raises(QuoteError) as error:

        obtener(trade=[{
            "price": "60000",
            "qty": "0.01",
            "time": "1700000000000"
        }])

    assert error.value.code == "INVALID_QUOTE_TIME"


def test_hora_servidor_invalida():

    with pytest.raises(QuoteError) as error:

        obtener(server_time="incorrecto")

    assert error.value.code == "INVALID_SERVER_TIME"


def test_fuente_invalida():

    quote = replace(
        obtener(),
        source="UNKNOWN"
    )

    with pytest.raises(QuoteError):

        validate_quote(quote, NOW)


def test_simbolo_invalido():

    quote = replace(
        obtener(),
        symbol="ETHUSDT"
    )

    with pytest.raises(QuoteError):

        validate_quote(quote, NOW)


def test_consulta_demasiado_lenta(monkeypatch):

    momentos = iter([0, 16])

    monkeypatch.setattr(
        market_quote.time,
        "perf_counter",
        lambda: next(momentos)
    )

    with pytest.raises(QuoteError) as error:

        obtener()

    assert error.value.code == "QUOTE_REQUEST_TOO_SLOW"


def test_endpoint_no_autorizado():

    with pytest.raises(QuoteError) as error:

        request_json("/api/v3/order")

    assert error.value.code == "INVALID_ENDPOINT"


def test_limite_de_solicitudes(monkeypatch):

    llamadas = []

    class Response:

        status_code = 429

    def fake_get(*args, **kwargs):

        llamadas.append(1)

        return Response()

    monkeypatch.setattr(
        requests.Session,
        "get",
        fake_get
    )

    with pytest.raises(QuoteError) as error:

        request_json("/api/v3/trades")

    assert error.value.code == "QUOTE_RATE_LIMIT"

    assert len(llamadas) == 1


def test_timeout_limitado(monkeypatch):

    llamadas = []

    def fake_get(*args, **kwargs):

        llamadas.append(1)

        raise requests.Timeout()

    monkeypatch.setattr(
        requests.Session,
        "get",
        fake_get
    )

    monkeypatch.setattr(
        market_quote.time,
        "sleep",
        lambda segundos: None
    )

    with pytest.raises(QuoteError) as error:

        request_json("/api/v3/time")

    assert error.value.code == "QUOTE_UNAVAILABLE"

    assert len(llamadas) == 3
