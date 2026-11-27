import json
import fcntl
import sqlite3

from datetime import datetime, timezone

import pytest

from backend.run_scheduled_agent import (
    inside_window,
    run_scheduled
)


def fecha(hour=0, minute=5, day=5):

    return datetime(
        2024, 11, day,
        hour, minute,
        tzinfo=timezone.utc
    )


def resultado():

    return {
        "status": "COMPLETED",
        "executed": True,
        "real_trading": False
    }


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (0, 4, False),
        (0, 5, True),
        (0, 44, True),
        (0, 45, False),
        (18, 5, False)
    ]
)
def test_ventana_utc(hour, minute, expected):

    assert inside_window(
        fecha(hour, minute)
    ) is expected


def test_fecha_sin_zona():

    with pytest.raises(ValueError):

        inside_window(
            datetime(2024, 11, 5, 0, 5)
        )


def test_fuera_horario_no_ejecuta(tmp_path):

    carpeta = tmp_path / "scheduler"

    def prohibido():

        pytest.fail("No debe ejecutar.")

    r = run_scheduled(
        carpeta,
        now=fecha(0, 46),
        runner=prohibido
    )

    assert r["status"] == "OUTSIDE_EXECUTION_WINDOW"
    assert r["executed"] is False
    assert not carpeta.exists()


def test_ejecucion_y_persistencia(tmp_path):

    r = run_scheduled(
        tmp_path,
        now=fecha(),
        runner=resultado
    )

    assert r["status"] == "FINISHED"
    assert r["executed"] is True

    registro = json.loads(
        (tmp_path / "2024-11-05.json").read_text()
    )

    assert registro["status"] == "FINISHED"
    assert registro["real_trading"] is False
    assert registro["supervisor_status"] == "COMPLETED"


def test_intento_duplicado(tmp_path):

    llamadas = []

    def runner():

        llamadas.append(1)

        return resultado()

    primero = run_scheduled(
        tmp_path,
        now=fecha(),
        runner=runner
    )

    segundo = run_scheduled(
        tmp_path,
        now=fecha(0, 20),
        runner=runner
    )

    assert primero["status"] == "FINISHED"
    assert segundo["status"] == "ALREADY_ATTEMPTED"
    assert segundo["executed"] is False
    assert len(llamadas) == 1


def test_siguiente_dia(tmp_path):

    primero = run_scheduled(
        tmp_path,
        now=fecha(day=5),
        runner=resultado
    )

    segundo = run_scheduled(
        tmp_path,
        now=fecha(day=6),
        runner=resultado
    )

    assert primero["status"] == "FINISHED"
    assert segundo["status"] == "FINISHED"

    assert len(
        list(tmp_path.glob("*.json"))
    ) == 2


def test_fallo_bloquea_siguiente_intento(tmp_path):

    def fallar():

        raise RuntimeError("Fallo controlado.")

    primero = run_scheduled(
        tmp_path,
        now=fecha(),
        runner=fallar
    )

    segundo = run_scheduled(
        tmp_path,
        now=fecha(day=6),
        runner=resultado
    )

    assert primero["status"] == "SCHEDULER_FAILED"

    assert segundo["status"] == (
        "SCHEDULER_REVIEW_REQUIRED"
    )

    assert segundo["executed"] is False


def test_reinicio_con_intento_interrumpido(tmp_path):

    (tmp_path / "2024-11-05.json").write_text(
        json.dumps({"status": "STARTED"})
    )

    r = run_scheduled(
        tmp_path,
        now=fecha(day=6),
        runner=resultado
    )

    assert r["status"] == "SCHEDULER_REVIEW_REQUIRED"
    assert r["executed"] is False


def test_registro_corrupto(tmp_path):

    (tmp_path / "2024-11-05.json").write_text(
        "JSON invalido"
    )

    r = run_scheduled(
        tmp_path,
        now=fecha(day=6),
        runner=resultado
    )

    assert r["status"] == "SCHEDULER_REVIEW_REQUIRED"


def test_bloqueo_concurrente(tmp_path):

    with (tmp_path / "scheduler.lock").open("a+") as lock:

        fcntl.flock(
            lock.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )

        r = run_scheduled(
            tmp_path,
            now=fecha(),
            runner=resultado
        )

        assert r["status"] == "SCHEDULER_BUSY"

        assert r["executed"] is False


def test_resultado_modo_no_autorizado(tmp_path):

    r = run_scheduled(
        tmp_path,
        now=fecha(),
        runner=lambda: {
            "status": "COMPLETED",
            "real_trading": True,
            "executed": False
        }
    )

    assert r["status"] == "SCHEDULER_FAILED"


def test_supervisor_real_cartera_pausada(tmp_path):

    from backend.app.core.database import (
        read_connection
    )

    from backend.app.services.agent_supervisor import (
        run_guarded
    )

    db = tmp_path / "financeai_test.db"

    # Copiar la base utilizando una conexion
    # de solo lectura sobre la base principal.

    with read_connection() as source:

        target = sqlite3.connect(db)

        try:

            source.backup(target)

        finally:

            target.close()

    def prohibido(*args, **kwargs):

        pytest.fail(
            "Una cartera pausada no debe iniciar Ollama."
        )

    r = run_scheduled(
        tmp_path / "scheduler",
        now=fecha(),
        runner=lambda: run_guarded(
            None,
            path=db,
            runner=prohibido
        )
    )

    assert r["status"] == "FINISHED"

    assert r["executed"] is False

    with read_connection(db) as c:

        assert c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0

        assert c.execute(
            "SELECT COUNT(*) FROM agent_cycles"
        ).fetchone()[0] == 0

        assert c.execute("""
            SELECT status
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()[0] == "PAUSED"

