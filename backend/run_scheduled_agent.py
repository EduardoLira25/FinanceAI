import argparse
import fcntl
import json
import os

from pathlib import Path
from datetime import datetime, timezone


BASE = Path(__file__).resolve().parent.parent
STATE_DIR = BASE / "results/scheduler"

WINDOW_START = 5
WINDOW_END = 45


def utc_now():

    return datetime.now(timezone.utc)


def normalize_time(now):

    if now.tzinfo is None:
        raise ValueError("Se requiere fecha con zona horaria.")

    return now.astimezone(timezone.utc)


def inside_window(now):

    now = normalize_time(now)

    minute = now.hour * 60 + now.minute

    return WINDOW_START <= minute < WINDOW_END


def response(status, **kwargs):

    return {
        "status": status,
        "executed": False,
        "real_trading": False,
        **kwargs
    }


def save_receipt(path, data):

    temporary = path.with_suffix(".tmp")

    with temporary.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        )

        file.flush()

        os.fsync(file.fileno())

    os.replace(temporary, path)


def read_receipt(path):

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def scheduled_runner():

    # Importar los servicios financieros solamente
    # cuando realmente corresponda ejecutar un ciclo.

    from backend.app.core.config import DATABASE_PATH

    from backend.app.services.agent_supervisor import (
        run_guarded
    )

    from backend.app.services.agent_cycle import (
        run_once
    )

    from backend.app.services.agent_context import (
        temporary_ollama
    )

    from backend.app.services.ollama_client import (
        OllamaClient
    )

    def runner(client, *, path):

        with temporary_ollama(
            BASE / "results/agent_scheduled_ollama.log"
        ):

            with OllamaClient() as ollama:

                return run_once(
                    ollama,
                    path=path
                )

    # El supervisor verifica el estado de la cartera
    # antes de iniciar Ollama o consultar MEXC.

    return run_guarded(
        None,
        path=DATABASE_PATH,
        runner=runner
    )


def run_scheduled(
    state_dir,
    *,
    now,
    runner
):

    now = normalize_time(now)

    if not inside_window(now):

        return response(
            "OUTSIDE_EXECUTION_WINDOW"
        )

    state_dir = Path(state_dir)

    state_dir.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700
    )

    lock_path = state_dir / "scheduler.lock"

    with lock_path.open("a+") as lock:

        try:

            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

        except BlockingIOError:

            return response(
                "SCHEDULER_BUSY"
            )

        try:

            # No continuar si existe un intento
            # interrumpido o un fallo sin revisar.

            for previous in sorted(
                state_dir.glob("????-??-??.json")
            ):

                try:

                    record = read_receipt(previous)

                    status = record["status"]

                except Exception:

                    return response(
                        "SCHEDULER_REVIEW_REQUIRED",
                        receipt=previous.name
                    )

                if status not in ("FINISHED", "REVIEWED"):

                    return response(
                        "SCHEDULER_REVIEW_REQUIRED",
                        receipt=previous.name
                    )

            day = now.date().isoformat()

            receipt = state_dir / f"{day}.json"

            # Un solo intento automatico por dia,
            # incluso despues de reiniciar el proceso.

            if receipt.exists():

                return response(
                    "ALREADY_ATTEMPTED",
                    date_utc=day
                )

            record = {
                "date_utc": day,
                "started_at_utc": now.isoformat(),
                "status": "STARTED",
                "mode": "PAPER_LIVE",
                "real_trading": False
            }

            # Guardar antes de consultar el mercado.

            save_receipt(receipt, record)

            try:

                result = runner()

                if not isinstance(result, dict):

                    raise ValueError(
                        "Resultado del supervisor invalido."
                    )

                if result.get("real_trading") is not False:

                    raise ValueError(
                        "Modo financiero no autorizado."
                    )

                if not isinstance(
                    result.get("status"), str
                ):

                    raise ValueError(
                        "Estado del supervisor invalido."
                    )

                if not isinstance(
                    result.get("executed"), bool
                ):

                    raise ValueError(
                        "Estado de ejecucion invalido."
                    )

                record.update({
                    "status": "FINISHED",
                    "finished_at_utc":
                        utc_now().isoformat(),
                    "supervisor_status":
                        result["status"],
                    "executed":
                        result["executed"]
                })

                save_receipt(
                    receipt,
                    record
                )

                return response(
                    "FINISHED",
                    supervisor_status=result["status"],
                    executed=result["executed"],
                    date_utc=day
                )

            except Exception as error:

                # Un fallo de infraestructura no se
                # convierte en una decision financiera.

                record.update({
                    "status": "FAILED",
                    "finished_at_utc":
                        utc_now().isoformat(),
                    "error_type":
                        type(error).__name__
                })

                save_receipt(
                    receipt,
                    record
                )

                return response(
                    "SCHEDULER_FAILED",
                    date_utc=day,
                    error_type=type(error).__name__
                )

        finally:

            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_UN
            )


def main():

    parser = argparse.ArgumentParser(
        description="FinanceAI - Programador diario"
    )

    options = parser.add_mutually_exclusive_group(
        required=True
    )

    options.add_argument(
        "--check",
        action="store_true"
    )

    options.add_argument(
        "--run",
        action="store_true"
    )

    args = parser.parse_args()

    now = utc_now()

    if args.check:

        result = response(
            "CHECK_ONLY",
            now_utc=now.isoformat(),
            inside_window=inside_window(now),
            execution_window_utc="00:05-00:45",
            financial_execution=False
        )

    else:

        result = run_scheduled(
            STATE_DIR,
            now=now,
            runner=scheduled_runner
        )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=4
        ),
        flush=True
    )

    return (
        1
        if result["status"] in (
            "SCHEDULER_FAILED",
            "SCHEDULER_REVIEW_REQUIRED"
        )
        else 0
    )


if __name__ == "__main__":

    raise SystemExit(main())

