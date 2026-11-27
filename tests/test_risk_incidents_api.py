import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.api import risk_incidents as service

from backend.app.main import app


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "risk_incidents.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def test_riesgo_vigente(db):

    r = service.risk_overview(db)

    assert r["current"]["max_exposure_pct"] == 25
    assert r["current"]["max_daily_loss_pct"] == 2
    assert r["current"]["max_data_age_seconds"] == 3600
    assert r["current"]["min_order_usdt"] == 10
    assert r["current"]["fee_pct"] == 0
    assert r["exposure_pct"] == 0
    assert r["real_trading"] is False


def test_cartera_pausada(db):

    r = service.risk_overview(db)

    assert "PORTFOLIO_NOT_ACTIVE" in r["known_blockers"]


def test_datos_antiguos(db):

    with read_connection(db) as c:

        cierre = c.execute(
            "SELECT MAX(close_time) FROM candles"
        ).fetchone()[0]

    r = service.risk_overview(
        db, now=cierre + 3601
    )

    assert "STALE_CANDLE" in r["known_blockers"]


def test_limite_temporal_exacto(db):

    with read_connection(db) as c:

        cierre = c.execute(
            "SELECT MAX(close_time) FROM candles"
        ).fetchone()[0]

    r = service.risk_overview(
        db, now=cierre + 3600
    )

    assert "STALE_CANDLE" not in r["known_blockers"]


def test_paro_emergencia(db):

    with write_transaction(db) as c:

        c.execute("""
            UPDATE risk_config
            SET emergency_stop = 1
        """)

    r = service.risk_overview(db)

    assert r["current"]["emergency_stop"] is True
    assert "EMERGENCY_STOP" in r["known_blockers"]


@pytest.fixture
def incidentes(db):

    with write_transaction(db) as c:

        c.execute("""
            INSERT INTO error_logs (
                component, error_type, message,
                cause, corrective_action, resolved
            )
            VALUES (
                'TEST', 'MEXC_TIMEOUT', 'Fallo sintetico',
                'Sin respuesta', 'Revisar conexion', 0
            )
        """)

        c.execute("""
            INSERT INTO error_logs (
                component, error_type, message,
                resolved, resolved_at
            )
            VALUES (
                'TEST', 'OLLAMA_OFFLINE',
                'Fallo sintetico resuelto',
                1, unixepoch()
            )
        """)

    return db


def test_resumen_incidentes(incidentes):

    h = service.incident_history(incidentes)

    assert h["total"] == 2
    assert h["pending"] == 1
    assert h["resolved"] == 1
    assert h["recovery_required"] is True


@pytest.mark.parametrize("status, esperado", [
    ("ALL", 2),
    ("PENDING", 1),
    ("RESOLVED", 1)
])
def test_filtros(incidentes, status, esperado):

    h = service.incident_history(
        incidentes, status=status
    )

    assert h["filtered_total"] == esperado

    assert len(h["incidents"]) == esperado


def test_paginacion(incidentes):

    primera = service.incident_history(
        incidentes, limit=1
    )

    segunda = service.incident_history(
        incidentes, limit=1, offset=1
    )

    assert primera["has_more"] is True
    assert segunda["has_more"] is False

    assert (
        primera["incidents"][0]["id"]
        != segunda["incidents"][0]["id"]
    )


def test_bloqueo_por_incidente(incidentes):

    r = service.risk_overview(incidentes)

    assert "RECOVERY_REQUIRED" in r["known_blockers"]


@pytest.mark.parametrize("ruta", [
    "/api/v1/risk/overview",
    "/api/v1/incidents/history"
])
@pytest.mark.parametrize("auth", [False, True])
def test_autenticacion(db, monkeypatch, ruta, auth):

    monkeypatch.setattr(service, "DATABASE_PATH", db)

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

            return await cliente.get(ruta)

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == (
        200 if auth else 401
    )

    if auth:

        assert respuesta.json()["real_trading"] is False

        assert load_api_key() not in respuesta.text
