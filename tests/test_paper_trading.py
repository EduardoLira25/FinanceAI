import sqlite3
import hashlib

import pytest

from backend.app.core.config import (
    BASE_DIR,
    MODEL_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services import paper_trading

from backend.app.services.paper_trading import (
    execute_replay_cycle,
    PaperTradingError
)

from backend.app.services.risk import (
    MICROS,
    DAY
)


@pytest.fixture(scope="module", autouse=True)
def proteger_originales():

    with read_connection() as conexion:

        antes = list(conexion.iterdump())

    hashes = {
        archivo: hashlib.sha256(
            archivo.read_bytes()
        ).hexdigest()
        for archivo in MODEL_PATH.iterdir()
        if archivo.is_file()
    }

    yield

    with read_connection() as conexion:

        assert list(conexion.iterdump()) == antes

    for archivo, huella in hashes.items():

        assert hashlib.sha256(
            archivo.read_bytes()
        ).hexdigest() == huella


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "paper_test.db"

    conexion = sqlite3.connect(ruta)

    try:

        esquema = (
            BASE_DIR / "database/schema.sql"
        ).read_text()

        conexion.executescript(esquema)

        conexion.execute("PRAGMA user_version = 1")

        conexion.execute("""
            INSERT INTO assets (
                id, symbol, base_currency,
                quote_currency, exchange
            )
            VALUES (
                1, 'BTCUSDT', 'BTC', 'USDT', 'MEXC'
            )
        """)

        conexion.execute("""
            INSERT INTO model_versions (
                version,
                architecture,
                window_size,
                feature_count,
                model_path,
                model_sha256
            )
            VALUES (
                '1.0.0', 'LSTM', 20, 3,
                'synthetic-test', ?
            )
        """, ("0" * 64,))

        # Velas sinteticas independientes del
        # entrenamiento y de la evaluacion TE.

        inicio = DAY * 18000

        precios = [
            (50000, 50000),
            (50000, 55000),
            (55000, 55000),
            (55000, 55000),
            (55000, 55000)
        ]

        for i, (apertura, cierre) in enumerate(precios):

            t = inicio + i * DAY

            conexion.execute("""
                INSERT INTO candles (
                    id,
                    asset_id,
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
                VALUES (
                    ?, 1, ?, ?, ?, ?, ?, ?,
                    100, 5000000, 'TEST'
                )
            """, (
                i + 1,
                t,
                t + DAY,
                apertura,
                max(apertura, cierre),
                min(apertura, cierre),
                cierre
            ))

            conexion.execute("""
                INSERT INTO predictions (
                    id,
                    candle_id,
                    model_version,
                    predicted_return,
                    predicted_price,
                    emission_time,
                    target_open_time,
                    target_close_time
                )
                VALUES (
                    ?, ?, '1.0.0', 0.002,
                    ?, ?, ?, ?
                )
            """, (
                i + 1,
                i + 1,
                cierre * 1.002,
                t + DAY,
                t + DAY,
                t + 2 * DAY
            ))

        conexion.execute("""
            INSERT INTO portfolio (
                id,
                name,
                mode,
                strategy,
                currency,
                initial_cash_micros,
                cash_micros,
                status
            )
            VALUES (
                1,
                'TEST_REPLAY',
                'REPLAY',
                'MODEL_ONLY',
                'USDT',
                ?, ?,
                'ACTIVE'
            )
        """, (
            50000 * MICROS,
            50000 * MICROS
        ))

        conexion.execute("""
            INSERT INTO positions (
                portfolio_id,
                asset_id,
                quantity_sats,
                cost_basis_micros
            )
            VALUES (1, 1, 0, 0)
        """)

        conexion.execute("""
            INSERT INTO risk_config (
                portfolio_id,
                version,
                max_exposure_bps,
                max_daily_loss_bps,
                max_data_age_seconds,
                min_order_micros,
                fee_bps,
                slippage_bps,
                prediction_threshold
            )
            VALUES (
                1, 1, 2500, 200, 3600,
                ?, 0, 0, 0.001
            )
        """, (10 * MICROS,))

        conexion.commit()

    finally:

        conexion.close()

    return ruta


def ejecutar(db, accion, prediction_id=1):

    return execute_replay_cycle(
        1,
        prediction_id,
        accion,
        "Prueba controlada",
        path=db
    )


def contar(db, tabla):

    with read_connection(db) as conexion:

        return conexion.execute(
            f"SELECT COUNT(*) FROM {tabla}"
        ).fetchone()[0]


def test_compra(db):

    resultado = ejecutar(db, "BUY")

    assert resultado["risk_approved"]
    assert resultado["quantity_sats"] == 25000000

    assert (
        resultado["notional_micros"]
        == 12500 * MICROS
    )

    assert (
        resultado["cash_micros"]
        == 37500 * MICROS
    )

    assert (
        resultado["equity_micros"]
        == 51250 * MICROS
    )

    assert contar(db, "orders") == 1
    assert contar(db, "equity_history") == 2


def test_venta(db):

    ejecutar(db, "BUY")

    resultado = ejecutar(
        db, "SELL", prediction_id=2
    )

    assert resultado["risk_approved"]
    assert resultado["order_side"] == "SELL"

    assert (
        resultado["cash_micros"]
        == 51250 * MICROS
    )

    assert resultado["position_value_micros"] == 0

    with read_connection(db) as conexion:

        posicion = conexion.execute("""
            SELECT quantity_sats, cost_basis_micros
            FROM positions
        """).fetchone()

        assert tuple(posicion) == (0, 0)

    assert contar(db, "orders") == 2


def test_hold(db):

    resultado = ejecutar(db, "HOLD")

    assert resultado["risk_approved"]
    assert resultado["order_id"] is None
    assert contar(db, "orders") == 0

    assert (
        resultado["equity_micros"]
        == 50000 * MICROS
    )


def test_cartera_pausada(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio SET status = 'PAUSED'
        """)

    resultado = ejecutar(db, "BUY")

    assert not resultado["risk_approved"]
    assert resultado["authorized_action"] == "HOLD"

    assert (
        "PORTFOLIO_NOT_ACTIVE"
        in resultado["risk_reason"]
    )

    assert contar(db, "orders") == 0


def test_paro_emergencia(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET emergency_stop = 1
        """)

    resultado = ejecutar(db, "BUY")

    assert not resultado["risk_approved"]

    assert (
        "EMERGENCY_STOP"
        in resultado["risk_reason"]
    )

    assert contar(db, "orders") == 0


def test_idempotencia_y_persistencia(db):

    primero = ejecutar(db, "BUY")

    segundo = ejecutar(db, "BUY")

    assert primero["created"] is True
    assert segundo["created"] is False

    assert (
        primero["order_id"]
        == segundo["order_id"]
    )

    assert (
        primero["cash_micros"]
        == segundo["cash_micros"]
    )

    assert contar(db, "orders") == 1
    assert contar(db, "agent_cycles") == 1
    assert contar(db, "agent_decisions") == 1
    assert contar(db, "equity_history") == 2


def test_reversion_atomica(db, monkeypatch):

    with read_connection(db) as conexion:

        antes = list(conexion.iterdump())

    def provocar_error(*args, **kwargs):

        raise RuntimeError(
            "Error controlado durante operacion"
        )

    monkeypatch.setattr(
        paper_trading,
        "_record_snapshot",
        provocar_error
    )

    with pytest.raises(RuntimeError):

        ejecutar(db, "BUY")

    with read_connection(db) as conexion:

        assert list(conexion.iterdump()) == antes


def test_venta_sin_posicion(db):

    resultado = ejecutar(db, "SELL")

    assert not resultado["risk_approved"]

    assert (
        "NO_POSITION_TO_SELL"
        in resultado["risk_reason"]
    )

    assert contar(db, "orders") == 0


def test_ciclo_fuera_de_orden(db):

    ejecutar(db, "HOLD", prediction_id=2)

    with pytest.raises(PaperTradingError):

        ejecutar(db, "BUY", prediction_id=1)


def test_ciclo_discontinuo(db):

    ejecutar(db, "HOLD")

    with pytest.raises(PaperTradingError):

        ejecutar(db, "BUY", prediction_id=3)


def test_limite_perdida_diaria(db):

    ejecutar(db, "BUY")

    # Simular una apertura con caida de precio.

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE candles
            SET open = 40000, low = 40000
            WHERE id = 3
        """)

    resultado = ejecutar(
        db, "BUY", prediction_id=2
    )

    assert not resultado["risk_approved"]

    assert (
        "DAILY_LOSS_LIMIT"
        in resultado["risk_reason"]
    )

    assert contar(db, "orders") == 1


def test_ejecucion_viva_deshabilitada(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET mode = 'PAPER_LIVE'
        """)

    with pytest.raises(PaperTradingError):

        ejecutar(db, "BUY")

    assert contar(db, "orders") == 0


def test_accion_invalida(db):

    with pytest.raises(PaperTradingError):

        ejecutar(db, "SHORT")

    assert contar(db, "agent_cycles") == 0


def test_sin_vela_objetivo(db):

    with pytest.raises(PaperTradingError):

        ejecutar(db, "BUY", prediction_id=5)

    assert contar(db, "orders") == 0


def test_patrimonio_inconsistente(db):

    ejecutar(db, "BUY")

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE portfolio
            SET cash_micros = cash_micros + 1000000
        """)

    with pytest.raises(PaperTradingError):

        ejecutar(db, "SELL", prediction_id=2)


def test_costos_financieros(db):

    with write_transaction(db) as conexion:

        conexion.execute("""
            UPDATE risk_config
            SET fee_bps = 10,
                slippage_bps = 10
        """)

    resultado = ejecutar(db, "BUY")

    assert resultado["risk_approved"]
    assert resultado["fee_micros"] > 0

    assert (
        resultado["price_micros"]
        > 50000 * MICROS
    )

    assert resultado["cash_micros"] >= 0

    with read_connection(db) as conexion:

        apertura = conexion.execute("""
            SELECT *
            FROM equity_history
            WHERE snapshot_type = 'EXECUTION'
        """).fetchone()

        assert (
            apertura["position_value_micros"] * 10000
            <= apertura["equity_micros"] * 2500
        )

        assert conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

        assert conexion.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
