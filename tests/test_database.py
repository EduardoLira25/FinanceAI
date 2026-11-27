import sqlite3
import tempfile
import hashlib
import json

from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "database/financeai.db"

resultados = []

print("=" * 60)
print("FINANCEAI - AUDITORIA FINAL SQLITE")
print("=" * 60)


def verificar(nombre, condicion):

    resultado = "APROBADO" if condicion else "REVISAR"

    resultados.append({
        "Prueba": nombre,
        "Resultado": resultado
    })

    print(f"{nombre}: {resultado}")


def huella_logica(conexion):

    contenido = "\n".join(conexion.iterdump())

    return hashlib.sha256(
        contenido.encode("utf-8")
    ).hexdigest()


def conectar(ruta):

    conexion = sqlite3.connect(ruta)
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 5000")

    return conexion


def debe_rechazar(conexion, nombre, sql, parametros=()):

    conexion.execute("SAVEPOINT prueba")

    rechazado = False

    try:

        conexion.execute(sql, parametros)

    except sqlite3.IntegrityError:

        rechazado = True

    finally:

        conexion.execute("ROLLBACK TO prueba")
        conexion.execute("RELEASE prueba")

    verificar(nombre, rechazado)


# 1. Proteger base de datos original

assert DB.is_file()

original = sqlite3.connect(
    DB.as_uri() + "?mode=ro",
    uri=True
)

huella_original = huella_logica(original)

modelo = BASE / "models/modelo_final_v1"

huellas_modelo = {
    ruta.name: hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()
    for ruta in modelo.iterdir()
    if ruta.is_file()
}

assert len(huellas_modelo) == 10

print("Base original abierta en modo lectura")
print("Archivos del modelo protegidos: 10")


# 2. Crear copia temporal mediante SQLite Backup

with tempfile.TemporaryDirectory(
    prefix="FinanceAI_DB_Test_"
) as temporal:

    ruta_prueba = Path(temporal) / "pruebas.db"

    conexion = conectar(ruta_prueba)

    original.backup(conexion)
    original.close()

    assert huella_logica(conexion) == huella_original

    print("Copia independiente: CREADA")

    # 3. Recuperar registros iniciales

    asset_id = conexion.execute("""
        SELECT id FROM assets
        WHERE symbol = 'BTCUSDT'
    """).fetchone()[0]

    portfolio_id = conexion.execute("""
        SELECT id FROM portfolio
        WHERE name = 'FinanceAI_Paper'
    """).fetchone()[0]

    risk_id = conexion.execute("""
        SELECT id FROM risk_config
        WHERE portfolio_id = ?
          AND version = 1
    """, (portfolio_id,)).fetchone()[0]

    candle_id, cierre, precio = conexion.execute("""
        SELECT id, close_time, close
        FROM candles
        WHERE asset_id = ?
        ORDER BY open_time DESC
        LIMIT 1
    """, (asset_id,)).fetchone()

    print("\nCONTROLES INICIALES\n")

    verificar(
        "Integridad estructural",
        conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
    )

    verificar(
        "Llaves foraneas activadas",
        conexion.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0] == 1
    )

    verificar(
        "Sin relaciones invalidas",
        conexion.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    )

    verificar(
        "2520 velas historicas",
        conexion.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0] == 2520
    )

    verificar(
        "Capital inicial de 50000 USDT",
        conexion.execute("""
            SELECT cash_micros FROM portfolio
            WHERE id = ?
        """, (portfolio_id,)).fetchone()[0]
        == 50_000 * 1_000_000
    )

    verificar(
        "Agente inicialmente pausado",
        conexion.execute("""
            SELECT status FROM portfolio
            WHERE id = ?
        """, (portfolio_id,)).fetchone()[0]
        == "PAUSED"
    )


    # 4. Pruebas de restricciones

    print("\nPRUEBAS DE RECHAZO\n")

    debe_rechazar(
        conexion,
        "Activo duplicado",
        """
        INSERT INTO assets (
            symbol, base_currency,
            quote_currency, exchange
        )
        VALUES ('BTCUSDT', 'BTC', 'USDT', 'MEXC')
        """
    )

    debe_rechazar(
        conexion,
        "Vela duplicada",
        """
        INSERT INTO candles (
            asset_id, interval_seconds,
            open_time, close_time,
            open, high, low, close,
            volume, quote_volume, source
        )
        SELECT
            asset_id, interval_seconds,
            open_time, close_time,
            open, high, low, close,
            volume, quote_volume, source
        FROM candles WHERE id = ?
        """,
        (candle_id,)
    )

    debe_rechazar(
        conexion,
        "Precio negativo",
        "UPDATE candles SET close = -1 WHERE id = ?",
        (candle_id,)
    )

    debe_rechazar(
        conexion,
        "Precio maximo inconsistente",
        """
        UPDATE candles SET high = low / 2
        WHERE id = ?
        """,
        (candle_id,)
    )

    debe_rechazar(
        conexion,
        "Fecha de cierre incorrecta",
        """
        UPDATE candles SET close_time = open_time
        WHERE id = ?
        """,
        (candle_id,)
    )

    debe_rechazar(
        conexion,
        "Llave foranea inexistente",
        """
        UPDATE candles SET asset_id = -999
        WHERE id = ?
        """,
        (candle_id,)
    )

    debe_rechazar(
        conexion,
        "Saldo monetario negativo",
        """
        UPDATE portfolio SET cash_micros = -1
        WHERE id = ?
        """,
        (portfolio_id,)
    )

    debe_rechazar(
        conexion,
        "Posicion BTC negativa",
        """
        UPDATE positions SET quantity_sats = -1
        WHERE portfolio_id = ?
        """,
        (portfolio_id,)
    )

    debe_rechazar(
        conexion,
        "Exposicion superior al 100 por ciento",
        """
        UPDATE risk_config SET max_exposure_bps = 10001
        WHERE id = ?
        """,
        (risk_id,)
    )

    debe_rechazar(
        conexion,
        "Comision negativa",
        """
        UPDATE risk_config SET fee_bps = -1
        WHERE id = ?
        """,
        (risk_id,)
    )


    # 5. Crear prediccion ficticia
    # Exclusivamente para probar SQLite

    print("\nPRUEBAS DE PREDICCIONES Y AGENTE\n")

    sql_prediccion = """
        INSERT INTO predictions (
            candle_id,
            model_version,
            predicted_return,
            predicted_price,
            emission_time,
            target_open_time,
            target_close_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    parametros = (
        candle_id,
        "1.0.0",
        0.002,
        precio * 1.002,
        cierre,
        cierre,
        cierre + 86400
    )

    prediction_id = conexion.execute(
        sql_prediccion,
        parametros
    ).lastrowid

    debe_rechazar(
        conexion,
        "Prediccion duplicada",
        sql_prediccion,
        parametros
    )

    sql_ciclo = """
        INSERT INTO agent_cycles (
            portfolio_id,
            candle_id,
            prediction_id,
            risk_config_id
        )
        VALUES (?, ?, ?, ?)
    """

    parametros_ciclo = (
        portfolio_id,
        candle_id,
        prediction_id,
        risk_id
    )

    cycle_id = conexion.execute(
        sql_ciclo,
        parametros_ciclo
    ).lastrowid

    debe_rechazar(
        conexion,
        "Ciclo duplicado",
        sql_ciclo,
        parametros_ciclo
    )

    sql_decision = """
        INSERT INTO agent_decisions (
            cycle_id,
            proposed_action,
            authorized_action,
            rationale,
            risk_approved
        )
        VALUES (?, ?, ?, ?, ?)
    """

    debe_rechazar(
        conexion,
        "Accion invalida del agente",
        sql_decision,
        (cycle_id, "SHORT", "SHORT", "Prueba", 1)
    )

    debe_rechazar(
        conexion,
        "Compra sin autorizacion de riesgo",
        sql_decision,
        (cycle_id, "BUY", "BUY", "Prueba", 0)
    )

    decision_id = conexion.execute(
        sql_decision,
        (cycle_id, "BUY", "BUY", "Prueba ficticia", 1)
    ).lastrowid


    # 6. Probar restricciones de ordenes

    sql_orden = """
        INSERT INTO orders (
            decision_id,
            side,
            quantity_sats
        )
        VALUES (?, ?, ?)
    """

    debe_rechazar(
        conexion,
        "Cantidad de orden negativa",
        sql_orden,
        (decision_id, "BUY", -100)
    )

    order_id = conexion.execute(
        sql_orden,
        (decision_id, "BUY", 100000)
    ).lastrowid

    debe_rechazar(
        conexion,
        "Orden duplicada",
        sql_orden,
        (decision_id, "BUY", 100000)
    )

    debe_rechazar(
        conexion,
        "Orden completada sin datos de ejecucion",
        """
        UPDATE orders SET status = 'FILLED'
        WHERE id = ?
        """,
        (order_id,)
    )

    debe_rechazar(
        conexion,
        "Patrimonio inconsistente",
        """
        INSERT INTO equity_history (
            cycle_id,
            snapshot_type,
            cash_micros,
            position_value_micros,
            equity_micros,
            drawdown,
            recorded_at
        )
        VALUES (?, 'VALUATION', 100, 50, 200, 0, ?)
        """,
        (cycle_id, cierre)
    )


    # 7. Probar reversion de transacciones

    print("\nPRUEBAS DE TRANSACCIONES Y PERSISTENCIA\n")

    conexion.commit()

    saldo_antes = conexion.execute("""
        SELECT cash_micros
        FROM portfolio
        WHERE id = ?
    """, (portfolio_id,)).fetchone()[0]

    conexion.execute("BEGIN IMMEDIATE")

    conexion.execute("""
        UPDATE portfolio
        SET cash_micros = cash_micros - 1000000
        WHERE id = ?
    """, (portfolio_id,))

    conexion.rollback()

    saldo_despues = conexion.execute("""
        SELECT cash_micros
        FROM portfolio
        WHERE id = ?
    """, (portfolio_id,)).fetchone()[0]

    verificar(
        "Reversion correcta de transaccion",
        saldo_antes == saldo_despues
    )

    huella_antes_cierre = huella_logica(conexion)

    conexion.close()

    # Simular reinicio de la aplicacion

    conexion = conectar(ruta_prueba)

    verificar(
        "Persistencia despues de reiniciar",
        huella_logica(conexion) == huella_antes_cierre
    )

    verificar(
        "Orden pendiente conservada",
        conexion.execute("""
            SELECT status FROM orders WHERE id = ?
        """, (order_id,)).fetchone()[0] == "PENDING"
    )

    verificar(
        "Integridad despues de reiniciar",
        conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
    )

    verificar(
        "Relaciones validas despues de reiniciar",
        conexion.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    )

    conexion.close()


# 8. Verificar que la base original permanezca intacta

original = sqlite3.connect(
    DB.as_uri() + "?mode=ro",
    uri=True
)

verificar(
    "Base de datos original intacta",
    huella_logica(original) == huella_original
)

verificar(
    "Sin ordenes ficticias en base original",
    original.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0] == 0
)

verificar(
    "Sin predicciones ficticias en base original",
    original.execute(
        "SELECT COUNT(*) FROM predictions"
    ).fetchone()[0] == 0
)

original.close()

verificar(
    "Modelo predictivo intacto",
    all(
        hashlib.sha256(
            (modelo / nombre).read_bytes()
        ).hexdigest() == huella
        for nombre, huella in huellas_modelo.items()
    )
)


# 9. Guardar evidencia de pruebas

aprobadas = sum(
    r["Resultado"] == "APROBADO"
    for r in resultados
)

total = len(resultados)

control = {
    "Proyecto": "FinanceAI",
    "Fecha_UTC": datetime.now(timezone.utc).isoformat(),
    "Etapa": "10.10",
    "Pruebas_totales": total,
    "Pruebas_aprobadas": aprobadas,
    "Pruebas": resultados,
    "Resultado": (
        "APROBADO" if aprobadas == total
        else "REVISAR"
    ),
    "Pruebas_en_copia_temporal": True,
    "Reglas_backend_pendientes": True
}

(BASE / "results/auditoria_database.json").write_text(
    json.dumps(
        control,
        indent=4,
        ensure_ascii=False
    ),
    encoding="utf-8"
)


# 10. Resultado definitivo

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO FINAL SQLITE")
print("=" * 60)

print("Pruebas totales:", total)
print("Pruebas aprobadas:", aprobadas)
print("Pruebas pendientes:", total - aprobadas)
print("Resultado:", control["Resultado"])
print("Entorno temporal eliminado: SI")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")

assert aprobadas == total, (
    "Existen pruebas pendientes de revision"
)

print("\nAUDITORIA SQLITE APROBADA")
print("PASO 10.10 COMPLETADO CORRECTAMENTE")
print("ETAPA 10 COMPLETADA CORRECTAMENTE")
