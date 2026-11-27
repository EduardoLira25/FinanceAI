import ast
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from backend.app.core.config import (
    load_api_key,
    DATABASE_PATH,
    MODEL_PATH
)

from backend.app.core.database import (
    read_connection
)

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)

from backend.app.services.prediction import (
    verify_artifacts
)

from backend.app.main import app as backend_app

from backend.app.dashboard_gateway import (
    create_app,
    ORIGIN
)

from backend.app.api import (
    agent_control,
    agent_recovery
)


BASE = Path.cwd()
FRONTEND = BASE / "frontend"
RESULTS = BASE / "results"

inicio = time.perf_counter()

db_antes = database_hash()
modelo_antes = model_hashes()

controles = {}

print("=" * 60)
print("FINANCEAI - AUDITORIA FINAL DEL FRONTEND")
print("=" * 60)


def comprobar(nombre, condicion):

    controles[nombre] = bool(condicion)

    print(
        nombre + ":",
        "APROBADO" if condicion else "RECHAZADO",
        flush=True
    )

    if not condicion:

        raise RuntimeError(
            "Control no aprobado: " + nombre
        )


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


# 1. Proteger archivos experimentales originales.

archivos_protegidos = list(
    MODEL_PATH.iterdir()
)

archivos_protegidos = [
    ruta for ruta in archivos_protegidos
    if ruta.is_file()
]

archivos_protegidos += [
    BASE / "data/processed/BTCUSUSDT_MEXC_limpio.csv"
]

# Utilizar el nombre definitivo del archivo financiero.
archivos_protegidos[-1] = (
    BASE / "data/processed/BTCUSDT_MEXC_limpio.csv"
)

archivos_protegidos += [
    BASE / "experimental/results/control_evaluacion_TE.json",
    BASE / "experimental/results/predicciones_TE.csv",
    BASE / "experimental/results/metricas_modelos_TE.csv"
]

huellas_antes = {
    str(ruta.relative_to(BASE)): sha256(ruta)
    for ruta in archivos_protegidos
}

comprobar(
    "14 archivos originales protegidos",
    len(huellas_antes) == 14
)

verify_artifacts()

comprobar(
    "Integridad inicial del modelo LSTM",
    True
)


# 2. Identificar todas las pruebas automatizadas.

archivos_pruebas = sorted(
    ruta for ruta in (BASE / "tests").glob("test_*.py")
    if ruta.name != "test_database.py"
)

comprobar(
    "Archivos de pruebas disponibles",
    len(archivos_pruebas) > 0
)

print("\nPRUEBAS AUTOMATIZADAS INTEGRALES", flush=True)

print(
    "Archivos de pruebas:",
    len(archivos_pruebas)
)

ruta_xml = RESULTS / "auditoria_frontend_pytest.xml"

subprocess.run(
    [
        sys.executable,
        "-m", "pytest",
        *[
            str(ruta.relative_to(BASE))
            for ruta in archivos_pruebas
        ],
        "-q",
        "--junitxml=" + str(ruta_xml)
    ],
    cwd=BASE,
    check=True
)

casos = ET.parse(ruta_xml).findall(
    ".//testcase"
)

aprobadas = sum(
    all(
        caso.find(etiqueta) is None
        for etiqueta in (
            "failure", "error", "skipped"
        )
    )
    for caso in casos
)

comprobar(
    "Todas las pruebas automatizadas aprobadas",
    len(casos) > 0 and aprobadas == len(casos)
)

comprobar(
    "Cobertura acumulada esperada",
    len(casos) >= 415
)

print("Pruebas totales:", len(casos))
print("Pruebas aprobadas:", aprobadas)


# 3. Auditar codigo Python.

print("\nAUDITORIA DE CODIGO PYTHON")

archivos_python = list(
    (BASE / "backend").rglob("*.py")
)

for ruta in archivos_python:

    ast.parse(
        ruta.read_text(encoding="utf-8"),
        filename=str(ruta)
    )

comprobar(
    "Sintaxis Python valida",
    len(archivos_python) > 0
)


# 4. Analisis estatico de React.

print("\nANALISIS ESTATICO DEL FRONTEND", flush=True)

lint = subprocess.run(
    ["npm", "run", "lint"],
    cwd=FRONTEND,
    text=True,
    capture_output=True,
    check=True
)

salida_lint = lint.stdout + lint.stderr

print(salida_lint)

comprobar(
    "Cero advertencias y errores",
    "0 warnings and 0 errors" in salida_lint
)


# 5. Compilacion TypeScript y Vite.

print("\nCOMPILACION DE PRODUCCION", flush=True)

subprocess.run(
    ["npm", "run", "build"],
    cwd=FRONTEND,
    check=True
)

comprobar(
    "Frontend compilado",
    (FRONTEND / "dist/index.html").is_file()
)

chunks = {
    ruta.name: round(ruta.stat().st_size / 1000, 3)
    for ruta in (
        FRONTEND / "dist/assets"
    ).glob("*.js")
}

comprobar(
    "Modulos JavaScript generados",
    len(chunks) > 0
)

print(
    "Mayor modulo JavaScript:",
    max(chunks.values()),
    "KB"
)


# 6. Verificar paginas y endpoints.

PAGINAS = [
    "/",
    "/mercado",
    "/predicciones",
    "/agente",
    "/cartera",
    "/operaciones",
    "/riesgo",
    "/incidentes"
]

ENDPOINTS = [
    "status",
    "database/status",
    "model/status",
    "portfolio",
    "portfolio/overview",
    "orders/history",
    "market/assets",
    "market/latest",
    "market/candles",
    "predictions/latest",
    "predictions/history",
    "agent/status",
    "agent/decisions",
    "agent/recovery/status",
    "risk/overview",
    "incidents/history",
    "risk/config"
]

RUTAS_ESCRITURA = [
    "predictions/generate",
    "agent/control/activate",
    "agent/control/pause",
    "agent/control/stop",
    "agent/control/run",
    "agent/recovery/recover",
    "agent/recovery/reset"
]

clave = load_api_key()

gateway_app = create_app(
    transport=httpx.ASGITransport(
        app=backend_app
    )
)

datos_api = {}


async def auditar_rutas():

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=backend_app
        ),
        base_url="http://127.0.0.1:8000"
    ) as api:

        print("\nAUTENTICACION DE FASTAPI")

        for endpoint in ENDPOINTS:

            respuesta = await api.get(
                "/api/v1/" + endpoint
            )

            comprobar(
                "Sin clave GET " + endpoint,
                respuesta.status_code == 401
            )

        for endpoint in RUTAS_ESCRITURA:

            cuerpo = {
                "confirm": "PAPER_ONLY"
            }

            if endpoint.startswith(
                "agent/recovery/"
            ):

                cuerpo.update({
                    "reason": (
                        "Prueba de acceso no autorizado."
                    ),
                    "incident_ids": (
                        [1]
                        if endpoint.endswith("recover")
                        else []
                    )
                })

            respuesta = await api.post(
                "/api/v1/" + endpoint,
                json=cuerpo
            )

            comprobar(
                "Sin clave POST " + endpoint,
                respuesta.status_code == 401
            )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=gateway_app
        ),
        base_url=ORIGIN,
        headers={
            "X-FinanceAI-Client": "browser"
        }
    ) as cliente:

        print("\nNAVEGACION REACT")

        for pagina in PAGINAS:

            respuesta = await cliente.get(pagina)

            comprobar(
                "Pagina " + pagina,
                respuesta.status_code == 200
                and "text/html" in respuesta.headers.get(
                    "content-type", ""
                )
                and clave not in respuesta.text
            )

        print("\nCONSULTAS AUTENTICADAS VIA GATEWAY")

        for endpoint in ENDPOINTS:

            respuesta = await cliente.get(
                "/bridge/" + endpoint
            )

            comprobar(
                "Gateway " + endpoint,
                respuesta.status_code == 200
                and clave not in respuesta.text
            )

            datos_api[endpoint] = respuesta.json()

        print("\nPROTECCION DE ORIGEN")

        respuesta = await cliente.post(
            "/control/agent/activate",
            headers={
                "Origin": "https://example.com",
                "Sec-Fetch-Site": "cross-site"
            },
            json={
                "confirm": "PAPER_ONLY"
            }
        )

        comprobar(
            "Escritura desde origen externo bloqueada",
            respuesta.status_code == 403
        )


asyncio.run(auditar_rutas())


# 7. Validar coherencia financiera entre modulos.

print("\nCOHERENCIA FINANCIERA")

cartera = datos_api["portfolio/overview"]

agente = datos_api["agent/status"]

riesgo = datos_api["risk/overview"]

incidentes = datos_api["incidents/history"]

recuperacion = datos_api["agent/recovery/status"]

ordenes = datos_api["orders/history"]

comprobar(
    "Capital inicial de 50000 USDT",
    cartera["initial_cash"] == 50000
)

comprobar(
    "Patrimonio conservado",
    cartera["equity"] == 50000
    and cartera["cash"] == 50000
)

comprobar(
    "Posicion inicial vacia",
    cartera["bitcoin_quantity"] == 0
)

comprobar(
    "Rendimiento inicial correcto",
    cartera["return_pct"] == 0
)

comprobar(
    "Estado de cartera consistente",
    cartera["status"] == "PAUSED"
    and agente["portfolio_status"] == "PAUSED"
    and riesgo["portfolio_status"] == "PAUSED"
    and recuperacion["portfolio_status"] == "PAUSED"
)

comprobar(
    "Sin operaciones principales",
    ordenes["total"] == 0
    and cartera["filled_orders"] == 0
    and agente["filled_orders"] == 0
)

comprobar(
    "Sin ciclos principales",
    agente["total_cycles"] == 0
)

comprobar(
    "Sin incidentes pendientes",
    incidentes["pending"] == 0
    and recuperacion["pending_count"] == 0
)

comprobar(
    "Limites financieros originales",
    riesgo["current"]["max_exposure_pct"] == 25
    and riesgo["current"]["max_daily_loss_pct"] == 2
    and riesgo["current"]["max_data_age_seconds"] == 3600
    and riesgo["current"]["min_order_usdt"] == 10
    and riesgo["current"]["fee_pct"] == 0
    and riesgo["current"]["slippage_pct"] == 0
)

comprobar(
    "Recuperacion innecesaria bloqueada",
    recuperacion["can_recover"] is False
    and recuperacion["can_reset"] is False
)

comprobar(
    "Modo exclusivamente simulado",
    all(
        objeto["real_trading"] is False
        for objeto in datos_api.values()
        if "real_trading" in objeto
    )
)

comprobar(
    "Programacion permanente deshabilitada",
    agente["scheduler_enabled"] is False
)


# 8. Prueba integral de escritura en copia temporal.

print("\nCONTROLES OPERATIVOS EN COPIA TEMPORAL")


async def auditar_controles(db_temporal):

    assert db_temporal.resolve() != (
        DATABASE_PATH.resolve()
    )

    gateway_temporal = create_app(
        transport=httpx.ASGITransport(
            app=backend_app
        )
    )

    with (
        patch.object(
            agent_control,
            "DATABASE_PATH",
            db_temporal
        ),
        patch.object(
            agent_recovery,
            "DATABASE_PATH",
            db_temporal
        )
    ):

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=gateway_temporal
            ),
            base_url=ORIGIN,
            headers={
                "Origin": ORIGIN,
                "X-FinanceAI-Client": "browser",
                "Sec-Fetch-Site": "same-origin"
            }
        ) as cliente:

            async def accion(
                nombre,
                esperado,
                cuerpo=None
            ):

                respuesta = await cliente.post(
                    "/control/agent/" + nombre,
                    json=(
                        cuerpo
                        if cuerpo is not None
                        else {
                            "confirm": "PAPER_ONLY"
                        }
                    )
                )

                comprobar(
                    "Control HTTP " + nombre,
                    respuesta.status_code == 200
                )

                resultado = respuesta.json()

                comprobar(
                    "Estado resultante " + nombre,
                    resultado["status"] == esperado
                    and resultado["real_trading"] is False
                    and clave not in respuesta.text
                )

            await accion("activate", "ACTIVE")

            await accion("pause", "PAUSED")

            await accion("stop", "STOPPED")

            respuesta = await cliente.post(
                "/control/agent/activate",
                json={
                    "confirm": "PAPER_ONLY"
                }
            )

            comprobar(
                "Reactivacion con paro bloqueada",
                respuesta.status_code == 409
            )

            await accion(
                "reset",
                "PAUSED",
                {
                    "confirm": "PAPER_ONLY",
                    "reason": (
                        "Revision controlada durante "
                        "auditoria integral del frontend."
                    ),
                    "incident_ids": []
                }
            )

    with read_connection(db_temporal) as c:

        estado = c.execute("""
            SELECT status, cash_micros
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()

        comprobar(
            "Cartera temporal nuevamente pausada",
            estado["status"] == "PAUSED"
        )

        comprobar(
            "Capital temporal intacto",
            estado["cash_micros"] == 50000000000
        )

        comprobar(
            "Sin ordenes durante controles",
            c.execute(
                "SELECT COUNT(*) FROM orders"
            ).fetchone()[0] == 0
        )

        configs = c.execute("""
            SELECT emergency_stop
            FROM risk_config
            ORDER BY version
        """).fetchall()

        comprobar(
            "Historial de paro conservado",
            [r["emergency_stop"] for r in configs]
                == [0, 1, 0]
        )


with tempfile.TemporaryDirectory(
    prefix="financeai_audit_frontend_"
) as temporal:

    db_temporal = (
        Path(temporal) / "financeai_test.db"
    )

    with read_connection() as original:

        copia = sqlite3.connect(db_temporal)

        try:
            original.backup(copia)
        finally:
            copia.close()

    asyncio.run(
        auditar_controles(db_temporal)
    )


# 9. Auditar SQLite principal.

print("\nINTEGRIDAD DE SQLITE")

with read_connection() as c:

    comprobar(
        "Integridad estructural",
        c.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
    )

    comprobar(
        "Integridad referencial",
        c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    )

    comprobar(
        "Version del esquema conservada",
        c.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == 1
    )

    tablas = c.execute("""
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
    """).fetchone()[0]

    velas = c.execute(
        "SELECT COUNT(*) FROM candles"
    ).fetchone()[0]

    comprobar(
        "13 tablas disponibles",
        tablas == 13
    )

    comprobar(
        "Historial financiero conservado",
        velas >= 2521
    )

    comprobar(
        "Sin ordenes en base principal",
        c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0
    )


# 10. Auditar credenciales.

print("\nSEGURIDAD DE CREDENCIALES")

comprobar(
    "Archivo privado con permisos restrictivos",
    (BASE / ".env").stat().st_mode & 0o777 == 0o600
)

comprobar(
    "Plantilla publica sin clave privada",
    clave not in (
        BASE / ".env.example"
    ).read_text(encoding="utf-8")
)

comprobar(
    "Archivo privado excluido de Git",
    ".env" in (
        BASE / ".gitignore"
    ).read_text(encoding="utf-8").splitlines()
)

clave_bytes = clave.encode()

archivos_revisados = 0

for carpeta in ("src", "dist"):

    for ruta in (
        FRONTEND / carpeta
    ).rglob("*"):

        if ruta.is_file():

            if clave_bytes in ruta.read_bytes():

                raise RuntimeError(
                    "Credencial detectada en frontend."
                )

            archivos_revisados += 1

comprobar(
    "Sin clave privada en codigo ni compilacion",
    archivos_revisados > 0
)


# 11. Auditar evidencias anteriores.

print("\nAUDITORIA DE EVIDENCIAS")

nombres_evidencia = [
    "control_frontend_inicial.json",
    "control_diseno_frontend.json",
    "control_conexion_frontend.json",
    "control_dashboard_real.json",
    "control_mercado_frontend.json",
    "control_predicciones_frontend.json",
    "control_agente_frontend.json",
    "control_operativo_frontend.json",
    "control_cartera_operaciones.json",
    "control_riesgo_incidentes_frontend.json",
    "control_recuperacion_frontend.json"
]

evidencias = {}

for nombre in nombres_evidencia:

    ruta = RESULTS / nombre

    comprobar(
        "Evidencia " + nombre,
        ruta.is_file()
    )

    contenido = json.loads(
        ruta.read_text(encoding="utf-8")
    )

    comprobar(
        "JSON valido " + nombre,
        isinstance(contenido, dict)
        and bool(contenido)
    )

    evidencias[nombre] = sha256(ruta)

incidente_desarrollo = json.loads(
    (
        RESULTS /
        "incidente_desarrollo_13_9_2.json"
    ).read_text(encoding="utf-8")
)

comprobar(
    "Errores de recuperacion documentados",
    incidente_desarrollo["Resultado"] == "RESUELTO"
)


# 12. Comprobar archivos originales.

print("\nPROTECCION DE ORIGINALES")

verify_artifacts()

comprobar(
    "Modelo LSTM intacto",
    model_hashes() == modelo_antes
)

comprobar(
    "Modelo identico al respaldo experimental",
    all(
        sha256(ruta) == sha256(
            BASE / "experimental/models/modelo_final_v1"
            / ruta.name
        )
        for ruta in MODEL_PATH.iterdir()
        if ruta.is_file()
    )
)

comprobar(
    "14 archivos protegidos intactos",
    all(
        sha256(BASE / nombre) == huella
        for nombre, huella in huellas_antes.items()
    )
)

comprobar(
    "Base principal intacta",
    database_hash() == db_antes
)


# 13. Guardar versiones del frontend.

package = json.loads(
    (FRONTEND / "package.json").read_text(
        encoding="utf-8"
    )
)

package_lock = json.loads(
    (FRONTEND / "package-lock.json").read_text(
        encoding="utf-8"
    )
)

dependencias = {
    nombre: package_lock["packages"][
        "node_modules/" + nombre
    ]["version"]
    for nombre in {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {})
    }
}

comprobar(
    "Dependencias registradas en package-lock",
    len(dependencias) > 0
)


# 14. Guardar evidencia final.

duracion = round(
    time.perf_counter() - inicio,
    4
)

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "13.10",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO_TECNICAMENTE",
    "Pruebas_automatizadas": len(casos),
    "Pruebas_aprobadas": aprobadas,
    "Pruebas_fallidas": len(casos) - aprobadas,
    "Archivos_pruebas": len(archivos_pruebas),
    "Controles_adicionales": controles,
    "Total_controles": len(controles),
    "Controles_aprobados": sum(controles.values()),
    "Paginas_disponibles": PAGINAS,
    "Endpoints_lectura": len(ENDPOINTS),
    "Rutas_escritura_protegidas": len(RUTAS_ESCRITURA),
    "Dependencias_frontend": dependencias,
    "Modulos_javascript_KB": chunks,
    "Mayor_modulo_javascript_KB": max(chunks.values()),
    "Evidencias_verificadas": evidencias,
    "Archivos_protegidos": huellas_antes,
    "Velas_historicas": velas,
    "Capital_virtual_USDT": cartera["equity"],
    "Ordenes_principales": ordenes["total"],
    "Cartera_principal": cartera["status"],
    "Base_principal_intacta": True,
    "Modelo_LSTM_intacto": True,
    "Credenciales_expuestas": False,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Pruebas_escritura_en_copia": True,
    "Programacion_permanente": False,
    "Dinero_real_utilizado": False,
    "Validacion_visual_predicciones": "PENDIENTE",
    "Prueba_ciclo_vivo_principal": False,
    "Tiempo_segundos": duracion
}

ruta_evidencia = (
    RESULTS / "auditoria_frontend_final.json"
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
print("FINANCEAI - RESULTADO FINAL DEL FRONTEND")
print("=" * 60)

print("Pruebas automatizadas:", len(casos))
print("Pruebas aprobadas:", aprobadas)
print("Pruebas fallidas:", len(casos) - aprobadas)
print("Controles adicionales:", len(controles))
print("Controles aprobados:", sum(controles.values()))
print("Paginas disponibles:", len(PAGINAS))
print("Endpoints de lectura:", len(ENDPOINTS))
print("Rutas de escritura protegidas:", len(RUTAS_ESCRITURA))
print("Evidencias verificadas:", len(evidencias))
print("React + TypeScript: FUNCIONAL")
print("Compilacion: APROBADA")
print("Controles operativos en copia: APROBADOS")
print("Capital virtual: 50000 USDT")
print("Cartera principal: PAUSADA")
print("Ordenes principales: 0")
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("Credenciales expuestas: NO")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")
print("Automatizacion permanente: PENDIENTE")
print("Simulacion historica comparativa: PENDIENTE")
print("Tiempo total:", duracion, "segundos")
print("Evidencia:", ruta_evidencia.name)

print("\nAUDITORIA TECNICA DEL FRONTEND APROBADA")
print("PASO 13.10 COMPLETADO TECNICAMENTE")

