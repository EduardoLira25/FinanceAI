import json
import time

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, ConfigDict

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.security import verify_api_key

from backend.app.core.database import write_transaction

from backend.app.services.agent_cycle import (
    cycle_lock,
    run_once
)

from backend.app.services.agent_supervisor import (
    run_guarded,
    supervisor_lock_path
)

from backend.app.services.agent_context import temporary_ollama

from backend.app.services.ollama_client import OllamaClient


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
    tags=["Agent Control"]
)


class ControlError(RuntimeError):
    pass


class Confirmation(BaseModel):

    model_config = ConfigDict(extra="forbid")

    confirm: Literal["PAPER_ONLY"]


def change_status(action, path=DATABASE_PATH):

    if action not in ("activate", "pause", "stop"):

        raise ControlError("Accion incompatible.")

    if action == "activate":

        # No reactivar mientras existe un ciclo
        # supervisado en ejecucion.

        with cycle_lock(
            supervisor_lock_path(path)
        ) as acquired:

            if not acquired:

                raise ControlError(
                    "El supervisor esta ocupado."
                )

            return update_status(action, path)

    # Pausar y detener no esperan a la inferencia.
    # SQLite serializa los cambios con la ejecucion.

    return update_status(action, path)


def update_status(action, path):

    with write_transaction(path) as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
              AND strategy = 'LLM'
              AND currency = 'USDT'
        """).fetchone()

        if cartera is None:

            raise ControlError(
                "Cartera paper no disponible."
            )

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        if riesgo is None:

            raise ControlError(
                "Configuracion de riesgo ausente."
            )

        anterior = cartera["status"]

        emergency = bool(riesgo["emergency_stop"])

        if action == "activate":

            if anterior == "STOPPED" or emergency:

                raise ControlError(
                    "Existe un paro de emergencia."
                )

            pendientes = conexion.execute("""
                SELECT COUNT(*)
                FROM error_logs
                WHERE resolved = 0
            """).fetchone()[0]

            incompletos = conexion.execute("""
                SELECT COUNT(*)
                FROM agent_cycles
                WHERE portfolio_id = ?
                  AND status NOT IN (
                    'COMPLETED', 'REJECTED'
                  )
            """, (cartera["id"],)).fetchone()[0]

            if pendientes or incompletos:

                raise ControlError(
                    "Se requiere recuperacion manual."
                )

            nuevo = "ACTIVE"

        elif action == "pause":

            nuevo = (
                "STOPPED"
                if anterior == "STOPPED"
                else "PAUSED"
            )

        else:

            nuevo = "STOPPED"

            if not emergency:

                # Crear nueva version de riesgo.
                # No modificar versiones historicas.

                conexion.execute("""
                    INSERT INTO risk_config (
                        portfolio_id,
                        version,
                        max_exposure_bps,
                        max_daily_loss_bps,
                        max_data_age_seconds,
                        min_order_micros,
                        fee_bps,
                        slippage_bps,
                        prediction_threshold,
                        emergency_stop
                    )
                    SELECT
                        portfolio_id,
                        version + 1,
                        max_exposure_bps,
                        max_daily_loss_bps,
                        max_data_age_seconds,
                        min_order_micros,
                        fee_bps,
                        slippage_bps,
                        prediction_threshold,
                        1
                    FROM risk_config
                    WHERE id = ?
                """, (riesgo["id"],))

                emergency = True

        changed = (
            nuevo != anterior
            or emergency != bool(
                riesgo["emergency_stop"]
            )
        )

        if changed:

            conexion.execute("""
                UPDATE portfolio
                SET status = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                nuevo,
                int(time.time()),
                cartera["id"]
            ))

            conexion.execute("""
                INSERT INTO system_logs (
                    level,
                    component,
                    message
                )
                VALUES (?, 'AGENT_CONTROL', ?)
            """, (
                "WARNING" if action == "stop" else "INFO",
                json.dumps({
                    "action": action,
                    "previous_status": anterior,
                    "new_status": nuevo,
                    "emergency_stop": emergency,
                    "mode": "PAPER_LIVE"
                })
            ))

    return {
        "status": nuevo,
        "changed": changed,
        "emergency_stop": emergency,
        "execution_started": False,
        "real_trading": False
    }


def run_with_ollama(client, *, path):

    # Esta funcion se ejecuta dentro del supervisor.
    # Sus fallos se registran y provocan una pausa.

    with temporary_ollama(
        BASE_DIR / "results/agent_manual_ollama.log"
    ):

        with OllamaClient() as cliente:

            return run_once(
                cliente,
                path=path
            )


def run_manual_cycle(path=DATABASE_PATH):

    return run_guarded(
        None,
        path=path,
        runner=run_with_ollama
    )


@router.post("/agent/control/{action}")
def control_endpoint(
    action: Literal[
        "activate", "pause", "stop", "run"
    ],
    confirmation: Confirmation
):

    try:

        if action == "run":

            return run_manual_cycle(DATABASE_PATH)

        return change_status(
            action,
            DATABASE_PATH
        )

    except ControlError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error)
        ) from None

    except Exception:

        raise HTTPException(
            status_code=503,
            detail=(
                "Control interrumpido. "
                "Revisar el estado del agente."
            )
        ) from None
