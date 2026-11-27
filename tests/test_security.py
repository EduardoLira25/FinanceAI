import asyncio
import secrets
import stat

import httpx
import pytest

from fastapi import FastAPI, Depends

from backend.app.core.config import (
    load_api_key,
    ENV_FILE
)

from backend.app.core.security import verify_api_key

app = FastAPI()


@app.get("/private")
def private(
    authorized: bool = Depends(verify_api_key)
):

    return {
        "authorized": authorized,
        "mode": "paper_trading"
    }


def request_private(key=None):

    async def ejecutar():

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver"
        ) as client:

            headers = {}

            if key is not None:
                headers["X-API-Key"] = key

            return await client.get(
                "/private",
                headers=headers
            )

    return asyncio.run(ejecutar())


def test_clave_correcta():

    respuesta = request_private(load_api_key())

    assert respuesta.status_code == 200
    assert respuesta.json()["authorized"] is True


def test_clave_incorrecta():

    incorrecta = secrets.token_hex(32)

    respuesta = request_private(incorrecta)

    assert respuesta.status_code == 401


def test_clave_ausente():

    assert request_private().status_code == 401


def test_clave_vacia():

    assert request_private("").status_code == 401


def test_clave_incompleta():

    assert request_private("123").status_code == 401


def test_clave_modificada():

    clave = load_api_key()

    ultimo = "0" if clave[-1] != "0" else "1"

    modificada = clave[:-1] + ultimo

    assert request_private(modificada).status_code == 401


def test_configuracion_ausente(tmp_path):

    with pytest.raises(RuntimeError):

        load_api_key(tmp_path / ".env")


def test_configuracion_invalida(tmp_path):

    ruta = tmp_path / ".env"

    ruta.write_text(
        "FINANCEAI_API_KEY=123",
        encoding="utf-8"
    )

    with pytest.raises(RuntimeError):

        load_api_key(ruta)


def test_permisos_archivo_privado():

    permisos = stat.S_IMODE(
        ENV_FILE.stat().st_mode
    )

    assert permisos == 0o600


def test_plantilla_sin_clave_privada():

    plantilla = (
        ENV_FILE.parent / ".env.example"
    ).read_text()

    assert load_api_key() not in plantilla


def test_clave_no_expuesta_en_respuesta():

    clave = load_api_key()

    respuesta = request_private(clave)

    assert clave not in respuesta.text
    assert clave not in str(respuesta.headers)
