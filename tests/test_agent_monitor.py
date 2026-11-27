import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.main import app

from backend.app.api import agent_monitor


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "agent_monitor.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def test_estado_inicial(db):

    estado = agent_monitor.read_agent_state(db)

    assert estado["portfolio_status"] == "PAUSED"
    assert estado["total_cycles"] == 0
    assert estado["real_trading"] is False


def test_historial_vacio(db):

    historia = agent_monitor.read_decisions(db)

    assert historia["total"] == 0
    assert historia["decisions"] == []


def test_paro_emergencia(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET emergency_stop = 1
        """)

    estado = agent_monitor.read_agent_state(db)

    assert estado["emergency_stop"] is True


def test_incidente_pendiente(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES (
                'AGENT_SUPERVISOR',
                'TEST_ERROR',
                'Incidente controlado'
            )
        """)

    estado = agent_monitor.read_agent_state(db)

    assert estado["pending_incidents"] == 1
    assert estado["recovery_required"] is True


@pytest.mark.parametrize("ruta", [
    "/api/v1/agent/status",
    "/api/v1/agent/decisions"
])
@pytest.mark.parametrize("autenticado", [
    False, True
])
def test_endpoint(ruta, autenticado, monkeypatch):

    async def probe():

        return {
            "available": False,
            "identity_verified": False,
            "status": "OFFLINE"
        }

    monkeypatch.setattr(
        agent_monitor,
        "probe_ollama",
        probe
    )

    async def consultar():

        headers = (
            {"X-API-Key": load_api_key()}
            if autenticado else {}
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=headers
        ) as cliente:

            return await cliente.get(ruta)

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == (
        200 if autenticado else 401
    )

    if autenticado:

        assert respuesta.json()["real_trading"] is False
        assert load_api_key() not in respuesta.text


@pytest.mark.parametrize("estado", [
    "VERIFIED",
    "IDENTITY_MISMATCH",
    "OFFLINE"
])
def test_probe_ollama(estado, monkeypatch):

    cliente_original = httpx.AsyncClient

    def upstream(request):

        assert request.method == "GET"

        assert request.url.host == "127.0.0.1"
        assert request.url.port == 11434

        if estado == "OFFLINE":

            raise httpx.ConnectError(
                "Servidor detenido"
            )

        if request.url.path == "/api/version":

            return httpx.Response(
                200,
                json={
                    "version": agent_monitor.OLLAMA_VERSION
                }
            )

        assert request.url.path == "/api/tags"

        return httpx.Response(
            200,
            json={
                "models": [{
                    "name": agent_monitor.MODEL,
                    "digest": (
                        agent_monitor.MODEL_DIGEST
                        if estado == "VERIFIED"
                        else "0" * 64
                    )
                }]
            }
        )

    def cliente(*args, **kwargs):

        return cliente_original(
            *args,
            transport=httpx.MockTransport(upstream),
            **kwargs
        )

    monkeypatch.setattr(
        agent_monitor.httpx,
        "AsyncClient",
        cliente
    )

    resultado = asyncio.run(
        agent_monitor.probe_ollama()
    )

    assert resultado["status"] == estado
