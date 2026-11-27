import json
import time

from datetime import datetime, timezone

import httpx

from fastapi import APIRouter, Depends, Query

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import read_connection

from backend.app.core.security import verify_api_key

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
    tags=["Agent"]
)


def utc(value):

    if value is None:
        return None

    return datetime.fromtimestamp(
        value,
        timezone.utc
    ).isoformat()


# 2. Consultar estado persistido del agente.

def read_agent_state(path=DATABASE_PATH):

    with read_connection(path) as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
              AND strategy = 'LLM'
              AND currency = 'USDT'
        """).fetchone()

        if cartera is None:

            raise RuntimeError(
                "Cartera principal no disponible."
            )

        portfolio_id = cartera["id"]

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (portfolio_id,)).fetchone()

        if riesgo is None:

            raise RuntimeError(
                "Configuracion de riesgo ausente."
            )

        ciclos = conexion.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
            WHERE portfolio_id = ?
        """, (portfolio_id,)).fetchone()[0]

        completados = conexion.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
            WHERE portfolio_id = ?
              AND status = 'COMPLETED'
        """, (portfolio_id,)).fetchone()[0]

        rechazados = conexion.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
            WHERE portfolio_id = ?
              AND status = 'REJECTED'
        """, (portfolio_id,)).fetchone()[0]

        pendientes = conexion.execute("""
            SELECT COUNT(*)
            FROM error_logs
            WHERE resolved = 0
        """).fetchone()[0]

        ordenes = conexion.execute("""
            SELECT COUNT(*)
            FROM orders o
            JOIN agent_decisions d
                ON d.id = o.decision_id
            JOIN agent_cycles c
                ON c.id = d.cycle_id
            WHERE c.portfolio_id = ?
              AND o.status = 'FILLED'
        """, (portfolio_id,)).fetchone()[0]

        ultimo = conexion.execute("""
            SELECT
                c.id,
                c.status,
                c.finished_at,
                d.proposed_action,
                d.authorized_action
            FROM agent_cycles c
            LEFT JOIN agent_decisions d
                ON d.cycle_id = c.id
            WHERE c.portfolio_id = ?
            ORDER BY c.id DESC
            LIMIT 1
        """, (portfolio_id,)).fetchone()


    from pathlib import Path
    from backend.scheduler_state import read_scheduler_state

    if Path(path).resolve() == Path(DATABASE_PATH).resolve():

        scheduler = read_scheduler_state()

    else:

        # No consultar ni exponer el programador
        # principal desde bases de datos de prueba.

        scheduler = read_scheduler_state(
            Path(path).parent / "scheduler",
            launchd_probe=lambda: {
                "installed": False,
                "loaded": False,
                "configuration_matches": False,
                "inspection_available": True,
                "enabled": False
            }
        )

    scheduler_operational = (
        scheduler["scheduler_enabled"]
        and cartera["status"] == "ACTIVE"
        and not bool(riesgo["emergency_stop"])
        and pendientes == 0
        and not scheduler["review_required"]
    )

    return {
        "portfolio_status": cartera["status"],
        "emergency_stop": bool(riesgo["emergency_stop"]),
        "recovery_required": pendientes > 0,
        "pending_incidents": pendientes,
        "total_cycles": ciclos,
        "completed_cycles": completados,
        "rejected_cycles": rechazados,
        "filled_orders": ordenes,
        "latest_cycle": (
            {
                **dict(ultimo),
                "finished_at_utc": utc(
                    ultimo["finished_at"]
                )
            }
            if ultimo is not None else None
        ),
        "scheduler_enabled": scheduler["scheduler_enabled"],
        "scheduler_operational": scheduler_operational,
        "scheduler": scheduler,
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


# 3. Comprobar Ollama sin iniciar inferencias.

async def probe_ollama():

    resultado = {
        "available": False,
        "identity_verified": False,
        "expected_model": MODEL,
        "expected_version": OLLAMA_VERSION,
        "server_version": None,
        "status": "OFFLINE"
    }

    try:

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:11434",
            timeout=2.0,
            trust_env=False,
            follow_redirects=False
        ) as cliente:

            version = await cliente.get("/api/version")
            version.raise_for_status()

            resultado["available"] = True

            datos = version.json()

            resultado["server_version"] = datos.get(
                "version"
            )

            tags = await cliente.get("/api/tags")
            tags.raise_for_status()

            modelos = tags.json()["models"]

            identidad = any(
                (
                    m.get("name") == MODEL
                    or m.get("model") == MODEL
                )
                and m.get("digest") == MODEL_DIGEST
                for m in modelos
            )

            verificado = (
                identidad
                and resultado["server_version"]
                    == OLLAMA_VERSION
            )

            resultado["identity_verified"] = verificado

            resultado["status"] = (
                "VERIFIED"
                if verificado else "IDENTITY_MISMATCH"
            )

    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError
    ):

        if resultado["available"]:

            resultado["status"] = "CHECK_FAILED"

    return resultado


# 4. Recuperar decisiones de la cartera principal.

def read_decisions(
    path=DATABASE_PATH,
    *,
    limit=100,
    offset=0
):

    with read_connection(path) as conexion:

        filtro = """
            FROM agent_decisions d
            JOIN agent_cycles c
                ON c.id = d.cycle_id
            JOIN portfolio p
                ON p.id = c.portfolio_id
            JOIN candles v
                ON v.id = c.candle_id
            LEFT JOIN orders o
                ON o.decision_id = d.id
            WHERE p.name = 'FinanceAI_Paper'
              AND p.mode = 'PAPER_LIVE'
              AND p.strategy = 'LLM'
        """

        total = conexion.execute(
            "SELECT COUNT(*) " + filtro
        ).fetchone()[0]

        filas = conexion.execute("""
            SELECT
                d.id,
                c.id AS cycle_id,
                c.status AS cycle_status,
                v.open_time,
                d.proposed_action,
                d.authorized_action,
                d.rationale,
                d.risk_approved,
                d.risk_reason,
                d.llm_model,
                d.latency_ms,
                d.created_at,
                o.id AS order_id
        """ + filtro + """
            ORDER BY c.id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

        decisiones = []

        for fila in filas:

            try:

                motivos = json.loads(
                    fila["risk_reason"] or "[]"
                )

                if not isinstance(motivos, list):

                    motivos = []

            except ValueError:

                motivos = [
                    "RISK_REASON_UNAVAILABLE"
                ]

            decisiones.append({
                "id": fila["id"],
                "cycle_id": fila["cycle_id"],
                "cycle_status": fila["cycle_status"],
                "candle_date": utc(
                    fila["open_time"]
                )[:10],
                "proposed_action": fila["proposed_action"],
                "authorized_action": fila["authorized_action"],
                "rationale": fila["rationale"],
                "risk_approved": bool(
                    fila["risk_approved"]
                ),
                "risk_reasons": motivos,
                "llm_model": fila["llm_model"],
                "latency_ms": fila["latency_ms"],
                "created_at_utc": utc(
                    fila["created_at"]
                ),
                "order_id": fila["order_id"]
            })

    return {
        "total": total,
        "returned": len(decisiones),
        "has_more": offset + len(decisiones) < total,
        "decisions": decisiones,
        "mode": "PAPER_LIVE",
        "real_trading": False
    }


@router.get("/agent/status")
async def agent_status():

    estado = read_agent_state()

    estado["ollama"] = await probe_ollama()

    estado["checked_at_utc"] = utc(
        int(time.time())
    )

    return estado


@router.get("/agent/decisions")
def agent_decisions(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1000000)
):

    return read_decisions(
        limit=limit,
        offset=offset
    )
