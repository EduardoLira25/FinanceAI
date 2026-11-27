import json
import hashlib
import statistics
import time
import os

from pathlib import Path
from datetime import date, datetime, timezone

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
    MICROS,
    SATOSHIS,
    price_to_micros
)

from backend.app.services.financial_prompt import (
    FinancialContext,
    build_context_data,
    build_messages,
    prompt_sha256
)

from backend.app.services.llm_decision import (
    request_decision,
    validate_decision,
    database_hash,
    model_hashes
)

from backend.app.services.ollama_client import (
    OllamaClient
)

from backend.app.services.agent_context import (
    temporary_ollama
)

from backend.app.services.paper_trading import (
    execute_replay_cycle
)


BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "replay"
RESULTS = BASE / "results"

DB = REPLAY / "financeai_replay.db"

JOURNAL = REPLAY / "llm_decisions"

JOURNAL.mkdir(exist_ok=True)

CAPITAL = 50000 * MICROS
DAY = 86400

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

    temporal = ruta.with_name(
        ruta.name + ".tmp"
    )

    with temporal.open(
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            contenido,
            archivo,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        )

        archivo.flush()

        os.fsync(archivo.fileno())

    os.replace(temporal, ruta)


def fecha_utc(timestamp):

    return datetime.fromtimestamp(
        timestamp,
        timezone.utc
    ).date().isoformat()


print("=" * 60)
print("FINANCEAI - SIMULACION LSTM + QWEN3")
print("=" * 60)


# 1. Verificar protocolo y modelo congelado.

ruta_protocolo = (
    REPLAY / "protocolo_replay_VA_30.json"
)

huella_protocolo = sha256(
    ruta_protocolo
)

assert huella_protocolo == (
    "6191c13274b511013f9f118636082772b"
    "3b3003a9e148776f4aaedc86c3b656c"
)

protocolo = leer_json(ruta_protocolo)

assert protocolo["Conjunto"] == "VA"

assert DB.is_file()

assert DB.resolve() != (
    DATABASE_PATH.resolve()
)

verify_artifacts()

assert prompt_sha256() == (
    "7367650d68302e39ea5d8a273f2d1344"
    "cc8f01f1affa5a1d6dd9d37b26fc8f1f"
)

print("Protocolo experimental: VERIFICADO")
print("Modelo LSTM: VERIFICADO")
print("Prompt financiero original: VERIFICADO")


# 2. Verificar contextos y fuentes originales.

ruta_contextos = (
    REPLAY / "contextos_causales_llm.json"
)

control_contextos = leer_json(
    RESULTS / "control_contextos_replay_llm.json"
)

assert sha256(ruta_contextos) == (
    control_contextos["SHA256_contextos"]
)

contextos = leer_json(ruta_contextos)

assert len(contextos) == 30

assert len({
    c["target_date"]
    for c in contextos
}) == 30

fuentes = {
    BASE / protocolo["Fuente_predicciones_VA"]:
        protocolo["SHA256_predicciones_VA"],

    BASE / protocolo["Archivo_datos_replay"]:
        protocolo["SHA256_datos_replay"],

    ruta_contextos:
        control_contextos["SHA256_contextos"]
}

control_model_only = leer_json(
    RESULTS / "control_replay_model_only.json"
)

fuentes[
    REPLAY / "metricas_model_only.json"
] = control_model_only[
    "SHA256_archivo_metricas"
]

fuentes[
    REPLAY / "replay_model_only_diario.csv"
] = control_model_only[
    "SHA256_archivo_diario"
]

for ruta, huella in fuentes.items():

    assert sha256(ruta) == huella

print("Contextos causales: 30 / 30")
print("Resultados MODEL_ONLY: PROTEGIDOS")


# 3. Identificar cartera independiente LLM.

with read_connection(DB) as c:

    cartera = c.execute("""
        SELECT *
        FROM portfolio
        WHERE strategy = 'LLM'
          AND mode = 'REPLAY'
          AND name = 'Replay_LLM'
    """).fetchone()

    assert cartera is not None

    PORTFOLIO_ID = cartera["id"]

    assert cartera["initial_cash_micros"] == CAPITAL

    assert cartera["status"] == "ACTIVE"

    assert cartera["currency"] == "USDT"

    predicciones = [
        dict(fila)
        for fila in c.execute("""
            SELECT
                p.*,
                v.asset_id,
                v.open_time AS reference_open,
                v.close_time AS reference_close_time,
                v.close AS reference_price
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

for pred, contexto in zip(
    predicciones, contextos
):

    assert pred["id"] == contexto["prediction_id"]

    assert pred["candle_id"] == contexto["candle_id"]

    assert pred["predicted_return"] == (
        contexto["predicted_return"]
    )

    assert fecha_utc(
        pred["target_open_time"]
    ) == contexto["target_date"]

    assert pred["reference_close_time"] == (
        pred["emission_time"]
    )

    assert pred["emission_time"] == (
        pred["target_open_time"]
    )


# 4. Proteger las otras estrategias y los datos.

def estado_protegido():

    with read_connection(DB) as c:

        resultado = {}

        for tabla in (
            "assets",
            "candles",
            "model_versions",
            "predictions",
            "risk_config"
        ):

            resultado[tabla] = [
                dict(f)
                for f in c.execute(
                    f"SELECT * FROM {tabla} ORDER BY rowid"
                ).fetchall()
            ]

        for tabla, campo in (
            ("portfolio", "id"),
            ("positions", "portfolio_id"),
            ("agent_cycles", "portfolio_id")
        ):

            resultado[tabla] = [
                dict(f)
                for f in c.execute(
                    f"""
                    SELECT *
                    FROM {tabla}
                    WHERE {campo} != ?
                    ORDER BY id
                    """,
                    (PORTFOLIO_ID,)
                ).fetchall()
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

            resultado[tabla] = [
                dict(f)
                for f in c.execute(
                    consulta,
                    (PORTFOLIO_ID,)
                ).fetchall()
            ]

    return resultado


protegido_antes = estado_protegido()


# 5. Verificar ciclos existentes.

with read_connection(DB) as c:

    existentes = [
        dict(f)
        for f in c.execute("""
            SELECT
                c.id AS cycle_id,
                c.prediction_id,
                c.status,
                d.proposed_action,
                d.llm_model,
                d.llm_response
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

    assert existente["status"] in (
        "COMPLETED", "REJECTED"
    )

    assert existente["llm_model"] == "qwen3:8b"

    ruta = JOURNAL / (
        fecha_utc(pred["target_open_time"]) + ".json"
    )

    registro = leer_json(ruta)

    assert registro["status"] in (
        "VALIDATED", "COMPLETED"
    )

    assert registro["prediction_id"] == pred["id"]

    assert registro["result"]["raw_response"] == (
        existente["llm_response"]
    )

    assert registro["result"]["decision"]["action"] == (
        existente["proposed_action"]
    )

    # Reconciliar un ciclo previamente confirmado.

    registro["status"] = "COMPLETED"

    registro["cycle_id"] = existente["cycle_id"]

    guardar_json(ruta, registro)


completados_antes = len(existentes)

print("Ciclos LLM existentes:", completados_antes)


# 6. Construir el contexto financiero de cada ciclo.

def construir_contexto(pred, previo):

    emision = pred["emission_time"]

    with read_connection(DB) as c:

        cierres = c.execute("""
            SELECT open_time, close_time, close
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = 86400
              AND close_time <= ?
            ORDER BY open_time DESC
            LIMIT 40
        """, (
            pred["asset_id"],
            emision
        )).fetchall()

        p = c.execute("""
            SELECT *
            FROM portfolio
            WHERE id = ?
        """, (PORTFOLIO_ID,)).fetchone()

        pos = c.execute("""
            SELECT *
            FROM positions
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (
            PORTFOLIO_ID,
            pred["asset_id"]
        )).fetchone()

        r = c.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (PORTFOLIO_ID,)).fetchone()

        anterior = c.execute("""
            SELECT
                e.recorded_at,
                e.equity_micros
            FROM equity_history e
            JOIN agent_cycles ac ON ac.id = e.cycle_id
            WHERE ac.portfolio_id = ?
              AND e.snapshot_type = 'VALUATION'
            ORDER BY e.recorded_at DESC
            LIMIT 1
        """, (PORTFOLIO_ID,)).fetchone()

    assert p["status"] == "ACTIVE"

    assert p["mode"] == "REPLAY"

    assert r["max_exposure_bps"] == 2500
    assert r["max_daily_loss_bps"] == 200
    assert r["max_data_age_seconds"] == 3600
    assert r["min_order_micros"] == 10000000
    assert r["fee_bps"] == 0
    assert r["slippage_bps"] == 0
    assert r["prediction_threshold"] == 0.001
    assert r["emergency_stop"] == 0

    cierres = list(reversed(cierres))

    assert len(cierres) == 40

    assert cierres[-1]["close_time"] == emision

    assert all(
        f["close_time"] <= emision
        for f in cierres
    )

    assert all(
        cierres[i]["open_time"] -
        cierres[i - 1]["open_time"] == DAY
        for i in range(1, 40)
    )

    valores = np.asarray(
        [f["close"] for f in cierres],
        dtype=np.float64
    )

    features = build_features(valores)

    assert features.shape == (20, 3)

    assert np.allclose(
        features[:, 0],
        previo["returns_20"],
        atol=1e-12,
        rtol=0
    )

    assert abs(
        features[-1, 1] - previo["sma_distance_20"]
    ) <= 1e-12

    assert abs(
        features[-1, 2] - previo["volatility_20"]
    ) <= 1e-12

    reproducida = float(
        infer_return(features)
    )

    assert abs(
        reproducida - pred["predicted_return"]
    ) <= 1e-6

    assert (
        reproducida > 0.001
    ) == (
        pred["predicted_return"] > 0.001
    )

    reference_price = float(valores[-1])

    assert reference_price == pred["reference_price"]

    valor_posicion = (
        pos["quantity_sats"]
        * price_to_micros(reference_price)
        // SATOSHIS
    )

    baseline = (
        p["cash_micros"] + valor_posicion
    )

    if anterior is None:

        assert baseline == CAPITAL

        assert pos["quantity_sats"] == 0

    else:

        assert anterior["recorded_at"] == emision

        assert anterior["equity_micros"] == baseline

    contexto = FinancialContext(
        mode="REPLAY",
        symbol="BTCUSDT",
        candle_date=date.fromisoformat(
            previo["candle_date"]
        ),
        as_of_utc=datetime.fromtimestamp(
            emision, timezone.utc
        ),
        reference_close=reference_price,
        predicted_return=float(
            pred["predicted_return"]
        ),
        returns_20=tuple(
            float(v) for v in features[:, 0]
        ),
        sma_distance_20=float(features[-1, 1]),
        volatility_20=float(features[-1, 2]),
        cash_micros=p["cash_micros"],
        quantity_sats=pos["quantity_sats"],
        day_start_equity_micros=baseline,
        portfolio_status=p["status"],
        max_exposure_bps=r["max_exposure_bps"],
        max_daily_loss_bps=r["max_daily_loss_bps"],
        max_data_age_seconds=r["max_data_age_seconds"],
        min_order_micros=r["min_order_micros"],
        fee_bps=r["fee_bps"],
        slippage_bps=r["slippage_bps"],
        prediction_threshold=r["prediction_threshold"],
        emergency_stop=bool(r["emergency_stop"])
    )

    datos = build_context_data(contexto)

    assert datos["data_age_seconds"] == 0

    assert datos["risk"]["data_is_stale"] is False

    assert datos["mode"] == "REPLAY"

    assert datos["target_date"] == previo["target_date"]

    assert datos["market"][
        "execution_quote_available"
    ] is False

    return contexto


# 7. Capturar respuesta original, incluso ante
# una respuesta JSON invalida del modelo.

class CaptureClient:

    def __init__(self, client):

        self.client = client

        self.raw = None

    def chat(self, messages, schema):

        response = self.client.chat(
            messages=messages,
            schema=schema
        )

        self.raw = response.get("content")

        return response


# 8. Registrar incidentes sin alterar el
# capital ni crear decisiones ficticias.

def registrar_fallo(fecha, etapa, error):

    codigo = getattr(
        error,
        "code",
        type(error).__name__
    )

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
            "REPLAY_LLM",
            str(codigo),
            f"Fallo en {etapa}: {fecha}",
            type(error).__name__,
            "Detener replay y revisar evidencia."
        ))

    print(
        "INCIDENTE:",
        fecha,
        etapa,
        codigo,
        flush=True
    )


# 9. Ejecutar los ciclos de manera secuencial.

def ejecutar_ciclos(client):

    for i, (pred, previo) in enumerate(
        zip(predicciones, contextos),
        start=1
    ):

        fecha = previo["target_date"]

        if i <= completados_antes:

            print(
                f"{i:02d}/30",
                fecha,
                "REGISTRO EXISTENTE",
                flush=True
            )

            continue

        ruta_registro = (
            JOURNAL / f"{fecha}.json"
        )

        print(
            f"\n{i:02d}/30 | {fecha}",
            flush=True
        )

        t0 = time.perf_counter()

        contexto = construir_contexto(
            pred, previo
        )

        datos_contexto = build_context_data(
            contexto
        )

        # Conservar una propuesta previamente validada
        # sin volver a consultar al LLM.

        if ruta_registro.exists():

            registro = leer_json(ruta_registro)

            if registro["status"] != "VALIDATED":

                raise RuntimeError(
                    "Existe un intento pendiente o fallido "
                    f"para {fecha}. Requiere revision manual."
                )

            assert registro["prediction_id"] == pred["id"]

            assert registro["context"] == datos_contexto

            respuesta = registro["result"]

            decision = validate_decision(
                respuesta["raw_response"],
                contexto
            ).model_dump()

            assert decision == respuesta["decision"]

            latencia_total = registro[
                "decision_latency_ms"
            ]

            print(
                "Propuesta validada existente: REUTILIZADA",
                flush=True
            )

        else:

            registro = {
                "status": "STARTED",
                "prediction_id": pred["id"],
                "target_date": fecha,
                "context": datos_contexto,
                "messages": build_messages(contexto),
                "started_at_utc": datetime.now(
                    timezone.utc
                ).isoformat()
            }

            guardar_json(
                ruta_registro, registro
            )

            captura = CaptureClient(client)

            try:

                respuesta = request_decision(
                    contexto,
                    captura
                )

                assert respuesta[
                    "validation_status"
                ] == "VALID"

                assert respuesta["real_trading"] is False

                assert respuesta["llm_model"] == (
                    protocolo["Modelo_LLM"]
                )

                assert respuesta[
                    "llm_digest"
                ].removeprefix("sha256:") == (
                    protocolo["Digest_LLM"]
                )

                assert respuesta[
                    "ollama_version"
                ] == protocolo["Ollama_version"]

                assert respuesta["prompt_sha256"] == (
                    prompt_sha256()
                )

                decision = respuesta["decision"]

                latencia_total = (
                    time.perf_counter() - t0
                ) * 1000

                registro.update({
                    "status": "VALIDATED",
                    "result": respuesta,
                    "decision_latency_ms": latencia_total
                })

                guardar_json(
                    ruta_registro, registro
                )

            except Exception as error:

                registro.update({
                    "status": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": str(
                        getattr(error, "code", "")
                    ),
                    "raw_response": (
                        captura.raw[:8192]
                        if isinstance(captura.raw, str)
                        else None
                    )
                })

                guardar_json(
                    ruta_registro, registro
                )

                registrar_fallo(
                    fecha, "LLM_DECISION", error
                )

                raise

        assert decision["symbol"] == "BTCUSDT"

        assert decision["candle_date"] == (
            previo["candle_date"]
        )

        propuesta = decision["action"]

        print(
            "Prediccion LSTM:",
            f"{pred['predicted_return'] * 100:+.4f}%"
        )

        print("Propuesta Qwen3:", propuesta)

        print(
            "Justificacion:",
            decision["rationale"]
        )

        # La propuesta ya esta fijada y validada.
        # El ejecutor accede ahora a la apertura
        # y posteriormente al cierre objetivo.

        try:

            resultado = execute_replay_cycle(
                PORTFOLIO_ID,
                pred["id"],
                propuesta,
                decision["rationale"],
                path=DB,
                llm_model=respuesta["llm_model"],
                llm_response=respuesta["raw_response"],
                latency_ms=latencia_total
            )

        except Exception as error:

            registro["status"] = "EXECUTION_FAILED"

            registro["execution_error"] = (
                type(error).__name__
            )

            guardar_json(
                ruta_registro,
                registro
            )

            registrar_fallo(
                fecha, "PAPER_EXECUTION", error
            )

            raise

        assert resultado["mode"] == "REPLAY"

        assert resultado["real_trading"] is False

        assert resultado["cycle_status"] in (
            "COMPLETED", "REJECTED"
        )

        registro.update({
            "status": "COMPLETED",
            "cycle_id": resultado["cycle_id"],
            "execution": resultado
        })

        guardar_json(
            ruta_registro,
            registro
        )

        print(
            "Accion autorizada:",
            resultado["authorized_action"]
        )

        print(
            "Patrimonio:",
            f"{resultado['equity_micros'] / MICROS:,.2f}",
            "USDT"
        )

        print(
            "Latencia Qwen3:",
            round(respuesta["latency_ms"], 2),
            "ms"
        )

        print(
            "Latencia total decision:",
            round(latencia_total, 2),
            "ms",
            flush=True
        )


# 10. Iniciar Ollama temporalmente.

try:

    if completados_antes < 30:

        print(
            "\nINICIANDO QWEN3 LOCAL",
            flush=True
        )

        with temporary_ollama(
            RESULTS / "ollama_replay_llm.log"
        ):

            with OllamaClient() as client:

                client.verify_model()

                print(
                    "Identidad Qwen3: VERIFICADA",
                    flush=True
                )

                ejecutar_ciclos(client)

    else:

        print("Los 30 ciclos ya existen.")

finally:

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    assert estado_protegido() == protegido_antes

    assert sha256(ruta_protocolo) == (
        huella_protocolo
    )

    for ruta, huella in fuentes.items():

        assert sha256(ruta) == huella


# 11. Consultar los resultados persistidos.

with read_connection(DB) as c:

    filas = [
        dict(f)
        for f in c.execute("""
            SELECT
                ac.id AS cycle_id,
                ac.status AS cycle_status,
                pr.target_open_time,
                pr.predicted_return,
                d.proposed_action,
                d.authorized_action,
                d.rationale,
                d.risk_approved,
                d.risk_reason,
                d.latency_ms,
                d.llm_model,
                d.llm_response,
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
        """, (PORTFOLIO_ID,)).fetchall()
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

    fallos = c.execute("""
        SELECT COUNT(*)
        FROM error_logs
        WHERE component = 'REPLAY_LLM'
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
    f["llm_model"] == "qwen3:8b"
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


# 12. Reconciliar operaciones financieras.

efectivo = CAPITAL

cantidad = 0

costo_abierto = 0

pnl_cerrados = []

compras = 0

ventas = 0

for f in filas:

    if f["order_status"] != "FILLED":

        continue

    assert f["fee_micros"] == 0

    assert f["slippage_micros"] == 0

    assert f["filled_at"] == f["target_open_time"]

    if f["order_side"] == "BUY":

        compras += 1

        efectivo -= f["notional_micros"]

        cantidad += f["quantity_sats"]

        costo_abierto += f["notional_micros"]

    elif f["order_side"] == "SELL":

        ventas += 1

        assert f["quantity_sats"] == cantidad

        efectivo += f["notional_micros"]

        pnl_cerrados.append(
            f["notional_micros"] - costo_abierto
        )

        cantidad = 0

        costo_abierto = 0

    assert efectivo >= 0

assert efectivo == cartera_final["cash_micros"]

assert cantidad == posicion_final["quantity_sats"]

assert costo_abierto == (
    posicion_final["cost_basis_micros"]
)

print("\nReconciliacion financiera: APROBADA")


# 13. Exportar decisiones y resultados diarios.

diario = []

latencias_llm = []

latencias_totales = []

huellas_decisiones = {}

for f in filas:

    fecha = fecha_utc(
        f["target_open_time"]
    )

    ruta = JOURNAL / f"{fecha}.json"

    registro = leer_json(ruta)

    assert registro["status"] == "COMPLETED"

    assert registro["result"]["raw_response"] == (
        f["llm_response"]
    )

    assert registro["result"]["decision"]["action"] == (
        f["proposed_action"]
    )

    assert registro["result"]["validation_status"] == "VALID"

    latencia_llm = registro["result"]["latency_ms"]

    assert latencia_llm >= 0

    assert f["latency_ms"] >= 0

    latencias_llm.append(latencia_llm)

    latencias_totales.append(
        f["latency_ms"]
    )

    huellas_decisiones[ruta.name] = sha256(ruta)

    diario.append({
        "Fecha_objetivo_UTC": fecha,
        "Ciclo_ID": f["cycle_id"],
        "Estado_ciclo": f["cycle_status"],
        "Rendimiento_predicho_pct": (
            f["predicted_return"] * 100
        ),
        "Propuesta": f["proposed_action"],
        "Accion_autorizada": f["authorized_action"],
        "Justificacion_LLM": f["rationale"],
        "Riesgo_aprobado": bool(f["risk_approved"]),
        "Motivo_riesgo": f["risk_reason"],
        "Orden_ID": f["order_id"],
        "Orden_tipo": f["order_side"],
        "Cantidad_BTC": (
            f["quantity_sats"] / SATOSHIS
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
        "Latencia_LLM_ms": latencia_llm,
        "Latencia_ms": f["latency_ms"]
    })

ruta_diaria = REPLAY / "replay_llm_diario.csv"

pd.DataFrame(diario).to_csv(
    ruta_diaria,
    index=False
)


# 14. Calcular metricas comparativas.

patrimonio = filas[-1]["equity_micros"] / MICROS

rendimiento = (
    patrimonio / 50000 - 1
) * 100

ganadoras = sum(
    pnl > 0
    for pnl in pnl_cerrados
)

rechazos = sum(
    not bool(f["risk_approved"])
    for f in filas
)

holds = sum(
    f["authorized_action"] == "HOLD"
    for f in filas
)

propuestas = {
    accion: sum(
        f["proposed_action"] == accion
        for f in filas
    )
    for accion in ("BUY", "SELL", "HOLD")
}

metricas = {
    "Estrategia": "LLM",
    "Periodo_inicio_UTC": protocolo["Inicio_objetivo_UTC"],
    "Periodo_fin_UTC": protocolo["Fin_objetivo_UTC"],
    "Capital_inicial_USDT": 50000,
    "Patrimonio_final_valorado_USDT": patrimonio,
    "Efectivo_final_USDT": efectivo / MICROS,
    "Posicion_final_BTC": cantidad / SATOSHIS,
    "Rendimiento_neto_pct": rendimiento,
    "Drawdown_maximo_pct": max_drawdown * 100,
    "Compras": compras,
    "Ventas": ventas,
    "Ordenes_ejecutadas": compras + ventas,
    "Operaciones_cerradas": len(pnl_cerrados),
    "Operaciones_ganadoras": ganadoras,
    "Win_rate_pct": (
        ganadoras / len(pnl_cerrados) * 100
        if pnl_cerrados
        else None
    ),
    "PnL_realizado_USDT": sum(pnl_cerrados) / MICROS,
    "Latencia_media_ms": statistics.mean(
        latencias_totales
    ),
    "Latencia_mediana_ms": statistics.median(
        latencias_totales
    ),
    "Latencia_LLM_media_ms": statistics.mean(
        latencias_llm
    ),
    "Latencia_LLM_mediana_ms": statistics.median(
        latencias_llm
    ),
    "Definicion_latencia": (
        "Preparacion del contexto, inferencia LSTM, "
        "inferencia Qwen3 y validacion de propuesta."
    ),
    "Propuestas_LLM": propuestas,
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
    "Fallos_registrados": fallos,
    "Comisiones_USDT": 0,
    "Deslizamiento_USDT": 0,
    "Liquidacion_final": (
        "PENDIENTE" if cantidad > 0
        else "NO_NECESARIA"
    ),
    "Inferencias_LLM_validas": 30,
    "Modelo_LLM": "qwen3:8b",
    "Ollama_version": protocolo["Ollama_version"],
    "Prompt_SHA256": prompt_sha256(),
    "Conjunto": "VA",
    "Modo": "REPLAY",
    "TE_reevaluado": False,
    "Reentrenamiento": False,
    "Dinero_real_utilizado": False
}

ruta_metricas = REPLAY / "metricas_llm.json"

guardar_json(ruta_metricas, metricas)


# 15. Verificacion final de integridad.

assert database_hash() == db_antes

assert model_hashes() == modelo_antes

assert estado_protegido() == protegido_antes

assert sha256(ruta_protocolo) == huella_protocolo

for ruta, huella in fuentes.items():

    assert sha256(ruta) == huella

verify_artifacts()


# 16. Comparacion preliminar con MODEL_ONLY.

model_only = leer_json(
    REPLAY / "metricas_model_only.json"
)

comparacion = {
    "Patrimonio_MODEL_ONLY": model_only[
        "Patrimonio_final_valorado_USDT"
    ],
    "Patrimonio_LLM": patrimonio,
    "Diferencia_patrimonio_USDT": (
        patrimonio -
        model_only["Patrimonio_final_valorado_USDT"]
    ),
    "Rendimiento_MODEL_ONLY_pct": model_only[
        "Rendimiento_neto_pct"
    ],
    "Rendimiento_LLM_pct": rendimiento,
    "Diferencia_rendimiento_pp": (
        rendimiento -
        model_only["Rendimiento_neto_pct"]
    ),
    "Rechazos_MODEL_ONLY": model_only[
        "Rechazos_riesgo"
    ],
    "Rechazos_LLM": rechazos,
    "Comparacion_definitiva": False
}


# 17. Guardar evidencia academica.

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "14.4.2",
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
    "SHA256_archivo_diario": sha256(ruta_diaria),
    "Archivo_metricas": str(
        ruta_metricas.relative_to(BASE)
    ),
    "SHA256_archivo_metricas": sha256(ruta_metricas),
    "SHA256_decisiones": huellas_decisiones,
    "Contextos_causales": 30,
    "Respuestas_JSON_validas": 30,
    "Reconciliacion_financiera": True,
    "Otras_carteras_intactas": True,
    "Resultados_MODEL_ONLY_intactos": True,
    "Base_principal_intacta": True,
    "Modelo_LSTM_intacto": True,
    "Prompt_original_intacto": True,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Datos_futuros_en_contextos": False,
    "Limitacion_metodologica": (
        "Qwen3 puede poseer conocimiento posterior "
        "al periodo historico por su entrenamiento previo."
    ),
    "Dinero_real_utilizado": False,
    "Tiempo_segundos": round(
        time.perf_counter() - inicio_proceso,
        4
    )
}

ruta_evidencia = (
    RESULTS / "control_replay_llm.json"
)

guardar_json(ruta_evidencia, evidencia)


print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO LSTM + QWEN3")
print("=" * 60)

print(json.dumps(
    metricas,
    indent=4,
    ensure_ascii=False,
    allow_nan=False
))

print("\nCOMPARACION PRELIMINAR")

print(json.dumps(
    comparacion,
    indent=4,
    ensure_ascii=False
))

print("\nCiclos validos: 30 / 30")
print("Inferencias LLM validas: 30 / 30")
print("Capital inicial: 50000 USDT")
print("Patrimonio final:", round(patrimonio, 6), "USDT")
print("Rendimiento neto:", round(rendimiento, 6), "%")
print("Compras:", compras)
print("Ventas:", ventas)
print("Rechazos de riesgo:", rechazos)
print("Decisiones HOLD:", holds)
print("Fallos registrados:", fallos)
print("Reconciliacion financiera: APROBADA")
print("Resultados MODEL_ONLY intactos: SI")
print("Cartera BUY_HOLD intacta: SI")
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("Prompt original intacto: SI")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")
print("Tiempo total:", evidencia["Tiempo_segundos"], "segundos")
print("Evidencia:", ruta_evidencia.name)

print("\nSIMULACION LSTM + QWEN3 COMPLETADA")
print("PASO 14.4.2 COMPLETADO CORRECTAMENTE")

