import asyncio
import hashlib

import httpx
import pytest

from backend.app.main import app
from backend.app.core.config import load_api_key
from backend.app.core.database import read_connection


def solicitar(ruta, autenticado=True, key=None):

    async def ejecutar():

        headers = {}

        if autenticado:

            headers["X-API-Key"] = (
                load_api_key() if key is None else key
            )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver"
        ) as cliente:

            return await cliente.get(
                ruta,
                headers=headers
            )

    return asyncio.run(ejecutar())


def huella_database():

    with read_connection() as conexion:

        return hashlib.sha256(
            "\n".join(
                conexion.iterdump()
            ).encode()
        ).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def proteger_database():

    antes = huella_database()

    yield

    assert huella_database() == antes


RUTAS = [
    "/api/v1/market/assets",
    "/api/v1/market/candles",
    "/api/v1/market/latest",
    "/api/v1/risk/config"
]


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_autenticacion(ruta):

    assert solicitar(
        ruta,
        autenticado=False
    ).status_code == 401


@pytest.mark.parametrize("ruta", RUTAS)
def test_clave_incorrecta(ruta):

    assert solicitar(
        ruta,
        key="incorrecta"
    ).status_code == 401


def test_activos_disponibles():

    respuesta = solicitar("/api/v1/market/assets")

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["total"] >= 1

    assert any(
        a["symbol"] == "BTCUSDT"
        and a["exchange"] == "MEXC"
        and a["active"] is True
        for a in datos["assets"]
    )


def test_velas_historicas():

    respuesta = solicitar("/api/v1/market/candles")

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["total"] >= 2520
    assert datos["returned"] == 100
    assert datos["interval"] == "1d"
    assert datos["timezone"] == "UTC"
    assert datos["has_more"] is True

    for vela in datos["candles"]:

        assert vela["close"] > 0

        assert (
            vela["high"]
            >= max(vela["open"], vela["close"])
        )

        assert (
            vela["close_time"] - vela["open_time"]
            == 86400
        )


def test_paginacion():

    primera = solicitar(
        "/api/v1/market/candles?limit=20"
    ).json()

    segunda = solicitar(
        "/api/v1/market/candles?limit=20&offset=20"
    ).json()

    ids_primera = {
        v["id"] for v in primera["candles"]
    }

    ids_segunda = {
        v["id"] for v in segunda["candles"]
    }

    assert len(ids_primera) == 20
    assert len(ids_segunda) == 20
    assert not ids_primera.intersection(ids_segunda)

    assert (
        primera["candles"][-1]["open_time"]
        > segunda["candles"][0]["open_time"]
    )


def test_filtro_fechas():

    respuesta = solicitar(
        "/api/v1/market/candles"
        "?start_date=2020-01-01"
        "&end_date=2020-01-10"
    )

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["total"] == 10
    assert datos["returned"] == 10
    assert datos["candles"][0]["date"] == "2020-01-10"
    assert datos["candles"][-1]["date"] == "2020-01-01"


def test_rango_fechas_invalido():

    assert solicitar(
        "/api/v1/market/candles"
        "?start_date=2021-01-01"
        "&end_date=2020-01-01"
    ).status_code == 422


@pytest.mark.parametrize("limite", [0, 1001])
def test_limite_invalido(limite):

    assert solicitar(
        f"/api/v1/market/candles?limit={limite}"
    ).status_code == 422


def test_fecha_invalida():

    assert solicitar(
        "/api/v1/market/candles?start_date=incorrecta"
    ).status_code == 422


@pytest.mark.parametrize("ruta", [
    "/api/v1/market/candles",
    "/api/v1/market/latest"
])
def test_activo_inexistente(ruta):

    assert solicitar(
        ruta + "?symbol=INVALIDO"
    ).status_code == 404


def test_ultima_vela():

    respuesta = solicitar("/api/v1/market/latest")

    assert respuesta.status_code == 200

    datos = respuesta.json()

    historial = solicitar(
        "/api/v1/market/candles?limit=1"
    ).json()

    assert datos["candle"] == historial["candles"][0]
    assert datos["data_type"] == "stored_history"


def test_configuracion_riesgo():

    respuesta = solicitar("/api/v1/risk/config")

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["max_exposure_pct"] == 25
    assert datos["max_daily_loss_pct"] == 2
    assert datos["min_order_usdt"] == 10
    assert datos["fee_pct"] == 0
    assert datos["prediction_threshold"] == 0.001
    assert datos["emergency_stop"] is False
    assert datos["real_trading"] is False
    assert datos["risk_engine_ready"] is False
