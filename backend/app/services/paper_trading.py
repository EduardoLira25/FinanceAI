import json
import math
import time

from backend.app.core.config import DATABASE_PATH

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.risk import (
    MICROS,
    SATOSHIS,
    DAY,
    RiskConfig,
    PortfolioState,
    MarketContext,
    evaluate,
    price_to_micros,
    ceil_div
)


class PaperTradingError(RuntimeError):
    pass


def _record_snapshot(
    conexion,
    portfolio_id,
    cycle_id,
    snapshot_type,
    cash,
    quantity,
    mark_price,
    timestamp,
    initial_cash
):

    position_value = (
        quantity * mark_price // SATOSHIS
    )

    equity = cash + position_value

    previous_peak = conexion.execute("""
        SELECT MAX(e.equity_micros)
        FROM equity_history e
        JOIN agent_cycles c
            ON c.id = e.cycle_id
        WHERE c.portfolio_id = ?
    """, (portfolio_id,)).fetchone()[0]

    peak = max(
        initial_cash,
        previous_peak or 0,
        equity
    )

    drawdown = (
        (peak - equity) / peak
        if peak > 0 else 0.0
    )

    conexion.execute("""
        INSERT INTO equity_history (
            cycle_id,
            snapshot_type,
            cash_micros,
            position_value_micros,
            equity_micros,
            drawdown,
            recorded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        cycle_id,
        snapshot_type,
        cash,
        position_value,
        equity,
        drawdown,
        timestamp
    ))


def _summary(conexion, cycle_id, created):

    fila = conexion.execute("""
        SELECT
            c.id AS cycle_id,
            c.status AS cycle_status,
            d.proposed_action,
            d.authorized_action,
            d.risk_approved,
            d.risk_reason,
            o.id AS order_id,
            o.side AS order_side,
            o.quantity_sats,
            o.price_micros,
            o.notional_micros,
            o.fee_micros,
            e.cash_micros,
            e.position_value_micros,
            e.equity_micros,
            e.drawdown
        FROM agent_cycles c
        JOIN agent_decisions d
            ON d.cycle_id = c.id
        LEFT JOIN orders o
            ON o.decision_id = d.id
        JOIN equity_history e
            ON e.cycle_id = c.id
           AND e.snapshot_type = 'VALUATION'
        WHERE c.id = ?
    """, (cycle_id,)).fetchone()

    if fila is None:

        raise PaperTradingError(
            "Ciclo incompleto. Requiere revision."
        )

    resultado = dict(fila)

    resultado["risk_approved"] = bool(
        resultado["risk_approved"]
    )

    resultado["created"] = created
    resultado["mode"] = "REPLAY"
    resultado["real_trading"] = False

    return resultado


def execute_replay_cycle(
    portfolio_id,
    prediction_id,
    proposed_action,
    rationale,
    *,
    path=DATABASE_PATH,
    llm_model=None,
    llm_response=None,
    latency_ms=None
):

    if proposed_action not in (
        "BUY", "HOLD", "SELL"
    ):

        raise PaperTradingError(
            "Accion no permitida."
        )

    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or len(rationale) > 1000
    ):

        raise PaperTradingError(
            "Justificacion invalida."
        )

    if latency_ms is not None:

        if (
            not math.isfinite(latency_ms)
            or latency_ms < 0
        ):

            raise PaperTradingError(
                "Latencia invalida."
            )

    # Todas las lecturas y escrituras financieras
    # ocurren dentro de la misma transaccion.

    with write_transaction(path) as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE id = ?
        """, (portfolio_id,)).fetchone()

        if cartera is None:

            raise PaperTradingError(
                "Cartera no encontrada."
            )

        # La ejecucion diaria en vivo se incorporara
        # posteriormente con cotizacion verificada.

        if cartera["mode"] != "REPLAY":

            raise PaperTradingError(
                "Ejecucion en vivo aun deshabilitada."
            )

        if cartera["currency"] != "USDT":

            raise PaperTradingError(
                "Moneda de cartera incompatible."
            )

        prediccion = conexion.execute("""
            SELECT
                p.*,
                c.asset_id,
                c.close AS reference_close,
                c.close_time,
                c.open_time,
                c.interval_seconds,
                a.symbol,
                a.exchange,
                a.active
            FROM predictions p
            JOIN candles c
                ON c.id = p.candle_id
            JOIN assets a
                ON a.id = c.asset_id
            WHERE p.id = ?
        """, (prediction_id,)).fetchone()

        if prediccion is None:

            raise PaperTradingError(
                "Prediccion no encontrada."
            )

        if (
            prediccion["symbol"] != "BTCUSDT"
            or prediccion["exchange"] != "MEXC"
            or prediccion["active"] != 1
            or prediccion["model_version"] != "1.0.0"
            or prediccion["interval_seconds"] != DAY
            or prediccion["close_time"]
                != prediccion["open_time"] + DAY
            or prediccion["target_open_time"]
                != prediccion["close_time"]
            or prediccion["target_close_time"]
                != prediccion["close_time"] + DAY
            or not math.isfinite(
                prediccion["predicted_return"]
            )
            or prediccion["predicted_return"] <= -1
        ):

            raise PaperTradingError(
                "Prediccion incompatible."
            )

        candle_id = prediccion["candle_id"]

        asset_id = prediccion["asset_id"]

        execution_time = prediccion["close_time"]

        # 2. Verificar idempotencia

        existente = conexion.execute("""
            SELECT id, status, prediction_id
            FROM agent_cycles
            WHERE portfolio_id = ?
              AND candle_id = ?
        """, (
            portfolio_id,
            candle_id
        )).fetchone()

        if existente is not None:

            if (
                existente["status"]
                not in ("COMPLETED", "REJECTED")
                or existente["prediction_id"]
                != prediction_id
            ):

                raise PaperTradingError(
                    "Ciclo anterior requiere revision."
                )

            return _summary(
                conexion,
                existente["id"],
                created=False
            )

        # 3. Control cronologico del replay

        anterior = conexion.execute("""
            SELECT
                c.id,
                v.close_time,
                c.status
            FROM agent_cycles c
            JOIN candles v
                ON v.id = c.candle_id
            WHERE c.portfolio_id = ?
            ORDER BY v.close_time DESC
            LIMIT 1
        """, (portfolio_id,)).fetchone()

        if anterior is not None:

            if (
                anterior["status"]
                not in ("COMPLETED", "REJECTED")
                or execution_time
                != anterior["close_time"] + DAY
            ):

                raise PaperTradingError(
                    "Ciclo fuera de orden o discontinuo."
                )

        # 4. Recuperar configuracion de riesgo vigente

        riesgo = conexion.execute("""
            SELECT *
            FROM risk_config
            WHERE portfolio_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (portfolio_id,)).fetchone()

        if riesgo is None:

            raise PaperTradingError(
                "Configuracion de riesgo ausente."
            )

        posicion = conexion.execute("""
            SELECT *
            FROM positions
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (
            portfolio_id,
            asset_id
        )).fetchone()

        if posicion is None:

            raise PaperTradingError(
                "Posicion no inicializada."
            )

        cash = cartera["cash_micros"]

        quantity = posicion["quantity_sats"]

        cost_basis = posicion["cost_basis_micros"]

        initial_cash = cartera["initial_cash_micros"]

        # 5. Calcular patrimonio diario de referencia

        reference_price = price_to_micros(
            prediccion["reference_close"]
        )

        baseline = (
            cash
            + quantity * reference_price // SATOSHIS
        )

        if anterior is not None:

            snapshot = conexion.execute("""
                SELECT equity_micros, recorded_at
                FROM equity_history
                WHERE cycle_id = ?
                  AND snapshot_type = 'VALUATION'
            """, (anterior["id"],)).fetchone()

            if (
                snapshot is None
                or snapshot["recorded_at"]
                    != execution_time
                or snapshot["equity_micros"]
                    != baseline
            ):

                raise PaperTradingError(
                    "Patrimonio diario inconsistente."
                )

        elif (
            cash != initial_cash
            or quantity != 0
            or cost_basis != 0
        ):

            raise PaperTradingError(
                "Estado inicial de cartera inconsistente."
            )

        # 6. Obtener solo la apertura de la vela objetivo.
        # Su cierre no se usa para decidir ni ejecutar.

        apertura = conexion.execute("""
            SELECT id, open, close_time
            FROM candles
            WHERE asset_id = ?
              AND interval_seconds = ?
              AND open_time = ?
        """, (
            asset_id,
            DAY,
            execution_time
        )).fetchone()

        if (
            apertura is None
            or apertura["close_time"]
                != execution_time + DAY
            or apertura["close_time"] > int(time.time())
        ):

            raise PaperTradingError(
                "Vela objetivo historica no disponible."
            )

        market_price = price_to_micros(
            apertura["open"]
        )

        config = RiskConfig(
            max_exposure_bps=riesgo[
                "max_exposure_bps"
            ],
            max_daily_loss_bps=riesgo[
                "max_daily_loss_bps"
            ],
            max_data_age_seconds=riesgo[
                "max_data_age_seconds"
            ],
            min_order_micros=riesgo[
                "min_order_micros"
            ],
            fee_bps=riesgo["fee_bps"],
            slippage_bps=riesgo["slippage_bps"],
            emergency_stop=bool(
                riesgo["emergency_stop"]
            )
        )

        estado = PortfolioState(
            cash_micros=cash,
            quantity_sats=quantity,
            status=cartera["status"],
            day_start_equity_micros=baseline
        )

        mercado = MarketContext(
            symbol="BTCUSDT",
            candle_close_time=execution_time,
            quote_time=execution_time,
            now=execution_time,
            price_micros=market_price
        )

        # 7. Reevaluar riesgo dentro de la transaccion

        decision = evaluate(
            proposed_action,
            estado,
            mercado,
            config
        )

        audit_time = int(time.time())

        cycle_id = conexion.execute("""
            INSERT INTO agent_cycles (
                portfolio_id,
                candle_id,
                prediction_id,
                risk_config_id,
                status,
                attempts,
                started_at
            )
            VALUES (?, ?, ?, ?, 'RUNNING', 1, ?)
        """, (
            portfolio_id,
            candle_id,
            prediction_id,
            riesgo["id"],
            audit_time
        )).lastrowid

        decision_id = conexion.execute("""
            INSERT INTO agent_decisions (
                cycle_id,
                proposed_action,
                authorized_action,
                rationale,
                llm_model,
                llm_response,
                risk_approved,
                risk_reason,
                latency_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cycle_id,
            proposed_action,
            decision.authorized_action,
            rationale.strip(),
            llm_model,
            llm_response,
            int(decision.approved),
            json.dumps(decision.reasons),
            latency_ms
        )).lastrowid

        # 8. Ejecutar compra o venta virtual

        if (
            decision.approved
            and decision.authorized_action
            in ("BUY", "SELL")
        ):

            qty = decision.quantity_sats

            notional = decision.notional_micros

            fee = decision.fee_micros

            execution_price = (
                decision.execution_price_micros
            )

            if decision.authorized_action == "BUY":

                cash -= notional + fee

                quantity += qty

                cost_basis += notional + fee

            else:

                if qty != quantity:

                    raise PaperTradingError(
                        "Cantidad de venta inconsistente."
                    )

                cash += notional - fee

                quantity -= qty

                cost_basis = 0

            if min(
                cash,
                quantity,
                cost_basis
            ) < 0:

                raise PaperTradingError(
                    "Saldo o posicion negativa."
                )

            slippage = ceil_div(
                qty * abs(
                    execution_price - market_price
                ),
                SATOSHIS
            )

            conexion.execute("""
                INSERT INTO orders (
                    decision_id,
                    side,
                    status,
                    quantity_sats,
                    price_micros,
                    notional_micros,
                    fee_micros,
                    slippage_micros,
                    execution_source,
                    filled_at
                )
                VALUES (
                    ?, ?, 'FILLED', ?, ?, ?, ?, ?,
                    'REPLAY_OPEN', ?
                )
            """, (
                decision_id,
                decision.authorized_action,
                qty,
                execution_price,
                notional,
                fee,
                slippage,
                execution_time
            ))

            conexion.execute("""
                UPDATE portfolio
                SET cash_micros = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                cash,
                audit_time,
                portfolio_id
            ))

            conexion.execute("""
                UPDATE positions
                SET quantity_sats = ?,
                    cost_basis_micros = ?,
                    updated_at = ?
                WHERE portfolio_id = ?
                  AND asset_id = ?
            """, (
                quantity,
                cost_basis,
                audit_time,
                portfolio_id,
                asset_id
            ))

        # 9. Registrar patrimonio en la apertura

        _record_snapshot(
            conexion,
            portfolio_id,
            cycle_id,
            "EXECUTION",
            cash,
            quantity,
            market_price,
            execution_time,
            initial_cash
        )

        # 10. Valoracion posterior al cierre.
        # Solo para medir el resultado del replay.

        cierre_objetivo = conexion.execute("""
            SELECT close
            FROM candles
            WHERE id = ?
        """, (apertura["id"],)).fetchone()[0]

        closing_price = price_to_micros(
            cierre_objetivo
        )

        _record_snapshot(
            conexion,
            portfolio_id,
            cycle_id,
            "VALUATION",
            cash,
            quantity,
            closing_price,
            execution_time + DAY,
            initial_cash
        )

        # 11. Finalizar ciclo y guardar evidencia

        status = (
            "COMPLETED"
            if decision.approved
            else "REJECTED"
        )

        conexion.execute("""
            UPDATE agent_cycles
            SET status = ?,
                finished_at = ?
            WHERE id = ?
        """, (
            status,
            int(time.time()),
            cycle_id
        ))

        conexion.execute("""
            INSERT INTO system_logs (
                cycle_id,
                level,
                component,
                message
            )
            VALUES (?, ?, 'PAPER_TRADING', ?)
        """, (
            cycle_id,
            "INFO" if decision.approved
            else "WARNING",
            json.dumps({
                "mode": "REPLAY",
                "action": proposed_action,
                "authorized": decision.authorized_action,
                "reasons": decision.reasons
            })
        ))

        return _summary(
            conexion,
            cycle_id,
            created=True
        )
