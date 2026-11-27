import json
import time

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.config import DATABASE_PATH
from backend.app.core.security import verify_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.agent_cycle import cycle_lock

from backend.app.services.agent_supervisor import (
    resume_after_review,
    pending_incidents,
    RecoveryError as SupervisorRecoveryError,
    supervisor_lock_path
)


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
    tags=["Agent Recovery"]
)


class RecoveryError(RuntimeError):
    pass


class RecoveryBody(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        strict=True
    )

    confirm: Literal["PAPER_ONLY"]

    reason: str = Field(
        min_length=10,
        max_length=240
    )

    incident_ids: list[int] = Field(
        max_length=100
    )


def principal(c):

    p = c.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
          AND mode = 'PAPER_LIVE'
          AND strategy = 'LLM'
          AND currency = 'USDT'
    """).fetchone()

    if p is None:

        raise RecoveryError(
            "Cartera principal no disponible."
        )

    r = c.execute("""
        SELECT *
        FROM risk_config
        WHERE portfolio_id = ?
        ORDER BY version DESC
        LIMIT 1
    """, (p["id"],)).fetchone()

    if r is None:

        raise RecoveryError(
            "Configuracion de riesgo no disponible."
        )

    return p, r


def recovery_overview(path=DATABASE_PATH):

    with read_connection(path) as c:

        p, r = principal(c)

        total = c.execute("""
            SELECT COUNT(*)
            FROM error_logs
            WHERE resolved = 0
        """).fetchone()[0]

        elegibles = pending_incidents(c)

        ids = sorted(
            fila["id"] for fila in elegibles
        )

        non_recoverable = total - len(ids)

        ids = ids[:100]

        incomplete = c.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
            WHERE portfolio_id = ?
              AND status NOT IN (
                  'COMPLETED', 'REJECTED'
              )
        """, (p["id"],)).fetchone()[0]

    stopped = (
        p["status"] == "STOPPED"
        or bool(r["emergency_stop"])
    )

    return {
        "portfolio_status": p["status"],
        "emergency_stop": bool(r["emergency_stop"]),
        "pending_incident_ids": ids,
         "pending_count": total,
        "non_recoverable_count": non_recoverable,
        "incomplete_cycles": incomplete,
        "can_recover": (
            p["status"] == "PAUSED"
            and not stopped
            and 0 < total <= 100
            and non_recoverable == 0
            and incomplete == 0
        ),
        "can_reset": stopped,
        "risk_version": r["version"],
        "real_trading": False
    }


def validate_reason(reason):

    reason = reason.strip()

    if not 10 <= len(reason) <= 240:

        raise RecoveryError(
            "Motivo de revision invalido."
        )

    return reason


def recover_incidents(
    incident_ids,
    reason,
    path=DATABASE_PATH
):

    reason = validate_reason(reason)

    if (
        not incident_ids
        or len(incident_ids) > 100
        or len(set(incident_ids)) != len(incident_ids)
        or any(
            type(i) is not int or i <= 0
            for i in incident_ids
        )
    ):

        raise RecoveryError(
            "Identificadores incompatibles."
        )

    estado = recovery_overview(path)

    if not estado["can_recover"]:

        raise RecoveryError(
            "Recuperacion no disponible."
        )

    if set(incident_ids) != set(
        estado["pending_incident_ids"]
    ):

        raise RecoveryError(
            "La lista de incidentes cambio. Actualizar."
        )

    # El supervisor conserva su propia validacion,
    # bloqueo y transaccion de recuperacion.

    try:

        resultado = resume_after_review(
            incident_ids,
            reason,
            path=path
        )

    except SupervisorRecoveryError as error:

        raise RecoveryError(str(error)) from None

    if resultado.get("real_trading") is not False:

        raise RecoveryError(
            "Resultado incompatible."
        )

    return resultado


def reset_emergency(reason, path=DATABASE_PATH):

    reason = validate_reason(reason)

    # No modificar las reglas durante un ciclo activo.

    with cycle_lock(
        supervisor_lock_path(path)
    ) as acquired:

        if not acquired:

            raise RecoveryError(
                "Existe un ciclo supervisado activo."
            )

        with write_transaction(path) as c:

            p, r = principal(c)

            if (
                p["status"] != "STOPPED"
                and not r["emergency_stop"]
            ):

                raise RecoveryError(
                    "No existe un paro activo."
                )

            if r["emergency_stop"]:

                # Crear una nueva version, conservando
                # todos los limites financieros.

                c.execute("""
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
                        0
                    FROM risk_config
                    WHERE id = ?
                """, (r["id"],))

            c.execute("""
                UPDATE portfolio
                SET status = 'PAUSED',
                    updated_at = ?
                WHERE id = ?
            """, (
                int(time.time()),
                p["id"]
            ))

            c.execute("""
                INSERT INTO system_logs (
                    level, component, message
                )
                VALUES (
                    'WARNING',
                    'AGENT_RECOVERY',
                    ?
                )
            """, (
                json.dumps({
                    "action": "RESET_EMERGENCY",
                    "reason": reason,
                    "previous_status": p["status"],
                    "new_status": "PAUSED",
                    "execution_started": False
                }, ensure_ascii=False),
            ))

    return {
        "status": "PAUSED",
        "changed": True,
        "emergency_stop": False,
        "execution_started": False,
        "real_trading": False
    }


@router.get("/agent/recovery/status")
def recovery_endpoint():

    return recovery_overview(DATABASE_PATH)


@router.post("/agent/recovery/{action}")
def recovery_action(
    action: Literal["recover", "reset"],
    body: RecoveryBody
):

    try:

        if action == "recover":

            return recover_incidents(
                body.incident_ids,
                body.reason,
                DATABASE_PATH
            )

        if body.incident_ids:

            raise RecoveryError(
                "Restablecer no resuelve incidentes."
            )

        return reset_emergency(
            body.reason,
            DATABASE_PATH
        )

    except RecoveryError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error)
        ) from None

    except Exception:

        raise HTTPException(
            status_code=503,
            detail=(
                "Recuperacion no confirmada. "
                "Consultar nuevamente el estado."
            )
        ) from None
