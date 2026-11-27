import json
import re
import time
import sqlite3
import tempfile

from pathlib import Path
from datetime import datetime, timezone

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.agent_cycle import (
    run_once,
    cycle_lock,
    AgentCycleError
)

from backend.app.services.mexc import MarketDataError

from backend.app.services.prediction import PredictionError

from backend.app.services.ollama_client import OllamaError

from backend.app.services.llm_decision import (
    DecisionError,
    database_hash,
    model_hashes
)

from backend.app.services.market_quote import QuoteError

from backend.app.services.agent_context import AgentContextError

from backend.app.services.agent_risk import AgentRiskError

from backend.app.services.live_paper_trading import LivePaperError

from backend.app.services.risk import RiskError, MICROS


COMPONENT = "AGENT_SUPERVISOR"


class RecoveryError(RuntimeError):

    pass


class SupervisorPersistenceError(RuntimeError):

    pass


# 2. Clasificar incidentes sin exponer secretos

def classify_error(error):

    if isinstance(error, MarketDataError):

        code = (
            "MARKET_RATE_LIMIT"
            if "Limite de solicitudes" in str(error)
            else "MARKET_DATA_ERROR"
        )

        subsystem = "MEXC"

        message = "Fallo en la sincronizacion del mercado."

    elif isinstance(error, OllamaError):

        code = error.code
        subsystem = "OLLAMA"
        message = "Fallo de comunicacion con el LLM."

    elif isinstance(error, DecisionError):

        code = error.code
        subsystem = "LLM_DECISION"
        message = "Propuesta financiera no valida."

    elif isinstance(error, QuoteError):

        code = error.code
        subsystem = "MARKET_QUOTE"
        message = "Cotizacion no disponible o no valida."

    elif isinstance(error, AgentRiskError):

        code = error.code
        subsystem = "AGENT_RISK"
        message = "Fallo de revalidacion financiera."

    elif isinstance(error, PredictionError):

        code = "PREDICTION_ERROR"
        subsystem = "LSTM"
        message = "No fue posible generar una prediccion valida."

    elif isinstance(error, AgentContextError):

        code = "CONTEXT_ERROR"
        subsystem = "AGENT_CONTEXT"
        message = "Contexto financiero no disponible o invalido."

    elif isinstance(error, RiskError):

        code = "RISK_ERROR"
        subsystem = "RISK"
        message = "Fallo en la evaluacion de riesgo."

    elif isinstance(error, LivePaperError):

        code = "PAPER_EXECUTION_ERROR"
        subsystem = "PAPER_TRADING"
        message = "Fallo en la ejecucion simulada."

    elif isinstance(error, AgentCycleError):

        code = "AGENT_CYCLE_ERROR"
        subsystem = "AGENT_CYCLE"
        message = "Fallo en el ciclo operativo."

    elif isinstance(error, sqlite3.Error):

        code = "DATABASE_ERROR"
        subsystem = "SQLITE"
        message = "Fallo de persistencia financiera."

    else:

        code = "UNEXPECTED_ERROR"
        subsystem = "AGENT"
        message = "Error inesperado durante el ciclo."

    if (
        not isinstance(code, str)
        or not re.fullmatch(
            r"[A-Z][A-Z0-9_]{1,63}",
            code
        )
    ):

        code = "UNCLASSIFIED_ERROR"

    return {
        "code": code,
        "subsystem": subsystem,
        "message": message,
        "corrective_action": (
            "Revisar el componente afectado, "
            "verificar integridad y confirmar "
            "recuperacion manual."
        )
    }


# 3. Obtener cartera principal

def get_portfolio(conexion):

    fila = conexion.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
          AND mode = 'PAPER_LIVE'
          AND strategy = 'LLM'
    """).fetchone()

    if fila is None:

        raise RecoveryError(
            "Cartera principal no disponible."
        )

    return fila


def pending_incidents(conexion):

    return conexion.execute("""
        SELECT
            id,
            error_type,
            cause,
            message,
            corrective_action,
            retry_count,
            created_at
        FROM error_logs
        WHERE component = ?
          AND resolved = 0
        ORDER BY id
    """, (COMPONENT,)).fetchall()


# 4. Registrar incidente y pausa de forma atomica

def record_failure(
    error,
    path=DATABASE_PATH
):

    incidente = classify_error(error)

    try:

        with write_transaction(path) as conexion:

            cartera = get_portfolio(conexion)

            now = int(time.time())

            error_id = conexion.execute("""
                INSERT INTO error_logs (
                    component,
                    error_type,
                    message,
                    cause,
                    corrective_action,
                    retry_count,
                    resolved,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, ?)
            """, (
                COMPONENT,
                incidente["code"],
                incidente["message"],
                incidente["subsystem"],
                incidente["corrective_action"],
                now
            )).lastrowid

            # No modificar STOPPED.
            # No desactivar el paro de emergencia.

            conexion.execute("""
                UPDATE portfolio
                SET status = 'PAUSED',
                    updated_at = ?
                WHERE id = ?
                  AND status = 'ACTIVE'
            """, (
                now,
                cartera["id"]
            ))

            estado = conexion.execute("""
                SELECT status
                FROM portfolio
                WHERE id = ?
            """, (cartera["id"],)).fetchone()[0]

            conexion.execute("""
                INSERT INTO system_logs (
                    level,
                    component,
                    message
                )
                VALUES ('ERROR', ?, ?)
            """, (
                COMPONENT,
                json.dumps({
                    "incident_id": error_id,
                    "error_code": incidente["code"],
                    "subsystem": incidente["subsystem"],
                    "portfolio_status": estado,
                    "automatic_retry": False
                })
            ))

    except Exception:

        raise SupervisorPersistenceError(
            "No fue posible persistir el incidente. "
            "Detener el supervisor y revisar SQLite."
        ) from None

    return {
        "status": (
            "PAUSED_ERROR"
            if estado == "PAUSED"
            else estado
        ),
        "incident_id": error_id,
        "error_code": incidente["code"],
        "subsystem": incidente["subsystem"],
        "message": incidente["message"],
        "portfolio_status": estado,
        "automatic_retry": False,
        "recovery_required": True,
        "execution_interrupted": True,
        "real_trading": False
    }


# 5. Bloqueo adicional para el supervisor

def supervisor_lock_path(path):

    ruta = Path(path).resolve()

    return ruta.with_name(
        ruta.name + ".supervisor"
    )


# 6. Verificar incidentes antes de iniciar ciclos

def preflight(path):

    with write_transaction(path) as conexion:

        cartera = get_portfolio(conexion)

        pendientes = pending_incidents(conexion)

        estado = cartera["status"]

        riesgo = conexion.execute("""
            SELECT emergency_stop
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        if riesgo is None:

            raise RecoveryError(
                "Configuracion de riesgo ausente."
            )

        if pendientes and estado == "ACTIVE":

            conexion.execute("""
                UPDATE portfolio
                SET status = 'PAUSED',
                    updated_at = ?
                WHERE id = ?
            """, (
                int(time.time()),
                cartera["id"]
            ))

            estado = "PAUSED"

        if riesgo["emergency_stop"]:

            return {
                "status": "EMERGENCY_STOP",
                "executed": False,
                "real_trading": False
            }

        if pendientes:

            return {
                "status": "RECOVERY_REQUIRED",
                "portfolio_status": estado,
                "pending_incident_ids": [
                    fila["id"]
                    for fila in pendientes
                ],
                "executed": False,
                "real_trading": False
            }

        if estado != "ACTIVE":

            return {
                "status": estado,
                "executed": False,
                "real_trading": False
            }

        return None


# 7. Ejecutar un ciclo supervisado

def run_guarded(
    client,
    *,
    path=DATABASE_PATH,
    runner=run_once,
    **kwargs
):

    with cycle_lock(
        supervisor_lock_path(path)
    ) as adquirido:

        if not adquirido:

            return {
                "status": "SUPERVISOR_BUSY",
                "executed": False,
                "real_trading": False
            }

        try:

            bloqueo = preflight(path)

            if bloqueo is not None:

                return bloqueo

            return runner(
                client,
                path=path,
                **kwargs
            )

        except Exception as error:

            # No repetir automaticamente un ciclo.
            # Los clientes HTTP ya tienen sus propios
            # mecanismos limitados de reintentos.

            return record_failure(
                error,
                path
            )


# 8. Consultar estado de recuperacion

def recovery_status(path=DATABASE_PATH):

    with read_connection(path) as conexion:

        cartera = get_portfolio(conexion)

        pendientes = pending_incidents(conexion)

        return {
            "portfolio_status": cartera["status"],
            "recovery_required": bool(pendientes),
            "pending_incidents": [
                dict(fila)
                for fila in pendientes
            ],
            "automatic_resume": False,
            "real_trading": False
        }


# 9. Recuperacion manual explicitamente confirmada

def resume_after_review(
    incident_ids,
    reason,
    *,
    path=DATABASE_PATH
):

    if (
        not isinstance(incident_ids, (list, tuple))
        or not incident_ids
        or any(
            type(valor) is not int or valor <= 0
            for valor in incident_ids
        )
        or len(set(incident_ids)) != len(incident_ids)
    ):

        raise RecoveryError(
            "Identificadores de incidentes invalidos."
        )

    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 240
    ):

        raise RecoveryError(
            "Se requiere una justificacion de recuperacion."
        )

    with cycle_lock(
        supervisor_lock_path(path)
    ) as adquirido:

        if not adquirido:

            raise RecoveryError(
                "Supervisor ocupado."
            )

        with write_transaction(path) as conexion:

            cartera = get_portfolio(conexion)

            if cartera["status"] != "PAUSED":

                raise RecoveryError(
                    "La cartera debe estar pausada."
                )

            riesgo = conexion.execute("""
                SELECT emergency_stop
                FROM risk_config
                WHERE portfolio_id = ?
                ORDER BY version DESC
                LIMIT 1
            """, (cartera["id"],)).fetchone()

            if riesgo is None or riesgo["emergency_stop"]:

                raise RecoveryError(
                    "Configuracion ausente o paro de emergencia activo."
                )


            # CONTROL ADICIONAL 13.9.2

            todos_pendientes = {
                fila["id"]
                for fila in conexion.execute("""
                    SELECT id
                    FROM error_logs
                    WHERE resolved = 0
                """).fetchall()
            }

            if todos_pendientes != set(incident_ids):

                raise RecoveryError(
                    "Existen incidentes adicionales por revisar."
                )

            incompletos = conexion.execute("""
                SELECT COUNT(*)
                FROM agent_cycles
                WHERE portfolio_id = ?
                  AND status NOT IN (
                      'COMPLETED', 'REJECTED'
                  )
            """, (cartera["id"],)).fetchone()[0]

            if incompletos:

                raise RecoveryError(
                    "Existen ciclos incompletos por revisar."
                )

            pendientes = pending_incidents(conexion)

            esperados = {
                fila["id"]
                for fila in pendientes
            }

            if (
                not esperados
                or set(incident_ids) != esperados
            ):

                raise RecoveryError(
                    "Los incidentes pendientes han cambiado."
                )

            otros = conexion.execute("""
                SELECT COUNT(*)
                FROM error_logs
                WHERE resolved = 0
                  AND component != ?
            """, (COMPONENT,)).fetchone()[0]

            if otros:

                raise RecoveryError(
                    "Existen otros incidentes sin resolver."
                )

            incompletos = conexion.execute("""
                SELECT COUNT(*)
                FROM agent_cycles
                WHERE portfolio_id = ?
                  AND status NOT IN (
                      'COMPLETED',
                      'REJECTED'
                  )
            """, (cartera["id"],)).fetchone()[0]

            if incompletos:

                raise RecoveryError(
                    "Existen ciclos incompletos."
                )

            if conexion.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0] != "ok":

                raise RecoveryError(
                    "Integridad SQLite no aprobada."
                )

            if conexion.execute(
                "PRAGMA foreign_key_check"
            ).fetchall():

                raise RecoveryError(
                    "Integridad referencial no aprobada."
                )

            now = int(time.time())

            for error_id in incident_ids:

                conexion.execute("""
                    UPDATE error_logs
                    SET resolved = 1,
                        resolved_at = ?
                    WHERE id = ?
                      AND component = ?
                      AND resolved = 0
                """, (
                    now,
                    error_id,
                    COMPONENT
                ))

            conexion.execute("""
                UPDATE portfolio
                SET status = 'ACTIVE',
                    updated_at = ?
                WHERE id = ?
            """, (
                now,
                cartera["id"]
            ))

            conexion.execute("""
                INSERT INTO system_logs (
                    level,
                    component,
                    message
                )
                VALUES ('INFO', ?, ?)
            """, (
                COMPONENT,
                json.dumps({
                    "action": "MANUAL_RECOVERY",
                    "resolved_incidents": incident_ids,
                    "operator_reason": reason.strip()
                }, ensure_ascii=False)
            ))

    return {
        "status": "ACTIVE",
        "resolved_incidents": list(incident_ids),
        "execution_started": False,
        "real_trading": False
    }


# 10. Diagnostico con un fallo controlado

def main():

    print("=" * 60)
    print("FINANCEAI - SUPERVISION Y RECUPERACION")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    with tempfile.TemporaryDirectory() as carpeta:

        ruta = Path(carpeta) / "supervisor_test.db"

        with read_connection() as original:

            copia = sqlite3.connect(ruta)

            try:

                original.backup(copia)

            finally:

                copia.close()

        with write_transaction(ruta) as conexion:

            conexion.execute("""
                UPDATE portfolio
                SET status = 'ACTIVE'
                WHERE name = 'FinanceAI_Paper'
            """)

        def fallo_controlado(path):

            raise MarketDataError(
                "MEXC no responde."
            )

        print("\nFALLO CONTROLADO: MEXC SIN RESPUESTA")

        fallo = run_guarded(
            None,
            path=ruta,
            sync_fn=fallo_controlado
        )

        assert fallo["status"] == "PAUSED_ERROR"

        print(json.dumps(
            fallo,
            indent=4,
            ensure_ascii=False
        ))

        # Simular reinicio mediante una nueva
        # invocacion sin estado en memoria.

        reinicio = run_guarded(
            None,
            path=ruta
        )

        assert reinicio["status"] == "RECOVERY_REQUIRED"

        print("\nESTADO DESPUES DEL REINICIO")

        print(json.dumps(
            reinicio,
            indent=4
        ))

        revision = recovery_status(ruta)

        ids = [
            fila["id"]
            for fila in revision["pending_incidents"]
        ]

        assert len(ids) == 1

        print("\nRECUPERACION MANUAL CONTROLADA")

        recuperacion = resume_after_review(
            ids,
            "Fallo sintetico revisado y corregido.",
            path=ruta
        )

        assert recuperacion["status"] == "ACTIVE"

        print(json.dumps(
            recuperacion,
            indent=4
        ))

        with read_connection(ruta) as conexion:

            cartera = get_portfolio(conexion)

            ordenes = conexion.execute("""
                SELECT COUNT(*)
                FROM orders
            """).fetchone()[0]

            incidente = conexion.execute("""
                SELECT resolved, resolved_at
                FROM error_logs
                WHERE id = ?
            """, (ids[0],)).fetchone()

            assert incidente["resolved"] == 1

            assert incidente["resolved_at"] is not None

            assert cartera["cash_micros"] == 50000 * MICROS

            assert ordenes == 0

            assert conexion.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0] == "ok"

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.9",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": "APROBADO",
        "Fallo_controlado": fallo,
        "Reinicio_simulado": reinicio,
        "Recuperacion": recuperacion,
        "Base_principal_intacta": True,
        "Modelo_LSTM_intacto": True,
        "Ordenes_diagnostico": 0,
        "Recuperacion_probada_en_copia": True,
        "Dinero_real_utilizado": False
    }

    archivo = (
        BASE_DIR /
        "results/control_agent_supervisor.json"
    )

    archivo.write_text(
        json.dumps(
            evidencia,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("FINANCEAI - RESULTADO DEL SUPERVISOR")
    print("=" * 60)

    print("Registro de incidentes: APROBADO")
    print("Pausa automatica: APROBADA")
    print("Persistencia tras reinicio simulado: APROBADA")
    print("Recuperacion manual en copia: APROBADA")
    print("Reintento automatico del ciclo: NO")
    print("Base principal intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Capital virtual conservado: 50000 USDT")
    print("Ordenes ejecutadas: NO")
    print("Dinero real utilizado: NO")
    print("Evidencia:", archivo.name)

    print("\nPASO 12.9 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
