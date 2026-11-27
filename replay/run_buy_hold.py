import json
import hashlib
import time
import statistics

from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.paper_trading import (
    execute_replay_cycle
)

from backend.app.services.prediction import (
    verify_artifacts
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

CAPITAL = 50000 * MICROS

inicio_proceso = time.perf_counter()

db_antes = database_hash()
modelo_antes = model_hashes()


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


def leer_json(ruta):

    return json.loads(
        ruta.read_text(encoding="utf-8")
    )


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


def fecha_utc(timestamp):

    return datetime.fromtimestamp(
        timestamp,
        timezone.utc
    ).date().isoformat()


print("=" * 60)
print("FINANCEAI - SIMULACION BUY & HOLD")
print("=" * 60)


# 1. Verificar protocolo experimental.

ruta_protocolo = (
    REPLAY / "protocolo_replay_VA_30.json"
)

huella_protocolo = sha256(ruta_protocolo)

assert huella_protocolo == (
    "6191c13274b511013f9f118636082772b"
    "3b3003a9e148776f4aaedc86c3b656c"
)

protocolo = leer_json(ruta_protocolo)

assert protocolo["Conjunto"] == "VA"

assert protocolo["Buy_Hold"][
    "Asignacion_inicial_pct"
] == 100

assert protocolo["Capital_inicial_USDT"] == 50000

assert DB.is_file()

assert DB.resolve() != (
    DATABASE_PATH.resolve()
)

verify_artifacts()

print("Protocolo experimental: VERIFICADO")
print("Modelo congelado: VERIFICADO")
print("Base independiente: VERIFICADA")


# 2. Proteger los resultados anteriores.

fuentes = {
    BASE / protocolo["Fuente_predicciones_VA"]:
        protocolo["SHA256_predicciones_VA"],

    BASE / protocolo["Archivo_datos_replay"]:
        protocolo["SHA256_datos_replay"]
}

for estrategia in ("model_only", "llm"):

    control = leer_json(
        RESULTS /
        f"control_replay_{estrategia}.json"
    )

    assert control["Metricas"][
        "Ciclos_validos"
    ] == 30

    fuentes[
        REPLAY / f"metricas_{estrategia}.json"
    ] = control["SHA256_archivo_metricas"]

    fuentes[
        REPLAY / f"replay_{estrategia}_diario.csv"
    ] = control["SHA256_archivo_diario"]

control_llm = leer_json(
    RESULTS / "control_replay_llm.json"
)

for nombre, huella in (
    control_llm["SHA256_decisiones"].items()
):

    fuentes[
        REPLAY / "llm_decisions" / nombre
    ] = huella

for ruta, huella in fuentes.items():

    assert sha256(ruta) == huella

print("Resultados MODEL_ONLY: PROTEGIDOS")
print("Resultados QWEN3: PROTEGIDOS")


# 3. Identificar la cartera pasiva.

with read_connection(DB) as c:

    cartera = c.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'Replay_Buy_Hold'
          AND mode = 'REPLAY'
          AND strategy = 'BUY_HOLD'
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

    assert riesgo["max_exposure_bps"] == 10000

    assert riesgo["fee_bps"] == 0

    assert riesgo["slippage_bps"] == 0

    assert riesgo["emergency_stop"] == 0

    predicciones = [
        dict(f)
        for f in c.execute("""
            SELECT
                p.id,
                p.candle_id,
                p.emission_time,
                p.target_open_time,
                p.target_close_time,
                v.asset_id
            FROM predictions p
            JOIN candles v ON v.id = p.candle_id
            JOIN assets a ON a.id = v.asset_id
            WHERE a.symbol = 'BTCUSDT'
              AND a.exchange = 'MEXC'
              AND p.model_version = '1.0.0'
            ORDER BY p.target_open_time
        """).fetchall()
    ]

assert len(predicciones) == 30

assert fecha_utc(
    predicciones[0]["target_open_time"]
) == protocolo["Inicio_objetivo_UTC"]

assert fecha_utc(
    predicciones[-1]["target_open_time"]
) == protocolo["Fin_objetivo_UTC"]

assert all(
    p["emission_time"] == p["target_open_time"]
    for p in predicciones
)

assert all(
    predicciones[i]["target_open_time"]
    - predicciones[i - 1]["target_open_time"]
    == 86400
    for i in range(1, 30)
)

print("Periodo historico: VERIFICADO")
print("Exposicion inicial permitida: 100%")


# 4. Proteger las otras dos carteras.

def estado_protegido():

    with read_connection(DB) as c:

        datos = {}

        for tabla in (
            "assets",
            "candles",
            "model_versions",
            "predictions",
            "risk_config"
        ):

            datos[tabla] = [
                dict(f)
                for f in c.execute(
                    f"SELECT * FROM {tabla} ORDER BY rowid"
                )
            ]

        for tabla, campo in (
            ("portfolio", "id"),
            ("positions", "portfolio_id"),
            ("agent_cycles", "portfolio_id")
        ):

            datos[tabla] = [
                dict(f)
                for f in c.execute(
                    f"""
                    SELECT *
                    FROM {tabla}
                    WHERE {campo} != ?
                    ORDER BY id
                    """,
                    (PORTFOLIO_ID,)
                )
            ]

        consultas = {
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
        }

        for tabla, consulta in consultas.items():

            datos[tabla] = [
                dict(f)
                for f in c.execute(
                    consulta,
                    (PORTFOLIO_ID,)
                )
            ]

    return datos


protegido_antes = estado_protegido()


# 5. Verificar ciclos anteriores.
# Permitir reanudar sin duplicar compras.

with read_connection(DB) as c:

    existentes = [
        dict(f)
        for f in c.execute("""
            SELECT
                ac.prediction_id,
                ac.status,
                d.proposed_action,
                d.authorized_action
            FROM agent_cycles ac
            JOIN agent_decisions d ON d.cycle_id = ac.id
            WHERE ac.portfolio_id = ?
            ORDER BY ac.id
        """, (PORTFOLIO_ID,))
    ]

assert len(existentes) <= 30

for i, existente in enumerate(existentes):

    esperada = "BUY" if i == 0 else "HOLD"

    assert existente["prediction_id"] == (
        predicciones[i]["id"]
    )

    assert existente["status"] == "COMPLETED"

    assert existente["proposed_action"] == esperada

    assert existente["authorized_action"] == esperada

completados_antes = len(existentes)

print("Ciclos existentes:", completados_antes)


# 6. Ejecutar la estrategia pasiva.
# No utilizar el rendimiento predicho para decidir.

print("\nSIMULACION BUY & HOLD")
print("-" * 60)

try:

    for i, pred in enumerate(
        predicciones,
        start=1
    ):

        fecha = fecha_utc(
            pred["target_open_time"]
        )

        if i <= completados_antes:

            print(
                f"{i:02d}/30",
                fecha,
                "REGISTRO EXISTENTE"
            )

            continue

        t0 = time.perf_counter()

        if i == 1:

            propuesta = "BUY"

            justificacion = (
                "BUY_HOLD: compra inicial con "
                "el capital disponible. "
                "No utiliza pronosticos."
            )

        else:

            propuesta = "HOLD"

            justificacion = (
                "BUY_HOLD: mantener la posicion "
                "hasta el final del periodo."
            )

        latencia_ms = (
            time.perf_counter() - t0
        ) * 1000

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

            with write_transaction(DB) as c:

                c.execute("""
                    INSERT INTO error_logs (
                        component,
                        error_type,
                        message,
                        corrective_action
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    "REPLAY_BUY_HOLD",
                    type(error).__name__,
                    f"Fallo en ciclo {fecha}.",
                    "Detener y revisar antes de continuar."
                ))

            raise

        assert resultado["real_trading"] is False

        assert resultado["mode"] == "REPLAY"

        assert resultado["cycle_status"] == "COMPLETED"

        assert resultado["authorized_action"] == propuesta

        print(
            f"{i:02d}/30",
            fecha,
            f"Accion: {propuesta}",
            f"Patrimonio: "
            f"{resultado['equity_micros'] / MICROS:,.2f}",
            "USDT",
            flush=True
        )

finally:

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    assert estado_protegido() == protegido_antes

    assert sha256(ruta_protocolo) == huella_protocolo

    for ruta, huella in fuentes.items():

        assert sha256(ruta) == huella


# 7. Obtener resultados persistidos.

with read_connection(DB) as c:

    filas = [
        dict(f)
        for f in c.execute("""
            SELECT
                ac.id AS cycle_id,
                ac.status AS cycle_status,
                pr.target_open_time,
                d.proposed_action,
                d.authorized_action,
                d.risk_approved,
                d.risk_reason,
                d.latency_ms,
                d.llm_model,
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
            FROM agent_cycles ac
            JOIN predictions pr ON pr.id = ac.prediction_id
            JOIN agent_decisions d ON d.cycle_id = ac.id
            JOIN equity_history e ON e.cycle_id = ac.id
                AND e.snapshot_type = 'VALUATION'
            LEFT JOIN orders o ON o.decision_id = d.id
            WHERE ac.portfolio_id = ?
            ORDER BY pr.target_open_time
        """, (PORTFOLIO_ID,))
    ]

    cartera_final = c.execute("""
        SELECT *
        FROM portfolio
        WHERE id = ?
    """, (PORTFOLIO_ID,)).fetchone()

    posicion_final = c.execute("""
        SELECT *
        FROM positions
        WHERE portfolio_id = ?
    """, (PORTFOLIO_ID,)).fetchone()

    max_drawdown = c.execute("""
        SELECT MAX(e.drawdown)
        FROM equity_history e
        JOIN agent_cycles ac ON ac.id = e.cycle_id
        WHERE ac.portfolio_id = ?
    """, (PORTFOLIO_ID,)).fetchone()[0]

    primera_vela = c.execute("""
        SELECT open
        FROM candles
        WHERE asset_id = ?
          AND open_time = ?
          AND interval_seconds = 86400
    """, (
        predicciones[0]["asset_id"],
        predicciones[0]["target_open_time"]
    )).fetchone()

    ultima_vela = c.execute("""
        SELECT close
        FROM candles
        WHERE asset_id = ?
          AND close_time = ?
          AND interval_seconds = 86400
    """, (
        predicciones[-1]["asset_id"],
        predicciones[-1]["target_close_time"]
    )).fetchone()

    fallos = c.execute("""
        SELECT COUNT(*)
        FROM error_logs
        WHERE component = 'REPLAY_BUY_HOLD'
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
    f["cycle_status"] == "COMPLETED"
    for f in filas
)

assert all(
    f["risk_approved"] == 1
    for f in filas
)

assert all(
    f["llm_model"] is None
    for f in filas
)

assert all(
    f["equity_micros"] ==
    f["cash_micros"] + f["position_value_micros"]
    for f in filas
)


# 8. Reconciliar la compra inicial.

ordenes = [
    f for f in filas
    if f["order_status"] == "FILLED"
]

assert len(ordenes) == 1

compra = ordenes[0]

assert compra["order_side"] == "BUY"

assert compra["filled_at"] == (
    predicciones[0]["target_open_time"]
)

assert compra["fee_micros"] == 0

assert compra["slippage_micros"] == 0

assert compra["quantity_sats"] > 0

assert compra["quantity_sats"] == (
    posicion_final["quantity_sats"]
)

assert compra["notional_micros"] == (
    posicion_final["cost_basis_micros"]
)

efectivo = (
    CAPITAL - compra["notional_micros"]
)

assert efectivo == (
    cartera_final["cash_micros"]
)

assert efectivo >= 0

# El residuo de efectivo debe ser menor
# que el precio de un satoshi, salvo redondeo.

assert efectivo <= (
    compra["price_micros"] + SATS - 1
) // SATS + 1

assert all(
    f["authorized_action"] == "HOLD"
    for f in filas[1:]
)

assert all(
    f["order_id"] is None
    for f in filas[1:]
)

print("\nReconciliacion financiera: APROBADA")


# 9. Calcular metricas preliminares.

patrimonio = (
    filas[-1]["equity_micros"] / MICROS
)

rendimiento = (
    patrimonio / 50000 - 1
) * 100

rendimiento_btc = (
    ultima_vela["close"] /
    primera_vela["open"] - 1
) * 100

assert abs(
    rendimiento - rendimiento_btc
) < 0.0001

latencias = [
    f["latency_ms"]
    for f in filas
]

metricas = {
    "Estrategia": "BUY_HOLD",
    "Periodo_inicio_UTC": protocolo[
        "Inicio_objetivo_UTC"
    ],
    "Periodo_fin_UTC": protocolo[
        "Fin_objetivo_UTC"
    ],
    "Capital_inicial_USDT": 50000,
    "Patrimonio_final_valorado_USDT": patrimonio,
    "Efectivo_final_USDT": efectivo / MICROS,
    "Posicion_final_BTC": (
        posicion_final["quantity_sats"] / SATS
    ),
    "Precio_apertura_inicial_USDT": primera_vela[
        "open"
    ],
    "Precio_cierre_final_USDT": ultima_vela[
        "close"
    ],
    "Rendimiento_neto_pct": rendimiento,
    "Rendimiento_BTC_pct": rendimiento_btc,
    "Drawdown_maximo_pct": max_drawdown * 100,
    "Compras": 1,
    "Ventas": 0,
    "Ordenes_ejecutadas": 1,
    "Operaciones_cerradas": 0,
    "Operaciones_ganadoras": 0,
    "Win_rate_pct": None,
    "PnL_realizado_USDT": 0,
    "Latencia_media_ms": statistics.mean(latencias),
    "Latencia_mediana_ms": statistics.median(latencias),
    "Definicion_latencia": (
        "Seleccion de la regla pasiva BUY/HOLD. "
        "No incluye inferencia LSTM ni LLM."
    ),
    "Rechazos_riesgo": 0,
    "Decisiones_HOLD_autorizadas": 29,
    "Ciclos_validos": 30,
    "Ciclos_COMPLETED": 30,
    "Ciclos_REJECTED": 0,
    "Ciclos_fallidos_no_completados": 0,
    "Fallos_registrados": fallos,
    "Comisiones_USDT": 0,
    "Deslizamiento_USDT": 0,
    "Liquidacion_final": "PENDIENTE",
    "Inferencias_LSTM": 0,
    "Inferencias_LLM": 0,
    "Asignacion_inicial_pct": 100,
    "Conjunto": "VA",
    "Modo": "REPLAY",
    "TE_reevaluado": False,
    "Reentrenamiento": False,
    "Dinero_real_utilizado": False
}


# 10. Exportar resultados diarios.

diario = []

for f in filas:

    diario.append({
        "Fecha_objetivo_UTC": fecha_utc(
            f["target_open_time"]
        ),
        "Ciclo_ID": f["cycle_id"],
        "Estado_ciclo": f["cycle_status"],
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

ruta_diaria = (
    REPLAY / "replay_buy_hold_diario.csv"
)

pd.DataFrame(diario).to_csv(
    ruta_diaria,
    index=False
)

ruta_metricas = (
    REPLAY / "metricas_buy_hold.json"
)

guardar_json(
    ruta_metricas,
    metricas
)


# 11. Comparar las tres estrategias.

comparacion = []

for nombre in ("model_only", "llm", "buy_hold"):

    m = leer_json(
        REPLAY / f"metricas_{nombre}.json"
    )

    comparacion.append({
        "Estrategia": m["Estrategia"],
        "Capital_inicial_USDT": m[
            "Capital_inicial_USDT"
        ],
        "Patrimonio_final_USDT": m[
            "Patrimonio_final_valorado_USDT"
        ],
        "Rendimiento_pct": m[
            "Rendimiento_neto_pct"
        ],
        "Drawdown_maximo_pct": m[
            "Drawdown_maximo_pct"
        ],
        "Compras": m["Compras"],
        "Ventas": m["Ventas"],
        "Rechazos": m["Rechazos_riesgo"],
        "Ciclos_validos": m["Ciclos_validos"],
        "Liquidacion_final": m["Liquidacion_final"]
    })

tabla_comparativa = pd.DataFrame(
    comparacion
)

assert tabla_comparativa[
    "Ciclos_validos"
].eq(30).all()

ruta_comparacion = (
    REPLAY / "comparacion_preliminar.csv"
)

tabla_comparativa.to_csv(
    ruta_comparacion,
    index=False
)


# 12. Verificar integridad final.

assert database_hash() == db_antes

assert model_hashes() == modelo_antes

assert estado_protegido() == protegido_antes

assert sha256(ruta_protocolo) == huella_protocolo

for ruta, huella in fuentes.items():

    assert sha256(ruta) == huella

verify_artifacts()


# 13. Guardar evidencia academica.

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "14.5",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",
    "SHA256_protocolo": huella_protocolo,
    "Metricas": metricas,
    "Comparacion_preliminar": comparacion,
    "Archivo_diario": str(
        ruta_diaria.relative_to(BASE)
    ),
    "SHA256_archivo_diario": sha256(
        ruta_diaria
    ),
    "Archivo_metricas": str(
        ruta_metricas.relative_to(BASE)
    ),
    "SHA256_archivo_metricas": sha256(
        ruta_metricas
    ),
    "SHA256_comparacion_preliminar": sha256(
        ruta_comparacion
    ),
    "Ciclos_validos_totales": 90,
    "Compra_inicial_unica": True,
    "Reconciliacion_financiera": True,
    "Resultados_anteriores_intactos": True,
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
    RESULTS / "control_replay_buy_hold.json"
)

guardar_json(
    ruta_evidencia,
    evidencia
)


# 14. Mostrar resultados.

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO BUY & HOLD")
print("=" * 60)

print(json.dumps(
    metricas,
    indent=4,
    ensure_ascii=False,
    allow_nan=False
))

print("\nCOMPARACION PRELIMINAR DE ESTRATEGIAS")

print(
    tabla_comparativa.to_string(index=False)
)

print("\nCiclos BUY_HOLD validos: 30 / 30")
print("Ciclos comparativos totales: 90 / 90")
print("Capital inicial: 50000 USDT")
print("Patrimonio final:", patrimonio, "USDT")
print("Rendimiento neto:", rendimiento, "%")
print("Compras: 1")
print("Ventas: 0")
print("Rechazos de riesgo: 0")
print("Reconciliacion financiera: APROBADA")
print("Resultados MODEL_ONLY intactos: SI")
print("Resultados QWEN3 intactos: SI")
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("LSTM utilizado para decidir: NO")
print("Qwen3 utilizado: NO")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")
print("Liquidacion final: PENDIENTE")
print("Tiempo total:", evidencia["Tiempo_segundos"])
print("Evidencia:", ruta_evidencia.name)

print("\nSIMULACION BUY & HOLD COMPLETADA")
print("PASO 14.5 COMPLETADO CORRECTAMENTE")

