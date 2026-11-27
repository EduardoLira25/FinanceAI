import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.api import agent_recovery as recovery

from backend.app.api.agent_control import change_status

from backend.app.services.agent_cycle import cycle_lock

from backend.app.services.agent_supervisor import (
    supervisor_lock_path
)

from backend.app.main import app


REASON = (
    "Incidente revisado y causa corregida "
    "durante la prueba controlada."
)


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "recovery.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def generar_incidente_supervisado(db):

    import runpy

    from pathlib import Path

    from backend.app.api.agent_control import (
        change_status
    )

    from backend.app.services.agent_supervisor import (
        pending_incidents
    )

    # Activar exclusivamente la copia temporal.
    # Activar no inicia operaciones financieras.

    activacion = change_status(
        "activate",
        db
    )

    assert activacion["status"] == "ACTIVE"

    assert activacion["execution_started"] is False

    # Reutilizar el fallo controlado original.

    pruebas = runpy.run_path(
        str(
            Path(__file__).with_name(
                "test_agent_supervisor.py"
            )
        )
    )

    fallar = pruebas["fallar"]

    resultado = fallar(db)

    # Comprobar el resultado real del supervisor.

    with read_connection(db) as c:

        cartera = c.execute("""
            SELECT status, cash_micros
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()

        registros = [
            dict(fila)
            for fila in c.execute("""
                SELECT id, component, error_type, resolved
                FROM error_logs
                ORDER BY id
            """).fetchall()
        ]

        pendientes = pending_incidents(c)

        assert len(pendientes) == 1, (
            f"Resultado del fallo: {resultado!r}. "
            f"Estado: {cartera['status']}. "
            f"Registros: {registros!r}"
        )

        assert cartera["status"] == "PAUSED"

        assert cartera["cash_micros"] == 50000000000

        ordenes = c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        assert ordenes == 0

        return pendientes[0]["id"]


@pytest.fixture
def pending(db):

    incident = generar_incidente_supervisado(db)

    return db, incident


def test_estado_inicial(db):

    estado = recovery.recovery_overview(db)

    assert estado["portfolio_status"] == "PAUSED"
    assert estado["pending_count"] == 0
    assert estado["can_recover"] is False
    assert estado["can_reset"] is False


def test_recuperacion_disponible(pending):

    db, incident = pending

    estado = recovery.recovery_overview(db)

    assert estado["pending_incident_ids"] == [incident]
    assert estado["can_recover"] is True


def test_rechazar_lista_incorrecta(pending):

    db, incident = pending

    with pytest.raises(recovery.RecoveryError):

        recovery.recover_incidents(
            [incident + 1000],
            REASON,
            db
        )


def test_rechazar_ids_duplicados(pending):

    db, incident = pending

    with pytest.raises(recovery.RecoveryError):

        recovery.recover_incidents(
            [incident, incident],
            REASON,
            db
        )


def test_recuperar_con_supervisor(pending):

    db, incident = pending

    resultado = recovery.recover_incidents(
        [incident],
        REASON,
        db
    )

    assert resultado["status"] == "ACTIVE"

    assert resultado["execution_started"] is False

    estado = recovery.recovery_overview(db)

    assert estado["pending_count"] == 0

    with read_connection(db) as c:

        fila = c.execute("""
            SELECT resolved, resolved_at
            FROM error_logs
            WHERE id = ?
        """, (incident,)).fetchone()

        assert fila["resolved"] == 1
        assert fila["resolved_at"] is not None

        assert c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_no_recuperar_con_paro(pending):

    db, incident = pending

    change_status("stop", db)

    with pytest.raises(recovery.RecoveryError):

        recovery.recover_incidents(
            [incident], REASON, db
        )


def test_reset_conserva_limites(db):

    change_status("stop", db)

    resultado = recovery.reset_emergency(
        REASON, db
    )

    assert resultado["status"] == "PAUSED"
    assert resultado["execution_started"] is False

    with read_connection(db) as c:

        configs = c.execute("""
            SELECT *
            FROM risk_config
            ORDER BY version
        """).fetchall()

        assert len(configs) == 3

        assert [
            r["emergency_stop"]
            for r in configs
        ] == [0, 1, 0]

        for key in (
            "max_exposure_bps",
            "max_daily_loss_bps",
            "max_data_age_seconds",
            "min_order_micros",
            "fee_bps",
            "slippage_bps",
            "prediction_threshold"
        ):

            assert configs[0][key] == configs[-1][key]

        assert c.execute("""
            SELECT cash_micros
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()[0] == 50000000000

        assert c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_reset_no_elimina_incidentes(pending):

    db, incident = pending

    change_status("stop", db)

    recovery.reset_emergency(REASON, db)

    estado = recovery.recovery_overview(db)

    assert estado["pending_incident_ids"] == [incident]
    assert estado["portfolio_status"] == "PAUSED"


def test_reset_sin_paro(db):

    with pytest.raises(recovery.RecoveryError):

        recovery.reset_emergency(REASON, db)


def test_reset_con_supervisor_ocupado(db):

    change_status("stop", db)

    with cycle_lock(
        supervisor_lock_path(db)
    ) as acquired:

        assert acquired

        with pytest.raises(recovery.RecoveryError):

            recovery.reset_emergency(REASON, db)


def test_motivo_invalido(db):

    change_status("stop", db)

    with pytest.raises(recovery.RecoveryError):

        recovery.reset_emergency("   ", db)


@pytest.mark.parametrize("auth, expected", [
    (False, 401),
    (True, 200)
])
def test_consulta_api(
    db, monkeypatch, auth, expected
):

    monkeypatch.setattr(
        recovery, "DATABASE_PATH", db
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

            return await cliente.get(
                "/api/v1/agent/recovery/status"
            )

    assert asyncio.run(consultar()).status_code == expected


@pytest.mark.parametrize("auth, confirm, expected", [
    (False, "PAPER_ONLY", 401),
    (True, "REAL", 422),
    (True, "PAPER_ONLY", 200)
])
def test_reset_api(
    db, monkeypatch, auth, confirm, expected
):

    change_status("stop", db)

    monkeypatch.setattr(
        recovery, "DATABASE_PATH", db
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
                "/api/v1/agent/recovery/reset",
                json={
                    "confirm": confirm,
                    "reason": REASON,
                    "incident_ids": []
                }
            )

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == expected

    assert load_api_key() not in respuesta.text



def test_limite_real_del_supervisor(pending):

    db, incident = pending

    with pytest.raises(recovery.RecoveryError):

        recovery.recover_incidents(
            [incident],
            "A" * 241,
            db
        )

    assert recovery.recovery_overview(db)[
        "pending_count"
    ] == 1


def test_no_recuperar_incidentes_ajenos(pending):

    db, incident = pending

    with write_transaction(db) as c:

        c.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES (
                'EXTERNAL_TEST',
                'TEST_ERROR',
                'Incidente no supervisado'
            )
        """)

    estado = recovery.recovery_overview(db)

    assert estado["pending_count"] == 2
    assert estado["non_recoverable_count"] == 1
    assert estado["can_recover"] is False

    with pytest.raises(recovery.RecoveryError):

        recovery.recover_incidents(
            [incident],
            REASON,
            db
        )


def test_supervisor_rechaza_incidentes_adicionales(pending):

    db, incident = pending

    from backend.app.services.agent_supervisor import (
        resume_after_review,
        RecoveryError
    )

    with write_transaction(db) as c:

        c.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES (
                'EXTERNAL_TEST',
                'TEST_ERROR',
                'Incidente adicional'
            )
        """)

    with pytest.raises(RecoveryError):

        resume_after_review(
            [incident],
            REASON,
            path=db
        )

    assert recovery.recovery_overview(db)[
        "portfolio_status"
    ] == "PAUSED"
