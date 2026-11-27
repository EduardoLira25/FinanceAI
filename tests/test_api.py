import asyncio

import httpx
import pytest

from backend.app.main import app
from backend.app.core.config import load_api_key


def solicitar(ruta, key=None):

    async def ejecutar():

        headers = {}

        if key is not None:

            headers["X-API-Key"] = key

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver"
        ) as cliente:

            return await cliente.get(
                ruta,
                headers=headers
            )

    return asyncio.run(ejecutar())


def test_root():

    respuesta = solicitar("/")

    assert respuesta.status_code == 200
    assert respuesta.json()["project"] == "FinanceAI"


def test_health():

    respuesta = solicitar("/health")

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"


def test_ruta_inexistente():

    assert solicitar("/inexistente").status_code == 404


@pytest.mark.parametrize("ruta", [
    "/api/v1/status",
    "/api/v1/database/status",
    "/api/v1/model/status",
    "/api/v1/portfolio"
])
def test_rutas_privadas_sin_clave(ruta):

    assert solicitar(ruta).status_code == 401


@pytest.mark.parametrize("ruta", [
    "/api/v1/status",
    "/api/v1/database/status",
    "/api/v1/model/status",
    "/api/v1/portfolio"
])
def test_rutas_privadas_clave_incorrecta(ruta):

    assert solicitar(
        ruta,
        "clave_incorrecta"
    ).status_code == 401


def test_estado_sistema():

    respuesta = solicitar(
        "/api/v1/status",
        load_api_key()
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    assert respuesta.json()["real_trading"] is False


def test_estado_database():

    respuesta = solicitar(
        "/api/v1/database/status",
        load_api_key()
    )

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["tables"] == 13
    assert datos["historical_candles"] >= 2520
    assert datos["foreign_keys"] is True


def test_estado_modelo():

    respuesta = solicitar(
        "/api/v1/model/status",
        load_api_key()
    )

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["version"] == "1.0.0"
    assert datos["window_size"] == 20
    assert datos["feature_count"] == 3
    assert datos["integrity_verified"] is True


def test_cartera():

    respuesta = solicitar(
        "/api/v1/portfolio",
        load_api_key()
    )

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["initial_cash"] == 50000
    assert datos["cash"] == 50000
    assert datos["status"] == "PAUSED"
    assert datos["real_trading"] is False
    assert len(datos["positions"]) == 1
    assert datos["positions"][0]["quantity"] == 0


def test_documentacion():

    assert solicitar("/docs").status_code == 200


def test_clave_no_expuesta():

    clave = load_api_key()

    respuesta = solicitar(
        "/api/v1/status",
        clave
    )

    assert clave not in respuesta.text
    assert clave not in str(respuesta.headers)


def test_sin_rutas_operaciones_reales():

    esquema = app.openapi()

    for ruta in esquema["paths"]:

        assert "withdraw" not in ruta.lower()
        assert "real_order" not in ruta.lower()
