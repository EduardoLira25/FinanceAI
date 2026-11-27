import asyncio
import sqlite3

import httpx
import pytest

from backend.app.core.config import load_api_key

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.api import portfolio_history as service
from backend.app.main import app


@pytest.fixture
def db(tmp_path):

    ruta = tmp_path / "portfolio.db"

    with read_connection() as original:

        copia = sqlite3.connect(ruta)

        try:
            original.backup(copia)
        finally:
            copia.close()

    return ruta


def test_cartera_inicial(db):

    p = service.portfolio_overview(db)

    assert p["cash"] == 50000
    assert p["equity"] == 50000
    assert p["return_pct"] == 0
    assert p["exposure_pct"] == 0
    assert p["bitcoin_quantity"] == 0
    assert p["valuations"] == []
    assert p["real_trading"] is False


def test_historial_inicial(db):

    h = service.order_history(db)

    assert h["total"] == 0
    assert h["orders"] == []
    assert h["has_more"] is False


@pytest.fixture
def db_con_compra(db):

    with write_transaction(db) as c:

        p = c.execute("""
            SELECT id FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()[0]

        pred = c.execute("""
            SELECT pr.id, pr.candle_id, v.asset_id
            FROM predictions pr
            JOIN candles v ON v.id = pr.candle_id
            ORDER BY pr.id DESC LIMIT 1
        """).fetchone()

        r = c.execute("""
            SELECT id FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC LIMIT 1
        """, (p,)).fetchone()[0]

        ciclo = c.execute("""
            INSERT INTO agent_cycles (
                portfolio_id, candle_id,
                prediction_id, risk_config_id, status
            )
            VALUES (?, ?, ?, ?, 'COMPLETED')
        """, (
            p, pred["candle_id"], pred["id"], r
        )).lastrowid

        decision = c.execute("""
            INSERT INTO agent_decisions (
                cycle_id, proposed_action,
                authorized_action, rationale, risk_approved
            )
            VALUES (?, 'BUY', 'BUY', 'Prueba sintetica', 1)
        """, (ciclo,)).lastrowid

        c.execute("""
            INSERT INTO orders (
                decision_id, side, status,
                quantity_sats, price_micros,
                notional_micros, fee_micros,
                slippage_micros, filled_at,
                execution_source
            )
            VALUES (
                ?, 'BUY', 'FILLED',
                10000000, 50000000000,
                5000000000, 0, 0, unixepoch(),
                'TEST'
            )
        """, (decision,))

        c.execute("""
            UPDATE portfolio
            SET cash_micros = 45000000000
            WHERE id = ?
        """, (p,))

        c.execute("""
            UPDATE positions
            SET quantity_sats = 10000000,
                cost_basis_micros = 5000000000
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (p, pred["asset_id"]))

        c.execute("""
            INSERT INTO equity_history (
                cycle_id, snapshot_type,
                cash_micros, position_value_micros,
                equity_micros, drawdown, recorded_at
            )
            VALUES (
                ?, 'VALUATION',
                45000000000, 6000000000,
                51000000000, 0, unixepoch()
            )
        """, (ciclo,))

    return db


def test_valoracion_con_posicion(db_con_compra):

    p = service.portfolio_overview(db_con_compra)

    assert p["bitcoin_quantity"] == pytest.approx(0.1)
    assert p["cash"] == 45000

    assert p["position_value"] == pytest.approx(
        p["reference_price"] * 0.1,
        abs=0.000001
    )

    assert p["equity"] == pytest.approx(
        p["cash"] + p["position_value"]
    )

    assert p["unrealized_pnl"] == pytest.approx(
        p["position_value"] - 5000
    )


def test_patrimonio_persistido(db_con_compra):

    p = service.portfolio_overview(db_con_compra)

    assert p["total_valuations"] == 1
    assert p["valuations"][0]["equity"] == 51000
    assert p["max_recorded_drawdown_pct"] == 0


def test_resumen_ordenes(db_con_compra):

    p = service.portfolio_overview(db_con_compra)

    assert p["filled_orders"] == 1
    assert p["buys"] == 1
    assert p["sells"] == 0
    assert p["fees_usdt"] == 0


def test_conversion_unidades(db_con_compra):

    h = service.order_history(db_con_compra)

    assert h["total"] == 1

    o = h["orders"][0]

    assert o["quantity_btc"] == pytest.approx(0.1)
    assert o["price_usdt"] == 50000
    assert o["notional_usdt"] == 5000
    assert o["filled_at_utc"] is not None


@pytest.mark.parametrize("side, status, expected", [
    ("BUY", None, 1),
    ("SELL", None, 0),
    (None, "FILLED", 1),
    (None, "REJECTED", 0)
])
def test_filtros(db_con_compra, side, status, expected):

    h = service.order_history(
        db_con_compra,
        side=side,
        status=status
    )

    assert h["total"] == expected


def test_paginacion(db_con_compra):

    h = service.order_history(
        db_con_compra,
        limit=1,
        offset=1
    )

    assert h["total"] == 1
    assert h["orders"] == []
    assert h["has_more"] is False


@pytest.mark.parametrize("ruta", [
    "/api/v1/portfolio/overview",
    "/api/v1/orders/history"
])
@pytest.mark.parametrize("auth", [False, True])
def test_api_autenticada(db, monkeypatch, ruta, auth):

    monkeypatch.setattr(
        service, "DATABASE_PATH", db
    )

    async def consultar():

        headers = (
            {"X-API-Key": load_api_key()}
            if auth else {}
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=headers
        ) as cliente:

            return await cliente.get(ruta)

    respuesta = asyncio.run(consultar())

    assert respuesta.status_code == (
        200 if auth else 401
    )

    if auth:

        assert respuesta.json()["real_trading"] is False
        assert load_api_key() not in respuesta.text


@pytest.mark.parametrize("query", [
    "side=INVALID",
    "status=INVALID",
    "limit=101",
    "offset=-1"
])
def test_parametros_invalidos(db, monkeypatch, query):

    monkeypatch.setattr(service, "DATABASE_PATH", db)

    async def consultar():

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers={"X-API-Key": load_api_key()}
        ) as cliente:

            return await cliente.get(
                "/api/v1/orders/history?" + query
            )

    assert asyncio.run(consultar()).status_code == 422
