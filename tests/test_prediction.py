import asyncio
import sqlite3

import numpy as np
import pytest
import httpx

from backend.app.main import app

from backend.app.core.database import read_connection

from backend.app.services.prediction import (
    DAY,
    PredictionError,
    verify_artifacts,
    build_features,
    validate_window,
    generate_prediction,
    latest_prediction
)


def test_integridad_modelo():

    manifiesto = verify_artifacts()

    assert manifiesto["Parametros"] == 1425

    assert manifiesto["Modelo_ID"] == "TEC_B_LSTM_S42"


def test_forma_ventana():

    closes = np.linspace(50000, 60000, 40)

    features = build_features(closes)

    assert features.shape == (20, 3)
    assert np.isfinite(features).all()


def test_indicadores():

    closes = np.linspace(50000, 60000, 40)

    features = build_features(closes)

    retornos = closes[1:] / closes[:-1] - 1

    assert np.isclose(
        features[-1, 0],
        retornos[-1]
    )

    assert np.isclose(
        features[-1, 1],
        closes[-1] / closes[-20:].mean() - 1
    )

    assert np.isclose(
        features[-1, 2],
        retornos[-20:].std(ddof=1)
    )


def test_historial_insuficiente():

    with pytest.raises(PredictionError):

        build_features(np.ones(39))


@pytest.mark.parametrize("valor", [
    -1, 0, np.nan, np.inf
])
def test_precio_invalido(valor):

    closes = np.ones(40)

    closes[-1] = valor

    with pytest.raises(PredictionError):

        build_features(closes)


def historial():

    return [
        {
            "open_time": i * DAY,
            "close_time": (i + 1) * DAY
        }
        for i in range(40)
    ]


def test_vela_abierta():

    with pytest.raises(PredictionError):

        validate_window(
            historial(),
            40 * DAY - 1
        )


def test_historial_discontinuo():

    filas = historial()

    filas[10]["open_time"] += DAY
    filas[10]["close_time"] += DAY

    with pytest.raises(PredictionError):

        validate_window(filas, 40 * DAY)


def test_objetivo_vencido():

    with pytest.raises(PredictionError):

        validate_window(
            historial(),
            41 * DAY
        )


@pytest.fixture
def db_temporal(tmp_path):

    ruta = tmp_path / "predictions_test.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    with sqlite3.connect(ruta) as conexion:

        conexion.execute(
            "DELETE FROM predictions"
        )

    return ruta


def test_persistencia_idempotencia(db_temporal):

    with read_connection(db_temporal) as conexion:

        cierre = conexion.execute("""
            SELECT MAX(close_time)
            FROM candles
        """).fetchone()[0]

    llamadas = []

    def inferencia(features):

        llamadas.append(1)

        assert features.shape == (20, 3)

        return 0.002

    primero = generate_prediction(
        db_temporal,
        clock=lambda: cierre + 100,
        inference=inferencia
    )

    segundo = generate_prediction(
        db_temporal,
        clock=lambda: cierre + 100,
        inference=inferencia
    )

    assert primero["created"] is True
    assert segundo["created"] is False
    assert primero["id"] == segundo["id"]
    assert len(llamadas) == 1

    guardada = latest_prediction(db_temporal)

    assert guardada["id"] == primero["id"]

    assert np.isclose(
        guardada["predicted_price"],
        guardada["reference_close"] * 1.002
    )

    with read_connection(db_temporal) as conexion:

        assert conexion.execute(
            "SELECT COUNT(*) FROM predictions"
        ).fetchone()[0] == 1

        assert conexion.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


@pytest.mark.parametrize("metodo, ruta", [
    ("GET", "/api/v1/predictions/latest"),
    ("POST", "/api/v1/predictions/generate")
])
def test_autenticacion(metodo, ruta):

    async def ejecutar():

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver"
        ) as cliente:

            return await cliente.request(
                metodo,
                ruta
            )

    respuesta = asyncio.run(ejecutar())

    assert respuesta.status_code == 401
