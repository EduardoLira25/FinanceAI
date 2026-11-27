import os
import json
import time
import socket
import shutil
import requests
import subprocess

from datetime import datetime, timezone

from backend.app.core.config import BASE_DIR


OLLAMA_URL = "http://127.0.0.1:11434"

OLLAMA_VERSION = "0.40.18"

MODEL = "qwen3:8b"

MODEL_DIGEST = (
    "500a1f067a9f782620b40bee6f7b0c89"
    "e17ae61f686b92c24933e4ca4b2b8b41"
)

OPTIONS = {
    "temperature": 0,
    "seed": 42,
    "num_ctx": 4096,
    "num_predict": 256
}

CONNECT_TIMEOUT = 3
READ_TIMEOUT = 120
MAX_ATTEMPTS = 3


class OllamaError(RuntimeError):

    def __init__(self, code, message):

        self.code = code

        super().__init__(message)


class OllamaClient:

    def __init__(self):

        self.session = requests.Session()

        # No utilizar proxies externos.
        self.session.trust_env = False

    def __enter__(self):

        return self

    def __exit__(self, exc_type, exc, tb):

        self.close()

    def close(self):

        self.session.close()

    def _request(self, method, path, payload=None):

        rutas = {
            ("GET", "/api/version"),
            ("GET", "/api/tags"),
            ("GET", "/api/ps"),
            ("POST", "/api/chat")
        }

        if (method, path) not in rutas:

            raise OllamaError(
                "INVALID_ENDPOINT",
                "Endpoint Ollama no autorizado."
            )

        intentos = (
            MAX_ATTEMPTS if method == "GET"
            else 1
        )

        for intento in range(intentos):

            try:

                respuesta = self.session.request(
                    method,
                    OLLAMA_URL + path,
                    json=payload,
                    timeout=(
                        CONNECT_TIMEOUT,
                        READ_TIMEOUT
                    ),
                    allow_redirects=False
                )

            except requests.Timeout:

                if intento + 1 < intentos:

                    time.sleep(2 ** intento)
                    continue

                raise OllamaError(
                    "OLLAMA_TIMEOUT",
                    "Tiempo de espera agotado."
                ) from None

            except requests.ConnectionError:

                if intento + 1 < intentos:

                    time.sleep(2 ** intento)
                    continue

                raise OllamaError(
                    "OLLAMA_UNAVAILABLE",
                    "Servidor Ollama no disponible."
                ) from None

            except requests.RequestException:

                raise OllamaError(
                    "OLLAMA_CONNECTION_ERROR",
                    "Error de comunicacion con Ollama."
                ) from None

            if respuesta.status_code == 429:

                raise OllamaError(
                    "OLLAMA_RATE_LIMIT",
                    "Limite de solicitudes alcanzado."
                )

            if (
                respuesta.status_code >= 500
                and intento + 1 < intentos
            ):

                time.sleep(2 ** intento)
                continue

            if respuesta.status_code != 200:

                raise OllamaError(
                    "OLLAMA_HTTP_ERROR",
                    f"Ollama HTTP {respuesta.status_code}"
                )

            try:

                datos = respuesta.json()

            except ValueError:

                raise OllamaError(
                    "INVALID_HTTP_JSON",
                    "Respuesta HTTP JSON invalida."
                ) from None

            if not isinstance(datos, dict):

                raise OllamaError(
                    "INVALID_HTTP_JSON",
                    "Respuesta HTTP inesperada."
                )

            return datos

        raise OllamaError(
            "OLLAMA_UNAVAILABLE",
            "Solicitudes agotadas."
        )

    def verify_model(self):

        version = self._request(
            "GET",
            "/api/version"
        ).get("version")

        if version != OLLAMA_VERSION:

            raise OllamaError(
                "OLLAMA_VERSION_CHANGED",
                "Version de Ollama diferente a la auditada."
            )

        modelos = self._request(
            "GET",
            "/api/tags"
        ).get("models")

        if not isinstance(modelos, list):

            raise OllamaError(
                "INVALID_MODEL_LIST",
                "Lista de modelos invalida."
            )

        modelo = next(
            (
                m for m in modelos
                if isinstance(m, dict)
                and m.get("name") == MODEL
            ),
            None
        )

        if modelo is None:

            raise OllamaError(
                "MODEL_NOT_FOUND",
                "Modelo local no disponible."
            )

        if modelo.get("digest") != MODEL_DIGEST:

            raise OllamaError(
                "MODEL_DIGEST_MISMATCH",
                "Identidad del modelo no verificada."
            )

        return {
            "ollama_version": version,
            "model": MODEL,
            "digest": MODEL_DIGEST
        }

    def chat(self, messages, schema):

        if (
            not isinstance(messages, list)
            or not messages
            or not isinstance(schema, dict)
            or not schema
        ):

            raise OllamaError(
                "INVALID_REQUEST",
                "Solicitud LLM invalida."
            )

        for mensaje in messages:

            if (
                not isinstance(mensaje, dict)
                or set(mensaje) != {"role", "content"}
                or mensaje["role"] not in (
                    "system", "user"
                )
                or not isinstance(
                    mensaje["content"], str
                )
                or not mensaje["content"].strip()
            ):

                raise OllamaError(
                    "INVALID_REQUEST",
                    "Mensaje LLM invalido."
                )

        identidad = self.verify_model()

        payload = {
            "model": MODEL,
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "format": schema,
            "options": OPTIONS.copy(),
            "messages": messages
        }

        inicio = time.perf_counter()

        datos = self._request(
            "POST",
            "/api/chat",
            payload
        )

        latency_ms = (
            time.perf_counter() - inicio
        ) * 1000

        if datos.get("model") != MODEL:

            raise OllamaError(
                "UNEXPECTED_MODEL",
                "Modelo de respuesta incompatible."
            )

        if (
            datos.get("done") is not True
            or datos.get("done_reason") != "stop"
        ):

            raise OllamaError(
                "INCOMPLETE_RESPONSE",
                "Generacion incompleta o truncada."
            )

        mensaje = datos.get("message")

        if not isinstance(mensaje, dict):

            raise OllamaError(
                "INVALID_LLM_RESPONSE",
                "Respuesta LLM invalida."
            )

        contenido = mensaje.get("content")

        if (
            not isinstance(contenido, str)
            or not contenido.strip()
        ):

            raise OllamaError(
                "EMPTY_LLM_RESPONSE",
                "Respuesta LLM vacia."
            )

        # Confirmar que el modelo no cambio
        # durante la solicitud.

        self.verify_model()

        return {
            **identidad,
            "content": contenido,
            "latency_ms": round(latency_ms, 3),
            "prompt_tokens": datos.get(
                "prompt_eval_count"
            ),
            "output_tokens": datos.get(
                "eval_count"
            ),
            "load_duration_ns": datos.get(
                "load_duration"
            ),
            "eval_duration_ns": datos.get(
                "eval_duration"
            )
        }


# 2. Diagnostico real de comunicacion

def main():

    from typing import Literal
    from pydantic import BaseModel, ConfigDict

    class DiagnosticResponse(BaseModel):

        model_config = ConfigDict(
            extra="forbid",
            strict=True
        )

        project: Literal["FinanceAI"]
        status: Literal["ok"]
        mode: Literal["paper_trading"]

    print("=" * 60)
    print("FINANCEAI - COMUNICACION PYTHON OLLAMA")
    print("=" * 60)

    ollama = shutil.which("ollama")

    assert ollama is not None

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as prueba:

        prueba.settimeout(1)

        assert prueba.connect_ex(
            ("127.0.0.1", 11434)
        ) != 0, "Puerto Ollama ocupado."

    entorno = os.environ.copy()

    entorno.update({
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_CONTEXT_LENGTH": "4096",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1"
    })

    ruta_log = (
        BASE_DIR /
        "results/ollama_client.log"
    )

    with ruta_log.open(
        "w", encoding="utf-8"
    ) as log:

        servidor = subprocess.Popen(
            [ollama, "serve"],
            env=entorno,
            stdout=log,
            stderr=subprocess.STDOUT
        )

        try:

            disponible = False

            with requests.Session() as sesion:

                sesion.trust_env = False

                for intento in range(60):

                    if servidor.poll() is not None:

                        raise RuntimeError(
                            "Ollama se detuvo."
                        )

                    try:

                        respuesta = sesion.get(
                            OLLAMA_URL + "/api/version",
                            timeout=2,
                            allow_redirects=False
                        )

                        if respuesta.status_code == 200:

                            disponible = True
                            break

                    except requests.RequestException:
                        pass

                    time.sleep(0.5)

            assert disponible

            with OllamaClient() as cliente:

                identidad = cliente.verify_model()

                print("Servidor local: DISPONIBLE")
                print("Version:", identidad["ollama_version"])
                print("Modelo:", identidad["model"])
                print("Digest:", identidad["digest"])
                print("Identidad del modelo: APROBADA")

                resultado = cliente.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Devuelve exclusivamente "
                                "JSON valido."
                            )
                        },
                        {
                            "role": "user",
                            "content": (
                                "Responde con project=FinanceAI, "
                                "status=ok y mode=paper_trading."
                            )
                        }
                    ],
                    schema=(
                        DiagnosticResponse
                        .model_json_schema()
                    )
                )

                validado = (
                    DiagnosticResponse
                    .model_validate_json(
                        resultado["content"]
                    )
                )

                print("\nRESPUESTA DEL MODELO")

                print(
                    validado.model_dump_json(
                        indent=4
                    )
                )

                print("\nLatencia:",
                      resultado["latency_ms"], "ms")

                print("Tokens de entrada:",
                      resultado["prompt_tokens"])

                print("Tokens de salida:",
                      resultado["output_tokens"])

        finally:

            if servidor.poll() is None:

                servidor.terminate()

                try:

                    servidor.wait(timeout=15)

                except subprocess.TimeoutExpired:

                    servidor.kill()
                    servidor.wait()

            print("\nServidor temporal detenido.")

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.3",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": "APROBADO",
        "Identidad": identidad,
        "Configuracion": OPTIONS,
        "Respuesta": validado.model_dump(),
        "Inferencia": resultado,
        "Servidor_temporal_detenido": True,
        "Operaciones_financieras": False
    }

    ruta = (
        BASE_DIR /
        "results/control_ollama_client.json"
    )

    ruta.write_text(
        json.dumps(
            evidencia,
            indent=4,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("FINANCEAI - RESULTADO CLIENTE OLLAMA")
    print("=" * 60)

    print("Cliente Python: FUNCIONAL")
    print("Identidad del modelo: VERIFICADA")
    print("Respuesta estructurada: APROBADA")
    print("Comunicacion local: APROBADA")
    print("Servidor temporal detenido: SI")
    print("Operaciones financieras: NO")
    print("Evidencia:", ruta.name)

    print("\nPASO 12.3 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
