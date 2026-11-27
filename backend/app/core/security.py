import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from .config import load_api_key

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False
)


def verify_api_key(
    supplied_key: str | None = Security(api_key_header)
):

    try:

        expected_key = load_api_key()

    except RuntimeError:

        raise HTTPException(
            status_code=503,
            detail="Servicio no disponible."
        )

    if not supplied_key:

        raise HTTPException(
            status_code=401,
            detail="Autenticacion requerida."
        )

    if not secrets.compare_digest(
        supplied_key.encode("utf-8"),
        expected_key.encode("utf-8")
    ):

        raise HTTPException(
            status_code=401,
            detail="Credenciales invalidas."
        )

    return True
