
import sqlite3

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import load_api_key
from backend.app.core.database import read_connection
from backend.app.api.agent_monitor import read_agent_state
from backend import scheduler_state


def estado_simulado(enabled=True, pending=False):

    return {
        "installed": enabled,
        "loaded": enabled,
        "configuration_matches": enabled,
        "inspection_available": True,
        "scheduler_enabled": enabled,
        "review_required": pending,
        "pending_receipts": [],
        "schedule_local": "18:05",
        "schedule_utc": "00:05",
        "execution_window_utc": "00:05-00:45",
        "attempts_per_day": 1,
        "attempts_recorded": 0,
        "latest_attempt": None,
        "next_scheduled_at_utc": None,
        "real_trading": False,
        "mode": "PAPER_LIVE"
    }


def test_programador_habilitado_cartera_pausada(monkeypatch):

    monkeypatch.setattr(
        scheduler_state,
        "read_scheduler_state",
        lambda: estado_simulado(True)
    )

    estado = read_agent_state()

    assert estado["scheduler_enabled"] is True

    assert estado["portfolio_status"] == "PAUSED"

    assert estado["scheduler_operational"] is False

    assert estado["real_trading"] is False


def test_base_temporal_no_consulta_launchd(tmp_path, monkeypatch):

    db = tmp_path / "test.db"

    with read_connection() as origen:

        destino = sqlite3.connect(db)

        try:
            origen.backup(destino)
        finally:
            destino.close()

    def prohibido():
        raise AssertionError("Consulta inesperada a launchd")

    monkeypatch.setattr(
        scheduler_state,
        "inspect_launchd",
        prohibido
    )

    estado = read_agent_state(db)

    assert estado["scheduler_enabled"] is False

    assert estado["scheduler_operational"] is False

    assert estado["scheduler"]["installed"] is False


def test_endpoint_programador_autenticado(monkeypatch):

    monkeypatch.setattr(
        scheduler_state,
        "read_scheduler_state",
        lambda: estado_simulado(False)
    )

    with TestClient(app) as cliente:

        respuesta = cliente.get(
            "/api/v1/agent/status"
        )

        assert respuesta.status_code == 401

        respuesta = cliente.get(
            "/api/v1/agent/status",
            headers={"X-API-Key": load_api_key()}
        )

        assert respuesta.status_code == 200

        def buscar(obj):

            if isinstance(obj, dict):

                if "scheduler_enabled" in obj:
                    return obj

                for valor in obj.values():

                    encontrado = buscar(valor)

                    if encontrado is not None:
                        return encontrado

            return None

        estado = buscar(respuesta.json())

        assert estado is not None

        assert estado["scheduler_enabled"] is False

        assert estado["scheduler_operational"] is False

        assert estado["scheduler"]["schedule_local"] == "18:05"

        assert estado["scheduler"]["real_trading"] is False
