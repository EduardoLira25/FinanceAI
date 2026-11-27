import sqlite3
import csv
import json
import math
import hashlib

from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
DATABASE = BASE / "database"
MODELO = BASE / "models/modelo_final_v1"
EXPERIMENTAL = BASE / "experimental"

ruta_db = DATABASE / "financeai.db"

ruta_datos = (
    BASE / "data/processed/BTCUSDT_MEXC_limpio.csv"
)

ruta_manifiesto = (
    MODELO / "manifiesto_modelo_final.json"
)

CAPITAL_INICIAL = 50_000
MICROS = 1_000_000
SATOSHIS = 100_000_000

print("=" * 60)
print("FINANCEAI - CARGA INICIAL SQLITE")
print("=" * 60)


def sha256(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# 1. Verificar archivos originales

assert ruta_db.is_file()
assert ruta_datos.is_file()
assert ruta_manifiesto.is_file()

huella_datos = sha256(ruta_datos)

assert huella_datos == sha256(
    EXPERIMENTAL /
    "data/processed/BTCUSDT_MEXC_limpio.csv"
)

assert sha256(ruta_manifiesto) == sha256(
    EXPERIMENTAL /
    "models/modelo_final_v1/manifiesto_modelo_final.json"
)

manifiesto = json.loads(
    ruta_manifiesto.read_text(encoding="utf-8")
)

for nombre, informacion in manifiesto["Archivos"].items():

    ruta = MODELO / nombre

    assert ruta.is_file()
    assert sha256(ruta) == informacion["SHA256"]
    assert ruta.stat().st_size == informacion["Bytes"]

assert manifiesto["Version"] == "1.0.0"
assert manifiesto["Activo"] == "BTCUSDT"
assert manifiesto["Ventana"] == 20
assert manifiesto["Forma_entrada"] == [None, 20, 3]

print("Integridad de datos: APROBADA")
print("Integridad del modelo: APROBADA")


# 2. Preparar datos financieros

def convertir_fecha(valor):

    fecha = datetime.fromisoformat(
        valor.replace("Z", "+00:00")
    )

    assert fecha.tzinfo is not None

    return int(fecha.timestamp())


velas = []

with ruta_datos.open(
    encoding="utf-8",
    newline=""
) as archivo:

    for fila in csv.DictReader(archivo):

        apertura = convertir_fecha(fila["Date"])

        cierre = convertir_fecha(fila["Close_Time"])

        valores = [
            float(fila["Open"]),
            float(fila["High"]),
            float(fila["Low"]),
            float(fila["Close"]),
            float(fila["Volume"]),
            float(fila["Quote_Volume"])
        ]

        assert all(math.isfinite(v) for v in valores)
        assert cierre - apertura == 86400
        assert apertura % 86400 == 0

        velas.append((
            86400,
            apertura,
            cierre,
            *valores,
            "MEXC"
        ))

assert len(velas) == 2520

assert all(
    velas[i][1] - velas[i-1][1] == 86400
    for i in range(1, len(velas))
)

assert velas[-1][2] <= int(
    datetime.now(timezone.utc).timestamp()
)

print("Observaciones preparadas:", len(velas))
print("Continuidad temporal: APROBADA")


# 3. Conectar con SQLite

conexion = sqlite3.connect(ruta_db)

conexion.execute("PRAGMA foreign_keys = ON")
conexion.execute("PRAGMA busy_timeout = 5000")
conexion.execute("PRAGMA synchronous = FULL")

try:

    conexion.execute("BEGIN IMMEDIATE")

    # Impedir que la carga reinicie una cartera utilizada

    for tabla in [
        "agent_cycles",
        "agent_decisions",
        "orders",
        "equity_history",
        "predictions"
    ]:

        cantidad = conexion.execute(
            f"SELECT COUNT(*) FROM {tabla}"
        ).fetchone()[0]

        assert cantidad == 0, (
            "La aplicacion ya contiene actividad. "
            "No se permite reinicializarla."
        )


    # 4. Registrar activo financiero

    conexion.execute("""
        INSERT INTO assets (
            symbol, base_currency,
            quote_currency, exchange
        )
        VALUES ('BTCUSDT', 'BTC', 'USDT', 'MEXC')
        ON CONFLICT(symbol) DO NOTHING
    """)

    activo = conexion.execute("""
        SELECT id, base_currency,
               quote_currency, exchange, active
        FROM assets
        WHERE symbol = 'BTCUSDT'
    """).fetchone()

    assert activo[1:] == ("BTC", "USDT", "MEXC", 1)

    asset_id = activo[0]

    print("\nActivo BTCUSDT: REGISTRADO")


    # 5. Importar 2520 velas historicas

    registros_velas = [
        (asset_id, *vela)
        for vela in velas
    ]

    conexion.executemany("""
        INSERT INTO candles (
            asset_id, interval_seconds,
            open_time, close_time,
            open, high, low, close,
            volume, quote_volume, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(
            asset_id, interval_seconds, open_time
        ) DO NOTHING
    """, registros_velas)

    velas_db = conexion.execute("""
        SELECT
            asset_id, interval_seconds,
            open_time, close_time,
            open, high, low, close,
            volume, quote_volume, source
        FROM candles
        WHERE asset_id = ?
        ORDER BY open_time
    """, (asset_id,)).fetchall()

    assert velas_db == registros_velas

    print("Velas historicas importadas:", len(velas_db))
    print("Datos almacenados identicos al CSV: SI")


    # 6. Registrar modelo definitivo

    datos_modelo = (
        manifiesto["Version"],
        manifiesto["Arquitectura"],
        manifiesto["Ventana"],
        len(manifiesto["Variables_ordenadas"]),
        "models/modelo_final_v1/modelo_final.keras",
        sha256(MODELO / "modelo_final.keras")
    )

    conexion.execute("""
        INSERT INTO model_versions (
            version, architecture,
            window_size, feature_count,
            model_path, model_sha256
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO NOTHING
    """, datos_modelo)

    modelo_db = conexion.execute("""
        SELECT version, architecture,
               window_size, feature_count,
               model_path, model_sha256
        FROM model_versions
        WHERE version = ?
    """, (manifiesto["Version"],)).fetchone()

    assert modelo_db == datos_modelo

    print("Modelo LSTM v1.0.0: REGISTRADO")


    # 7. Crear cartera virtual

    capital_micros = CAPITAL_INICIAL * MICROS

    conexion.execute("""
        INSERT INTO portfolio (
            name, mode, strategy, currency,
            initial_cash_micros, cash_micros, status
        )
        VALUES (
            'FinanceAI_Paper',
            'PAPER_LIVE',
            'LLM',
            'USDT',
            ?, ?,
            'PAUSED'
        )
        ON CONFLICT(name) DO NOTHING
    """, (
        capital_micros,
        capital_micros
    ))

    cartera = conexion.execute("""
        SELECT id, initial_cash_micros,
               cash_micros, status,
               mode, strategy, currency
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
    """).fetchone()

    portfolio_id = cartera[0]

    assert cartera[1:] == (
        capital_micros,
        capital_micros,
        "PAUSED",
        "PAPER_LIVE",
        "LLM",
        "USDT"
    )

    print("Cartera virtual: CREADA O VERIFICADA")


    # 8. Inicializar posicion de Bitcoin

    conexion.execute("""
        INSERT INTO positions (
            portfolio_id, asset_id,
            quantity_sats, cost_basis_micros
        )
        VALUES (?, ?, 0, 0)
        ON CONFLICT(portfolio_id, asset_id)
        DO NOTHING
    """, (
        portfolio_id,
        asset_id
    ))

    posicion = conexion.execute("""
        SELECT quantity_sats, cost_basis_micros
        FROM positions
        WHERE portfolio_id = ?
          AND asset_id = ?
    """, (
        portfolio_id,
        asset_id
    )).fetchone()

    assert posicion == (0, 0)

    print("Posicion inicial BTC: 0")


    # 9. Registrar configuracion de riesgo

    datos_riesgo = (
        portfolio_id,
        1,                   # Version
        2500,                # Exposicion maxima: 25%
        200,                 # Perdida diaria: 2%
        3600,                # Antiguedad: 60 minutos
        10 * MICROS,         # Orden minima: 10 USDT
        0,                   # Comision: 0%
        0,                   # Deslizamiento: 0%
        manifiesto["Umbral"],
        0                    # Paro de emergencia
    )

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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(portfolio_id, version)
        DO NOTHING
    """, datos_riesgo)

    riesgo_db = conexion.execute("""
        SELECT
            portfolio_id, version,
            max_exposure_bps,
            max_daily_loss_bps,
            max_data_age_seconds,
            min_order_micros,
            fee_bps,
            slippage_bps,
            prediction_threshold,
            emergency_stop
        FROM risk_config
        WHERE portfolio_id = ?
          AND version = 1
    """, (portfolio_id,)).fetchone()

    assert riesgo_db == datos_riesgo

    print("Configuracion de riesgo: REGISTRADA")


    # 10. Registrar evento de inicializacion

    mensaje = "Carga inicial FinanceAI verificada"

    existe = conexion.execute("""
        SELECT COUNT(*)
        FROM system_logs
        WHERE component = 'DATABASE'
          AND message = ?
    """, (mensaje,)).fetchone()[0]

    if existe == 0:

        conexion.execute("""
            INSERT INTO system_logs (
                level, component, message
            )
            VALUES ('INFO', 'DATABASE', ?)
        """, (mensaje,))


    # 11. Validar integridad antes de confirmar

    assert conexion.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"

    assert conexion.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []

    tablas = conexion.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    conteos = {
        nombre: conexion.execute(
            f'SELECT COUNT(*) FROM "{nombre}"'
        ).fetchone()[0]
        for (nombre,) in tablas
    }

    assert conteos == {
        "agent_cycles": 0,
        "agent_decisions": 0,
        "assets": 1,
        "candles": 2520,
        "equity_history": 0,
        "error_logs": 0,
        "model_versions": 1,
        "orders": 0,
        "portfolio": 1,
        "positions": 1,
        "predictions": 0,
        "risk_config": 1,
        "system_logs": 1
    }

    assert sha256(ruta_datos) == huella_datos

    for nombre, informacion in manifiesto["Archivos"].items():

        assert sha256(
            MODELO / nombre
        ) == informacion["SHA256"]

    conexion.commit()

    print("\nTransaccion SQLite: CONFIRMADA")

except Exception:

    conexion.rollback()

    print("ERROR: cambios de la transaccion revertidos.")

    raise

finally:

    conexion.close()


# 12. Guardar evidencia de la carga inicial

control = {
    "Proyecto": "FinanceAI",
    "Fecha_UTC": datetime.now(timezone.utc).isoformat(),
    "Resultado": "APROBADO",
    "Registros_por_tabla": conteos,
    "Observaciones_historicas": len(velas),
    "Capital_inicial_USDT": CAPITAL_INICIAL,
    "Efectivo_USDT": CAPITAL_INICIAL,
    "Cantidad_BTC": 0,
    "Modelo_version": manifiesto["Version"],
    "SHA256_datos": huella_datos,
    "SHA256_modelo": datos_modelo[-1],
    "Exposicion_maxima_pct": 25,
    "Limite_perdida_diaria_pct": 2,
    "Configuracion_riesgo_provisional": True,
    "Estado_agente": "PAUSED",
    "Integridad_SQLite": True,
    "Modelo_modificado": False,
    "TE_reevaluado": False
}

(DATABASE / "control_carga_inicial.json").write_text(
    json.dumps(
        control,
        indent=4,
        ensure_ascii=False
    ),
    encoding="utf-8"
)


# 13. Mostrar resultados finales

print("\n" + "=" * 60)
print("REGISTROS DE FINANCEAI")
print("=" * 60)

for nombre, cantidad in conteos.items():

    print(f"{nombre:<22} {cantidad:>6}")

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO DE CARGA INICIAL")
print("=" * 60)

print("Tablas:", len(conteos))
print("Registros totales:", sum(conteos.values()))
print("Observaciones historicas:", len(velas))
print("Modelo registrado: LSTM v1.0.0")
print("Capital inicial:", CAPITAL_INICIAL, "USDT")
print("Efectivo disponible:", CAPITAL_INICIAL, "USDT")
print("Cantidad BTC: 0")
print("Operaciones realizadas: 0")
print("Exposicion maxima: 25%")
print("Limite de perdida diaria: 2%")
print("Comision: 0%")
print("Estado del agente: PAUSADO")
print("Integridad SQLite: APROBADA")
print("Modelo modificado: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")

print("\nCARGA INICIAL COMPLETADA CORRECTAMENTE")
print("PASO 10.9 COMPLETADO CORRECTAMENTE")
