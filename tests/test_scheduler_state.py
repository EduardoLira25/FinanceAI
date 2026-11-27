import json
import sqlite3

from datetime import datetime, timezone

import pytest

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.scheduler_state import (
    next_execution,
    read_scheduler_state,
    review_receipt
)

from backend.run_scheduled_agent import (
    run_scheduled
)


def fecha(day=5):

    return datetime(
        2024, 11, day, 0, 10,
        tzinfo=timezone.utc
    )


def launchd_fake():

    return {
        "installed": False,
        "loaded": False,
        "configuration_matches": False,
        "inspection_available": True,
        "enabled": False
    }


@pytest.fixture
def db(tmp_path):

    destino = tmp_path / "test.db"

    with read_connection() as source:

        target = sqlite3.connect(destino)

        try:

            source.backup(target)

        finally:

            target.close()

    return destino


def crear_registro(carpeta, status="STARTED"):

    ruta = carpeta / "2024-11-05.json"

    ruta.write_text(json.dumps({
        "date_utc": "2024-11-05",
        "status": status,
        "real_trading": False
    }))

    return ruta


def runner():

    return {
        "status": "PAUSED",
        "executed": False,
        "real_trading": False
    }


def test_siguiente_ejecucion():

    assert next_execution(
        fecha()
    ) == "2024-11-06T00:05:00+00:00"


def test_estado_sin_instalar(tmp_path):

    estado = read_scheduler_state(
        tmp_path,
        launchd_probe=launchd_fake
    )

    assert not estado["scheduler_enabled"]
    assert not estado["review_required"]
    assert estado["latest_attempt"] is None


def test_estado_interrumpido(tmp_path):

    crear_registro(tmp_path)

    estado = read_scheduler_state(
        tmp_path,
        launchd_probe=launchd_fake
    )

    assert estado["review_required"]

    assert estado["pending_receipts"] == [
        "2024-11-05"
    ]


def test_registro_corrupto(tmp_path):

    ruta = tmp_path / "2024-11-05.json"

    ruta.write_text("JSON invalido")

    estado = read_scheduler_state(
        tmp_path,
        launchd_probe=launchd_fake
    )

    assert estado["review_required"]

    assert estado["latest_attempt"]["status"] == (
        "INVALID_RECEIPT"
    )


@pytest.mark.parametrize(
    "status",
    ["STARTED", "FAILED"]
)
def test_revision_conserva_registro(
    tmp_path, db, status
):

    ruta = crear_registro(tmp_path, status)

    anterior = json.loads(ruta.read_text())

    resultado = review_receipt(
        "2024-11-05",
        "Revision manual del intento.",
        state_dir=tmp_path,
        db=db
    )

    revisado = json.loads(ruta.read_text())

    assert resultado["status"] == "REVIEWED"

    assert resultado["execution_started"] is False

    assert revisado["original_receipt"] == anterior

    assert revisado["status"] == "REVIEWED"

    assert not revisado["automatic_retry"]

    mismo_dia = run_scheduled(
        tmp_path,
        now=fecha(),
        runner=runner
    )

    assert mismo_dia["status"] == "ALREADY_ATTEMPTED"

    siguiente = run_scheduled(
        tmp_path,
        now=fecha(day=6),
        runner=runner
    )

    assert siguiente["status"] == "FINISHED"


def test_revision_cartera_activa(tmp_path, db):

    ruta = crear_registro(tmp_path)

    with write_transaction(db) as c:

        c.execute("""
            UPDATE portfolio
            SET status = 'ACTIVE'
        """)

    with pytest.raises(RuntimeError):

        review_receipt(
            "2024-11-05",
            "Revision manual del intento.",
            state_dir=tmp_path,
            db=db
        )

    assert json.loads(
        ruta.read_text()
    )["status"] == "STARTED"


def test_revision_incidentes_pendientes(
    tmp_path, db
):

    crear_registro(tmp_path)

    with write_transaction(db) as c:

        c.execute("""
            INSERT INTO error_logs (
                component,
                error_type,
                message
            )
            VALUES (
                'TEST',
                'CONTROLLED_ERROR',
                'Incidente controlado.'
            )
        """)

    with pytest.raises(RuntimeError):

        review_receipt(
            "2024-11-05",
            "Revision manual del intento.",
            state_dir=tmp_path,
            db=db
        )


def test_revision_no_reabre_ciclo_finalizado(
    tmp_path, db
):

    crear_registro(
        tmp_path,
        "FINISHED"
    )

    with pytest.raises(ValueError):

        review_receipt(
            "2024-11-05",
            "Revision manual del intento.",
            state_dir=tmp_path,
            db=db
        )


def test_revision_motivo_obligatorio(
    tmp_path, db
):

    crear_registro(tmp_path)

    with pytest.raises(ValueError):

        review_receipt(
            "2024-11-05",
            "",
            state_dir=tmp_path,
            db=db
        )

