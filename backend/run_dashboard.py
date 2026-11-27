import sys
import json
import time
import socket
import subprocess

from contextlib import ExitStack

from datetime import datetime, timezone

import httpx

from backend.app.core.config import (
    BASE_DIR,
    load_api_key
)

from backend.app.services.llm_decision import (
    database_hash,
    model_hashes
)

from backend.app.dashboard_gateway import READ_ENDPOINTS


def main():

    db_antes = database_hash()

    modelo_antes = model_hashes()

    procesos = []

    for puerto in (8000, 5173):

        with socket.socket() as prueba:

            prueba.settimeout(1)

            if prueba.connect_ex(
                ("127.0.0.1", puerto)
            ) == 0:

                raise RuntimeError(
                    f"Puerto {puerto} ocupado. "
                    "Deten el servidor anterior."
                )

    with ExitStack() as recursos:

        client = recursos.enter_context(
            httpx.Client(
                trust_env=False,
                timeout=15,
                follow_redirects=False
            )
        )

        def detener():

            for proceso in reversed(procesos):

                if proceso.poll() is None:

                    proceso.terminate()

                    try:

                        proceso.wait(timeout=10)

                    except subprocess.TimeoutExpired:

                        proceso.kill()
                        proceso.wait()

        recursos.callback(detener)

        configuraciones = [
            (
                "backend.app.main:app",
                8000,
                "dashboard_fastapi.log"
            ),
            (
                "backend.app.dashboard_gateway:app",
                5173,
                "dashboard_gateway.log"
            )
        ]

        for modulo, puerto, nombre in configuraciones:

            log = recursos.enter_context(
                (
                    BASE_DIR / "results" / nombre
                ).open("w", encoding="utf-8")
            )

            proceso = subprocess.Popen(
                [
                    sys.executable,
                    "-m", "uvicorn",
                    modulo,
                    "--host", "127.0.0.1",
                    "--port", str(puerto),
                    "--no-proxy-headers"
                ],
                cwd=BASE_DIR,
                stdout=log,
                stderr=subprocess.STDOUT
            )

            procesos.append(proceso)

        for puerto, ruta in [
            (8000, "/health"),
            (5173, "/")
        ]:

            disponible = False

            for intento in range(60):

                if any(
                    p.poll() is not None
                    for p in procesos
                ):

                    raise RuntimeError(
                        "Un servidor se detuvo. "
                        "Revisar logs en results."
                    )

                try:

                    respuesta = client.get(
                        f"http://127.0.0.1:{puerto}{ruta}",
                        timeout=2
                    )

                    if respuesta.status_code == 200:

                        disponible = True

                        break

                except httpx.RequestError:

                    pass

                time.sleep(0.5)

            assert disponible, (
                f"Servidor {puerto} no disponible."
            )

            print("Servidor", puerto, ": DISPONIBLE")

        # Comprobar que el backend conserva
        # su autenticacion original.

        respuesta = client.get(
            "http://127.0.0.1:8000/api/v1/status"
        )

        assert respuesta.status_code == 401

        print("FastAPI sin clave: BLOQUEADO")

        headers = {
            "X-FinanceAI-Client": "browser"
        }

        controles = {}

        base_url = "http://127.0.0.1:5173"

        clave = load_api_key().encode()

        # Verificar todas las consultas permitidas.

        for endpoint in READ_ENDPOINTS:

            params = (
                {"limit": 1}
                if endpoint == "market/candles"
                else {}
            )

            respuesta = client.get(
                base_url + "/bridge/" + endpoint,
                headers=headers,
                params=params
            )

            assert respuesta.status_code == 200, (
                endpoint,
                respuesta.status_code
            )

            assert clave not in respuesta.content

            respuesta.json()

            controles[endpoint] = True

            print(endpoint + ": APROBADO")

        assert client.post(
            base_url + "/bridge/predictions/generate",
            headers=headers
        ).status_code == 405

        assert client.get(
            base_url + "/bridge/status",
            headers={
                **headers,
                "Origin": "https://example.com"
            }
        ).status_code == 403

        assert database_hash() == db_antes

        assert model_hashes() == modelo_antes

        evidencia = {
            "Proyecto": "FinanceAI",
            "Etapa": "13.3",
            "Fecha_UTC": datetime.now(
                timezone.utc
            ).isoformat(),
            "Resultado": "APROBADO",
            "Endpoints_lectura": controles,
            "Endpoints_aprobados": len(controles),
            "Backend_autenticado": True,
            "Intermediario_local": True,
            "Operaciones_escritura_bloqueadas": True,
            "Origen_externo_bloqueado": True,
            "Credenciales_expuestas": False,
            "Base_principal_intacta": True,
            "Modelo_LSTM_intacto": True,
            "Dinero_real_utilizado": False
        }

        ruta = (
            BASE_DIR /
            "results/control_conexion_frontend.json"
        )

        ruta.write_text(
            json.dumps(
                evidencia,
                indent=4,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

        print("\n" + "=" * 60)
        print("FINANCEAI - CONEXION SEGURA APROBADA")
        print("=" * 60)

        print("FastAPI: CONECTADO")
        print("React: DISPONIBLE")
        print("Endpoints de lectura:", len(controles))
        print("Credenciales expuestas: NO")
        print("Base principal intacta: SI")
        print("Modelo LSTM intacto: SI")
        print("Operaciones financieras: NO")
        print("Evidencia:", ruta.name)

        print("\nPASO 13.3 COMPLETADO CORRECTAMENTE")

        print("\nAbre http://127.0.0.1:5173")
        print("Presiona Control+C para detener ambos servidores.")

        try:

            while True:

                if any(
                    p.poll() is not None
                    for p in procesos
                ):

                    raise RuntimeError(
                        "Un servidor se detuvo."
                    )

                time.sleep(1)

        except KeyboardInterrupt:

            print("\nDeteniendo FinanceAI...")


if __name__ == "__main__":
    main()
