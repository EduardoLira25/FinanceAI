import sqlite3
import hashlib

import pytest

from backend.app.core.config import (
    DATABASE_PATH,
    MODEL_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction,
    database_status
)


def huella_logica(conexion):

    contenido = "\n".join(
        conexion.iterdump()
    )

    return hashlib.sha256(
        contenido.encode("utf-8")
    ).hexdigest()


@pytest.fixture
def db_temporal(tmp_path):

    destino = tmp_path / "financeai_test.db"

    with read_connection() as original:

        copia = sqlite3.connect(destino)

        try:

            original.backup(copia)

            assert (
                huella_logica(original)
                == huella_logica(copia)
            )

        finally:

            copia.close()

    return destino


@pytest.fixture(scope="module", autouse=True)
def proteger_originales():

    with read_connection() as conexion:

        huella_antes = huella_logica(conexion)

    modelos = {
        ruta: hashlib.sha256(
            ruta.read_bytes()
        ).hexdigest()
        for ruta in MODEL_PATH.iterdir()
        if ruta.is_file()
    }

    yield

    with read_connection() as conexion:

        assert (
            huella_logica(conexion)
            == huella_antes
        )

    for ruta, huella in modelos.items():

        assert hashlib.sha256(
            ruta.read_bytes()
        ).hexdigest() == huella


def test_conexion_base_original():

    with read_connection() as conexion:

        resultado = conexion.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0]

        assert resultado >= 2520


def test_resultados_con_nombre_de_columna():

    with read_connection() as conexion:

        fila = conexion.execute("""
            SELECT symbol, exchange
            FROM assets
            WHERE symbol = 'BTCUSDT'
        """).fetchone()

        assert fila["symbol"] == "BTCUSDT"
        assert fila["exchange"] == "MEXC"


def test_lectura_sin_escritura(db_temporal):

    with read_connection(db_temporal) as conexion:

        with pytest.raises(sqlite3.OperationalError):

            conexion.execute("""
                UPDATE portfolio SET cash_micros = 0
            """)


def test_llaves_foraneas_lectura():

    with read_connection() as conexion:

        assert conexion.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0] == 1


def test_llaves_foraneas_escritura(db_temporal):

    with write_transaction(db_temporal) as conexion:

        assert conexion.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0] == 1


def test_confirmacion_transaccion(db_temporal):

    with write_transaction(db_temporal) as conexion:

        identificador = conexion.execute("""
            INSERT INTO system_logs (
                level, component, message
            )
            VALUES ('INFO', 'TEST', 'Prueba de commit')
        """).lastrowid

    with read_connection(db_temporal) as conexion:

        fila = conexion.execute("""
            SELECT message FROM system_logs
            WHERE id = ?
        """, (identificador,)).fetchone()

        assert fila["message"] == "Prueba de commit"


def test_reversion_transaccion(db_temporal):

    with read_connection(db_temporal) as conexion:

        antes = huella_logica(conexion)

    with pytest.raises(RuntimeError):

        with write_transaction(db_temporal) as conexion:

            conexion.execute("""
                UPDATE portfolio SET cash_micros = 0
            """)

            raise RuntimeError("Error controlado")

    with read_connection(db_temporal) as conexion:

        assert huella_logica(conexion) == antes


def test_reversion_por_restriccion(db_temporal):

    with read_connection(db_temporal) as conexion:

        antes = huella_logica(conexion)

    with pytest.raises(sqlite3.IntegrityError):

        with write_transaction(db_temporal) as conexion:

            conexion.execute("""
                INSERT INTO system_logs (
                    level, component, message
                )
                VALUES ('INFO', 'TEST', 'Registro temporal')
            """)

            conexion.execute("""
                UPDATE portfolio SET cash_micros = -1
            """)

    with read_connection(db_temporal) as conexion:

        assert huella_logica(conexion) == antes


def test_cierre_automatico_lectura():

    with read_connection() as conexion:

        conexion.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):

        conexion.execute("SELECT 1")


def test_cierre_automatico_escritura(db_temporal):

    with write_transaction(db_temporal) as conexion:

        conexion.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):

        conexion.execute("SELECT 1")


def test_base_inexistente(tmp_path):

    ruta = tmp_path / "inexistente.db"

    with pytest.raises(FileNotFoundError):

        with read_connection(ruta):
            pass

    with pytest.raises(FileNotFoundError):

        with write_transaction(ruta):
            pass

    assert not ruta.exists()


def test_version_incompatible(db_temporal):

    conexion = sqlite3.connect(db_temporal)

    try:

        conexion.execute("PRAGMA user_version = 999")

    finally:

        conexion.close()

    with pytest.raises(RuntimeError):

        with read_connection(db_temporal):
            pass


def test_tiempo_espera():

    with read_connection() as conexion:

        assert conexion.execute(
            "PRAGMA busy_timeout"
        ).fetchone()[0] == 5000


def test_estado_database():

    estado = database_status()

    assert estado["status"] == "ok"
    assert estado["schema_version"] == 1
    assert estado["journal_mode"] == "wal"
    assert estado["foreign_keys"] is True
    assert estado["tables"] == 13
    assert estado["historical_candles"] >= 2520
