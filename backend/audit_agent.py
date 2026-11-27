import sys
import json
import time
import stat
import hashlib
import subprocess
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone

from backend.app.core.database import read_connection

from backend.app.services.prediction import verify_artifacts

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)

from backend.app.services.financial_prompt import (
    PROMPT_VERSION,
    prompt_sha256
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)

from backend.app.services.agent_supervisor import (
    run_guarded,
    recovery_status
)

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"
MODEL_PATH = BASE / "models/modelo_final_v1"

inicio = time.perf_counter()

controles = {}

print("=" * 60)
print("FINANCEAI - AUDITORIA FINAL DEL AGENTE")
print("=" * 60)


def comprobar(nombre, condicion):

    controles[nombre] = bool(condicion)

    print(
        nombre + ":",
        "APROBADO" if condicion else "ERROR"
    )

    if not condicion:

        raise AssertionError(nombre)


def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


# 1. Proteger archivos originales

archivos_protegidos = [
    archivo
    for archivo in MODEL_PATH.iterdir()
    if archivo.is_file()
]

archivos_protegidos.extend([
    BASE / "data/processed/BTCUSDT_MEXC_limpio.csv",

    BASE / "experimental/results/control_evaluacion_TE.json",

    BASE / "experimental/results/predicciones_TE.csv",

    BASE / "experimental/results/metricas_modelos_TE.csv"
])

huellas_antes = {
    str(ruta.relative_to(BASE)): sha256(ruta)
    for ruta in archivos_protegidos
}

db_antes = database_hash()
modelo_antes = model_hashes()

comprobar(
    "14 archivos originales protegidos",
    len(huellas_antes) == 14
)

comprobar(
    "10 archivos del modelo LSTM",
    len(modelo_antes) == 10
)


# 2. Ejecutar todas las pruebas automatizadas

print("\nPRUEBAS AUTOMATIZADAS")

archivos_pruebas = [
    "test_security.py",
    "test_db_connection.py",
    "test_api.py",
    "test_market_api.py",
    "test_mexc.py",
    "test_prediction.py",
    "test_risk.py",
    "test_paper_trading.py",
    "test_ollama_client.py",
    "test_financial_prompt.py",
    "test_llm_decision.py",
    "test_agent_context.py",
    "test_agent_risk.py",
    "test_market_quote.py",
    "test_live_paper_trading.py",
    "test_agent_cycle.py",
    "test_agent_supervisor.py"
]

ruta_xml = RESULTS / "auditoria_agente_pytest.xml"

subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        *[
            str(BASE / "tests" / nombre)
            for nombre in archivos_pruebas
        ],
        "-q",
        "--junitxml=" + str(ruta_xml)
    ],
    cwd=BASE,
    check=True
)

arbol = ET.parse(ruta_xml)

casos = arbol.findall(".//testcase")

aprobadas = sum(
    not any(
        caso.find(etiqueta) is not None
        for etiqueta in (
            "failure",
            "error",
            "skipped"
        )
    )
    for caso in casos
)

comprobar(
    "282 pruebas automatizadas aprobadas",
    len(casos) == aprobadas == 282
)


# 3. Verificar evidencias de la etapa 12

print("\nAUDITORIA DE EVIDENCIAS")

archivos_evidencia = {
    "12.1": "control_instalacion_ollama.json",
    "12.2": "control_qwen3_local.json",
    "12.3": "control_ollama_client.json",
    "12.4": "control_prompt_financiero.json",
    "12.5": "control_validacion_llm.json",
    "12.6": "control_integracion_lstm_llm.json",
    "12.7": "control_integracion_riesgo_llm.json",
    "12.8.1": "control_market_quote.json",
    "12.8.2": "control_live_paper_trading.json",
    "12.8.3": "control_agent_cycle.json",
    "12.9": "control_agent_supervisor.json"
}

evidencias = {}
huellas_evidencias = {}

for etapa, nombre in archivos_evidencia.items():

    ruta = RESULTS / nombre

    comprobar(
        "Evidencia disponible " + etapa,
        ruta.is_file()
    )

    datos = json.loads(
        ruta.read_text(encoding="utf-8")
    )

    comprobar(
        "Resultado aprobado " + etapa,
        datos["Resultado"] == "APROBADO"
    )

    comprobar(
        "Identidad de etapa " + etapa,
        datos["Etapa"] == etapa
    )

    evidencias[etapa] = datos

    huellas_evidencias[nombre] = sha256(ruta)


# 4. Verificar modelo LSTM original

print("\nAUDITORIA DEL MODELO LSTM")

manifiesto = verify_artifacts()

comprobar(
    "Modelo original identificado",
    manifiesto["Modelo_ID"] == "TEC_B_LSTM_S42"
)

comprobar(
    "Version original del LSTM",
    manifiesto["Version"] == "1.0.0"
)

comprobar(
    "Parametros originales",
    manifiesto["Parametros"] == 1425
)

comprobar(
    "Ventana de 20 observaciones",
    manifiesto["Ventana"] == 20
)

comprobar(
    "Variables originales del modelo",
    manifiesto["Variables_ordenadas"] == [
        "Return",
        "SMA_Distance_20",
        "Volatility_20"
    ]
)

comprobar(
    "Umbral cuantitativo original",
    manifiesto["Umbral"] == 0.001
)

respaldo_modelo = (
    BASE / "experimental/models/modelo_final_v1"
)

comprobar(
    "Modelo identico al respaldo experimental",
    all(
        (respaldo_modelo / nombre).is_file()
        and sha256(respaldo_modelo / nombre) == huella
        for nombre, huella in modelo_antes.items()
    )
)


# 5. Verificar identidad de Ollama y Qwen3

print("\nAUDITORIA DEL MODELO DE LENGUAJE")

qwen = evidencias["12.2"]

comprobar(
    "Version registrada de Ollama",
    qwen["Ollama_version"] == OLLAMA_VERSION
)

comprobar(
    "Modelo Qwen3 identificado",
    qwen["Modelo"] == MODEL
)

comprobar(
    "Digest original de Qwen3",
    qwen["Digest_modelo"] == MODEL_DIGEST
)

comprobar(
    "Inferencias locales registradas",
    len(qwen["Pruebas"]) == 2
)

comprobar(
    "Respuestas JSON locales aprobadas",
    all(
        prueba["JSON_valido"]
        for prueba in qwen["Pruebas"]
    )
)

comprobar(
    "Cuantizacion Q4_K_M",
    qwen["Detalles_modelo"]["quantization_level"]
    == "Q4_K_M"
)

comprobar(
    "Contexto de 4096 tokens",
    qwen["Configuracion_inferencia"]["num_ctx"]
    == 4096
)

comprobar(
    "Configuracion sin nube",
    evidencias["12.1"][
        "Modo_nube_deshabilitado_configurado"
    ] is True
)


# 6. Verificar prompt financiero

print("\nAUDITORIA DEL PROMPT FINANCIERO")

prompt = evidencias["12.4"]

comprobar(
    "Version del prompt financiero",
    prompt["Prompt_version"] == PROMPT_VERSION
)

comprobar(
    "Huella original del prompt",
    prompt["SHA256_prompt"] == prompt_sha256()
)

comprobar(
    "Acciones financieras permitidas",
    set(prompt["Acciones_permitidas"])
    == {"BUY", "HOLD", "SELL"}
)

comprobar(
    "Dos inferencias financieras aprobadas",
    evidencias["12.5"]["Inferencias_aprobadas"]
    == 2
)


# 7. Verificar integracion de riesgo

print("\nAUDITORIA DEL MOTOR DE RIESGO")

riesgo = evidencias["12.7"]["Integracion"]

comprobar(
    "Contexto revalidado despues del LLM",
    riesgo["context_revalidated"] is True
)

comprobar(
    "HOLD autorizado",
    riesgo["llm_risk"]["authorized_action"]
    == "HOLD"
)

comprobar(
    "Compra cuantitativa bloqueada",
    riesgo["model_only_risk"]["approved"]
    is False
)

comprobar(
    "Sin cotizacion no se autorizan ordenes",
    "NO_VERIFIED_EXECUTION_QUOTE"
    in riesgo["model_only_risk"]["reasons"]
)

comprobar(
    "Diagnostico de riesgo sin operaciones",
    riesgo["executed"] is False
)


# 8. Verificar evidencia de cotizacion

print("\nAUDITORIA DE DATOS DE MERCADO")

cotizacion = evidencias["12.8.1"]["Cotizacion"]

comprobar(
    "Simbolo financiero correcto",
    cotizacion["symbol"] == "BTCUSDT"
)

comprobar(
    "Fuente publica de mercado",
    cotizacion["source"] == "MEXC_RECENT_TRADE"
)

comprobar(
    "Cotizacion valida al momento de consulta",
    0 <= cotizacion["age_seconds_at_receipt"] <= 60
)

comprobar(
    "Precio exclusivamente simulado",
    cotizacion["paper_reference_only"] is True
)


# 9. Verificar ciclo integrado

print("\nAUDITORIA DEL CICLO OPERATIVO")

ciclo = evidencias["12.8.3"]["Ciclo_temporal"]

comprobar(
    "Ciclo integrado completado",
    ciclo["status"] == "COMPLETED"
)

comprobar(
    "Decision persistida en copia temporal",
    ciclo["cycle"]["created"] is True
)

comprobar(
    "Capital virtual conservado en diagnostico",
    ciclo["cycle"]["equity_micros"]
    == 50000 * 1000000
)

comprobar(
    "Sin ordenes durante ciclo real de diagnostico",
    ciclo["cycle"]["order_id"] is None
)

comprobar(
    "Decision HOLD persistida",
    ciclo["cycle"]["authorized_action"] == "HOLD"
)

comprobar(
    "Prediccion original reutilizada",
    ciclo["prediction"]["created"] is False
)


# 10. Verificar recuperacion de incidentes

print("\nAUDITORIA DEL SUPERVISOR")

supervisor = evidencias["12.9"]

comprobar(
    "Pausa automatica ante fallo",
    supervisor["Fallo_controlado"]["status"]
    == "PAUSED_ERROR"
)

comprobar(
    "Incidente conservado tras reinicio",
    supervisor["Reinicio_simulado"]["status"]
    == "RECOVERY_REQUIRED"
)

comprobar(
    "Recuperacion manual aprobada",
    supervisor["Recuperacion"]["status"]
    == "ACTIVE"
)

comprobar(
    "Recuperacion sin iniciar operaciones",
    supervisor["Recuperacion"]["execution_started"]
    is False
)

comprobar(
    "Recuperacion probada solamente en copia",
    supervisor["Recuperacion_probada_en_copia"]
    is True
)


# 11. Verificar SQLite y cartera principal

print("\nAUDITORIA DE LA BASE PRINCIPAL")

with read_connection() as conexion:

    comprobar(
        "Integridad estructural SQLite",
        conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
    )

    comprobar(
        "Integridad referencial SQLite",
        conexion.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    )

    cartera = conexion.execute("""
        SELECT *
        FROM portfolio
        WHERE name = 'FinanceAI_Paper'
    """).fetchone()

    comprobar(
        "Cartera exclusivamente simulada",
        cartera["mode"] == "PAPER_LIVE"
    )

    comprobar(
        "Cartera principal pausada",
        cartera["status"] == "PAUSED"
    )

    comprobar(
        "Capital inicial intacto",
        cartera["initial_cash_micros"]
        == 50000 * 1000000
    )

    comprobar(
        "Efectivo principal intacto",
        cartera["cash_micros"]
        == 50000 * 1000000
    )

    posiciones = conexion.execute("""
        SELECT *
        FROM positions
        WHERE portfolio_id = ?
    """, (cartera["id"],)).fetchall()

    comprobar(
        "Posicion original intacta",
        len(posiciones) == 1
        and posiciones[0]["quantity_sats"] == 0
        and posiciones[0]["cost_basis_micros"] == 0
    )

    ordenes = conexion.execute("""
        SELECT COUNT(*)
        FROM orders
    """).fetchone()[0]

    ciclos = conexion.execute("""
        SELECT COUNT(*)
        FROM agent_cycles
    """).fetchone()[0]

    velas = conexion.execute("""
        SELECT COUNT(*)
        FROM candles
    """).fetchone()[0]

    comprobar(
        "Cero ordenes en base principal",
        ordenes == 0
    )

    comprobar(
        "Cero ciclos en base principal",
        ciclos == 0
    )

    comprobar(
        "Historial financiero disponible",
        velas >= 2521
    )


# 12. Verificar bloqueo del agente principal

print("\nAUDITORIA DEL BLOQUEO OPERATIVO")

estado = recovery_status()

comprobar(
    "Sin incidentes principales pendientes",
    estado["recovery_required"] is False
)

def impedir_ejecucion(*args, **kwargs):

    raise AssertionError(
        "El supervisor no debia ejecutar un ciclo."
    )

bloqueo = run_guarded(
    None,
    runner=impedir_ejecucion
)

comprobar(
    "Supervisor respeta cartera pausada",
    bloqueo["status"] == "PAUSED"
)

comprobar(
    "Supervisor no inicia operaciones",
    bloqueo["executed"] is False
)


# 13. Verificar proteccion de credenciales

print("\nAUDITORIA DE SEGURIDAD")

env = BASE / ".env"

comprobar(
    "Permisos privados de credenciales",
    stat.S_IMODE(env.stat().st_mode) == 0o600
)

gitignore = (
    BASE / ".gitignore"
).read_text(encoding="utf-8").splitlines()

comprobar(
    "Credenciales excluidas del repositorio",
    ".env" in gitignore
)

comprobar(
    "Archivos de bloqueo excluidos",
    "*.agent.lock" in gitignore
)


# 14. Confirmar integridad final

print("\nPROTECCION DE ORIGINALES")

huellas_despues = {
    str(ruta.relative_to(BASE)): sha256(ruta)
    for ruta in archivos_protegidos
}

comprobar(
    "14 archivos protegidos intactos",
    huellas_antes == huellas_despues
)

comprobar(
    "Modelo LSTM intacto",
    model_hashes() == modelo_antes
)

comprobar(
    "Base principal intacta",
    database_hash() == db_antes
)

comprobar(
    "Evidencias anteriores intactas",
    all(
        sha256(RESULTS / nombre) == huella
        for nombre, huella
        in huellas_evidencias.items()
    )
)


# 15. Registrar dependencias del entorno

dependencias = subprocess.check_output(
    [
        sys.executable,
        "-m",
        "pip",
        "freeze"
    ],
    text=True
)

(
    BASE / "backend/requirements-lock-macos.txt"
).write_text(
    dependencias,
    encoding="utf-8"
)


# 16. Guardar auditoria final

duracion = round(
    time.perf_counter() - inicio,
    4
)

auditoria = {
    "Proyecto": "FinanceAI",
    "Etapa": "12.10",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",

    "Pruebas_automatizadas": len(casos),
    "Pruebas_aprobadas": aprobadas,

    "Controles_adicionales": controles,
    "Total_controles": len(controles),
    "Controles_aprobados": sum(
        controles.values()
    ),

    "Evidencias_verificadas": len(evidencias),
    "SHA256_evidencias": huellas_evidencias,

    "Modelo_LSTM": manifiesto["Modelo_ID"],
    "Version_LSTM": manifiesto["Version"],
    "Modelo_LLM": MODEL,
    "Ollama_version": OLLAMA_VERSION,
    "Digest_LLM": MODEL_DIGEST,

    "Prompt_version": PROMPT_VERSION,
    "Prompt_SHA256": prompt_sha256(),

    "Hardware": qwen["Procesador"],
    "RAM_GiB": qwen["RAM_GiB"],

    "Velas_almacenadas": velas,
    "Capital_virtual_USDT": 50000,
    "Cartera_principal": cartera["status"],
    "Ordenes_principales": ordenes,
    "Ciclos_principales": ciclos,

    "Archivos_protegidos": len(
        archivos_protegidos
    ),
    "SHA256_archivos_protegidos": huellas_antes,

    "Base_principal_intacta": True,
    "Modelo_LSTM_intacto": True,
    "Reentrenamiento": False,
    "TE_reevaluado": False,
    "Dinero_real_utilizado": False,

    "Agente_probado_en_copia": True,
    "Inferencias_nuevas_en_auditoria": False,
    "Automatizacion_permanente": False,

    "Pendientes": [
        "Frontend React y TypeScript",
        "Interfaz autenticada de control",
        "Programacion diaria permanente",
        "Pruebas de reinicio real del proceso",
        "Replay comparativo de estrategias",
        "Validacion integral de incidentes",
        "Pruebas independientes de la base principal",
        "Documentacion y entrega final"
    ],

    "Tiempo_segundos": duracion
}

ruta_auditoria = (
    RESULTS / "auditoria_agente_final.json"
)

ruta_auditoria.write_text(
    json.dumps(
        auditoria,
        indent=4,
        ensure_ascii=False,
        allow_nan=False
    ),
    encoding="utf-8"
)


# 17. Resultado definitivo

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO FINAL DEL AGENTE")
print("=" * 60)

print("Pruebas automatizadas:", len(casos))
print("Pruebas aprobadas:", aprobadas)
print("Controles adicionales:", len(controles))
print("Controles aprobados:", sum(controles.values()))
print("Evidencias verificadas:", len(evidencias))

print("Modelo LSTM:", manifiesto["Modelo_ID"])
print("Modelo LLM:", MODEL)
print("Ollama:", OLLAMA_VERSION)
print("Hardware:", qwen["Procesador"])
print("RAM:", qwen["RAM_GiB"], "GiB")

print("Motor de riesgo: FUNCIONAL")
print("Ejecutor Paper Trading: FUNCIONAL")
print("Orquestador: FUNCIONAL")
print("Supervisor: FUNCIONAL")
print("Control de duplicados: FUNCIONAL")

print("Velas almacenadas:", velas)
print("Capital virtual: 50000 USDT")
print("Cartera principal: PAUSADA")
print("Ordenes principales:", ordenes)
print("Ciclos principales:", ciclos)

print("Archivos protegidos:", len(archivos_protegidos))
print("Base principal intacta: SI")
print("Modelo LSTM intacto: SI")
print("Reentrenamiento: NO")
print("TE reevaluado: NO")
print("Dinero real utilizado: NO")

print("Automatizacion permanente: PENDIENTE")
print("Frontend React: PENDIENTE")

print("Tiempo total:", duracion, "segundos")
print("Evidencia:", ruta_auditoria.name)

print("\nAUDITORIA DEL AGENTE APROBADA")
print("PASO 12.10 COMPLETADO CORRECTAMENTE")
print("ETAPA 12 COMPLETADA CORRECTAMENTE")
