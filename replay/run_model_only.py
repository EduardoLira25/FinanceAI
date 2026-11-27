import csv
import json
import math
import time
import hashlib
import statistics

from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.prediction import (
    verify_artifacts,
    build_features,
    infer_return
)

from backend.app.services.risk import (
    model_only_action
)

from backend.app.services.paper_trading import (
    execute_replay_cycle
)

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)


BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "replay"
RESULTS = BASE / "results"

DB = REPLAY / "financeai_replay.db"

MICROS = 1000000
SATS = 100000000
DAY = 86400

CAPITAL = 50000000000
THRESHOLD = 0.001

inicio_proceso = time.perf_counter()

db_antes = database_hash()
modelo_antes = model_hashes()


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


def fecha_utc(timestamp):

    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).strftime("%Y-%m-%d")


def guardar_json(ruta, contenido):

    ruta.write_text(
        json.dumps(
            contenido,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )


print("=" * 60)
print("FINANCEAI - SIMULACION MODEL ONLY")
print("=" * 60)


# 1. Verificar el protocolo congelado.

ruta_protocolo = (
    REPLAY / "protocolo_replay_VA_30.json"
)

huella = sha256(ruta_protocolo)

assert huella == (
    "6191c13274b511013f9f118636082772b"
    "3b3003a9e148776f4aaedc86c3b656c"
)

protocolo = json.loads(
    ruta_protocolo.read_text(encoding="utf-8")
)

assert protocolo["Conjunto"] == "VA"

assert protocolo["Capital_inicial_USDT"] == 50000

assert protocolo[
    "Ciclos_previstos_por_estrategia"
] == 30

assert DB.is_file()

assert DB.resolve() != DATABASE_PATH.resolve()

verify_artifacts()

print("Protocolo experimental: VERIFICADO")
print("Modelo congelado: VERIFICADO")
print("Base independiente: VERIFICADA")


# 2. Verificar archivos originales.

ruta_predicciones = BASE / protocolo[
    "Fuente_predicciones_VA"
]

ruta_datos = BASE / protocolo[
    "Archivo_datos_replay"
]

assert sha256(ruta_predicciones) == protocolo[
    "SHA256_predicciones_VA"
]

assert sha256(ruta_datos) == protocolo[
    "SHA256_datos_replay"
]

originales = pd.read_csv(
    ruta_predicciones,
    usecols=[
        "Target_Date",
        "Window_End",
        "Rendimiento_predicho"
    ],
    nrows=30,
    float_precision="round_trip"
)

originales["Target_Date"] = pd.to_datetime(
    originales["Target_Date"],
    utc=True
)

originales["Window_End"] = pd.to_datetime(
    originales["Window_End"],
    utc=True
)


# 3. Identificar la cartera y las predicciones.

with read_connection(DB) as c:

    cartera = c.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'Replay_Model_Only'
          AND mode = 'REPLAY'
          AND strategy = 'MODEL_ONLY'
          AND currency = 'USDT'
    """).fetchone()

    assert cartera is not None

    PORTFOLIO_ID = cartera["id"]

    assert cartera["status"] == "ACTIVE"

    assert cartera["initial_cash_micros"] == CAPITAL

    riesgo = c.execute("""
        SELECT *
        FROM risk_config
        WHERE portfolio_id = ?
        ORDER BY version DESC
        LIMIT 1
    """, (PORTFOLIO_ID,)).fetchone()

    assert riesgo["max_exposure_bps"] == 2500
    assert riesgo["max_daily_loss_bps"] == 200
    assert riesgo["max_data_age_seconds"] == 3600
    assert riesgo["min_order_micros"] == 10000000
    assert riesgo["fee_bps"] == 0
    assert riesgo["slippage_bps"] == 0
    assert riesgo["prediction_threshold"] == THRESHOLD
    assert riesgo["emergency_stop"] == 0

    predicciones = [
        dict(fila)
        for fila in c.execute("""
            SELECT
                p.id,
                p.candle_id,
                p.predicted_return,
                p.predicted_price,
                p.emission_time,
                p.target_open_time,
                p.target_close_time,
                v.asset_id,
                v.open_time AS reference_time,
                v.close_time AS reference_close_time,
                v.close AS reference_price
            FROM predictions p
            JOIN candles v ON v.id = p.candle_id
            JOIN assets a ON a.id = v.asset_id
            WHERE p.model_version = '1.0.0'
              AND a.symbol = 'BTCUSDT'
              AND a.exchange = 'MEXC'
            ORDER BY p.target_open_time
        """).fetchall()
    ]

assert len(predicciones) == 30

for pred, (_, original) in zip(
    predicciones,
    originales.iterrows()
):

    assert pred["target_open_time"] == int(
        original["Target_Date"].timestamp()
    )

    assert pred["reference_time"] == int(
        original["Window_End"].timestamp()
    )

    assert pred["predicted_return"] == float(
        original["Rendimiento_predicho"]
    )

    assert pred["reference_close_time"] == (
        pred["target_open_time"]
    )

    assert pred["emission_time"] == (
        pred["target_open_time"]
    )

print("Predicciones originales: 30 / 30")
print("Configuracion de riesgo: VERIFICADA")


# 4. Proteger las otras estrategias.

def estado_otras_carteras():

    with read_connection(DB) as c:

        resultado = {}

        for tabla in (
            "portfolio",
            "positions",
            "risk_config",
            "agent_cycles"
        ):

            campo = (
                "id" if tabla == "portfolio"
                else "portfolio_id"
            )

            resultado[tabla] = [
                dict(fila)
                for fila in c.execute(
                    f"""
                    SELECT *
                    FROM {tabla}
                    WHERE {campo} != ?
                    ORDER BY id
                    """,
                    (PORTFOLIO_ID,)
                ).fetchall()
            ]

        for tabla, consulta in {
            "agent_decisions": """
                SELECT d.*
                FROM agent_decisions d
                JOIN agent_cycles c ON c.id = d.cycle_id
                WHERE c.portfolio_id != ?
                ORDER BY d.id
            """,
            "orders": """
                SELECT o.*
                FROM orders o
                JOIN agent_decisions d ON d.id = o.decision_id
                JOIN agent_cycles c ON c.id = d.cycle_id
                WHERE c.portfolio_id != ?
                ORDER BY o.id
            """,
            "equity_history": """
                SELECT e.*
                FROM equity_history e
                JOIN agent_cycles c ON c.id = e.cycle_id
                WHERE c.portfolio_id != ?
                ORDER BY e.id
            """
        }.items():

            resultado[tabla] = [
                dict(fila)
                for fila in c.execute(
                    consulta,
                    (PORTFOLIO_ID,)
                ).fetchall()
            ]

        return resultado


otras_antes = estado_otras_carteras()


# 5. Verificar ciclos previamente registrados.
# Permitir continuar sin duplicar operaciones.

with read_connection(DB) as c:

    existentes = [
        dict(fila)
        for fila in c.execute("""
            SELECT
                c.prediction_id,
                c.candle_id,
                c.status,
                d.proposed_action
            FROM agent_cycles c
            JOIN agent_decisions d ON d.cycle_id = c.id
            WHERE c.portfolio_id = ?
            ORDER BY c.id
        """, (PORTFOLIO_ID,)).fetchall()
    ]

assert len(existentes) <= 30

for existente, pred in zip(
    existentes,
    predicciones
):

    assert existente["prediction_id"] == pred["id"]

    assert existente["candle_id"] == pred["candle_id"]

    assert existente["status"] in (
        "COMPLETED", "REJECTED"
    )

    assert existente["proposed_action"] == (
        model_only_action(
            pred["predicted_return"],
            THRESHOLD
        )
    )

completados_antes = len(existentes)

print("Ciclos previamente registrados:", completados_antes)


# 6. Ejecutar los ciclos cronologicamente.

print("\nSIMULACION FINANCIERA")
print("-" * 60)

try:

    for numero, pred in enumerate(
        predicciones,
        start=1
    ):

        fecha = fecha_utc(
            pred["target_open_time"]
        )

        if numero <= completados_antes:

            print(
                f"{numero:02d}/30",
                fecha,
                "REGISTRO EXISTENTE",
                flush=True
            )

            continue

        # Consultar exclusivamente cierres disponibles
        # en el instante historico de decision.

        with read_connection(DB) as c:

            contexto = c.execute("""
                SELECT
                    open_time,
                    close_time,
                    close
                FROM candles
                WHERE asset_id = ?
                  AND interval_seconds = 86400
                  AND close_time <= ?
                ORDER BY open_time DESC
                LIMIT 40
            """, (
                pred["asset_id"],
                pred["emission_time"]
            )).fetchall()

        contexto = list(reversed(contexto))

        assert len(contexto) == 40

        assert contexto[-1]["close_time"] == (
            pred["emission_time"]
        )

        assert all(
            contexto[i]["open_time"]
            - contexto[i - 1]["open_time"] == DAY
            for i in range(1, len(contexto))
        )

        assert all(
            vela["close_time"] <= pred["emission_time"]
            for vela in contexto
        )

        cierres = np.array(
            [vela["close"] for vela in contexto],
            dtype=np.float64
        )

        # Medir inferencia local real.
        # No modificar el reloj historico simulado.

        t0 = time.perf_counter()

        features = build_features(cierres)

        reproducida = float(
            infer_return(features)
        )

        original = pred["predicted_return"]

        assert abs(reproducida - original) <= 1e-6

        assert (
            reproducida > THRESHOLD
        ) == (
            original > THRESHOLD
        )

        propuesta = model_only_action(
            original,
            THRESHOLD
        )

        latencia_ms = (
            time.perf_counter() - t0
        ) * 1000

        assert propuesta in ("BUY", "SELL", "HOLD")

        justificacion = (
            f"MODEL_ONLY: rendimiento pronosticado "
            f"{original * 100:+.8f}%; "
            f"umbral {THRESHOLD * 100:.4f}%. "
            f"Propuesta cuantitativa: {propuesta}."
        )

        # La propuesta ya esta determinada.
        # Solo ahora el ejecutor puede consultar
        # la apertura y cierre del dia objetivo.

        try:

            resultado = execute_replay_cycle(
                PORTFOLIO_ID,
                pred["id"],
                propuesta,
                justificacion,
                path=DB,
                latency_ms=latencia_ms
            )

        except Exception as error:

            # Registrar el fallo sin inventar una
            # decision ni continuar fuera de secuencia.

            with write_transaction(DB) as c:

                c.execute("""
                    INSERT INTO error_logs (
                        component,
                        error_type,
                        message,
                        cause,
                        corrective_action
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    "REPLAY_MODEL_ONLY",
                    type(error).__name__,
                    f"Fallo en ciclo objetivo {fecha}.",
                    type(error).__name__,
                    "Revisar antes de continuar."
                ))

            raise

        assert resultado["real_trading"] is False

        assert resultado["mode"] == "REPLAY"

        assert resultado["cycle_status"] in (
            "COMPLETED", "REJECTED"
        )

        print(
            f"{numero:02d}/30",
            fecha,
            f"Pred: {original * 100:+.4f}%",
            f"Propuesta: {propuesta}",
            f"Autorizada: {resultado['authorized_action']}",
            f"Patrimonio: "
            f"{resultado['equity_micros'] / MICROS:,.2f}",
            "USDT",
            flush=True
        )

finally:

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    assert estado_otras_carteras() == otras_antes

    assert sha256(ruta_protocolo) == huella


# 7. Consultar los resultados persistidos.

with read_connection(DB) as c:

    filas = [
        dict(fila)
        for fila in c.execute("""
            SELECT
                c.id AS cycle_id,
                c.status AS cycle_status,
                pr.target_open_time,
                pr.predicted_return,
                d.proposed_action,
                d.authorized_action,
                d.risk_approved,
                d.risk_reason,
                d.latency_ms,
                o.id AS order_id,
                o.side AS order_side,
                o.status AS order_status,
                o.quantity_sats,
                o.price_micros,
                o.notional_micros,
                o.fee_micros,
                o.slippage_micros,
                o.filled_at,
                e.cash_micros,
                e.position_value_micros,
                e.equity_micros,
                e.drawdown
            FROM agent_cycles c
            JOIN predictions pr ON pr.id = c.prediction_id
            JOIN agent_decisions d ON d.cycle_id = c.id
            JOIN equity_history e ON e.cycle_id = c.id
                AND e.snapshot_type = 'VALUATION'
            LEFT JOIN orders o ON o.decision_id = d.id
            WHERE c.portfolio_id = ?
            ORDER BY pr.target_open_time
        """, (PORTFOLIO_ID,)).fetchall()
    ]

    patrimonio = c.execute("""
        SELECT MAX(e.drawdown)
        FROM equity_history e
        JOIN agent_cycles c ON c.id = e.cycle_id
        WHERE c.portfolio_id = ?
    """, (PORTFOLIO_ID,)).fetchone()[0]

    cartera_final = c.execute("""
        SELECT *
        FROM portfolio
        WHERE id = ?
    """, (PORTFOLIO_ID,)).fetchone()

    posicion_final = c.execute("""
        SELECT quantity_sats, cost_basis_micros
        FROM positions
        WHERE portfolio_id = ?
    """, (PORTFOLIO_ID,)).fetchone()

    fallos_registrados = c.execute("""
        SELECT COUNT(*)
        FROM error_logs
        WHERE component = 'REPLAY_MODEL_ONLY'
    """).fetchone()[0]

    assert c.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"

    assert c.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []


assert len(filas) == 30

assert len({
    f["target_open_time"] for f in filas
}) == 30

assert all(
    f["cycle_status"] in ("COMPLETED", "REJECTED")
    for f in filas
)

assert all(
    f["equity_micros"] ==
    f["cash_micros"] + f["position_value_micros"]
    for f in filas
)

assert all(
    f["cash_micros"] >= 0
    for f in filas
)

assert all(
    f["latency_ms"] is not None
    and f["latency_ms"] >= 0
    for f in filas
)

ejecutadas = [
    f for f in filas
    if f["order_status"] == "FILLED"
]

compras = [
    f for f in ejecutadas
    if f["order_side"] == "BUY"
]

ventas = [
    f for f in ejecutadas
    if f["order_side"] == "SELL"
]

assert all(
    f["fee_micros"] == 0
    and f["slippage_micros"] == 0
    for f in ejecutadas
)

assert all(
    f["filled_at"] == f["target_open_time"]
    for f in ejecutadas
)


# 8. Reconciliar efectivo y posiciones.

efectivo_calculado = CAPITAL
cantidad_calculada = 0
costo_abierto = 0

resultados_cerrados = []

for orden in ejecutadas:

    cantidad = orden["quantity_sats"]

    importe = orden["notional_micros"]

    comision = orden["fee_micros"]

    if orden["order_side"] == "BUY":

        efectivo_calculado -= importe + comision

        cantidad_calculada += cantidad

        costo_abierto += importe + comision

    else:

        # El ejecutor vende la posicion completa.

        assert cantidad == cantidad_calculada

        efectivo_calculado += importe - comision

        pnl = importe - comision - costo_abierto

        resultados_cerrados.append(pnl)

        cantidad_calculada = 0

        costo_abierto = 0

assert efectivo_calculado == (
    cartera_final["cash_micros"]
)

assert cantidad_calculada == (
    posicion_final["quantity_sats"]
)

assert costo_abierto == (
    posicion_final["cost_basis_micros"]
)

print("\nReconciliacion financiera: APROBADA")


# 9. Calcular metricas preliminares.
# La liquidacion final se realizara de manera
# uniforme para las tres estrategias.

patrimonio_final = (
    filas[-1]["equity_micros"] / MICROS
)

rendimiento = (
    patrimonio_final / 50000 - 1
) * 100

ganadoras = sum(
    pnl > 0 for pnl in resultados_cerrados
)

latencias = [
    f["latency_ms"]
    for f in filas
]

rechazos = sum(
    not bool(f["risk_approved"])
    for f in filas
)

holds = sum(
    f["authorized_action"] == "HOLD"
    for f in filas
)

metricas = {
    "Estrategia": "MODEL_ONLY",
    "Periodo_inicio_UTC": protocolo["Inicio_objetivo_UTC"],
    "Periodo_fin_UTC": protocolo["Fin_objetivo_UTC"],
    "Capital_inicial_USDT": 50000,
    "Patrimonio_final_valorado_USDT": patrimonio_final,
    "Efectivo_final_USDT": (
        cartera_final["cash_micros"] / MICROS
    ),
    "Posicion_final_BTC": (
        posicion_final["quantity_sats"] / SATS
    ),
    "Rendimiento_neto_pct": rendimiento,
    "Drawdown_maximo_pct": patrimonio * 100,
    "Compras": len(compras),
    "Ventas": len(ventas),
    "Ordenes_ejecutadas": len(ejecutadas),
    "Operaciones_cerradas": len(resultados_cerrados),
    "Operaciones_ganadoras": ganadoras,
    "Win_rate_pct": (
        ganadoras / len(resultados_cerrados) * 100
        if resultados_cerrados else None
    ),
    "PnL_realizado_USDT": (
        sum(resultados_cerrados) / MICROS
    ),
    "Latencia_media_ms": statistics.mean(latencias),
    "Latencia_mediana_ms": statistics.median(latencias),
    "Definicion_latencia": (
        "Preparacion de variables, inferencia LSTM "
        "y determinacion de la propuesta cuantitativa."
    ),
    "Rechazos_riesgo": rechazos,
    "Decisiones_HOLD_autorizadas": holds,
    "Ciclos_validos": len(filas),
    "Ciclos_COMPLETED": sum(
        f["cycle_status"] == "COMPLETED"
        for f in filas
    ),
    "Ciclos_REJECTED": sum(
        f["cycle_status"] == "REJECTED"
        for f in filas
    ),
    "Ciclos_fallidos_no_completados": 30 - len(filas),
    "Fallos_de_ejecucion_registrados": fallos_registrados,
    "Comisiones_USDT": 0,
    "Deslizamiento_USDT": 0,
    "Liquidacion_final": (
        "PENDIENTE"
        if posicion_final["quantity_sats"] > 0
        else "NO_NECESARIA"
    ),
    "Conjunto": "VA",
    "Modo": "REPLAY",
    "Inferencias_LLM": 0,
    "TE_reevaluado": False,
    "Reentrenamiento": False,
    "Dinero_real_utilizado": False
}


# 10. Exportar los resultados diarios.

ruta_diaria = REPLAY / "replay_model_only_diario.csv"

registros = []

for f in filas:

    registros.append({
        "Fecha_objetivo_UTC": fecha_utc(
            f["target_open_time"]
        ),
        "Ciclo_ID": f["cycle_id"],
        "Estado_ciclo": f["cycle_status"],
        "Rendimiento_predicho_pct": (
            f["predicted_return"] * 100
        ),
        "Propuesta": f["proposed_action"],
        "Accion_autorizada": f["authorized_action"],
        "Riesgo_aprobado": bool(f["risk_approved"]),
        "Motivo_riesgo": f["risk_reason"],
        "Orden_ID": f["order_id"],
        "Orden_tipo": f["order_side"],
        "Cantidad_BTC": (
            f["quantity_sats"] / SATS
            if f["quantity_sats"] is not None
            else None
        ),
        "Precio_ejecucion_USDT": (
            f["price_micros"] / MICROS
            if f["price_micros"] is not None
            else None
        ),
        "Efectivo_USDT": f["cash_micros"] / MICROS,
        "Posicion_USDT": (
            f["position_value_micros"] / MICROS
        ),
        "Patrimonio_USDT": f["equity_micros"] / MICROS,
        "Drawdown_pct": f["drawdown"] * 100,
        "Latencia_ms": f["latency_ms"]
    })

with ruta_diaria.open(
    "w",
    encoding="utf-8",
    newline=""
) as archivo:

    writer = csv.DictWriter(
        archivo,
        fieldnames=list(registros[0])
    )

    writer.writeheader()
    writer.writerows(registros)


ruta_metricas = (
    REPLAY / "metricas_model_only.json"
)

guardar_json(ruta_metricas, metricas)


# 11. Verificacion final de proteccion.

verify_artifacts()

assert database_hash() == db_antes

assert model_hashes() == modelo_antes

assert estado_otras_carteras() == otras_antes

assert sha256(ruta_protocolo) == huella

assert sha256(ruta_predicciones) == protocolo[
    "SHA256_predicciones_VA"
]

assert sha256(ruta_datos) == protocolo[
    "SHA256_datos_replay"
]


# 12. Guardar evidencia.

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "14.3",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",
    "SHA256_protocolo": huella,
    "Metricas": metricas,
    "Archivo_diario": str(
        ruta_diaria.relative_to(BASE)
    ),
    "SHA256_archivo_diario": sha256(ruta_diaria),
    "Archivo_metricas": str(
        ruta_metricas.relative_to(BASE)
    ),
    "SHA256_archivo_metricas": sha256(ruta_metricas),
    "Correspondencia_predicciones": "30/30",
    "Reconciliacion_financiera": True,
    "Otras_carteras_intactas": True,
    "Base_principal_intacta": True,
    "Modelo_LSTM_intacto": True,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Liquidacion_final_comparativa": "PENDIENTE",
    "Dinero_real_utilizado": False,
    "Tiempo_segundos": round(
        time.perf_counter() - inicio_proceso,
        4
    )
}

ruta_evidencia = (
    RESULTS / "control_replay_model_only.json"
)

guardar_json(ruta_evidencia, evidencia)


# 13. Mostrar resultados.

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO MODEL ONLY")
print("=" * 60)

print(json.dumps(
    metricas,
    indent=4,
    ensure_ascii=False,
    allow_nan=False
))

print("\nCiclos validos: 30 / 30")
print("Capital inicial: 50000 USDT")

print(
    "Patrimonio final:",
    round(patrimonio_final, 6),
    "USDT"
)

print(
    "Rendimiento neto:",
    round(rendimiento, 6),
    "%"
)

print("Compras:", len(compras))
print("Ventas:", len(ventas))
print("Rechazos de riesgo:", rechazos)
print("Decisiones HOLD:", holds)

print("Reconciliacion financiera: APROBADA")
print("Otras carteras intactas: SI")
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("Qwen3 utilizado: NO")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")

print(
    "Tiempo total:",
    evidencia["Tiempo_segundos"],
    "segundos"
)

print("Evidencia:", ruta_evidencia.name)

print("\nSIMULACION MODEL ONLY COMPLETADA")
print("PASO 14.3 COMPLETADO CORRECTAMENTE")

