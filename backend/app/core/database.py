import sqlite3

from pathlib import Path
from contextlib import contextmanager

from .config import DATABASE_PATH

BUSY_TIMEOUT_MS = 5000
SCHEMA_VERSION = 1


def _connect(path=DATABASE_PATH, readonly=True):

    ruta = Path(path).resolve()

    if not ruta.is_file():

        raise FileNotFoundError(
            "Base de datos no disponible."
        )

    mode = "ro" if readonly else "rw"

    conexion = sqlite3.connect(
        ruta.as_uri() + f"?mode={mode}",
        uri=True,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None
    )

    try:

        conexion.row_factory = sqlite3.Row

        conexion.execute("PRAGMA foreign_keys = ON")

        conexion.execute(
            f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}"
        )

        version = conexion.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        if version != SCHEMA_VERSION:

            raise RuntimeError(
                "Version de esquema incompatible."
            )

        if readonly:

            conexion.execute("PRAGMA query_only = ON")

        else:

            conexion.execute("PRAGMA synchronous = FULL")

        return conexion

    except BaseException:

        conexion.close()
        raise


@contextmanager
def read_connection(path=DATABASE_PATH):

    conexion = _connect(
        path,
        readonly=True
    )

    try:

        conexion.execute("BEGIN")

        yield conexion

    finally:

        try:

            if conexion.in_transaction:
                conexion.rollback()

        finally:

            conexion.close()


@contextmanager
def write_transaction(path=DATABASE_PATH):

    conexion = _connect(
        path,
        readonly=False
    )

    try:

        conexion.execute("BEGIN IMMEDIATE")

        yield conexion

        conexion.commit()

    except BaseException:

        if conexion.in_transaction:
            conexion.rollback()

        raise

    finally:

        conexion.close()


def database_status(path=DATABASE_PATH):

    with read_connection(path) as conexion:

        version = conexion.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        journal = conexion.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]

        foreign_keys = conexion.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        tablas = conexion.execute("""
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
        """).fetchone()[0]

        velas = conexion.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0]

        return {
            "status": "ok",
            "schema_version": version,
            "journal_mode": journal,
            "foreign_keys": bool(foreign_keys),
            "tables": tablas,
            "historical_candles": velas
        }
