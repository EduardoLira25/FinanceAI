import os
import json
import time
import socket
import shutil
import hashlib
import sqlite3
import platform
import subprocess
import requests

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"

MODEL = "qwen3:8b"
URL = "http://127.0.0.1:11434"

print("=" * 60)
print("FINANCEAI - DESCARGA Y PRUEBA DE QWEN3")
print("=" * 60)


# 1. Proteger archivos originales

def sha256(ruta):

    return hashlib.sha256(
        ruta.read_bytes()
    ).hexdigest()


def database_hash():

    ruta = BASE / "database/financeai.db"

    conexion = sqlite3.connect(
        ruta.as_uri() + "?mode=ro",
        uri=True
    )

    try:

        contenido = "\n".join(
            conexion.iterdump()
        )

        return hashlib.sha256(
            contenido.encode()
        ).hexdigest()

    finally:

        conexion.close()


huella_db = database_hash()

huellas_modelo = {
    ruta: sha256(ruta)
    for ruta in (
        BASE / "models/modelo_final_v1"
    ).iterdir()
    if ruta.is_file()
}

assert len(huellas_modelo) == 10

print("Archivos LSTM protegidos: 10")


# 2. Verificar hardware y almacenamiento

ollama = shutil.which("ollama")

assert ollama is not None

procesador = subprocess.check_output(
    ["sysctl", "-n", "machdep.cpu.brand_string"],
    text=True
).strip()

ram = int(subprocess.check_output(
    ["sysctl", "-n", "hw.memsize"],
    text=True
).strip())

espacio = shutil.disk_usage(
    Path.home()
).free / 1024**3

print("Procesador:", procesador)
print("RAM:", ram / 1024**3, "GB")
print("Espacio disponible:", round(espacio, 2), "GiB")


# 3. Verificar puerto local

with socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
) as prueba:

    prueba.settimeout(1)

    assert prueba.connect_ex(
        ("127.0.0.1", 11434)
    ) != 0, "Puerto 11434 ocupado."


# 4. Configurar Ollama

entorno = os.environ.copy()

entorno.update({
    "OLLAMA_HOST": "127.0.0.1:11434",
    "OLLAMA_NO_CLOUD": "1",
    "OLLAMA_CONTEXT_LENGTH": "4096",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1"
})

sesion = requests.Session()
sesion.trust_env = False


def get(path):

    respuesta = sesion.get(
        URL + path,
        timeout=(5, 30),
        allow_redirects=False
    )

    respuesta.raise_for_status()

    return respuesta.json()


# 5. Definir formato estricto de prueba

class TestResponse(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        strict=True
    )

    project: Literal["FinanceAI"]

    status: Literal["ok"]

    mode: Literal["paper_trading"]

    message: str = Field(
        min_length=1,
        max_length=250
    )


opciones = {
    "temperature": 0,
    "seed": 42,
    "num_ctx": 4096,
    "num_predict": 256
}

payload = {
    "model": MODEL,
    "stream": False,
    "think": False,
    "keep_alive": "5m",
    "format": TestResponse.model_json_schema(),
    "options": opciones,
    "messages": [
        {
            "role": "system",
            "content": (
                "Eres un asistente del proyecto FinanceAI. "
                "Responde exclusivamente en JSON valido."
            )
        },
        {
            "role": "user",
            "content": (
                "Confirma que FinanceAI funciona en modo "
                "paper_trading, sin utilizar dinero real. "
                "Usa project=FinanceAI, status=ok, "
                "mode=paper_trading y un mensaje breve "
                "en espanol."
            )
        }
    ]
}


# 6. Iniciar servidor temporal

ruta_log = RESULTS / "ollama_qwen3.log"

with ruta_log.open("w", encoding="utf-8") as log:

    servidor = subprocess.Popen(
        [ollama, "serve"],
        env=entorno,
        stdout=log,
        stderr=subprocess.STDOUT
    )

    try:

        version = None

        for intento in range(60):

            if servidor.poll() is not None:

                raise RuntimeError(
                    "Ollama se detuvo inesperadamente."
                )

            try:

                version = get("/api/version")["version"]
                break

            except requests.RequestException:

                time.sleep(0.5)

        assert version is not None

        print("\nOllama:", version)
        print("Servidor local: FUNCIONAL")


        # 7. Descargar modelo

        instalados = get("/api/tags")["models"]

        if not any(
            m["name"] == MODEL
            for m in instalados
        ):

            assert espacio >= 10, (
                "Espacio disponible insuficiente."
            )

        print("\nDESCARGANDO QWEN3:8B\n", flush=True)

        inicio_descarga = time.perf_counter()

        subprocess.run(
            [ollama, "pull", MODEL],
            env=entorno,
            check=True
        )

        tiempo_descarga = round(
            time.perf_counter() - inicio_descarga,
            4
        )

        modelos = get("/api/tags")["models"]

        modelo = next(
            m for m in modelos
            if m["name"] == MODEL
        )

        digest = modelo["digest"]

        assert len(digest) == 64

        print("\nMODELO DESCARGADO")

        print("Nombre:", modelo["name"])

        print("Digest:", digest)

        print(
            "Tamano:",
            round(modelo["size"] / 1e9, 3),
            "GB"
        )

        print(
            "Parametros:",
            modelo["details"]["parameter_size"]
        )

        print(
            "Cuantizacion:",
            modelo["details"]["quantization_level"]
        )


        # 8. Realizar dos inferencias

        pruebas = []

        for numero in range(1, 3):

            print(
                f"\nINFERENCIA {numero} DE 2",
                flush=True
            )

            inicio = time.perf_counter()

            respuesta = sesion.post(
                URL + "/api/chat",
                json=payload,
                timeout=(5, 300),
                allow_redirects=False
            )

            respuesta.raise_for_status()

            datos = respuesta.json()

            duracion = round(
                time.perf_counter() - inicio,
                4
            )

            assert datos["done"] is True

            assert datos.get("done_reason") == "stop"

            assert datos["model"] == MODEL

            # Validar respuesta JSON mediante Pydantic

            contenido = TestResponse.model_validate_json(
                datos["message"]["content"]
            )

            tokens = datos["eval_count"]

            segundos_generacion = (
                datos["eval_duration"] / 1e9
            )

            velocidad = (
                tokens / segundos_generacion
                if segundos_generacion > 0 else 0
            )

            prueba = {
                "Numero": numero,
                "Respuesta": contenido.model_dump(),
                "JSON_valido": True,
                "Latencia_segundos": duracion,
                "Tokens_entrada": datos.get(
                    "prompt_eval_count"
                ),
                "Tokens_salida": tokens,
                "Tokens_por_segundo": round(
                    velocidad, 3
                ),
                "Tiempo_carga_segundos": (
                    datos["load_duration"] / 1e9
                )
            }

            pruebas.append(prueba)

            print(json.dumps(
                prueba,
                indent=4,
                ensure_ascii=False
            ))


        # 9. Verificar modelo cargado en memoria

        activos = get("/api/ps")["models"]

        cargado = next(
            m for m in activos
            if m["name"] == MODEL
        )

        assert cargado["digest"] == digest

        print("\nRECURSOS UTILIZADOS")

        print(
            "Memoria del modelo:",
            round(cargado["size"] / 1024**3, 3),
            "GiB"
        )

        print(
            "Memoria reportada en GPU:",
            round(
                cargado.get("size_vram", 0)
                / 1024**3,
                3
            ),
            "GiB"
        )

        print(
            "Contexto efectivo:",
            cargado.get("context_length")
        )

    finally:

        sesion.close()

        if servidor.poll() is None:

            servidor.terminate()

            try:

                servidor.wait(timeout=15)

            except subprocess.TimeoutExpired:

                servidor.kill()
                servidor.wait()

        print("\nServidor temporal detenido.")


# 10. Confirmar integridad de originales

assert database_hash() == huella_db

assert all(
    sha256(ruta) == huella
    for ruta, huella in huellas_modelo.items()
)

print("Base de datos intacta: SI")
print("Modelo LSTM intacto: SI")


# 11. Guardar evidencia

evidencia = {
    "Proyecto": "FinanceAI",
    "Etapa": "12.2",
    "Fecha_UTC": datetime.now(
        timezone.utc
    ).isoformat(),
    "Resultado": "APROBADO",
    "Ollama_version": version,
    "Modelo": MODEL,
    "Digest_modelo": digest,
    "Detalles_modelo": modelo["details"],
    "Tamano_bytes": modelo["size"],
    "Procesador": procesador,
    "Arquitectura": platform.machine(),
    "RAM_GiB": ram / 1024**3,
    "Tiempo_descarga_segundos": tiempo_descarga,
    "Configuracion_inferencia": opciones,
    "Think": False,
    "Pruebas": pruebas,
    "Modelo_en_memoria": cargado,
    "Servidor_temporal_detenido": True,
    "Base_datos_modificada": False,
    "Modelo_LSTM_modificado": False,
    "Dinero_real_utilizado": False
}

ruta_evidencia = (
    RESULTS / "control_qwen3_local.json"
)

ruta_evidencia.write_text(
    json.dumps(
        evidencia,
        indent=4,
        ensure_ascii=False
    ),
    encoding="utf-8"
)


# 12. Resultado final

print("\n" + "=" * 60)
print("FINANCEAI - RESULTADO FINAL QWEN3")
print("=" * 60)

print("Ollama:", version)
print("Modelo:", MODEL)
print("Procesador:", procesador)
print("RAM:", ram / 1024**3, "GB")
print("Modelo descargado: SI")
print("Inferencias aprobadas:", len(pruebas), "/ 2")
print("Respuestas JSON validas: SI")

print(
    "Latencia primera inferencia:",
    pruebas[0]["Latencia_segundos"],
    "segundos"
)

print(
    "Latencia segunda inferencia:",
    pruebas[1]["Latencia_segundos"],
    "segundos"
)

print(
    "Velocidad de generacion:",
    pruebas[1]["Tokens_por_segundo"],
    "tokens/s"
)

print("Modelo LSTM modificado: NO")
print("Base de datos modificada: NO")
print("Operaciones financieras: NO")
print("Evidencia:", ruta_evidencia.name)

print("\nQWEN3 FUNCIONANDO LOCALMENTE")
print("PASO 12.2 COMPLETADO CORRECTAMENTE")
