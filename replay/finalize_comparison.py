import json
import hashlib
import sqlite3
import tempfile
import os
import time

from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.core.config import DATABASE_PATH
from backend.app.core.database import read_connection

from backend.app.services.risk import price_to_micros

from backend.app.services.prediction import verify_artifacts

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "replay"
RESULTS = BASE / "results"
FIGURAS = REPLAY / "figuras"

FIGURAS.mkdir(exist_ok=True)

DB = REPLAY / "financeai_replay.db"
FINAL = REPLAY / "financeai_replay_final.db"

MICROS = 1000000
SATS = 100000000
CAPITAL = 50000 * MICROS

inicio_proceso = time.perf_counter()

db_antes = database_hash()
modelo_antes = model_hashes()

NOMBRES = {
    "MODEL_ONLY": "LSTM",
    "LLM": "LSTM + Qwen3",
    "BUY_HOLD": "Buy & Hold"
}

COLORES = {
    "MODEL_ONLY": "#64748b",
    "LLM": "#6366f1",
    "BUY_HOLD": "#16a34a"
}

ESTRATEGIAS = [
    ("MODEL_ONLY", "model_only"),
    ("LLM", "llm"),
    ("BUY_HOLD", "buy_hold")
]


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


def hash_logico(ruta):

    with read_connection(ruta) as c:

        contenido = "\n".join(
            c.iterdump()
        ).encode("utf-8")

    return hashlib.sha256(
        contenido
    ).hexdigest()


def leer_json(ruta):

    return json.loads(
        ruta.read_text(encoding="utf-8")
    )


def guardar_json(ruta, datos):

    ruta.write_text(
        json.dumps(
            datos,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )


print("=" * 60)
print("FINANCEAI - COMPARACION FINANCIERA FINAL")
print("=" * 60)


# 1. Verificar protocolo y originales.

assert DB.resolve() != DATABASE_PATH.resolve()

assert FINAL.resolve() != DATABASE_PATH.resolve()

assert DB.resolve() != FINAL.resolve()

verify_artifacts()

replay_antes = hash_logico(DB)

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

assert protocolo["Capital_inicial_USDT"] == 50000

print("Protocolo congelado: VERIFICADO")
print("Modelo LSTM: VERIFICADO")


# 2. Verificar resultados de las tres estrategias.

fuentes = {
    ruta_protocolo: huella_protocolo,

    BASE / protocolo["Fuente_predicciones_VA"]:
        protocolo["SHA256_predicciones_VA"],

    BASE / protocolo["Archivo_datos_replay"]:
        protocolo["SHA256_datos_replay"]
}

metricas_originales = {}

diarios = {}

for estrategia, nombre in ESTRATEGIAS:

    control = leer_json(
        RESULTS / f"control_replay_{nombre}.json"
    )

    ruta_metricas = (
        REPLAY / f"metricas_{nombre}.json"
    )

    ruta_diario = (
        REPLAY / f"replay_{nombre}_diario.csv"
    )

    fuentes[ruta_metricas] = (
        control["SHA256_archivo_metricas"]
    )

    fuentes[ruta_diario] = (
        control["SHA256_archivo_diario"]
    )

    m = leer_json(ruta_metricas)

    assert m["Estrategia"] == estrategia

    assert m["Ciclos_validos"] == 30

    assert m["Ciclos_fallidos_no_completados"] == 0

    assert m["Capital_inicial_USDT"] == 50000

    assert m["Comisiones_USDT"] == 0

    assert m["Deslizamiento_USDT"] == 0

    assert m["Periodo_inicio_UTC"] == (
        protocolo["Inicio_objetivo_UTC"]
    )

    assert m["Periodo_fin_UTC"] == (
        protocolo["Fin_objetivo_UTC"]
    )

    metricas_originales[estrategia] = m

    df = pd.read_csv(ruta_diario)

    df["Fecha_objetivo_UTC"] = pd.to_datetime(
        df["Fecha_objetivo_UTC"],
        utc=True
    )

    assert len(df) == 30

    assert df["Fecha_objetivo_UTC"].is_unique

    assert df["Fecha_objetivo_UTC"].is_monotonic_increasing

    assert df["Fecha_objetivo_UTC"].diff().dropna().eq(
        pd.Timedelta(days=1)
    ).all()

    assert np.allclose(
        df["Patrimonio_USDT"],
        df["Efectivo_USDT"] + df["Posicion_USDT"],
        atol=1e-6,
        rtol=0
    )

    diarios[estrategia] = df

    print(
        estrategia,
        "30 ciclos: VERIFICADOS"
    )


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

print("Evidencias originales: VERIFICADAS")


# 3. Obtener el ultimo cierre historico.

fin = pd.Timestamp(
    protocolo["Fin_objetivo_UTC"],
    tz="UTC"
)

apertura_final = int(fin.timestamp())

cierre_final = apertura_final + 86400

with read_connection(DB) as c:

    vela = c.execute("""
        SELECT v.*
        FROM candles v
        JOIN assets a ON a.id = v.asset_id
        WHERE a.symbol = 'BTCUSDT'
          AND v.interval_seconds = 86400
          AND v.open_time = ?
    """, (apertura_final,)).fetchone()

    assert vela is not None

    assert vela["close_time"] == cierre_final

    precio_final = float(vela["close"])

    ASSET_ID = vela["asset_id"]

    assert c.execute("""
        SELECT COUNT(*)
        FROM agent_cycles
    """).fetchone()[0] == 90

    assert c.execute("""
        SELECT COUNT(*)
        FROM agent_decisions
    """).fetchone()[0] == 90

    assert c.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status = 'FILLED'
    """).fetchone()[0] == 6

PRECIO_MICROS = price_to_micros(precio_final)

assert precio_final == 98608.0

print("\nPrecio de liquidacion:", precio_final)
print("Ciclos originales: 90")
print("Ordenes originales: 6")


# 4. Crear registro independiente de liquidaciones.
# No modificar las decisiones diarias originales.

SCHEMA_LIQUIDACION = """
CREATE TABLE replay_liquidations (

    portfolio_id INTEGER PRIMARY KEY
        REFERENCES portfolio(id),

    asset_id INTEGER NOT NULL
        REFERENCES assets(id),

    quantity_sats INTEGER NOT NULL
        CHECK(quantity_sats >= 0),

    price_micros INTEGER NOT NULL
        CHECK(price_micros > 0),

    proceeds_micros INTEGER NOT NULL
        CHECK(proceeds_micros >= 0),

    cost_basis_micros INTEGER NOT NULL
        CHECK(cost_basis_micros >= 0),

    realized_pnl_micros INTEGER NOT NULL,

    cash_before_micros INTEGER NOT NULL
        CHECK(cash_before_micros >= 0),

    cash_after_micros INTEGER NOT NULL
        CHECK(cash_after_micros >= 0),

    fee_micros INTEGER NOT NULL
        CHECK(fee_micros = 0),

    liquidation_time INTEGER NOT NULL,

    source_db_sha256 TEXT NOT NULL
        CHECK(length(source_db_sha256) = 64),

    status TEXT NOT NULL
        CHECK(status IN ('FILLED', 'NOT_REQUIRED')),

    reason TEXT NOT NULL,

    created_at INTEGER NOT NULL
        DEFAULT (unixepoch()),

    CHECK(
        cash_after_micros =
        cash_before_micros + proceeds_micros
    ),

    CHECK(
        realized_pnl_micros =
        proceeds_micros - cost_basis_micros
    ),

    CHECK(
        (status = 'FILLED' AND quantity_sats > 0)
        OR
        (
            status = 'NOT_REQUIRED'
            AND quantity_sats = 0
            AND proceeds_micros = 0
            AND cost_basis_micros = 0
        )
    )
) STRICT;
"""


def liquidar_copia(ruta):

    c = sqlite3.connect(ruta)

    c.row_factory = sqlite3.Row

    try:

        c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA journal_mode = DELETE")

        c.execute("PRAGMA synchronous = FULL")

        c.execute("BEGIN IMMEDIATE")

        c.execute(SCHEMA_LIQUIDACION)

        carteras = c.execute("""
            SELECT *
            FROM portfolio
            WHERE mode = 'REPLAY'
            ORDER BY id
        """).fetchall()

        assert len(carteras) == 3

        for p in carteras:

            estrategia = p["strategy"]

            assert estrategia in NOMBRES

            assert p["initial_cash_micros"] == CAPITAL

            assert p["status"] == "ACTIVE"

            pos = c.execute("""
                SELECT *
                FROM positions
                WHERE portfolio_id = ?
                  AND asset_id = ?
            """, (
                p["id"],
                ASSET_ID
            )).fetchone()

            ultima = c.execute("""
                SELECT e.*
                FROM equity_history e
                JOIN agent_cycles ac
                  ON ac.id = e.cycle_id
                WHERE ac.portfolio_id = ?
                  AND e.snapshot_type = 'VALUATION'
                ORDER BY e.recorded_at DESC
                LIMIT 1
            """, (p["id"],)).fetchone()

            assert ultima["recorded_at"] == cierre_final

            cantidad = pos["quantity_sats"]

            costo = pos["cost_basis_micros"]

            efectivo_antes = p["cash_micros"]

            importe = (
                cantidad * PRECIO_MICROS // SATS
            )

            efectivo_despues = (
                efectivo_antes + importe
            )

            pnl = importe - costo

            assert importe == (
                ultima["position_value_micros"]
            )

            assert efectivo_despues == (
                ultima["equity_micros"]
            )

            estado = (
                "FILLED"
                if cantidad > 0
                else "NOT_REQUIRED"
            )

            c.execute("""
                INSERT INTO replay_liquidations (
                    portfolio_id,
                    asset_id,
                    quantity_sats,
                    price_micros,
                    proceeds_micros,
                    cost_basis_micros,
                    realized_pnl_micros,
                    cash_before_micros,
                    cash_after_micros,
                    fee_micros,
                    liquidation_time,
                    source_db_sha256,
                    status,
                    reason
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0, ?, ?, ?, ?
                )
            """, (
                p["id"],
                ASSET_ID,
                cantidad,
                PRECIO_MICROS,
                importe,
                costo,
                pnl,
                efectivo_antes,
                efectivo_despues,
                cierre_final,
                replay_antes,
                estado,
                "END_OF_EXPERIMENT"
            ))

            c.execute("""
                UPDATE positions
                SET quantity_sats = 0,
                    cost_basis_micros = 0,
                    updated_at = unixepoch()
                WHERE id = ?
            """, (pos["id"],))

            c.execute("""
                UPDATE portfolio
                SET cash_micros = ?,
                    status = 'PAUSED',
                    updated_at = unixepoch()
                WHERE id = ?
            """, (
                efectivo_despues,
                p["id"]
            ))

        c.commit()

        assert c.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

        assert c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    except BaseException:

        c.rollback()
        raise

    finally:

        c.close()


# 5. Auditar la copia finalizada.

def auditar_final(ruta):

    with (
        read_connection(DB) as original,
        read_connection(ruta) as final
    ):

        # Las tablas originales de decisiones,
        # precios y ejecuciones deben ser identicas.

        tablas_protegidas = (
            "assets",
            "candles",
            "model_versions",
            "predictions",
            "risk_config",
            "agent_cycles",
            "agent_decisions",
            "orders",
            "equity_history",
            "system_logs",
            "error_logs"
        )

        for tabla in tablas_protegidas:

            consulta = (
                f"SELECT * FROM {tabla} ORDER BY rowid"
            )

            antes = [
                tuple(f)
                for f in original.execute(consulta)
            ]

            despues = [
                tuple(f)
                for f in final.execute(consulta)
            ]

            assert antes == despues, tabla

        filas = [
            dict(f)
            for f in final.execute("""
                SELECT
                    l.*,
                    p.strategy,
                    p.status AS portfolio_status,
                    p.cash_micros,
                    pos.quantity_sats AS remaining_sats,
                    pos.cost_basis_micros AS remaining_cost
                FROM replay_liquidations l
                JOIN portfolio p
                  ON p.id = l.portfolio_id
                JOIN positions pos
                  ON pos.portfolio_id = p.id
                  AND pos.asset_id = l.asset_id
                ORDER BY p.id
            """)
        ]

        assert len(filas) == 3

        assert {
            f["strategy"] for f in filas
        } == set(NOMBRES)

        for f in filas:

            p_original = original.execute("""
                SELECT *
                FROM portfolio
                WHERE id = ?
            """, (f["portfolio_id"],)).fetchone()

            pos_original = original.execute("""
                SELECT *
                FROM positions
                WHERE portfolio_id = ?
                  AND asset_id = ?
            """, (
                f["portfolio_id"],
                ASSET_ID
            )).fetchone()

            assert f["source_db_sha256"] == replay_antes

            assert f["portfolio_status"] == "PAUSED"

            assert f["remaining_sats"] == 0

            assert f["remaining_cost"] == 0

            assert f["price_micros"] == PRECIO_MICROS

            assert f["liquidation_time"] == cierre_final

            assert f["fee_micros"] == 0

            assert f["quantity_sats"] == (
                pos_original["quantity_sats"]
            )

            assert f["cost_basis_micros"] == (
                pos_original["cost_basis_micros"]
            )

            assert f["cash_before_micros"] == (
                p_original["cash_micros"]
            )

            assert f["proceeds_micros"] == (
                f["quantity_sats"]
                * PRECIO_MICROS // SATS
            )

            assert f["cash_after_micros"] == (
                f["cash_micros"]
            )

            assert f["cash_micros"] == round(
                metricas_originales[
                    f["strategy"]
                ]["Patrimonio_final_valorado_USDT"]
                * MICROS
            )

        assert sum(
            f["status"] == "FILLED"
            for f in filas
        ) == 2

        assert final.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

        assert final.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    return filas


if FINAL.exists():

    liquidaciones = auditar_final(FINAL)

    print("\nCopia final existente: VERIFICADA")

else:

    with tempfile.TemporaryDirectory(
        prefix="finalize_replay_",
        dir=REPLAY
    ) as temporal:

        copia = Path(temporal) / "final.db"

        with read_connection(DB) as original:

            destino = sqlite3.connect(copia)

            try:
                original.backup(destino)
            finally:
                destino.close()

        liquidar_copia(copia)

        liquidaciones = auditar_final(copia)

        os.link(copia, FINAL)

    print("\nBase final independiente: CREADA")


liquidaciones = auditar_final(FINAL)

print("Liquidaciones verificadas: 2")
print("Cartera sin liquidacion necesaria: 1")
print("90 decisiones originales conservadas: SI")


# 6. Exportar registro de liquidaciones.

registros_liquidacion = []

for f in liquidaciones:

    registros_liquidacion.append({
        "Estrategia": f["strategy"],
        "Estado": f["status"],
        "Fecha_liquidacion_UTC":
            datetime.fromtimestamp(
                f["liquidation_time"],
                timezone.utc
            ).isoformat(),
        "Cantidad_BTC": f["quantity_sats"] / SATS,
        "Precio_USDT": f["price_micros"] / MICROS,
        "Importe_USDT": f["proceeds_micros"] / MICROS,
        "Costo_adquisicion_USDT":
            f["cost_basis_micros"] / MICROS,
        "PnL_liquidacion_USDT":
            f["realized_pnl_micros"] / MICROS,
        "Efectivo_anterior_USDT":
            f["cash_before_micros"] / MICROS,
        "Efectivo_final_USDT":
            f["cash_after_micros"] / MICROS,
        "Comision_USDT": 0
    })

ruta_liquidaciones = (
    REPLAY / "liquidaciones_finales.csv"
)

pd.DataFrame(
    registros_liquidacion
).to_csv(
    ruta_liquidaciones,
    index=False
)

print("\nLIQUIDACIONES FINALES")

print(
    pd.DataFrame(
        registros_liquidacion
    ).to_string(index=False)
)


# 7. Calcular metricas definitivas.

comparacion = []

series = {}

for f in liquidaciones:

    estrategia = f["strategy"]

    m = metricas_originales[estrategia]

    df = diarios[estrategia].copy()

    equity = np.concatenate((
        [50000.0],
        df["Patrimonio_USDT"].to_numpy()
    ))

    retornos_diarios = (
        equity[1:] / equity[:-1] - 1
    )

    maximos = np.maximum.accumulate(equity)

    drawdown_cierres = (
        1 - equity / maximos
    ) * 100

    capital_final = f["cash_micros"] / MICROS

    ganancia = capital_final - 50000

    rendimiento = ganancia / 50000 * 100

    venta_final = int(
        f["status"] == "FILLED"
    )

    pnl_final = (
        f["realized_pnl_micros"] / MICROS
    )

    operaciones_cerradas = (
        m["Operaciones_cerradas"] + venta_final
    )

    ganadoras = (
        m["Operaciones_ganadoras"]
        + int(venta_final == 1 and pnl_final > 0)
    )

    pnl_realizado = (
        m["PnL_realizado_USDT"] + pnl_final
    )

    assert abs(
        pnl_realizado - ganancia
    ) <= 1e-6

    assert abs(
        rendimiento - m["Rendimiento_neto_pct"]
    ) <= 1e-8

    assert abs(
        equity[-1] - capital_final
    ) <= 1e-6

    assert max(drawdown_cierres) <= (
        m["Drawdown_maximo_pct"] + 1e-8
    )

    exposicion_cierre = (
        df["Posicion_USDT"]
        / df["Patrimonio_USDT"]
        * 100
    )

    comparacion.append({
        "Estrategia": estrategia,
        "Capital_inicial_USDT": 50000,
        "Capital_final_USDT": capital_final,
        "Ganancia_neta_USDT": ganancia,
        "Rendimiento_neto_pct": rendimiento,
        "Drawdown_maximo_pct":
            m["Drawdown_maximo_pct"],
        "Drawdown_maximo_cierres_pct":
            float(max(drawdown_cierres)),
        "Volatilidad_diaria_pct":
            float(np.std(
                retornos_diarios,
                ddof=1
            ) * 100),
        "Exposicion_media_cierres_pct":
            float(exposicion_cierre.mean()),
        "Exposicion_maxima_cierres_pct":
            float(exposicion_cierre.max()),
        "Compras": m["Compras"],
        "Ventas_estrategia": m["Ventas"],
        "Ventas_liquidacion": venta_final,
        "Ordenes_totales":
            m["Ordenes_ejecutadas"] + venta_final,
        "Operaciones_cerradas":
            operaciones_cerradas,
        "Operaciones_ganadoras": ganadoras,
        "Win_rate_pct": (
            ganadoras / operaciones_cerradas * 100
            if operaciones_cerradas
            else None
        ),
        "PnL_realizado_USDT": pnl_realizado,
        "Latencia_media_ms": m["Latencia_media_ms"],
        "Latencia_mediana_ms":
            m["Latencia_mediana_ms"],
        "Rechazos_riesgo": m["Rechazos_riesgo"],
        "Tasa_rechazo_pct":
            m["Rechazos_riesgo"] / 30 * 100,
        "Ciclos_validos": m["Ciclos_validos"],
        "Fallos_tecnicos":
            m["Ciclos_fallidos_no_completados"],
        "Posicion_final_BTC": 0.0,
        "Comisiones_USDT": 0,
        "Deslizamiento_USDT": 0
    })

    df["Rendimiento_acumulado_pct"] = (
        df["Patrimonio_USDT"] / 50000 - 1
    ) * 100

    df["Drawdown_cierres_pct"] = (
        drawdown_cierres[1:]
    )

    df["Rendimiento_diario_pct"] = (
        retornos_diarios * 100
    )

    df["Exposicion_pct"] = exposicion_cierre

    series[estrategia] = df


tabla = pd.DataFrame(comparacion)

assert tabla["Ciclos_validos"].sum() == 90

assert tabla["Fallos_tecnicos"].sum() == 0

assert tabla["Ordenes_totales"].sum() == 8

assert tabla["Operaciones_cerradas"].sum() == 4

assert tabla["Posicion_final_BTC"].eq(0).all()

ruta_comparacion = (
    REPLAY / "comparacion_final.csv"
)

tabla.to_csv(
    ruta_comparacion,
    index=False
)

guardar_json(
    REPLAY / "metricas_comparativas_finales.json",
    comparacion
)

serie_comparativa = pd.DataFrame()

for estrategia, df in series.items():

    fechas = df[
        "Fecha_objetivo_UTC"
    ].dt.strftime("%Y-%m-%d")

    if serie_comparativa.empty:

        serie_comparativa[
            "Fecha_objetivo_UTC"
        ] = fechas

    else:

        assert serie_comparativa[
            "Fecha_objetivo_UTC"
        ].equals(fechas)

    for campo in (
        "Patrimonio_USDT",
        "Rendimiento_acumulado_pct",
        "Rendimiento_diario_pct",
        "Drawdown_cierres_pct",
        "Exposicion_pct"
    ):

        serie_comparativa[
            f"{estrategia}_{campo}"
        ] = df[campo]

serie_comparativa.to_csv(
    REPLAY / "series_comparativas_diarias.csv",
    index=False
)


# 8. Referencia adicional de igual asignacion inicial.
# No sustituye al Buy & Hold original.
# 25% BTC + 75% efectivo, sin rebalanceo.

precio_inicial = price_to_micros(
    metricas_originales["BUY_HOLD"][
        "Precio_apertura_inicial_USDT"
    ]
)

asignacion = CAPITAL // 4

sats_25 = (
    asignacion * SATS // precio_inicial
)

costo_25 = (
    sats_25 * precio_inicial // SATS
)

efectivo_25 = CAPITAL - costo_25

capital_final_25 = (
    efectivo_25
    + sats_25 * PRECIO_MICROS // SATS
)

referencia_25 = {
    "Tipo": "REFERENCIA_ANALITICA_COMPLEMENTARIA",
    "Asignacion_inicial_BTC_pct": 25,
    "Asignacion_inicial_efectivo_pct": 75,
    "Rebalanceo": False,
    "Capital_inicial_USDT": 50000,
    "Capital_final_USDT":
        capital_final_25 / MICROS,
    "Rendimiento_neto_pct":
        (capital_final_25 / CAPITAL - 1) * 100,
    "Incluida_en_90_ciclos": False,
    "Sustituye_protocolo_original": False
}

guardar_json(
    REPLAY / "referencia_pasiva_25pct.json",
    referencia_25
)


# 9. Generar las seis figuras academicas.

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 15,
    "axes.labelsize": 11,
    "figure.dpi": 150,
    "axes.spines.top": False,
    "axes.spines.right": False
})


def finalizar_figura(fig, nombre):

    fig.tight_layout()

    ruta = FIGURAS / nombre

    fig.savefig(
        ruta,
        dpi=220,
        bbox_inches="tight",
        facecolor="white"
    )

    plt.close(fig)

    print("Figura generada:", nombre)


def grafica_series(campo, titulo, ylabel, archivo):

    fig, ax = plt.subplots(
        figsize=(11, 5.5)
    )

    for estrategia, df in series.items():

        ax.plot(
            df["Fecha_objetivo_UTC"],
            df[campo],
            label=NOMBRES[estrategia],
            color=COLORES[estrategia],
            linewidth=2.1
        )

    ax.set_title(titulo)

    ax.set_ylabel(ylabel)

    ax.set_xlabel("Fecha objetivo UTC")

    ax.grid(
        alpha=0.22,
        linestyle="--"
    )

    ax.legend()

    fig.autofmt_xdate()

    finalizar_figura(fig, archivo)


def grafica_barras(campo, titulo, ylabel, archivo):

    fig, ax = plt.subplots(
        figsize=(9, 5)
    )

    nombres = [
        NOMBRES[e] for e in tabla["Estrategia"]
    ]

    colores = [
        COLORES[e] for e in tabla["Estrategia"]
    ]

    barras = ax.bar(
        nombres,
        tabla[campo],
        color=colores,
        width=0.58
    )

    ax.bar_label(
        barras,
        fmt="%.2f",
        padding=5
    )

    ax.margins(y=0.18)

    ax.set_title(titulo)

    ax.set_ylabel(ylabel)

    ax.grid(
        axis="y",
        alpha=0.20
    )

    finalizar_figura(fig, archivo)


grafica_series(
    "Patrimonio_USDT",
    "FinanceAI - Evolucion del patrimonio",
    "Patrimonio virtual (USDT)",
    "01_patrimonio_comparativo.png"
)

grafica_series(
    "Rendimiento_acumulado_pct",
    "FinanceAI - Rendimiento acumulado",
    "Rendimiento (%)",
    "02_rendimiento_acumulado.png"
)

grafica_series(
    "Drawdown_cierres_pct",
    "FinanceAI - Drawdown a cierres diarios",
    "Caida desde maximo previo (%)",
    "03_drawdown_comparativo.png"
)

grafica_barras(
    "Rendimiento_neto_pct",
    "FinanceAI - Rendimiento final",
    "Rendimiento neto (%)",
    "04_rendimiento_final.png"
)

grafica_barras(
    "Rechazos_riesgo",
    "FinanceAI - Rechazos del motor de riesgo",
    "Numero de rechazos",
    "05_rechazos_riesgo.png"
)

fig, ax = plt.subplots(
    figsize=(9, 5)
)

latencias = tabla[
    "Latencia_media_ms"
].to_numpy()

assert (latencias > 0).all()

barras = ax.bar(
    [
        NOMBRES[e] for e in tabla["Estrategia"]
    ],
    latencias,
    color=[
        COLORES[e] for e in tabla["Estrategia"]
    ],
    width=0.58
)

ax.set_yscale("log")

ax.bar_label(
    barras,
    labels=[
        f"{v:.6g} ms" for v in latencias
    ],
    padding=5
)

ax.set_title(
    "FinanceAI - Latencia media de decision"
)

ax.set_ylabel(
    "Milisegundos (escala logaritmica)"
)

ax.grid(
    axis="y",
    alpha=0.20
)

ax.margins(y=0.15)

finalizar_figura(
    fig,
    "06_latencia_comparativa.png"
)


# 10. Calcular diferencias entre estrategias.

m = tabla.set_index("Estrategia")

diferencias = {
    "LLM_vs_MODEL_ONLY_USDT": float(
        m.loc["LLM", "Capital_final_USDT"]
        - m.loc["MODEL_ONLY", "Capital_final_USDT"]
    ),
    "LLM_vs_MODEL_ONLY_rendimiento_pp": float(
        m.loc["LLM", "Rendimiento_neto_pct"]
        - m.loc["MODEL_ONLY", "Rendimiento_neto_pct"]
    ),
    "Reduccion_rechazos_LLM_pct": float(
        (
            1 - m.loc["LLM", "Rechazos_riesgo"]
            / m.loc["MODEL_ONLY", "Rechazos_riesgo"]
        ) * 100
    ),
    "Multiplicador_latencia_LLM": float(
        m.loc["LLM", "Latencia_media_ms"]
        / m.loc["MODEL_ONLY", "Latencia_media_ms"]
    ),
    "Diferencia_drawdown_LLM_pp": float(
        m.loc["LLM", "Drawdown_maximo_pct"]
        - m.loc["MODEL_ONLY", "Drawdown_maximo_pct"]
    ),
    "Estrategia_mayor_rendimiento": str(
        m["Rendimiento_neto_pct"].idxmax()
    ),
    "Estrategia_menor_drawdown": str(
        m["Drawdown_maximo_pct"].idxmin()
    )
}


# 11. Verificar proteccion final.

assert hash_logico(DB) == replay_antes

assert database_hash() == db_antes

assert model_hashes() == modelo_antes

for ruta, huella in fuentes.items():

    assert sha256(ruta) == huella

verify_artifacts()

auditar_final(FINAL)

figuras_generadas = sorted(
    FIGURAS.glob("0[1-6]_*.png")
)

assert len(figuras_generadas) == 6

assert all(
    ruta.stat().st_size > 0
    for ruta in figuras_generadas
)


# 12. Registrar evidencia academica.

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "14.6",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",
    "SHA256_protocolo": huella_protocolo,
    "Base_replay_original": str(
        DB.relative_to(BASE)
    ),
    "Base_replay_final": str(
        FINAL.relative_to(BASE)
    ),
    "SHA256_logico_replay_original": replay_antes,
    "SHA256_logico_replay_final": hash_logico(FINAL),
    "Estrategias": 3,
    "Ciclos_validos": 90,
    "Inferencias_LLM_validas": 30,
    "Ordenes_diarias_originales": 6,
    "Ventas_liquidacion": 2,
    "Ordenes_y_liquidaciones_totales": 8,
    "Operaciones_cerradas_totales": 4,
    "Fallos_tecnicos": 0,
    "Metricas_definitivas": comparacion,
    "Diferencias": diferencias,
    "Liquidaciones": registros_liquidacion,
    "Referencia_complementaria_25pct": referencia_25,
    "Figuras": {
        str(ruta.relative_to(BASE)): sha256(ruta)
        for ruta in figuras_generadas
    },
    "Reconciliacion_financiera": True,
    "Base_replay_original_intacta": True,
    "Base_principal_intacta": True,
    "Modelo_LSTM_intacto": True,
    "Protocolo_original_intacto": True,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Dinero_real_utilizado": False,
    "Limitaciones": [
        "Simulacion retrospectiva en validacion VA.",
        "Un unico periodo de 30 dias.",
        "Las reglas fueron evaluadas con datos de validacion.",
        "Buy & Hold original tiene asignacion inicial del 100%.",
        "Las estrategias activas limitan nuevas compras al 25%.",
        "La exposicion existente puede aumentar por apreciacion.",
        "Comisiones y deslizamiento iguales a cero.",
        "Ejecucion idealizada a la apertura historica.",
        "Qwen3 puede conocer eventos posteriores al periodo.",
        "Win rate basado en pocas operaciones cerradas.",
        "Latencias incluyen alcances computacionales diferentes.",
        "No demuestra rentabilidad futura ni superioridad general."
    ],
    "Tiempo_segundos": round(
        time.perf_counter() - inicio_proceso,
        4
    )
}

ruta_evidencia = (
    RESULTS / "control_comparacion_final_replay.json"
)

guardar_json(
    ruta_evidencia,
    evidencia
)


# 13. Mostrar resultados.

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO COMPARATIVO DEFINITIVO")
print("=" * 60)

columnas_resumen = [
    "Estrategia",
    "Capital_final_USDT",
    "Ganancia_neta_USDT",
    "Rendimiento_neto_pct",
    "Drawdown_maximo_pct",
    "Ordenes_totales",
    "Operaciones_cerradas",
    "Win_rate_pct",
    "Rechazos_riesgo"
]

print(
    tabla[columnas_resumen].to_string(
        index=False
    )
)

print("\nDIFERENCIAS ENTRE ESTRATEGIAS")

print(json.dumps(
    diferencias,
    indent=4,
    ensure_ascii=False
))

print("\nREFERENCIA PASIVA ADICIONAL DEL 25%")

print(json.dumps(
    referencia_25,
    indent=4,
    ensure_ascii=False
))

print("\nEXPOSICION Y VOLATILIDAD")

print(
    tabla[[
        "Estrategia",
        "Exposicion_media_cierres_pct",
        "Exposicion_maxima_cierres_pct",
        "Volatilidad_diaria_pct"
    ]].to_string(index=False)
)

print("\nCiclos validos: 90 / 90")
print("Inferencias Qwen3 validas: 30 / 30")
print("Fallos tecnicos: 0")
print("Ordenes originales: 6")
print("Liquidaciones adicionales: 2")
print("Total ejecuciones financieras: 8")
print("Operaciones cerradas: 4")
print("Carteras finales liquidadas: 3 / 3")
print("Figuras generadas:", len(figuras_generadas))
print("Reconciliacion financiera: APROBADA")
print("Base replay original intacta: SI")
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("Protocolo intacto: SI")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")
print("Evidencia:", ruta_evidencia.name)

print("\nCOMPARACION FINANCIERA COMPLETADA")
print("PASO 14.6 COMPLETADO CORRECTAMENTE")

