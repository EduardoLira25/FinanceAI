import asyncio

import httpx
import pytest

from backend.app import dashboard_gateway as gateway


KEY = "b" * 64

HEADERS = {
    "Origin": gateway.ORIGIN,
    "X-FinanceAI-Client": "browser",
    "Sec-Fetch-Site": "same-origin"
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

        assert request.method == "POST"

        assert request.url.host == "127.0.0.1"

        assert request.url.port == 8000

        assert request.headers["X-API-Key"] == KEY

        return httpx.Response(
            200,
            json={
                "status": "ACTIVE",
                "real_trading": False,
                "changed": True
            }
        )

    app = gateway.create_app(
        transport=httpx.MockTransport(upstream)
    )

    def enviar(
        path="/control/agent/activate",
        headers=None,
        body=None,
        method="POST"
    ):

        async def consultar():

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=gateway.ORIGIN
            ) as cliente:

                return await cliente.request(
                    method,
                    path,
                    headers=(
                        HEADERS if headers is None
                        else headers
                    ),
                    json=(
                        {"confirm": "PAPER_ONLY"}
                        if body is None else body
                    )
                )

        return asyncio.run(consultar())

    return enviar, llamadas


@pytest.mark.parametrize("action", [
    "activate", "pause", "stop", "run"
])
def test_control_permitido(client, action):

    enviar, llamadas = client

    response = enviar(
        "/control/agent/" + action
    )

    assert response.status_code == 200

    assert KEY not in response.text

    assert len(llamadas) == 1

    assert llamadas[0].url.path == (
        "/api/v1/agent/control/" + action
    )


@pytest.mark.parametrize("headers", [
    {"X-FinanceAI-Client": "browser"},
    {**HEADERS, "Origin": "https://example.com"},
    {**HEADERS, "Sec-Fetch-Site": "cross-site"},
    {**HEADERS, "X-FinanceAI-Client": "invalid"},
    {**HEADERS, "Host": "example.com"}
])
def test_origen_bloqueado(client, headers):

    enviar, llamadas = client

    assert enviar(
        headers=headers
    ).status_code == 403

    assert llamadas == []


@pytest.mark.parametrize("body", [
    {},
    {"confirm": "REAL"},
    {"confirm": "PAPER_ONLY", "amount": 1000}
])
def test_confirmacion_invalida(client, body):

    enviar, llamadas = client

    assert enviar(body=body).status_code == 400

    assert llamadas == []


def test_ruta_arbitraria_bloqueada(client):

    enviar, llamadas = client

    assert enviar(
        "/control/agent/unknown"
    ).status_code == 405

    assert llamadas == []


def test_get_no_ejecuta(client):

    enviar, llamadas = client

    assert enviar(method="GET").status_code == 405

    assert llamadas == []


def test_parametros_bloqueados(client):

    enviar, llamadas = client

    assert enviar(
        "/control/agent/run?amount=50000"
    ).status_code == 400

    assert llamadas == []
