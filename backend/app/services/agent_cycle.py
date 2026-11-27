import json
import time
import fcntl
import sqlite3
import tempfile

from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.mexc import synchronize

from backend.app.services.prediction import (
    generate_prediction
)

from backend.app.services.agent_context import (
    load_live_context,
    temporary_ollama
)

from backend.app.services.ollama_client import (
    OllamaClient
)

from backend.app.services.llm_decision import (
    request_decision,
    database_hash,
    model_hashes
)

from backend.app.services.market_quote import (
    get_latest_quote
)

from backend.app.services.live_paper_trading import (
    execute_live_cycle,
    cycle_summary
)

from backend.app.services.paper_trading import (
    _record_snapshot
)

from backend.app.services.risk import (
    MICROS,
    DAY,
    price_to_micros
)


class AgentCycleError(RuntimeError):

    pass


# 2. Evitar ciclos simultaneos en diferentes procesos

@contextmanager
def cycle_lock(path):

    ruta = Path(path).resolve()

    lock_path = ruta.with_name(
        ruta.name + ".agent.lock"
    )

    with lock_path.open("a") as archivo:

        try:

            fcntl.flock(
                archivo.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

        except BlockingIOError:

            yield False

            return

        try:

            yield True

        finally:

            fcntl.flock(
                archivo.fileno(),
                fcntl.LOCK_UN
            )


# 3. Consultar estado operativo de la cartera

def operational_status(path=DATABASE_PATH):

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

            raise AgentCycleError(
                "Cartera principal no disponible."
            )

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        if riesgo is None:

            raise AgentCycleError(
                "Configuracion de riesgo no disponible."
            )

        if riesgo["emergency_stop"]:

            estado = "EMERGENCY_STOP"

        else:

            estado = cartera["status"]

        return {
            "portfolio_id": cartera["id"],
            "status": estado,
            "cash_micros": cartera["cash_micros"]
        }


# 4. Registrar patrimonio al cierre diario

def finalize_previous_valuation(
    path=DATABASE_PATH,
    clock=time.time
):

    now = int(clock())

    with write_transaction(path) as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
        """).fetchone()

        if cartera is None:

            raise AgentCycleError(
                "Cartera no disponible."
            )

        ciclo = conexion.execute("""
            SELECT
                ac.id,
                ac.status,
                p.target_open_time,
                p.target_close_time,
                c.asset_id
            FROM agent_cycles ac
            JOIN predictions p
                ON p.id = ac.prediction_id
            JOIN candles c
                ON c.id = ac.candle_id
            WHERE ac.portfolio_id = ?
            ORDER BY c.open_time DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        if ciclo is None:

            return False

        if ciclo["status"] not in (
            "COMPLETED", "REJECTED"
        ):

            raise AgentCycleError(
                "Ciclo previo incompleto."
            )

        if ciclo["target_close_time"] > now:

            return False

        existente = conexion.execute("""
            SELECT id
            FROM equity_history
            WHERE cycle_id = ?
              AND snapshot_type = 'VALUATION'
        """, (ciclo["id"],)).fetchone()

        if existente is not None:

            return False

        vela = conexion.execute("""
            SELECT close, close_time
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
              AND open_time = ?
              AND close_time = ?
        """, (
            ciclo["asset_id"],
            DAY,
            ciclo["target_open_time"],
            ciclo["target_close_time"]
        )).fetchone()

        if vela is None:

            raise AgentCycleError(
                "Cierre diario pendiente de sincronizacion."
            )

        posicion = conexion.execute("""
            SELECT *
            FROM positions
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (
            cartera["id"],
            ciclo["asset_id"]
        )).fetchone()

        if posicion is None:

            raise AgentCycleError(
                "Posicion financiera no disponible."
            )

        # Verificar saldos contra el historial
        # de todas las ordenes virtuales.

        efectivo = cartera["initial_cash_micros"]

        cantidad = 0

        ordenes = conexion.execute("""
            SELECT
                o.side,
                o.quantity_sats,
                o.notional_micros,
                o.fee_micros,
                o.filled_at
            FROM orders o
            JOIN agent_decisions d
                ON d.id = o.decision_id
            JOIN agent_cycles ac
                ON ac.id = d.cycle_id
            WHERE ac.portfolio_id = ?
              AND o.status = 'FILLED'
            ORDER BY o.filled_at, o.id
        """, (cartera["id"],)).fetchall()

        for orden in ordenes:

            if (
                orden["filled_at"]
                >= ciclo["target_close_time"]
            ):

                raise AgentCycleError(
                    "Orden posterior al cierre evaluado."
                )

            if orden["side"] == "BUY":

                efectivo -= (
                    orden["notional_micros"]
                    + orden["fee_micros"]
                )

                cantidad += orden["quantity_sats"]

            else:

                efectivo += (
                    orden["notional_micros"]
                    - orden["fee_micros"]
                )

                cantidad -= orden["quantity_sats"]

            if min(efectivo, cantidad) < 0:

                raise AgentCycleError(
                    "Historial financiero inconsistente."
                )

        if (
            efectivo != cartera["cash_micros"]
            or cantidad != posicion["quantity_sats"]
        ):

            raise AgentCycleError(
                "Saldo diferente al historial de ordenes."
            )

        _record_snapshot(
            conexion,
            cartera["id"],
            ciclo["id"],
            "VALUATION",
            efectivo,
            cantidad,
            price_to_micros(vela["close"]),
            vela["close_time"],
            cartera["initial_cash_micros"]
        )

        conexion.execute("""
            INSERT INTO system_logs (
                cycle_id,
                level,
                component,
                message
            )
            VALUES (?, 'INFO', 'AGENT_CYCLE', ?)
        """, (
            ciclo["id"],
            "Valoracion diaria completada con vela cerrada."
        ))

        return True


# 5. Detectar ciclos previamente procesados

def existing_cycle(path, portfolio_id):

    with read_connection(path) as conexion:

        vela = conexion.execute("""
            SELECT c.id
            FROM candles c
            JOIN assets a
                ON a.id = c.asset_id
            WHERE a.symbol = 'BTCUSDT'
              AND a.exchange = 'MEXC'
              AND a.active = 1
              AND c.interval_seconds = 86400
            ORDER BY c.open_time DESC
            LIMIT 1
        """).fetchone()

        if vela is None:

            raise AgentCycleError(
                "Historial financiero no disponible."
            )

        ciclo = conexion.execute("""
            SELECT id, status
            FROM agent_cycles
            WHERE portfolio_id = ?
              AND candle_id = ?
        """, (
            portfolio_id,
            vela["id"]
        )).fetchone()

        if ciclo is None:

            return None

        if ciclo["status"] not in (
            "COMPLETED", "REJECTED"
        ):

            raise AgentCycleError(
                "Ciclo pendiente de recuperacion."
            )

        return cycle_summary(
            conexion,
            ciclo["id"],
            created=False
        )


# 6. Ejecutar un ciclo completo

def run_once(
    client,
    *,
    path=DATABASE_PATH,
    clock=time.time,
    sync_fn=synchronize,
    prediction_fn=generate_prediction,
    quote_fn=get_latest_quote
):

    inicio = time.perf_counter()

    def resultado(status, **datos):

        return {
            "status": status,
            **datos,
            "real_trading": False,
            "total_latency_ms": round(
                (time.perf_counter() - inicio)
                * 1000,
                3
            )
        }

    with cycle_lock(path) as adquirido:

        if not adquirido:

            return resultado(
                "CYCLE_ALREADY_RUNNING",
                executed=False
            )

        estado = operational_status(path)

        if estado["status"] != "ACTIVE":

            return resultado(
                estado["status"],
                executed=False
            )

        # A. Sincronizar mercado.

        sincronizacion = sync_fn(path)

        # B. Registrar el cierre del ciclo anterior.

        valoracion = finalize_previous_valuation(
            path,
            clock
        )

        estado = operational_status(path)

        if estado["status"] != "ACTIVE":

            return resultado(
                estado["status"],
                executed=False
            )

        # C. Evitar repetir ciclos e inferencias.

        existente = existing_cycle(
            path,
            estado["portfolio_id"]
        )

        if existente is not None:

            return resultado(
                "WAITING_NEXT_CANDLE",
                cycle=existente,
                executed=False,
                daily_valuation_created=valoracion
            )

        # D. Generar o recuperar prediccion LSTM.

        prediccion = prediction_fn(
            path,
            clock=clock
        )

        contexto, metadata = load_live_context(
            path,
            clock
        )

        if (
            metadata["prediction_id"]
            != prediccion["id"]
        ):

            raise AgentCycleError(
                "Prediccion cambio antes del analisis."
            )

        if contexto.portfolio_status != "ACTIVE":

            return resultado(
                contexto.portfolio_status,
                executed=False
            )

        if contexto.emergency_stop:

            return resultado(
                "EMERGENCY_STOP",
                executed=False
            )

        # E. Consultar Qwen3 y validar propuesta.

        propuesta = request_decision(
            contexto,
            client
        )

        # F. Consultar cotizacion despues del LLM.

        cotizacion = quote_fn()

        # G. Revalidar y ejecutar dentro de SQLite.

        ciclo = execute_live_cycle(
            contexto,
            metadata,
            propuesta,
            cotizacion,
            path=path,
            clock=clock
        )

        return resultado(
            ciclo["cycle_status"],
            synchronization=sincronizacion,
            daily_valuation_created=valoracion,
            prediction=prediccion,
            llm_proposal=propuesta["decision"],
            cycle=ciclo,
            executed=(
                ciclo["created"]
                and ciclo["executed"]
            )
        )


# 7. Diagnostico integrado con una copia temporal

def main():

    print("=" * 60)
    print("FINANCEAI - CICLO OPERATIVO INTEGRADO")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.8.3",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Dinero_real_utilizado": False
    }

    try:

        # La cartera principal debe seguir pausada.

        principal = run_once(None)

        assert principal["status"] == "PAUSED"

        assert principal["executed"] is False

        evidencia["Cartera_principal"] = principal

        print("Cartera principal: PAUSADA")
        print("Ejecucion principal: BLOQUEADA")

        # Ejecutar el flujo real exclusivamente
        # sobre una copia temporal de SQLite.

        with tempfile.TemporaryDirectory() as carpeta:

            ruta = (
                Path(carpeta) / "diagnostico.db"
            )

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

            print("\nIniciando ciclo en copia temporal...",
                  flush=True)

            with temporary_ollama(
                BASE_DIR /
                "results/agent_cycle_ollama.log"
            ):

                with OllamaClient() as cliente:

                    resultado = run_once(
                        cliente,
                        path=ruta
                    )

            assert resultado["status"] in (
                "COMPLETED",
                "REJECTED"
            )

            print("\nRESULTADO DEL CICLO")

            print(json.dumps(
                resultado,
                indent=4,
                ensure_ascii=False,
                allow_nan=False
            ))

            with read_connection(ruta) as conexion:

                assert conexion.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0] == "ok"

                assert conexion.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall() == []

            evidencia["Ciclo_temporal"] = resultado

            evidencia["Resultado"] = "APROBADO"

    except Exception as error:

        evidencia["Resultado"] = "REVISAR"

        evidencia["Error"] = {
            "tipo": type(error).__name__,
            "codigo": getattr(
                error,
                "code",
                None
            ),
            "mensaje": str(error)
        }

        print("Ciclo interrumpido:", str(error))

    finally:

        assert database_hash() == db_antes

        assert model_hashes() == modelo_antes

        evidencia["Base_principal_intacta"] = True

        evidencia["Modelo_LSTM_intacto"] = True

        evidencia["TE_reevaluado"] = False

        ruta_control = (
            BASE_DIR /
            "results/control_agent_cycle.json"
        )

        ruta_control.write_text(
            json.dumps(
                evidencia,
                indent=4,
                ensure_ascii=False,
                allow_nan=False
            ),
            encoding="utf-8"
        )

    print("\n" + "=" * 60)
    print("FINANCEAI - RESULTADO DEL CICLO")
    print("=" * 60)

    print("Base principal intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Capital principal: 50000 USDT")
    print("Cartera principal: PAUSADA")
    print("Ordenes principales nuevas: 0")
    print("TE reevaluado: NO")
    print("Dinero real utilizado: NO")
    print("Evidencia:", ruta_control.name)

    if evidencia["Resultado"] != "APROBADO":

        raise SystemExit(1)

    print("Ciclo integrado: APROBADO")
    print("Persistencia en copia temporal: APROBADA")
    print("Automatizacion permanente: PENDIENTE")

    print("\nPASO 12.8.3 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
