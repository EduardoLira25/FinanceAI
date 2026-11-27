import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.api import agent_control as control

from backend.app.main import app

from backend.app.services.agent_cycle import cycle_lock

from backend.app.services.agent_supervisor import (
    supervisor_lock_path
)


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "control.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def test_activar_y_pausar(db):

    resultado = control.change_status(
        "activate", db
    )

    assert resultado["status"] == "ACTIVE"

    assert resultado["execution_started"] is False

    assert control.change_status(
        "pause", db
    )["status"] == "PAUSED"

    with read_connection(db) as conexion:

        assert conexion.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_activacion_idempotente(db):

    control.change_status("activate", db)

    segundo = control.change_status(
        "activate", db
    )

    assert segundo["changed"] is False


def test_paro_emergencia(db):

    control.change_status("activate", db)

    resultado = control.change_status(
        "stop", db
    )

    assert resultado["status"] == "STOPPED"

    assert resultado["emergency_stop"] is True

    with read_connection(db) as conexion:

        versiones = conexion.execute("""
            SELECT version, emergency_stop
            FROM risk_config
            ORDER BY version
        """).fetchall()

        assert len(versiones) == 2

        assert versiones[0]["emergency_stop"] == 0

        assert versiones[1]["emergency_stop"] == 1

    with pytest.raises(control.ControlError):

        control.change_status("activate", db)


def test_pausa_no_desactiva_paro(db):

    control.change_status("stop", db)

    assert control.change_status(
        "pause", db
    )["status"] == "STOPPED"


def test_incidente_bloquea_activacion(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES ('TEST', 'TEST_ERROR', 'Prueba')
        """)

    with pytest.raises(control.ControlError):

        control.change_status("activate", db)


def test_activacion_con_supervisor_ocupado(db):

    with cycle_lock(
        supervisor_lock_path(db)
    ) as acquired:

        assert acquired

        with pytest.raises(control.ControlError):

            control.change_status("activate", db)


def test_ciclo_pausado_no_inicia_ollama(db, monkeypatch):

    def prohibido(*args, **kwargs):

        pytest.fail("No se debia iniciar Ollama")

    monkeypatch.setattr(
        control,
        "run_with_ollama",
        prohibido
    )

    resultado = control.run_manual_cycle(db)

    assert resultado["status"] == "PAUSED"


def test_ciclo_activo_supervisado(db, monkeypatch):

    control.change_status("activate", db)

    llamadas = []

    def simulado(client, *, path):

        llamadas.append(path)

        return {
            "status": "WAITING_NEXT_CANDLE",
            "executed": False,
            "real_trading": False
        }

    monkeypatch.setattr(
        control,
        "run_with_ollama",
        simulado
    )

    resultado = control.run_manual_cycle(db)

    assert resultado["status"] == "WAITING_NEXT_CANDLE"

    assert llamadas == [db]


@pytest.mark.parametrize("auth, body, expected", [
    (False, {"confirm": "PAPER_ONLY"}, 401),
    (True, {}, 422),
    (True, {"confirm": "REAL"}, 422),
    (True, {"confirm": "PAPER_ONLY"}, 200)
])
def test_api_control(
    db, monkeypatch, auth, body, expected
):

    monkeypatch.setattr(
        control,
        "DATABASE_PATH",
        db
    )

    async def consultar():

        headers = (
            {"X-API-Key": load_api_key()}
            if auth else {}
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=headers
        ) as cliente:

            return await cliente.post(
                "/api/v1/agent/control/activate",
                json=body
            )

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == expected

    assert load_api_key() not in respuesta.text
