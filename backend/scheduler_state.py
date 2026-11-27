import argparse
import fcntl
import hashlib
import json
import os
import subprocess

from pathlib import Path
from datetime import date, datetime, timezone, timedelta

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import read_connection

from backend.app.services.agent_supervisor import (
    cycle_lock,
    supervisor_lock_path
)

from backend.run_scheduled_agent import (
    BASE,
    STATE_DIR,
    save_receipt,
    read_receipt,
    utc_now
)

LABEL = "com.financeai.daily"

CONFIG = (
    BASE / "deployment/macos"
    / f"{LABEL}.plist"
)

INSTALLED = (
    Path.home() / "Library/LaunchAgents"
    / f"{LABEL}.plist"
)


def next_execution(now=None):

    now = now or utc_now()

    now = now.astimezone(timezone.utc)

    siguiente = now.replace(
        hour=0,
        minute=5,
        second=0,
        microsecond=0
    )

    if siguiente <= now:

        siguiente += timedelta(days=1)

    return siguiente.isoformat()


def inspect_launchd():

    installed = INSTALLED.is_file()

    matches = (
        installed
        and CONFIG.is_file()
        and INSTALLED.read_bytes()
        == CONFIG.read_bytes()
    )

    try:

        proceso = subprocess.run(
            [
                "/bin/launchctl",
                "print",
                f"gui/{os.getuid()}/{LABEL}"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        loaded = proceso.returncode == 0

        available = True

    except (OSError, subprocess.TimeoutExpired):

        loaded = None

        available = False

    return {
        "installed": installed,
        "configuration_matches": matches,
        "loaded": loaded,
        "inspection_available": available,
        "enabled": bool(
            installed and matches and loaded
        )
    }


def read_scheduler_state(
    state_dir=STATE_DIR,
    *,
    now=None,
    launchd_probe=inspect_launchd
):

    state_dir = Path(state_dir)

    now = now or utc_now()

    launchd = launchd_probe()

    pending = []

    records = []

    for ruta in sorted(
        state_dir.glob("????-??-??.json")
    ):

        try:

            record = read_receipt(ruta)

            status = record["status"]

            if status not in (
                "STARTED",
                "FAILED",
                "FINISHED",
                "REVIEWED"
            ):

                raise ValueError(
                    "Estado desconocido."
                )

            records.append({
                "date_utc": ruta.stem,
                "status": status,
                "started_at_utc": record.get(
                    "started_at_utc"
                ),
                "finished_at_utc": record.get(
                    "finished_at_utc"
                ),
                "supervisor_status": record.get(
                    "supervisor_status"
                ),
                "executed": record.get("executed"),
                "error_type": record.get(
                    "error_type"
                )
            })

            if status in ("STARTED", "FAILED"):

                pending.append(ruta.stem)

        except Exception:

            pending.append(ruta.stem)

            records.append({
                "date_utc": ruta.stem,
                "status": "INVALID_RECEIPT"
            })

    return {
        "installed": launchd["installed"],
        "loaded": launchd["loaded"],
        "configuration_matches":
            launchd["configuration_matches"],
        "inspection_available":
            launchd["inspection_available"],
        "scheduler_enabled": launchd["enabled"],
        "schedule_local": "18:05",
        "schedule_utc": "00:05",
        "execution_window_utc": "00:05-00:45",
        "next_scheduled_at_utc": (
            next_execution(now)
            if launchd["enabled"]
            else None
        ),
        "attempts_per_day": 1,
        "attempts_recorded": len(records),
        "latest_attempt": (
            records[-1] if records else None
        ),
        "review_required": bool(pending),
        "pending_receipts": pending,
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


def review_receipt(
    day,
    reason,
    *,
    state_dir=STATE_DIR,
    db=DATABASE_PATH
):

    fecha = date.fromisoformat(day)

    if fecha.isoformat() != day:

        raise ValueError("Fecha no canonica.")

    if fecha > utc_now().date():

        raise ValueError("Fecha futura.")

    reason = reason.strip()

    if not 10 <= len(reason) <= 240:

        raise ValueError(
            "Motivo requerido: 10 a 240 caracteres."
        )

    state_dir = Path(state_dir)

    if not state_dir.is_dir():

        raise ValueError("No existen registros.")

    ruta = state_dir / f"{day}.json"

    # Mismo bloqueo que utiliza el programador.

    with (state_dir / "scheduler.lock").open("a+") as lock:

        try:

            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

        except BlockingIOError:

            raise RuntimeError(
                "Programador ocupado."
            ) from None

        try:

            # Impedir revision simultanea con el agente.

            with cycle_lock(
                supervisor_lock_path(db)
            ) as acquired:

                if not acquired:

                    raise RuntimeError(
                        "Supervisor ocupado."
                    )

                with read_connection(db) as c:

                    p = c.execute("""
                        SELECT *
                        FROM portfolio
                        WHERE name = 'FinanceAI_Paper'
                          AND mode = 'PAPER_LIVE'
                    """).fetchone()

                    if p is None:

                        raise RuntimeError(
                            "Cartera no disponible."
                        )

                    if p["status"] != "PAUSED":

                        raise RuntimeError(
                            "Primero pausa la cartera."
                        )

                    pendientes = c.execute("""
                        SELECT COUNT(*)
                        FROM error_logs
                        WHERE resolved = 0
                    """).fetchone()[0]

                    if pendientes:

                        raise RuntimeError(
                            "Existen incidentes pendientes."
                        )

                    incompletos = c.execute("""
                        SELECT COUNT(*)
                        FROM agent_cycles
                        WHERE portfolio_id = ?
                          AND status NOT IN (
                              'COMPLETED',
                              'REJECTED'
                          )
                    """, (p["id"],)).fetchone()[0]

                    if incompletos:

                        raise RuntimeError(
                            "Existen ciclos incompletos."
                        )

                contenido = ruta.read_bytes()

                original = json.loads(contenido)

                if original.get("status") not in (
                    "STARTED", "FAILED"
                ):

                    raise ValueError(
                        "Registro no elegible."
                    )

                # Conservar el contenido original.
                # No eliminar el intento ni permitir
                # que se repita en la misma fecha.

                revisado = {
                    **original,
                    "status": "REVIEWED",
                    "reviewed_at_utc":
                        utc_now().isoformat(),
                    "review_reason": reason,
                    "original_sha256":
                        hashlib.sha256(
                            contenido
                        ).hexdigest(),
                    "original_receipt": original,
                    "automatic_retry": False,
                    "real_trading": False
                }

                save_receipt(ruta, revisado)

                return {
                    "status": "REVIEWED",
                    "date_utc": day,
                    "portfolio_status": "PAUSED",
                    "execution_started": False,
                    "automatic_retry": False,
                    "real_trading": False
                }

        finally:

            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_UN
            )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--review",
        metavar="YYYY-MM-DD"
    )

    parser.add_argument("--reason")

    parser.add_argument("--confirm")

    args = parser.parse_args()

    if args.review:

        if args.confirm != "PAPER_ONLY":

            parser.error(
                "Se requiere --confirm PAPER_ONLY"
            )

        resultado = review_receipt(
            args.review,
            args.reason or ""
        )

    else:

        resultado = read_scheduler_state()

    print(json.dumps(
        resultado,
        indent=4,
        ensure_ascii=False,
        allow_nan=False
    ))


if __name__ == "__main__":

    main()

