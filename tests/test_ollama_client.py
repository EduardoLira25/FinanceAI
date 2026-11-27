import pytest
import requests

from backend.app.services import ollama_client

from backend.app.services.ollama_client import (
    OllamaClient,
    OllamaError,
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION,
    OLLAMA_URL
)


MESSAGES = [
    {
        "role": "user",
        "content": "Prueba FinanceAI"
    }
]

SCHEMA = {
    "type": "object"
}

VERSION = {
    "version": OLLAMA_VERSION
}

TAGS = {
    "models": [
        {
            "name": MODEL,
            "digest": MODEL_DIGEST
        }
    ]
}

VALID_RESPONSE = {
    "model": MODEL,
    "done": True,
    "done_reason": "stop",
    "message": {
        "content": '{"status":"ok"}'
    },
    "prompt_eval_count": 20,
    "eval_count": 8
}


class Response:

    def __init__(self, data=None, status=200):

        self.data = data
        self.status_code = status

    def json(self):

        if isinstance(self.data, Exception):

            raise self.data

        return self.data


@pytest.fixture
def mock_http(monkeypatch):

    cola = []
    llamadas = []

    def request(self, method, url, **kwargs):

        llamadas.append(
            (method, url, kwargs)
        )

        assert url.startswith(
            OLLAMA_URL + "/"
        )

        assert self.trust_env is False

        assert (
            kwargs["allow_redirects"]
            is False
        )

        respuesta = cola.pop(0)

        if isinstance(respuesta, Exception):

            raise respuesta

        return respuesta

    monkeypatch.setattr(
        requests.Session,
        "request",
        request
    )

    monkeypatch.setattr(
        ollama_client.time,
        "sleep",
        lambda segundos: None
    )

    return cola, llamadas


def preparar_chat(cola, respuesta):

    cola.extend([
        Response(VERSION),
        Response(TAGS),
        respuesta,
        Response(VERSION),
        Response(TAGS)
    ])


def test_comunicacion_correcta(mock_http):

    cola, llamadas = mock_http

    preparar_chat(
        cola,
        Response(VALID_RESPONSE)
    )

    with OllamaClient() as cliente:

        resultado = cliente.chat(
            MESSAGES, SCHEMA
        )

    assert resultado["model"] == MODEL
    assert resultado["digest"] == MODEL_DIGEST
    assert resultado["content"] == '{"status":"ok"}'
    assert len(llamadas) == 5

    payload = llamadas[2][2]["json"]

    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["format"] == SCHEMA
    assert payload["options"]["seed"] == 42


def test_digest_incorrecto(mock_http):

    cola, _ = mock_http

    cola.extend([
        Response(VERSION),
        Response({
            "models": [
                {
                    "name": MODEL,
                    "digest": "0" * 64
                }
            ]
        })
    ])

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "MODEL_DIGEST_MISMATCH"


def test_modelo_ausente(mock_http):

    cola, _ = mock_http

    cola.extend([
        Response(VERSION),
        Response({"models": []})
    ])

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "MODEL_NOT_FOUND"


def test_version_diferente(mock_http):

    cola, _ = mock_http

    cola.append(
        Response({"version": "0.0.0"})
    )

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "OLLAMA_VERSION_CHANGED"


def test_recuperacion_get(mock_http):

    cola, llamadas = mock_http

    cola.extend([
        Response(status=503),
        Response(VERSION),
        Response(TAGS)
    ])

    with OllamaClient() as cliente:

        resultado = cliente.verify_model()

    assert resultado["model"] == MODEL
    assert len(llamadas) == 3


def test_timeout_get(mock_http):

    cola, llamadas = mock_http

    cola.extend([
        requests.Timeout(),
        requests.Timeout(),
        requests.Timeout()
    ])

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "OLLAMA_TIMEOUT"
    assert len(llamadas) == 3


def test_timeout_inferencia_sin_repeticion(mock_http):

    cola, llamadas = mock_http

    cola.extend([
        Response(VERSION),
        Response(TAGS),
        requests.Timeout()
    ])

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.chat(MESSAGES, SCHEMA)

    assert error.value.code == "OLLAMA_TIMEOUT"

    assert sum(
        metodo == "POST"
        for metodo, _, _ in llamadas
    ) == 1


def test_limite_solicitudes(mock_http):

    cola, llamadas = mock_http

    cola.append(
        Response(status=429)
    )

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "OLLAMA_RATE_LIMIT"
    assert len(llamadas) == 1


def test_json_http_invalido(mock_http):

    cola, _ = mock_http

    cola.append(
        Response(ValueError("JSON invalido"))
    )

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "INVALID_HTTP_JSON"


@pytest.mark.parametrize("cambios, codigo", [
    (
        {"done": False},
        "INCOMPLETE_RESPONSE"
    ),
    (
        {"done_reason": "length"},
        "INCOMPLETE_RESPONSE"
    ),
    (
        {"model": "otro-modelo"},
        "UNEXPECTED_MODEL"
    ),
    (
        {"message": {"content": ""}},
        "EMPTY_LLM_RESPONSE"
    )
])
def test_respuesta_invalida(
    mock_http, cambios, codigo
):

    cola, _ = mock_http

    preparar_chat(
        cola,
        Response({
            **VALID_RESPONSE,
            **cambios
        })
    )

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.chat(MESSAGES, SCHEMA)

    assert error.value.code == codigo


def test_redireccion_rechazada(mock_http):

    cola, llamadas = mock_http

    cola.append(
        Response(status=302)
    )

    with OllamaClient() as cliente:

        with pytest.raises(OllamaError) as error:

            cliente.verify_model()

    assert error.value.code == "OLLAMA_HTTP_ERROR"
    assert len(llamadas) == 1
