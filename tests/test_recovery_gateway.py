import asyncio

import httpx
import pytest

from backend.app import dashboard_gateway as gateway


KEY = "c" * 64

BODY = {
    "confirm": "PAPER_ONLY",
    "reason": "Incidente revisado correctamente.",
    "incident_ids": []
}

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

        assert request.headers["X-API-Key"] == KEY
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 8000

        return httpx.Response(
            200,
            json={
                "status": "PAUSED",
                "real_trading": False
            }
        )

    app = gateway.create_app(
        transport=httpx.MockTransport(upstream)
    )

    def enviar(action, body, headers=HEADERS):

        async def consultar():

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=gateway.ORIGIN
            ) as cliente:

                return await cliente.post(
                    "/control/agent/" + action,
                    json=body,
                    headers=headers
                )

        return asyncio.run(consultar())

    return enviar, llamadas


@pytest.mark.parametrize("action, ids", [
    ("recover", [1, 2]),
    ("reset", [])
])
def test_recuperacion_autorizada(client, action, ids):

    enviar, llamadas = client

    response = enviar(
        action,
        {**BODY, "incident_ids": ids}
    )

    assert response.status_code == 200

    assert llamadas[0].url.path == (
        "/api/v1/agent/recovery/" + action
    )

    assert KEY not in response.text


@pytest.mark.parametrize("body", [
    {"confirm": "REAL"},
    {**BODY, "reason": "corto"},
    {**BODY, "incident_ids": [1, 1]},
    {**BODY, "incident_ids": [True]},
    {**BODY, "incident_ids": []}
])
def test_recuperacion_invalida(client, body):

    enviar, llamadas = client

    assert enviar(
        "recover", body
    ).status_code == 400

    assert llamadas == []


def test_reset_con_incidentes(client):

    enviar, llamadas = client

    assert enviar(
        "reset",
        {**BODY, "incident_ids": [1]}
    ).status_code == 400

    assert llamadas == []


def test_origen_externo_bloqueado(client):

    enviar, llamadas = client

    response = enviar(
        "reset",
        BODY,
        {
            **HEADERS,
            "Origin": "https://example.com"
        }
    )

    assert response.status_code == 403
    assert llamadas == []



def test_motivo_supera_limite(client):

    enviar, llamadas = client

    respuesta = enviar(
        "reset",
        {
            **BODY,
            "reason": "A" * 241
        }
    )

    assert respuesta.status_code == 400
    assert llamadas == []
