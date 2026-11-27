import sqlite3
import pytest
import requests

from backend.app.core.database import read_connection

from backend.app.services import mexc

from backend.app.services.mexc import (
    DAY,
    DAY_MS,
    MarketDataError,
    normalize_candles,
    synchronize,
    latest_stored,
    get_server_time
)


def vela(t):

    return [
        t,
        "60000",
        "61000",
        "59000",
        "60500",
        "100",
        t + DAY_MS,
        "6050000"
    ]


def test_vela_valida():

    resultado = normalize_candles(
        [vela(0)],
        DAY_MS
    )

    assert len(resultado) == 1
    assert resultado[0][5] == 60500


def test_vela_abierta_descartada():

    assert normalize_candles(
        [vela(0)],
        DAY_MS - 1
    ) == []


def test_vela_duplicada_identica():

    assert len(normalize_candles(
        [vela(0), vela(0)],
        DAY_MS
    )) == 1


def test_duplicado_inconsistente():

    otra = vela(0)
    otra[4] = "60100"

    with pytest.raises(MarketDataError):

        normalize_candles(
            [vela(0), otra],
            DAY_MS
        )


@pytest.mark.parametrize("indice, valor", [
    (1, "-1"),
    (2, "100"),
    (4, "NaN"),
    (5, "-100"),
    (6, 123),
    (7, "inf")
])
def test_valores_invalidos(indice, valor):

    fila = vela(0)
    fila[indice] = valor

    with pytest.raises(MarketDataError):

        normalize_candles([fila], DAY_MS)


def test_json_invalido():

    with pytest.raises(MarketDataError):

        normalize_candles(
            {"code": 500},
            DAY_MS
        )


def test_cierre_menos_un_milisegundo():

    fila = vela(0)
    fila[6] = DAY_MS - 1

    resultado = normalize_candles(
        [fila],
        DAY_MS
    )

    assert resultado[0][1] == DAY


def test_hora_invalida():

    with pytest.raises(MarketDataError):

        get_server_time(
            lambda path: {"serverTime": "incorrecto"}
        )


@pytest.fixture
def db_temporal(tmp_path):

    ruta = tmp_path / "test_mexc.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def contar(ruta):

    with read_connection(ruta) as conexion:

        return conexion.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0]


def test_sincronizacion_e_idempotencia(db_temporal):

    inicio = (
        latest_stored(db_temporal)["close_time"]
        * 1000
    )

    def fetch(path, params=None):

        if path == "/api/v3/time":

            return {
                "serverTime": inicio + DAY_MS
            }

        return [
            vela(inicio),
            vela(inicio + DAY_MS)
        ]

    antes = contar(db_temporal)

    resultado = synchronize(
        db_temporal,
        fetch
    )

    assert resultado["new_candles"] == 1
    assert contar(db_temporal) == antes + 1

    segundo = synchronize(
        db_temporal,
        fetch
    )

    assert segundo["new_candles"] == 0
    assert contar(db_temporal) == antes + 1


def test_historial_incompleto(db_temporal):

    inicio = (
        latest_stored(db_temporal)["close_time"]
        * 1000
    )

    def fetch(path, params=None):

        if path == "/api/v3/time":
            return {
                "serverTime": inicio + 2 * DAY_MS
            }

        return [vela(inicio)]

    antes = contar(db_temporal)

    with pytest.raises(MarketDataError):

        synchronize(db_temporal, fetch)

    assert contar(db_temporal) == antes


def test_limite_solicitudes(monkeypatch):

    intentos = []

    class Respuesta:
        status_code = 429

    def fake_get(*args, **kwargs):

        intentos.append(1)

        return Respuesta()

    monkeypatch.setattr(
        mexc.requests, "get", fake_get
    )

    with pytest.raises(MarketDataError):

        mexc.request_json("/api/v3/time")

    assert len(intentos) == 1


def test_timeout_reintentos_limitados(monkeypatch):

    intentos = []

    def fake_get(*args, **kwargs):

        intentos.append(1)

        raise requests.Timeout()

    monkeypatch.setattr(
        mexc.requests, "get", fake_get
    )

    monkeypatch.setattr(
        mexc.time, "sleep", lambda x: None
    )

    with pytest.raises(MarketDataError):

        mexc.request_json("/api/v3/time")

    assert len(intentos) == 3


def test_endpoint_no_autorizado():

    with pytest.raises(MarketDataError):

        mexc.request_json("/api/v3/order")
