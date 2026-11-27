import json

import httpx

from fastapi import FastAPI, Request

from fastapi.responses import (
    JSONResponse,
    FileResponse,
    Response
)

from fastapi.staticfiles import StaticFiles

from backend.app.core.config import (
    BASE_DIR,
    load_api_key
)


ORIGIN = "http://127.0.0.1:5173"

HOST = "127.0.0.1:5173"

BACKEND = "http://127.0.0.1:8000"

DIST = BASE_DIR / "frontend/dist"

READ_ENDPOINTS = {
    "status": set(),
    "database/status": set(),
    "model/status": set(),
    "portfolio": set(),
    "portfolio/overview": set(),
    "orders/history": {
        "limit", "offset", "side", "status"
    },
    "market/assets": set(),
    "market/latest": {"symbol"},
    "market/candles": {
        "symbol",
        "limit",
        "offset",
        "start_date",
        "end_date"
    },
    "predictions/latest": set(),
    "predictions/history": {"limit", "offset"},
    "agent/status": set(),
    "agent/recovery/status": set(),
    "agent/decisions": {"limit", "offset"},
    "risk/overview": set(),
    "incidents/history": {"limit", "offset", "status"},
    "risk/config": set()
}

CONTROL_ACTIONS = {
    "activate", "pause", "stop", "run", "recover", "reset"
}

CONTROL_PATHS = {
    "/control/agent/" + action
    for action in CONTROL_ACTIONS
}

PAGE_ROUTES = [
    "/",
    "/mercado",
    "/predicciones",
    "/agente",
    "/cartera",
    "/operaciones",
    "/riesgo",
    "/incidentes"
]


def create_app(transport=None):

    app = FastAPI(
        title="FinanceAI Dashboard Gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None
    )

    @app.middleware("http")
    async def security(request: Request, call_next):

        host = request.headers.get("host")

        origin = request.headers.get("origin")

        site = request.headers.get(
            "sec-fetch-site"
        )

        peer = (
            request.client.host
            if request.client
            else None
        )

        if (
            host != HOST
            or peer != "127.0.0.1"
        ):

            response = JSONResponse(
                {"detail": "Host no autorizado."},
                status_code=403
            )

        elif (
            origin not in (None, ORIGIN)
            or site not in (
                None, "none", "same-origin"
            )
        ):

            response = JSONResponse(
                {"detail": "Origen no autorizado."},
                status_code=403
            )

        elif (
            request.method not in ("GET", "HEAD")
            and not (
                request.method == "POST"
                and request.url.path in CONTROL_PATHS
            )
        ):

            response = JSONResponse(
                {"detail": "Metodo no permitido."},
                status_code=405
            )

        else:

            response = await call_next(request)

        response.headers["Cache-Control"] = "no-store"

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

        response.headers[
            "Referrer-Policy"
        ] = "no-referrer"

        response.headers[
            "Content-Security-Policy"
        ] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )

        return response

    @app.get("/bridge/{endpoint:path}")
    async def bridge(endpoint: str, request: Request):

        if endpoint not in READ_ENDPOINTS:

            return JSONResponse(
                {"detail": "Ruta no autorizada."},
                status_code=404
            )

        if request.headers.get(
            "X-FinanceAI-Client"
        ) != "browser":

            return JSONResponse(
                {"detail": "Solicitud no autorizada."},
                status_code=403
            )

        parametros = list(
            request.query_params.multi_items()
        )

        claves = [k for k, _ in parametros]

        if (
            len(claves) != len(set(claves))
            or not set(claves).issubset(
                READ_ENDPOINTS[endpoint]
            )
            or any(
                len(valor) > 100
                for _, valor in parametros
            )
        ):

            return JSONResponse(
                {"detail": "Parametros invalidos."},
                status_code=400
            )

        try:

            api_key = load_api_key()

            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(
                    15.0,
                    connect=3.0
                )
            ) as client:

                respuesta = await client.get(
                    BACKEND + "/api/v1/" + endpoint,
                    params=parametros,
                    headers={
                        "X-API-Key": api_key,
                        "Accept": "application/json"
                    }
                )

        except (httpx.HTTPError, RuntimeError, OSError):

            return JSONResponse(
                {"detail": "Backend no disponible."},
                status_code=503
            )

        if respuesta.status_code != 200:

            status = (
                respuesta.status_code
                if respuesta.status_code in (
                    404, 409, 422, 429, 503
                )
                else 502
            )

            return JSONResponse(
                {"detail": "Consulta no disponible."},
                status_code=status
            )

        if api_key.encode() in respuesta.content:

            return JSONResponse(
                {"detail": "Respuesta bloqueada."},
                status_code=502
            )

        try:

            datos = respuesta.json()

            if not isinstance(datos, (dict, list)):

                raise ValueError()

            return JSONResponse(datos)

        except ValueError:

            return JSONResponse(
                {"detail": "Respuesta invalida."},
                status_code=502
            )


    @app.post("/control/agent/{action}")
    async def control_agent(
        action: str,
        request: Request
    ):

        if action not in CONTROL_ACTIONS:

            return JSONResponse(
                {"detail": "Accion no autorizada."},
                status_code=404
            )

        # Para escrituras el Origin es obligatorio.
        # No basta con que la solicitud sea local.

        if (
            request.headers.get("origin") != ORIGIN
            or request.headers.get(
                "X-FinanceAI-Client"
            ) != "browser"
            or request.headers.get(
                "sec-fetch-site"
            ) not in (None, "same-origin")
        ):

            return JSONResponse(
                {"detail": "Origen no autorizado."},
                status_code=403
            )

        if request.query_params:

            return JSONResponse(
                {"detail": "Parametros no permitidos."},
                status_code=400
            )

        if request.headers.get(
            "content-type", ""
        ).split(";")[0].strip().lower() != "application/json":

            return JSONResponse(
                {"detail": "Formato incompatible."},
                status_code=415
            )

        cuerpo = bytearray()

        async for chunk in request.stream():

            cuerpo.extend(chunk)

            if len(cuerpo) > (
                8192 if action in ("recover", "reset")
                else 512
            ):

                return JSONResponse(
                    {"detail": "Solicitud demasiado grande."},
                    status_code=413
                )

        try:

            datos = json.loads(cuerpo)

        except (ValueError, UnicodeError):

            return JSONResponse(
                {"detail": "JSON invalido."},
                status_code=400
            )

        recovery = action in ("recover", "reset")

        if recovery:

            valido = (
                isinstance(datos, dict)
                and set(datos) == {
                    "confirm", "reason", "incident_ids"
                }
                and datos.get("confirm") == "PAPER_ONLY"
                and isinstance(datos.get("reason"), str)
                and 10 <= len(datos["reason"].strip()) <= 240
                and isinstance(datos.get("incident_ids"), list)
                and len(datos["incident_ids"]) <= 100
                and all(
                    type(i) is int and i > 0
                    for i in datos["incident_ids"]
                )
            )

            if valido:

                ids = datos["incident_ids"]

                valido = (
                    len(set(ids)) == len(ids)
                    and (
                        bool(ids)
                        if action == "recover"
                        else not ids
                    )
                )

        else:

            valido = datos == {"confirm": "PAPER_ONLY"}

        if not valido:

            return JSONResponse(
                {"detail": "Confirmacion requerida."},
                status_code=400
            )

        try:

            key = load_api_key()

            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(
                    240.0 if action == "run" else 15.0,
                    connect=3.0
                )
            ) as client:

                respuesta = await client.post(
                    BACKEND + (
                        "/api/v1/agent/recovery/"
                        if recovery
                        else "/api/v1/agent/control/"
                    ) + action,
                    json=datos,
                    headers={
                        "X-API-Key": key,
                        "Accept": "application/json"
                    }
                )

        except (httpx.HTTPError, RuntimeError, OSError):

            return JSONResponse(
                {"detail": "Resultado no confirmado. Actualizar estado."},
                status_code=503
            )

        if (
            respuesta.status_code != 200
            or key.encode() in respuesta.content
        ):

            return JSONResponse(
                {"detail": "Control no confirmado. Revisar estado."},
                status_code=(
                    respuesta.status_code
                    if respuesta.status_code in (409, 422, 503)
                    else 502
                )
            )

        try:

            datos = respuesta.json()

            if (
                not isinstance(datos, dict)
                or datos.get("real_trading") is not False
            ):

                raise ValueError()

            # Solo devolver el resultado operativo.
            # No reenviar respuestas internas completas.

            return JSONResponse({
                "status": datos["status"],
                "real_trading": False,
                "changed": datos.get("changed"),
                "executed": datos.get("executed"),
                "incident_id": datos.get("incident_id")
            })

        except (ValueError, KeyError):

            return JSONResponse(
                {"detail": "Respuesta incompatible."},
                status_code=502
            )

    async def frontend_page():

        return FileResponse(
            DIST / "index.html",
            media_type="text/html"
        )

    for ruta in PAGE_ROUTES:

        app.add_api_route(
            ruta,
            frontend_page,
            methods=["GET"],
            include_in_schema=False
        )

    app.mount(
        "/assets",
        StaticFiles(directory=DIST / "assets"),
        name="assets"
    )

    return app


app = create_app()
