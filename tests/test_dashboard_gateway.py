import asyncio

import httpx
import pytest

from backend.app import dashboard_gateway as gateway


KEY = "a" * 64

HEADERS = {
    "X-FinanceAI-Client": "browser"
}


@pytest.fixture
def client(monkeypatch):

    llamadas = []

    monkeypatch.setattr(
        gateway,
        "load_api_key",
        lambda: KEY
    )

    def upstream(request):

        llamadas.append(request)

        assert request.url.host == "127.0.0.1"

        assert request.url.port == 8000

        assert request.method == "GET"

        assert request.headers["X-API-Key"] == KEY

        if request.url.path.endswith("/model/status"):

            return httpx.Response(
                200,
                json={"secret": KEY}
            )

        return httpx.Response(
            200,
            json={
                "status": "ok",
                "real_trading": False
            }
        )

    app = gateway.create_app(
        transport=httpx.MockTransport(upstream)
    )

    def solicitar(method, path, **kwargs):

        async def ejecutar():

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=gateway.ORIGIN
            ) as session:

                return await session.request(
                    method, path, **kwargs
                )

        return asyncio.run(ejecutar())

    return solicitar, llamadas


def test_consulta_autenticada(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status",
        headers=HEADERS
    )

    assert response.status_code == 200

    assert response.json()["real_trading"] is False

    assert len(llamadas) == 1

    assert KEY not in response.text

    assert response.headers["cache-control"] == "no-store"


def test_sin_encabezado(client):

    solicitar, llamadas = client

    assert solicitar(
        "GET", "/bridge/status"
    ).status_code == 403

    assert llamadas == []


def test_origen_externo(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status",
        headers={
            **HEADERS,
            "Origin": "https://example.com"
        }
    )

    assert response.status_code == 403

    assert llamadas == []


def test_host_externo(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status",
        headers={
            **HEADERS,
            "Host": "example.com"
        }
    )

    assert response.status_code == 403

    assert llamadas == []


def test_fetch_cross_site(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status",
        headers={
            **HEADERS,
            "Sec-Fetch-Site": "cross-site"
        }
    )

    assert response.status_code == 403

    assert llamadas == []


def test_otro_puerto_local(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status",
        headers={
            **HEADERS,
            "Origin": "http://127.0.0.1:9999"
        }
    )

    assert response.status_code == 403

    assert llamadas == []


@pytest.mark.parametrize("method", [
    "POST", "PUT", "DELETE", "PATCH", "OPTIONS"
])
def test_metodos_bloqueados(client, method):

    solicitar, llamadas = client

    response = solicitar(
        method,
        "/bridge/status",
        headers=HEADERS
    )

    assert response.status_code == 405

    assert llamadas == []


@pytest.mark.parametrize("ruta", [
    "/bridge/predictions/generate",
    "/bridge/orders",
    "/bridge/agent/start",
    "/bridge/unknown"
])
def test_rutas_bloqueadas(client, ruta):

    solicitar, llamadas = client

    assert solicitar(
        "GET", ruta, headers=HEADERS
    ).status_code == 404

    assert llamadas == []


def test_parametros_validos(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/market/candles?limit=10",
        headers=HEADERS
    )

    assert response.status_code == 200

    assert llamadas[0].url.params["limit"] == "10"


def test_parametros_no_autorizados(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/status?secret=true",
        headers=HEADERS
    )

    assert response.status_code == 400

    assert llamadas == []


def test_parametros_duplicados(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/market/candles?limit=1&limit=2",
        headers=HEADERS
    )

    assert response.status_code == 400

    assert llamadas == []


def test_filtracion_bloqueada(client):

    solicitar, llamadas = client

    response = solicitar(
        "GET",
        "/bridge/model/status",
        headers=HEADERS
    )

    assert response.status_code == 502

    assert KEY not in response.text


@pytest.mark.parametrize(
    "ruta",
    gateway.PAGE_ROUTES
)
def test_paginas_disponibles(client, ruta):

    solicitar, llamadas = client

    response = solicitar("GET", ruta)

    assert response.status_code == 200

    assert "FinanceAI" in response.text

    assert KEY not in response.text

    assert llamadas == []
