import os
import json
import math
import time
import socket
import shutil
import subprocess

from contextlib import contextmanager
from datetime import datetime, timezone

import requests

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.database import read_connection

from backend.app.services.prediction import (
    verify_artifacts,
    build_features,
    validate_window
)

from backend.app.services.financial_prompt import (
    FinancialContext,
    build_context_data,
    prompt_sha256
)

from backend.app.services.llm_decision import (
    request_decision,
    DecisionError,
    database_hash,
    model_hashes
)

from backend.app.services.ollama_client import (
    OllamaClient,
    OllamaError,
    OLLAMA_URL
)

DAY = 86400
SYMBOL = "BTCUSDT"
MODEL_VERSION = "1.0.0"


class AgentContextError(RuntimeError):

    pass


# 2. Construir contexto desde SQLite

def load_live_context(
    path=DATABASE_PATH,
    clock=time.time
):

    manifiesto = verify_artifacts()

    now = int(clock())

    with read_connection(path) as conexion:

        activo = conexion.execute("""
            SELECT *
            FROM assets
            WHERE symbol = ?
              AND exchange = 'MEXC'
              AND active = 1
        """, (SYMBOL,)).fetchone()

        if activo is None:

            raise AgentContextError(
                "Activo financiero no disponible."
            )

        modelo = conexion.execute("""
            SELECT *
            FROM model_versions
            WHERE version = ?
        """, (MODEL_VERSION,)).fetchone()

        if (
            modelo is None
            or modelo["model_sha256"]
                != manifiesto["Archivos"][
                    "modelo_final.keras"
                ]["SHA256"]
            or modelo["window_size"] != 20
            or modelo["feature_count"] != 3
        ):

            raise AgentContextError(
                "Modelo registrado incompatible."
            )

        # Recuperar los 40 cierres necesarios.

        filas = conexion.execute("""
            SELECT
                id,
                open_time,
                close_time,
                close
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
            ORDER BY open_time DESC
            LIMIT 40
        """, (
            activo["id"],
            DAY
        )).fetchall()

        filas = list(reversed(filas))

        try:

            validate_window(filas, now)

        except RuntimeError as error:

            raise AgentContextError(
                str(error)
            ) from error

        ultima = filas[-1]

        # La prediccion debe pertenecer exactamente
        # a la ultima vela disponible.

        prediccion = conexion.execute("""
            SELECT *
            FROM predictions
            WHERE candle_id = ?
              AND model_version = ?
        """, (
            ultima["id"],
            MODEL_VERSION
        )).fetchone()

        if prediccion is None:

            raise AgentContextError(
                "No existe prediccion para la ultima vela."
            )

        if (
            prediccion["target_open_time"]
                != ultima["close_time"]
            or prediccion["target_close_time"]
                != ultima["close_time"] + DAY
            or prediccion["emission_time"]
                != ultima["close_time"]
        ):

            raise AgentContextError(
                "Horizonte predictivo incompatible."
            )

        # No utilizar una prediccion antes de su
        # generacion real, ni despues de su vencimiento.

        if not (
            ultima["close_time"]
            <= prediccion["created_at"]
            <= now
            < prediccion["target_close_time"]
        ):

            raise AgentContextError(
                "Prediccion fuera de tiempo."
            )

        retorno = prediccion["predicted_return"]

        if (
            not math.isfinite(retorno)
            or retorno <= -1
        ):

            raise AgentContextError(
                "Rendimiento pronosticado invalido."
            )

        precio_esperado = (
            ultima["close"] * (1 + retorno)
        )

        if not math.isclose(
            prediccion["predicted_price"],
            precio_esperado,
            rel_tol=0,
            abs_tol=1e-6
        ):

            raise AgentContextError(
                "Precio pronosticado inconsistente."
            )

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
              AND strategy = 'LLM'
              AND currency = 'USDT'
        """).fetchone()

        if cartera is None:

            raise AgentContextError(
                "Cartera principal no disponible."
            )

        posicion = conexion.execute("""
            SELECT *
            FROM positions
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (
            cartera["id"],
            activo["id"]
        )).fetchone()

        if posicion is None:

            raise AgentContextError(
                "Posicion financiera no disponible."
            )

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (cartera["id"],)).fetchone()

        if riesgo is None:

            raise AgentContextError(
                "Configuracion de riesgo no disponible."
            )

        # Recuperar patrimonio diario solamente
        # cuando existe una valoracion registrada
        # exactamente en el cierre de referencia.

        referencia = conexion.execute("""
            SELECT e.equity_micros
            FROM equity_history e
            JOIN agent_cycles c
                ON c.id = e.cycle_id
            WHERE c.portfolio_id = ?
              AND e.snapshot_type = 'VALUATION'
              AND e.recorded_at = ?
            ORDER BY e.id DESC
            LIMIT 1
        """, (
            cartera["id"],
            ultima["close_time"]
        )).fetchone()

        patrimonio_inicial = (
            referencia["equity_micros"]
            if referencia is not None
            else None
        )

        # 3. Calcular indicadores identicos al LSTM

        features = build_features([
            fila["close"] for fila in filas
        ])

        contexto = FinancialContext(
            symbol=SYMBOL,
            mode="PAPER_LIVE",
            candle_date=datetime.fromtimestamp(
                ultima["open_time"],
                timezone.utc
            ).date(),
            as_of_utc=datetime.fromtimestamp(
                now,
                timezone.utc
            ),
            reference_close=float(
                ultima["close"]
            ),
            predicted_return=float(retorno),
            returns_20=tuple(
                float(valor)
                for valor in features[:, 0]
            ),
            sma_distance_20=float(
                features[-1, 1]
            ),
            volatility_20=float(
                features[-1, 2]
            ),
            cash_micros=cartera["cash_micros"],
            quantity_sats=posicion["quantity_sats"],
            day_start_equity_micros=patrimonio_inicial,
            portfolio_status=cartera["status"],
            max_exposure_bps=riesgo[
                "max_exposure_bps"
            ],
            max_daily_loss_bps=riesgo[
                "max_daily_loss_bps"
            ],
            max_data_age_seconds=riesgo[
                "max_data_age_seconds"
            ],
            min_order_micros=riesgo[
                "min_order_micros"
            ],
            fee_bps=riesgo["fee_bps"],
            slippage_bps=riesgo["slippage_bps"],
            prediction_threshold=riesgo[
                "prediction_threshold"
            ],
            emergency_stop=bool(
                riesgo["emergency_stop"]
            )
        )

        metadatos = {
            "portfolio_id": cartera["id"],
            "asset_id": activo["id"],
            "candle_id": ultima["id"],
            "prediction_id": prediccion["id"],
            "model_version": MODEL_VERSION,
            "risk_config_id": riesgo["id"],
            "risk_config_version": riesgo["version"],
            "prediction_generated_at_utc": (
                datetime.fromtimestamp(
                    prediccion["created_at"],
                    timezone.utc
                ).isoformat()
            ),
            "context_created_at_utc": (
                contexto.as_of_utc.isoformat()
            ),
            "historical_closes_used": len(filas),
            "prediction_reused": True,
            "replay": False
        }

    return contexto, metadatos


# 4. Obtener una propuesta real sin ejecutar ordenes

def propose_live_decision(
    client,
    path=DATABASE_PATH,
    clock=time.time
):

    contexto, metadatos = load_live_context(
        path,
        clock
    )

    datos = build_context_data(contexto)

    resultado = request_decision(
        contexto,
        client
    )

    return {
        "metadata": metadatos,
        "context": datos,
        "llm_result": resultado,
        "risk_evaluation_pending": True,
        "executed": False,
        "real_trading": False
    }


# 5. Administrar servidor temporal de Ollama

@contextmanager
def temporary_ollama(log_path):

    ollama = shutil.which("ollama")

    if ollama is None:

        raise AgentContextError(
            "Ollama no instalado."
        )

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as prueba:

        prueba.settimeout(1)

        if prueba.connect_ex(
            ("127.0.0.1", 11434)
        ) == 0:

            raise AgentContextError(
                "Puerto Ollama ocupado."
            )

    entorno = os.environ.copy()

    entorno.update({
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_CONTEXT_LENGTH": "4096",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1"
    })

    with log_path.open(
        "w", encoding="utf-8"
    ) as log:

        servidor = subprocess.Popen(
            [ollama, "serve"],
            env=entorno,
            stdout=log,
            stderr=subprocess.STDOUT
        )

        try:

            disponible = False

            with requests.Session() as sesion:

                sesion.trust_env = False

                for intento in range(60):

                    if servidor.poll() is not None:

                        raise AgentContextError(
                            "Ollama se detuvo."
                        )

                    try:

                        respuesta = sesion.get(
                            OLLAMA_URL + "/api/version",
                            timeout=2,
                            allow_redirects=False
                        )

                        if respuesta.status_code == 200:

                            disponible = True
                            break

                    except requests.RequestException:

                        pass

                    time.sleep(0.5)

            if not disponible:

                raise AgentContextError(
                    "Servidor Ollama no disponible."
                )

            yield

        finally:

            if servidor.poll() is None:

                servidor.terminate()

                try:

                    servidor.wait(timeout=15)

                except subprocess.TimeoutExpired:

                    servidor.kill()
                    servidor.wait()

            print("Servidor temporal detenido.")


# 6. Diagnostico con datos reales

def main():

    print("=" * 60)
    print("FINANCEAI - INTEGRACION LSTM + QWEN3")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.6",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Prompt_SHA256": prompt_sha256(),
        "Operaciones_financieras": False,
        "TE_reevaluado": False
    }

    try:

        contexto, metadatos = load_live_context()

        datos = build_context_data(contexto)

        evidencia["Contexto_preliminar"] = datos

        print("Modelo LSTM: VERIFICADO")
        print("Prediccion ID:", metadatos["prediction_id"])
        print("Vela ID:", metadatos["candle_id"])
        print("Cierres utilizados:", metadatos[
            "historical_closes_used"
        ])

        print("\nDATOS FINANCIEROS REALES")

        print("Fecha de referencia:", datos["candle_date"])

        print("Precio de cierre:",
              contexto.reference_close, "USDT")

        print("Rendimiento pronosticado:",
              contexto.predicted_return * 100, "%")

        print("Distancia SMA:",
              contexto.sma_distance_20 * 100, "%")

        print("Volatilidad diaria:",
              contexto.volatility_20 * 100, "%")

        print("Estado de cartera:",
              contexto.portfolio_status)

        print("Antiguedad de datos:",
              datos["data_age_seconds"], "segundos")

        print("Datos antiguos:",
              datos["risk"]["data_is_stale"])

        print("\nSOLICITANDO PROPUESTA A QWEN3",
              flush=True)

        with temporary_ollama(
            BASE_DIR / "results/agent_context_ollama.log"
        ):

            with OllamaClient() as cliente:

                resultado = propose_live_decision(
                    cliente
                )

        decision = resultado["llm_result"]["decision"]

        print("\nDECISION FINANCIERA DEL LLM")

        print(json.dumps(
            decision,
            indent=4,
            ensure_ascii=False
        ))

        print("\nLatencia del LLM:",
              resultado["llm_result"][
                  "latency_ms"
              ], "ms")

        print("Validacion JSON: APROBADA")
        print("Validacion contextual: APROBADA")

        evidencia["Resultado"] = "APROBADO"
        evidencia["Integracion"] = resultado

    except (
        AgentContextError,
        OllamaError,
        DecisionError
    ) as error:

        evidencia["Resultado"] = "REVISAR"

        evidencia["Error"] = {
            "code": getattr(
                error,
                "code",
                type(error).__name__
            ),
            "message": str(error)
        }

        print("Propuesta bloqueada:", str(error))

    finally:

        assert database_hash() == db_antes

        assert model_hashes() == modelo_antes

        evidencia["Base_datos_intacta"] = True

        evidencia["Modelo_LSTM_intacto"] = True

        ruta = (
            BASE_DIR /
            "results/control_integracion_lstm_llm.json"
        )

        ruta.write_text(
            json.dumps(
                evidencia,
                indent=4,
                ensure_ascii=False,
                allow_nan=False
            ),
            encoding="utf-8"
        )

    print("\n" + "=" * 60)
    print("FINANCEAI - RESULTADO DE INTEGRACION")
    print("=" * 60)

    print("Base de datos intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("TE reevaluado: NO")
    print("Reentrenamiento: NO")
    print("Ordenes ejecutadas: NO")
    print("Dinero real utilizado: NO")
    print("Evidencia:", ruta.name)

    if evidencia["Resultado"] != "APROBADO":

        raise SystemExit(1)

    print("LSTM + Qwen3: INTEGRADOS")
    print("Datos utilizados: REALES")
    print("Motor de riesgo integrado: PENDIENTE")
    print("\nPASO 12.6 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
