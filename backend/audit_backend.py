import asyncio
import hashlib
import json
import math
import stat
import subprocess
import sys
import time

from pathlib import Path
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx

from backend.app.main import app

from backend.app.core.config import (
    BASE_DIR,
    MODEL_PATH,
    ENV_FILE,
    load_api_key
)

from backend.app.core.database import (
    read_connection,
    database_status
)

from backend.app.services.prediction import (
    verify_artifacts,
    build_features,
    infer_return
)

BASE = BASE_DIR
RESULTS = BASE / "results"

inicio = time.perf_counter()

controles = {}

print("=" * 60)
print("FINANCEAI - AUDITORIA FINAL DEL BACKEND")
print("=" * 60)


def verificar(nombre, condicion):

    controles[nombre] = bool(condicion)

    print(
        nombre + ":",
        "APROBADO" if condicion else "REVISAR"
    )

    assert condicion, nombre


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


def huella_database():

    with read_connection() as conexion:

        return hashlib.sha256(
            "\n".join(
                conexion.iterdump()
            ).encode()
        ).hexdigest()


# 1. Proteger archivos originales

huella_db = huella_database()

archivos_protegidos = [
    archivo
    for archivo in MODEL_PATH.iterdir()
    if archivo.is_file()
]

assert len(archivos_protegidos) == 10

archivos_protegidos.extend([
    BASE / "data/processed/BTCUSDT_MEXC_limpio.csv",
    BASE / "experimental/results/control_evaluacion_TE.json",
    BASE / "experimental/results/predicciones_TE.csv",
    BASE / "experimental/results/metricas_modelos_TE.csv"
])

huellas = {
    archivo: sha256(archivo)
    for archivo in archivos_protegidos
}

print("\nArchivos protegidos:", len(huellas))


# 2. Ejecutar las 140 pruebas del backend

print("\nPRUEBAS AUTOMATIZADAS\n", flush=True)

archivos_pruebas = [
    "tests/test_security.py",
    "tests/test_db_connection.py",
    "tests/test_api.py",
    "tests/test_market_api.py",
    "tests/test_mexc.py",
    "tests/test_prediction.py",
    "tests/test_risk.py",
    "tests/test_paper_trading.py"
]

ruta_xml = RESULTS / "auditoria_backend_pytest.xml"

proceso = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        *archivos_pruebas,
        "-q",
        f"--junitxml={ruta_xml}"
    ],
    cwd=BASE
)

assert proceso.returncode == 0

xml = ElementTree.parse(ruta_xml)

casos = xml.findall(".//testcase")

aprobadas = sum(
    all(
        caso.find(etiqueta) is None
        for etiqueta in (
            "failure",
            "error",
            "skipped"
        )
    )
    for caso in casos
)

verificar(
    "140 pruebas automatizadas",
    len(casos) == 140 and aprobadas == 140
)


# 3. Auditar SQLite

print("\nAUDITORIA DE SQLITE\n")

estado_db = database_status()

verificar(
    "Version del esquema",
    estado_db["schema_version"] == 1
)

verificar(
    "13 tablas disponibles",
    estado_db["tables"] == 13
)

verificar(
    "Modo WAL",
    estado_db["journal_mode"] == "wal"
)

with read_connection() as conexion:

    verificar(
        "Integridad estructural",
        conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
    )

    verificar(
        "Integridad referencial",
        conexion.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    )

    velas = conexion.execute("""
        SELECT c.*
        FROM candles c
        JOIN assets a
            ON a.id = c.asset_id
        WHERE a.symbol = 'BTCUSDT'
          AND c.interval_seconds = 86400
        ORDER BY c.open_time
    """).fetchall()

    verificar(
        "Historial financiero disponible",
        len(velas) >= 2521
    )

    verificar(
        "Continuidad diaria",
        all(
            velas[i]["open_time"]
            == velas[i-1]["close_time"]
            for i in range(1, len(velas))
        )
    )

    verificar(
        "Velas cerradas exclusivamente",
        all(
            v["close_time"] <= int(time.time())
            for v in velas
        )
    )

    cartera = conexion.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
    """).fetchone()

    posicion = conexion.execute("""
        SELECT quantity_sats, cost_basis_micros
        FROM positions
        WHERE portfolio_id = ?
    """, (cartera["id"],)).fetchone()

    ordenes = conexion.execute("""
        SELECT COUNT(*) FROM orders
    """).fetchone()[0]

    verificar(
        "Capital virtual conservado",
        cartera["cash_micros"] == 50000 * 1000000
    )

    verificar(
        "Posicion inicial conservada",
        tuple(posicion) == (0, 0)
    )

    verificar(
        "Cartera principal pausada",
        cartera["status"] == "PAUSED"
    )

    verificar(
        "Sin operaciones en base principal",
        ordenes == 0
    )

    verificar(
        "Modo exclusivamente simulado",
        cartera["mode"] == "PAPER_LIVE"
    )

    prediccion = conexion.execute("""
        SELECT p.*, c.close AS reference_close,
               c.asset_id, c.open_time,
               c.close_time
        FROM predictions p
        JOIN candles c
            ON c.id = p.candle_id
        WHERE p.model_version = '1.0.0'
        ORDER BY c.open_time DESC
        LIMIT 1
    """).fetchone()

    assert prediccion is not None

    historial = conexion.execute("""
        SELECT close
        FROM candles
        WHERE asset_id = ?
          AND interval_seconds = 86400
          AND open_time <= ?
        ORDER BY open_time DESC
        LIMIT 40
    """, (
        prediccion["asset_id"],
        prediccion["open_time"]
    )).fetchall()


# 4. Auditar modelo predictivo

print("\nAUDITORIA DEL MODELO LSTM\n")

manifiesto = verify_artifacts()

verificar(
    "Modelo original identificado",
    manifiesto["Modelo_ID"] == "TEC_B_LSTM_S42"
)

verificar(
    "Version original del modelo",
    manifiesto["Version"] == "1.0.0"
)

verificar(
    "Parametros originales",
    manifiesto["Parametros"] == 1425
)

verificar(
    "Ventana de datos disponible",
    len(historial) == 40
)

features = build_features([
    fila["close"]
    for fila in reversed(historial)
])

verificar(
    "Forma de entrada 20 por 3",
    features.shape == (20, 3)
)

# Reproducir exclusivamente la nueva prediccion
# almacenada, sin volver a evaluar TE.

retorno = infer_return(features)

diferencia = abs(
    retorno - prediccion["predicted_return"]
)

verificar(
    "Inferencia local reproducida",
    diferencia <= 1e-6
)

verificar(
    "Precio pronosticado consistente",
    math.isclose(
        prediccion["predicted_price"],
        prediccion["reference_close"]
        * (1 + prediccion["predicted_return"]),
        abs_tol=1e-6,
        rel_tol=0
    )
)

verificar(
    "Horizonte diario correcto",
    prediccion["target_open_time"]
        == prediccion["close_time"]
    and prediccion["target_close_time"]
        == prediccion["close_time"] + 86400
)

verificar(
    "Generacion dentro del periodo objetivo",
    prediccion["target_open_time"]
        <= prediccion["created_at"]
        < prediccion["target_close_time"]
)

print("Rendimiento reproducido:", retorno * 100, "%")
print("Diferencia numerica:", diferencia)


# 5. Auditar rutas y seguridad

print("\nAUDITORIA DE SEGURIDAD\n")

clave = load_api_key()

verificar(
    "Permisos del archivo privado",
    stat.S_IMODE(ENV_FILE.stat().st_mode) == 0o600
)

verificar(
    "Plantilla publica sin secretos",
    clave not in (
        BASE / ".env.example"
    ).read_text()
)

verificar(
    "Clave excluida mediante gitignore",
    ".env" in (
        BASE / ".gitignore"
    ).read_text().splitlines()
)

rutas_esperadas = {
    "/": "get",
    "/health": "get",
    "/api/v1/status": "get",
    "/api/v1/database/status": "get",
    "/api/v1/model/status": "get",
    "/api/v1/portfolio": "get",
    "/api/v1/market/assets": "get",
    "/api/v1/market/candles": "get",
    "/api/v1/market/latest": "get",
    "/api/v1/risk/config": "get",
    "/api/v1/predictions/latest": "get",
    "/api/v1/predictions/generate": "post"
}

esquema = app.openapi()["paths"]

verificar(
    "12 rutas previstas",
    set(esquema) == set(rutas_esperadas)
    and all(
        set(esquema[ruta]) == {metodo}
        for ruta, metodo in rutas_esperadas.items()
    )
)

rutas_privadas = {
    ruta: metodo
    for ruta, metodo in rutas_esperadas.items()
    if ruta.startswith("/api/v1/")
}

verificar(
    "10 rutas privadas protegidas",
    len(rutas_privadas) == 10
    and all(
        esquema[ruta][metodo].get("security")
        for ruta, metodo in rutas_privadas.items()
    )
)


async def auditar_http():

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver"
    ) as cliente:

        for ruta, metodo in rutas_privadas.items():

            respuesta = await cliente.request(
                metodo.upper(),
                ruta
            )

            verificar(
                "Sin clave " + ruta,
                respuesta.status_code == 401
            )

        respuesta = await cliente.get(
            "/api/v1/predictions/latest",
            headers={"X-API-Key": clave}
        )

        verificar(
            "Consulta privada de prediccion",
            respuesta.status_code == 200
            and respuesta.json()["id"]
                == prediccion["id"]
            and clave not in respuesta.text
        )


asyncio.run(auditar_http())


# 6. Confirmar integridad de archivos

print("\nPROTECCION DE ORIGINALES\n")

verificar(
    "Base de datos original intacta",
    huella_database() == huella_db
)

verificar(
    "Modelo y resultados experimentales intactos",
    all(
        sha256(archivo) == huella
        for archivo, huella in huellas.items()
    )
)


# 7. Guardar versiones completas del entorno

dependencias = subprocess.check_output(
    [sys.executable, "-m", "pip", "freeze"],
    text=True
)

ruta_lock = BASE / "backend/requirements-lock-macos.txt"

ruta_lock.write_text(
    dependencias,
    encoding="utf-8"
)

print("Dependencias del entorno: REGISTRADAS")


# 8. Guardar evidencia definitiva

duracion = round(
    time.perf_counter() - inicio,
    4
)

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "11.10",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",
    "Pruebas_automatizadas": len(casos),
    "Pruebas_aprobadas": aprobadas,
    "Controles_adicionales": controles,
    "Total_controles": len(controles),
    "Endpoints": len(rutas_esperadas),
    "Endpoints_privados": len(rutas_privadas),
    "Velas_historicas": len(velas),
    "Capital_virtual_USDT": 50000,
    "Ordenes_principales": ordenes,
    "Modelo": manifiesto["Modelo_ID"],
    "Modelo_version": manifiesto["Version"],
    "Prediccion_reproducida": retorno,
    "Diferencia_numerica": diferencia,
    "Archivos_protegidos": len(huellas),
    "Base_datos_intacta": True,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Dinero_real_utilizado": False,
    "Ejecucion_paper_en_vivo": False,
    "Ollama_integrado": False,
    "Tiempo_segundos": duracion
}

ruta_evidencia = (
    RESULTS / "auditoria_backend_final.json"
)

ruta_evidencia.write_text(
    json.dumps(
        evidencia,
        indent=4,
        ensure_ascii=False,
        allow_nan=False
    ),
    encoding="utf-8"
)

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO FINAL DEL BACKEND")
print("=" * 60)

print("Pruebas automatizadas:", len(casos))
print("Pruebas aprobadas:", aprobadas)
print("Controles adicionales:", len(controles))
print("Controles aprobados:", sum(controles.values()))
print("Endpoints disponibles:", len(rutas_esperadas))
print("Endpoints privados:", len(rutas_privadas))
print("Velas almacenadas:", len(velas))
print("Capital virtual: 50000 USDT")
print("Ordenes en cartera principal:", ordenes)
print("Modelo predictivo: FUNCIONAL")
print("Motor de riesgo: FUNCIONAL")
print("Paper Trading historico: FUNCIONAL")
print("Ejecucion paper en vivo: PENDIENTE")
print("Ollama: PENDIENTE")
print("Modelo modificado: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")
print("Tiempo total:", duracion, "segundos")
print("Evidencia:", ruta_evidencia.name)

print("\nAUDITORIA DEL BACKEND APROBADA")
print("PASO 11.10 COMPLETADO CORRECTAMENTE")
print("ETAPA 11 COMPLETADA CORRECTAMENTE")
