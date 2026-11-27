import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.main import app

from backend.app.api.prediction_history import (
    prediction_history
)


@pytest.fixture
def escenario(tmp_path):

    ruta = tmp_path / "prediction_history.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    with write_transaction(ruta) as conexion:

        p = conexion.execute("""
            SELECT p.*, c.asset_id
            FROM predictions p
            JOIN candles c ON c.id = p.candle_id
            ORDER BY p.target_open_time DESC
            LIMIT 1
        """).fetchone()

        conexion.execute("""
            INSERT INTO candles (
                asset_id,
                interval_seconds,
                open_time,
                close_time,
                open,
                high,
                low,
                close,
                volume,
                quote_volume,
                source
            )
            VALUES (?, 86400, ?, ?,
                60000, 62000, 59000, 61000,
                100, 6000000, 'TEST')
            ON CONFLICT (
                asset_id,
                interval_seconds,
                open_time
            ) DO NOTHING
        """, (
            p["asset_id"],
            p["target_open_time"],
            p["target_close_time"]
        ))

        return ruta, p["target_close_time"]


def test_no_utilizar_cierre_futuro(escenario):

    ruta, cierre = escenario

    resultado = prediction_history(
        ruta,
        now=cierre - 1
    )

    p = resultado["predictions"][0]

    assert p["observation_status"] == "PENDING"

    assert p["observed_close"] is None

    assert p["absolute_error_pp"] is None


def test_comparacion_cierre_observado(escenario):

    ruta, cierre = escenario

    resultado = prediction_history(
        ruta,
        now=cierre
    )

    p = resultado["predictions"][0]

    assert p["observation_status"] == "OBSERVED"

    assert p["observed_close"] > 0

    esperado = (
        p["observed_close"]
        / p["reference_close"] - 1
    ) * 100

    assert p["observed_return_pct"] == pytest.approx(
        esperado
    )

    assert p["absolute_error_pp"] == pytest.approx(
        abs(esperado - p["predicted_return_pct"])
    )


def test_paginacion(escenario):

    ruta, cierre = escenario

    resultado = prediction_history(
        ruta,
        limit=1,
        now=cierre
    )

    assert len(resultado["predictions"]) == 1

    vacio = prediction_history(
        ruta,
        offset=resultado["total"],
        now=cierre
    )

    assert vacio["predictions"] == []


@pytest.mark.parametrize(
    "autenticado, esperado",
    [(False, 401), (True, 200)]
)
def test_endpoint_autenticado(
    autenticado,
    esperado
):

    async def consultar():

        headers = (
            {"X-API-Key": load_api_key()}
            if autenticado else {}
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=headers
        ) as cliente:

            return await cliente.get(
                "/api/v1/predictions/history"
            )

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == esperado

    if autenticado:

        assert respuesta.json()["real_trading"] is False

        assert load_api_key() not in respuesta.text
