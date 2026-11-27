import os
import json
import time
import socket
import shutil
import hashlib
import subprocess

from datetime import datetime, timedelta, timezone
from typing import Literal

import requests

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator
)

from backend.app.core.config import (
    BASE_DIR,
    MODEL_PATH
)

from backend.app.core.database import read_connection

from backend.app.services.financial_prompt import (
    FinancialContext,
    build_messages,
    build_context_data,
    synthetic_context,
    prompt_sha256,
    PROMPT_VERSION
)

from backend.app.services.ollama_client import (
    OllamaClient,
    OllamaError,
    OLLAMA_URL
)


class DecisionError(RuntimeError):

    def __init__(self, code, message):

        self.code = code

        super().__init__(message)


# 2. Definir esquema estricto de respuesta

class LLMDecision(BaseModel):

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True
    )

    action: Literal["BUY", "HOLD", "SELL"]

    symbol: Literal["BTCUSDT"]

    candle_date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        min_length=10,
        max_length=10
    )

    rationale: str = Field(
        min_length=1,
        max_length=240
    )

    @field_validator("rationale")
    @classmethod
    def validar_justificacion(cls, valor):

        if not valor.strip():

            raise ValueError(
                "Justificacion vacia."
            )

        if any(
            ord(c) < 32 or ord(c) == 127
            for c in valor
        ):

            raise ValueError(
                "Caracteres de control no permitidos."
            )

        return valor.strip()


# 3. Rechazar campos JSON duplicados

def reject_duplicate_keys(pairs):

    resultado = {}

    for clave, valor in pairs:

        if clave in resultado:

            raise DecisionError(
                "DUPLICATE_JSON_KEY",
                "Campo JSON duplicado."
            )

        resultado[clave] = valor

    return resultado


def reject_constant(valor):

    raise DecisionError(
        "INVALID_JSON_CONSTANT",
        "Constante JSON no permitida."
    )


# 4. Validar estructura y contenido

def validate_decision(raw, context):

    if not isinstance(context, FinancialContext):

        raise DecisionError(
            "INVALID_CONTEXT",
            "Contexto financiero invalido."
        )

    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > 4096
    ):

        raise DecisionError(
            "INVALID_RAW_RESPONSE",
            "Respuesta vacia o demasiado extensa."
        )

    try:

        datos = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant
        )

    except json.JSONDecodeError:

        raise DecisionError(
            "INVALID_DECISION_JSON",
            "Respuesta financiera no es JSON valido."
        ) from None

    try:

        decision = LLMDecision.model_validate(
            datos
        )

    except ValidationError:

        raise DecisionError(
            "INVALID_DECISION_SCHEMA",
            "Respuesta incompatible con el esquema."
        ) from None

    if decision.symbol != context.symbol:

        raise DecisionError(
            "SYMBOL_MISMATCH",
            "Simbolo diferente al contexto."
        )

    if (
        decision.candle_date
        != context.candle_date.isoformat()
    ):

        raise DecisionError(
            "CANDLE_DATE_MISMATCH",
            "Fecha diferente a la vela analizada."
        )

    datos_contexto = build_context_data(context)

    # 5. Validar coherencia financiera

    if decision.action != "HOLD":

        if context.portfolio_status != "ACTIVE":

            raise DecisionError(
                "PORTFOLIO_NOT_ACTIVE",
                "La cartera no esta activa."
            )

        if context.emergency_stop:

            raise DecisionError(
                "EMERGENCY_STOP",
                "Paro de emergencia activado."
            )

        if datos_contexto["risk"]["data_is_stale"]:

            raise DecisionError(
                "STALE_CANDLE",
                "Datos financieros antiguos."
            )

    if (
        decision.action == "BUY"
        and context.cash_micros <= 0
    ):

        raise DecisionError(
            "INSUFFICIENT_CASH",
            "No existe efectivo disponible."
        )

    if (
        decision.action == "SELL"
        and context.quantity_sats <= 0
    ):

        raise DecisionError(
            "NO_POSITION_TO_SELL",
            "No existe Bitcoin disponible."
        )

    return decision


# 6. Solicitar propuesta al modelo local

def request_decision(context, client):

    if not isinstance(context, FinancialContext):

        raise DecisionError(
            "INVALID_CONTEXT",
            "Contexto financiero invalido."
        )

    inicio = time.perf_counter()

    respuesta = client.chat(
        messages=build_messages(context),
        schema=LLMDecision.model_json_schema()
    )

    decision = validate_decision(
        respuesta["content"],
        context
    )

    total_ms = (
        time.perf_counter() - inicio
    ) * 1000

    return {
        "decision": decision.model_dump(),
        "raw_response": respuesta["content"],
        "llm_model": respuesta["model"],
        "llm_digest": respuesta["digest"],
        "ollama_version": respuesta["ollama_version"],
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(),
        "latency_ms": respuesta["latency_ms"],
        "total_latency_ms": round(total_ms, 3),
        "prompt_tokens": respuesta.get("prompt_tokens"),
        "output_tokens": respuesta.get("output_tokens"),
        "validation_status": "VALID",
        "risk_authorized": False,
        "executed": False,
        "real_trading": False
    }


# 7. Verificar que las pruebas no alteren originales

def database_hash():

    with read_connection() as conexion:

        contenido = "\n".join(
            conexion.iterdump()
        )

    return hashlib.sha256(
        contenido.encode()
    ).hexdigest()


def model_hashes():

    return {
        archivo.name: hashlib.sha256(
            archivo.read_bytes()
        ).hexdigest()
        for archivo in MODEL_PATH.iterdir()
        if archivo.is_file()
    }


# 8. Diagnostico financiero con Ollama

def main():

    print("=" * 60)
    print("FINANCEAI - VALIDACION DE DECISIONES LLM")
    print("=" * 60)

    db_antes = database_hash()
    modelo_antes = model_hashes()

    assert len(modelo_antes) == 10

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

    # Escenario A:
    # Pronostico positivo, cartera activa.

    activo = synthetic_context()

    # Escenario B:
    # Pronostico positivo, cartera pausada
    # y datos antiguos.

    datos_pausado = activo.model_dump()

    datos_pausado.update({
        "portfolio_status": "PAUSED",
        "as_of_utc": (
            activo.candle_close
            + timedelta(hours=14)
        )
    })

    pausado = FinancialContext.model_validate(
        datos_pausado
    )

    escenarios = [
        ("A_CARTERA_ACTIVA", activo),
        ("B_CARTERA_PAUSADA", pausado)
    ]

    resultados = []

    ruta_log = (
        BASE_DIR /
        "results/ollama_decisiones.log"
    )

    with ruta_log.open(
        "w",
        encoding="utf-8"
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

            print("Servidor Ollama: DISPONIBLE")

            with OllamaClient() as cliente:

                identidad = cliente.verify_model()

                print("Modelo:", identidad["model"])

                for nombre, contexto in escenarios:

                    print(
                        "\nESCENARIO:", nombre,
                        flush=True
                    )

                    registro = {
                        "scenario": nombre,
                        "context": build_context_data(
                            contexto
                        )
                    }

                    try:

                        resultado = request_decision(
                            contexto,
                            cliente
                        )

                        registro.update({
                            "approved": True,
                            "result": resultado
                        })

                        print(json.dumps(
                            resultado["decision"],
                            indent=4,
                            ensure_ascii=False
                        ))

                        print(
                            "Latencia:",
                            resultado["latency_ms"],
                            "ms"
                        )

                        print(
                            "Validacion JSON: APROBADA"
                        )

                        print(
                            "Validacion contextual: APROBADA"
                        )

                    except (
                        DecisionError,
                        OllamaError
                    ) as error:

                        registro.update({
                            "approved": False,
                            "error_code": error.code,
                            "error_message": str(error),
                            "execution_blocked": True
                        })

                        print(
                            "Propuesta bloqueada:",
                            error.code
                        )

                    resultados.append(registro)

        finally:

            if servidor.poll() is None:

                servidor.terminate()

                try:

                    servidor.wait(timeout=15)

                except subprocess.TimeoutExpired:

                    servidor.kill()
                    servidor.wait()

            print("\nServidor temporal detenido.")

    # 9. Confirmar integridad

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    aprobadas = sum(
        registro["approved"]
        for registro in resultados
    )

    correcto = (
        len(resultados) == 2
        and aprobadas == 2
        and resultados[1]["result"]["decision"]["action"]
            == "HOLD"
    )

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.5",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": (
            "APROBADO" if correcto else "REVISAR"
        ),
        "Modelo": identidad,
        "Prompt_version": PROMPT_VERSION,
        "Prompt_SHA256": prompt_sha256(),
        "Escenarios": resultados,
        "Inferencias_aprobadas": aprobadas,
        "Base_datos_intacta": True,
        "Modelo_LSTM_intacto": True,
        "Datos_sinteticos": True,
        "TE_reevaluado": False,
        "Operaciones_financieras": False
    }

    ruta = (
        BASE_DIR /
        "results/control_validacion_llm.json"
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
    print("FINANCEAI - RESULTADO VALIDACION LLM")
    print("=" * 60)

    print("Inferencias aprobadas:", aprobadas, "/ 2")
    print("Base de datos intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Datos utilizados: SINTETICOS")
    print("TE reevaluado: NO")
    print("Operaciones financieras: NO")
    print("Evidencia:", ruta.name)

    if not correcto:

        print("\nDIAGNOSTICO PENDIENTE DE REVISION")

        raise SystemExit(1)

    print("Validador financiero: FUNCIONAL")
    print("Restricciones contextuales: APROBADAS")
    print("Cartera pausada: HOLD")
    print("\nPASO 12.5 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
