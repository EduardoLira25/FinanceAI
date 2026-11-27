import json
import math
import time

from dataclasses import replace
from datetime import datetime, timezone

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

from backend.app.services.agent_context import (
    load_live_context
)

from backend.app.services.agent_risk import (
    build_risk_inputs,
    verify_unchanged_context
)

from backend.app.services.financial_prompt import (
    FinancialContext,
    PROMPT_VERSION,
    prompt_sha256
)

from backend.app.services.llm_decision import (
    validate_decision,
    database_hash,
    model_hashes
)

from backend.app.services.ollama_client import (
    MODEL,
    MODEL_DIGEST,
    OLLAMA_VERSION
)

from backend.app.services.market_quote import (
    validate_quote,
    serialize_quote
)

from backend.app.services.risk import (
    MICROS,
    SATOSHIS,
    DAY,
    evaluate,
    ceil_div
)

from backend.app.services.paper_trading import (
    _record_snapshot
)


class LivePaperError(RuntimeError):

    pass


# 2. Recuperar resultado persistido de un ciclo

def cycle_summary(conexion, cycle_id, created):

    fila = conexion.execute("""
        SELECT
            c.id AS cycle_id,
            c.status AS cycle_status,
            c.candle_id,
            c.prediction_id,
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
            o.slippage_micros,
            o.filled_at,
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
           AND e.snapshot_type = 'EXECUTION'
        WHERE c.id = ?
    """, (cycle_id,)).fetchone()

    if fila is None:

        raise LivePaperError(
            "Ciclo incompleto."
        )

    resultado = dict(fila)

    resultado.update({
        "risk_approved": bool(
            fila["risk_approved"]
        ),
        "created": created,
        "executed": fila["order_id"] is not None,
        "mode": "PAPER_LIVE",
        "real_trading": False
    })

    return resultado


# 3. Validar procedencia de la propuesta

def verify_proposal(context, proposal):

    if not isinstance(context, FinancialContext):

        raise LivePaperError(
            "Contexto financiero invalido."
        )

    if context.mode != "PAPER_LIVE":

        raise LivePaperError(
            "Modo financiero incompatible."
        )

    if not isinstance(proposal, dict):

        raise LivePaperError(
            "Propuesta invalida."
        )

    identidad = {
        "llm_model": MODEL,
        "llm_digest": MODEL_DIGEST,
        "ollama_version": OLLAMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(),
        "validation_status": "VALID"
    }

    if any(
        proposal.get(k) != v
        for k, v in identidad.items()
    ):

        raise LivePaperError(
            "Identidad de propuesta no verificada."
        )

    for campo in (
        "executed",
        "risk_authorized",
        "real_trading"
    ):

        if proposal.get(campo) is not False:

            raise LivePaperError(
                "Estado de propuesta incompatible."
            )

    decision = validate_decision(
        proposal.get("raw_response"),
        context
    )

    if decision.model_dump() != proposal.get(
        "decision"
    ):

        raise LivePaperError(
            "La propuesta no coincide con su JSON."
        )

    latency = proposal.get("latency_ms")

    if (
        type(latency) not in (int, float)
        or not math.isfinite(latency)
        or latency < 0
    ):

        raise LivePaperError(
            "Latencia de propuesta invalida."
        )

    return decision


# 4. Ejecutar un ciclo financiero exclusivamente virtual

def execute_live_cycle(
    context,
    metadata,
    proposal,
    quote,
    *,
    path=DATABASE_PATH,
    clock=time.time
):

    decision_llm = verify_proposal(
        context,
        proposal
    )

    if not isinstance(metadata, dict):

        raise LivePaperError(
            "Metadatos invalidos."
        )

    for campo in (
        "portfolio_id",
        "asset_id",
        "candle_id",
        "prediction_id",
        "risk_config_id"
    ):

        valor = metadata.get(campo)

        if type(valor) is not int or valor <= 0:

            raise LivePaperError(
                "Identificador de contexto invalido."
            )

    portfolio_id = metadata["portfolio_id"]

    candle_id = metadata["candle_id"]

    # SQLite bloquea otras escrituras mientras
    # se valida y ejecuta la operacion.

    with write_transaction(path) as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE id = ?
              AND name = 'FinanceAI_Paper'
              AND mode = 'PAPER_LIVE'
              AND strategy = 'LLM'
              AND currency = 'USDT'
        """, (portfolio_id,)).fetchone()

        if cartera is None:

            raise LivePaperError(
                "Cartera paper incompatible."
            )

        # 5. Idempotencia: no repetir una operacion
        # financiera para la misma vela.

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
                    != metadata["prediction_id"]
            ):

                raise LivePaperError(
                    "Ciclo anterior requiere revision."
                )

            return cycle_summary(
                conexion,
                existente["id"],
                created=False
            )

        # 6. Revalidar el estado desde SQLite.
        # La transaccion de escritura sigue bloqueada.
        # No se realizan consultas HTTP aqui.

        actual, metadata_actual = load_live_context(
            path,
            clock
        )

        verify_unchanged_context(
            context,
            actual,
            metadata,
            metadata_actual
        )

        now_ms = int(clock() * 1000)

        now = now_ms // 1000

        if now < int(
            actual.as_of_utc.timestamp()
        ):

            raise LivePaperError(
                "Reloj local retrocedio."
            )

        cierre = int(
            actual.candle_close.timestamp()
        )

        if not cierre <= now < cierre + DAY:

            raise LivePaperError(
                "Horizonte de prediccion vencido."
            )

        # 7. Validar nuevamente la cotizacion.

        validate_quote(
            quote,
            now_ms
        )

        if quote.trade_time_ms < cierre * 1000:

            raise LivePaperError(
                "Cotizacion anterior al cierre."
            )

        if quote.received_at_ms < int(
            context.as_of_utc.timestamp() * 1000
        ):

            raise LivePaperError(
                "Cotizacion anterior al contexto."
            )

        portfolio, market, config = (
            build_risk_inputs(actual)
        )

        posicion = conexion.execute("""
            SELECT *
            FROM positions
            WHERE portfolio_id = ?
              AND asset_id = ?
        """, (
            portfolio_id,
            metadata["asset_id"]
        )).fetchone()

        if posicion is None:

            raise LivePaperError(
                "Posicion no inicializada."
            )

        cash = cartera["cash_micros"]

        quantity = posicion["quantity_sats"]

        cost_basis = posicion["cost_basis_micros"]

        initial_cash = cartera["initial_cash_micros"]

        if (
            cash != portfolio.cash_micros
            or quantity != portfolio.quantity_sats
        ):

            raise LivePaperError(
                "Saldo inconsistente."
            )

        ciclos_previos = conexion.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
            WHERE portfolio_id = ?
        """, (portfolio_id,)).fetchone()[0]

        # 8. Establecer patrimonio inicial diario.
        # Solo se permite usar el capital inicial
        # en la primera operacion de una cartera
        # completamente en efectivo.

        baseline_source = (
            "RECORDED_DAILY_VALUATION"
            if portfolio.day_start_equity_micros
                is not None
            else "UNAVAILABLE"
        )

        if (
            portfolio.day_start_equity_micros is None
            and ciclos_previos == 0
            and cash == initial_cash
            and quantity == 0
            and cost_basis == 0
        ):

            portfolio = replace(
                portfolio,
                day_start_equity_micros=initial_cash
            )

            baseline_source = "INITIAL_CASH"

        # Usar el precio reciente, no el cierre
        # historico empleado para la prediccion.

        market = replace(
            market,
            quote_time=quote.trade_time,
            now=now,
            price_micros=quote.price_micros
        )

        riesgo = evaluate(
            decision_llm.action,
            portfolio,
            market,
            config
        )

        # 9. Registrar ciclo y decision.

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
            metadata["prediction_id"],
            metadata["risk_config_id"],
            now
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
            decision_llm.action,
            riesgo.authorized_action,
            decision_llm.rationale,
            MODEL,
            proposal["raw_response"],
            int(riesgo.approved),
            json.dumps(riesgo.reasons),
            proposal["latency_ms"]
        )).lastrowid

        # 10. Ejecutar orden exclusivamente virtual.

        if (
            riesgo.approved
            and riesgo.authorized_action
                in ("BUY", "SELL")
        ):

            qty = riesgo.quantity_sats

            notional = riesgo.notional_micros

            fee = riesgo.fee_micros

            precio = riesgo.execution_price_micros

            if riesgo.authorized_action == "BUY":

                cash -= notional + fee

                quantity += qty

                cost_basis += notional + fee

            else:

                if qty != quantity:

                    raise LivePaperError(
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

                raise LivePaperError(
                    "Saldo o posicion negativa."
                )

            slippage = ceil_div(
                qty * abs(
                    precio - quote.price_micros
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
                    'PAPER_MEXC_RECENT_TRADE', ?
                )
            """, (
                decision_id,
                riesgo.authorized_action,
                qty,
                precio,
                notional,
                fee,
                slippage,
                now
            ))

            conexion.execute("""
                UPDATE portfolio
                SET cash_micros = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                cash,
                now,
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
                now,
                portfolio_id,
                metadata["asset_id"]
            ))

        # 11. Registrar patrimonio al instante
        # de ejecucion, sin utilizar precios futuros.

        _record_snapshot(
            conexion,
            portfolio_id,
            cycle_id,
            "EXECUTION",
            cash,
            quantity,
            quote.price_micros,
            now,
            initial_cash
        )

        status = (
            "COMPLETED"
            if riesgo.approved
            else "REJECTED"
        )

        conexion.execute("""
            UPDATE agent_cycles
            SET status = ?,
                finished_at = ?
            WHERE id = ?
        """, (
            status,
            now,
            cycle_id
        ))

        # 12. Guardar evidencia de precio,
        # riesgo y procedencia del modelo.

        evidencia = {
            "mode": "PAPER_LIVE",
            "real_trading": False,
            "quote": serialize_quote(quote),
            "execution_time": now,
            "baseline_source": baseline_source,
            "day_start_equity_micros": (
                portfolio.day_start_equity_micros
            ),
            "model_digest": MODEL_DIGEST,
            "prompt_sha256": prompt_sha256(),
            "context_metadata": metadata_actual,
            "proposed_action": decision_llm.action,
            "authorized_action": riesgo.authorized_action,
            "risk_reasons": riesgo.reasons
        }

        conexion.execute("""
            INSERT INTO system_logs (
                cycle_id,
                level,
                component,
                message
            )
            VALUES (?, ?, 'LIVE_PAPER_TRADING', ?)
        """, (
            cycle_id,
            "INFO" if riesgo.approved
            else "WARNING",
            json.dumps(
                evidencia,
                ensure_ascii=False,
                allow_nan=False
            )
        ))

        return cycle_summary(
            conexion,
            cycle_id,
            created=True
        )


# 13. Diagnostico de la cartera principal.
# No activa el agente ni ejecuta operaciones.

def main():

    print("=" * 60)
    print("FINANCEAI - EJECUTOR PAPER EN VIVO")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    with read_connection() as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = 'FinanceAI_Paper'
        """).fetchone()

        ordenes = conexion.execute("""
            SELECT COUNT(*)
            FROM orders
        """).fetchone()[0]

        ciclos = conexion.execute("""
            SELECT COUNT(*)
            FROM agent_cycles
        """).fetchone()[0]

    assert cartera["status"] == "PAUSED"

    assert cartera["cash_micros"] == 50000 * MICROS

    assert ordenes == 0

    assert ciclos == 0

    assert database_hash() == db_antes

    assert model_hashes() == modelo_antes

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.8.2",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": "APROBADO",
        "Ejecutor_paper_live": True,
        "Capital_virtual_USDT": (
            cartera["cash_micros"] / MICROS
        ),
        "Cartera": cartera["status"],
        "Ordenes_principales": ordenes,
        "Ciclos_principales": ciclos,
        "Base_datos_intacta": True,
        "Modelo_LSTM_intacto": True,
        "Ejecucion_automatica_activada": False,
        "Dinero_real_utilizado": False
    }

    ruta = (
        BASE_DIR /
        "results/control_live_paper_trading.json"
    )

    ruta.write_text(
        json.dumps(
            evidencia,
            indent=4,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print("Ejecutor Paper Trading: IMPLEMENTADO")
    print("Cotizacion reciente: REQUERIDA")
    print("Revalidacion transaccional: IMPLEMENTADA")
    print("Control de duplicados: IMPLEMENTADO")
    print("Persistencia financiera: IMPLEMENTADA")
    print("Capital virtual: 50000 USDT")
    print("Cartera principal: PAUSADA")
    print("Ordenes principales:", ordenes)
    print("Ciclos principales:", ciclos)
    print("Base de datos intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Ejecucion automatica: DESHABILITADA")
    print("Dinero real utilizado: NO")
    print("Evidencia:", ruta.name)

    print("\nPASO 12.8.2 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
