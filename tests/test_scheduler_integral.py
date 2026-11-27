import json

from datetime import datetime, timezone

from tests.test_agent_cycle import (
    escenario,
    ejecutar,
    contar
)

from backend.run_scheduled_agent import run_scheduled

from backend.app.services.agent_supervisor import (
    run_guarded
)


def test_programador_supervisor_ciclo_integral(
    escenario, tmp_path
):

    db, now = escenario

    fecha = datetime.fromtimestamp(
        now, timezone.utc
    ).replace(
        hour=0,
        minute=5,
        second=0,
        microsecond=0
    )

    llamadas = []

    def runner(client, *, path):

        assert path == db

        llamadas.append(1)

        return ejecutar(
            escenario,
            action="HOLD"
        )

    def supervisor():

        return run_guarded(
            None,
            path=db,
            runner=runner
        )

    carpeta = tmp_path / "scheduler_integral"

    primero = run_scheduled(
        carpeta,
        now=fecha,
        runner=supervisor
    )

    segundo = run_scheduled(
        carpeta,
        now=fecha,
        runner=supervisor
    )

    assert primero["status"] == "FINISHED"

    assert primero["supervisor_status"] == "COMPLETED"

    assert primero["real_trading"] is False

    assert primero["executed"] is False

    assert segundo["status"] == "ALREADY_ATTEMPTED"

    assert len(llamadas) == 1

    assert contar(db, "agent_cycles") == 1

    assert contar(db, "agent_decisions") == 1

    assert contar(db, "orders") == 0

    registro = json.loads(
        (
            carpeta /
            f"{fecha.date().isoformat()}.json"
        ).read_text()
    )

    assert registro["status"] == "FINISHED"

    assert registro["real_trading"] is False

