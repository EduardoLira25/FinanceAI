import json
import time

from dataclasses import asdict
from datetime import datetime, timezone

from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH
)

from backend.app.services.agent_context import (
    load_live_context,
    temporary_ollama,
    AgentContextError
)

from backend.app.services.financial_prompt import (
    FinancialContext,
    build_context_data
)

from backend.app.services.llm_decision import (
    request_decision,
    DecisionError,
    database_hash,
    model_hashes
)

from backend.app.services.ollama_client import (
    OllamaClient,
    OllamaError
)

from backend.app.services.risk import (
    RiskConfig,
    PortfolioState,
    MarketContext,
    RiskError,
    evaluate,
    reject,
    model_only_action,
    price_to_micros
)


class AgentRiskError(RuntimeError):

    def __init__(self, code, message):

        self.code = code

        super().__init__(message)


# 2. Convertir contexto financiero a estructuras
#    compatibles con el motor de riesgo

def build_risk_inputs(context):

    if not isinstance(context, FinancialContext):

        raise AgentRiskError(
            "INVALID_CONTEXT",
            "Contexto financiero incompatible."
        )

    config = RiskConfig(
        max_exposure_bps=context.max_exposure_bps,
        max_daily_loss_bps=context.max_daily_loss_bps,
        max_data_age_seconds=context.max_data_age_seconds,
        min_order_micros=context.min_order_micros,
        fee_bps=context.fee_bps,
        slippage_bps=context.slippage_bps,
        emergency_stop=context.emergency_stop
    )

    portfolio = PortfolioState(
        cash_micros=context.cash_micros,
        quantity_sats=context.quantity_sats,
        status=context.portfolio_status,
        day_start_equity_micros=(
            context.day_start_equity_micros
        )
    )

    cierre = int(
        context.candle_close.timestamp()
    )

    now = int(
        context.as_of_utc.timestamp()
    )

    # IMPORTANTE:
    # Este precio es una referencia historica.
    # No constituye una cotizacion ejecutable actual.

    market = MarketContext(
        symbol=context.symbol,
        candle_close_time=cierre,
        quote_time=cierre,
        now=now,
        price_micros=price_to_micros(
            context.reference_close
        )
    )

    return portfolio, market, config


# 3. Evaluar propuesta sin ejecutar operaciones

def preview_action(action, context):

    if action not in ("BUY", "HOLD", "SELL"):

        raise AgentRiskError(
            "INVALID_ACTION",
            "Accion financiera no permitida."
        )

    portfolio, market, config = build_risk_inputs(
        context
    )

    resultado = evaluate(
        action,
        portfolio,
        market,
        config
    )

    # Ninguna compra o venta puede autorizarse
    # utilizando solamente un cierre historico.

    if action in ("BUY", "SELL"):

        motivos = tuple(
            motivo
            for motivo in resultado.reasons
            if motivo != "RISK_APPROVED"
        )

        resultado = reject(
            action,
            *motivos,
            "NO_VERIFIED_EXECUTION_QUOTE"
        )

    return {
        **asdict(resultado),
        "market_quote_verified": False,
        "order_authorized": False,
        "executed": False,
        "real_trading": False
    }


# 4. Obtener restricciones operativas generales

def operational_blockers(context):

    datos = build_context_data(context)

    blockers = []

    if context.portfolio_status != "ACTIVE":

        blockers.append(
            "PORTFOLIO_NOT_ACTIVE"
        )

    if context.emergency_stop:

        blockers.append(
            "EMERGENCY_STOP"
        )

    if datos["risk"]["data_is_stale"]:

        blockers.append(
            "STALE_CANDLE"
        )

    if context.day_start_equity_micros is None:

        blockers.append(
            "MISSING_DAILY_EQUITY_BASELINE_FOR_BUY"
        )

    blockers.append(
        "NO_VERIFIED_EXECUTION_QUOTE"
    )

    return blockers


# 5. Detectar cambios durante la inferencia LLM

def verify_unchanged_context(
    before,
    after,
    metadata_before,
    metadata_after
):

    if after.as_of_utc < before.as_of_utc:

        raise AgentRiskError(
            "CLOCK_MOVED_BACKWARD",
            "El reloj cambio durante la inferencia."
        )

    datos_antes = before.model_dump(
        exclude={"as_of_utc"}
    )

    datos_despues = after.model_dump(
        exclude={"as_of_utc"}
    )

    meta_antes = {
        k: v
        for k, v in metadata_before.items()
        if k != "context_created_at_utc"
    }

    meta_despues = {
        k: v
        for k, v in metadata_after.items()
        if k != "context_created_at_utc"
    }

    if (
        datos_antes != datos_despues
        or meta_antes != meta_despues
    ):

        raise AgentRiskError(
            "CONTEXT_CHANGED",
            "El contexto financiero cambio durante la inferencia."
        )


# 6. Integracion completa:
#    SQLite -> LSTM -> Qwen3 -> Riesgo

def preview_live_decision(
    client,
    path=DATABASE_PATH,
    clock=time.time
):

    inicio = time.perf_counter()

    contexto_antes, metadata_antes = (
        load_live_context(
            path,
            clock
        )
    )

    propuesta = request_decision(
        contexto_antes,
        client
    )

    # Volver a consultar SQLite despues de recibir
    # la respuesta de Ollama.

    contexto_despues, metadata_despues = (
        load_live_context(
            path,
            clock
        )
    )

    verify_unchanged_context(
        contexto_antes,
        contexto_despues,
        metadata_antes,
        metadata_despues
    )

    accion_llm = propuesta[
        "decision"
    ]["action"]

    accion_modelo = model_only_action(
        contexto_despues.predicted_return,
        contexto_despues.prediction_threshold
    )

    # Evaluar la propuesta del agente.

    riesgo_llm = preview_action(
        accion_llm,
        contexto_despues
    )

    # Evaluar tambien la estrategia cuantitativa
    # para efectos de diagnostico comparativo.

    riesgo_modelo = preview_action(
        accion_modelo,
        contexto_despues
    )

    return {
        "metadata": metadata_despues,

        "context": build_context_data(
            contexto_despues
        ),

        "llm_result": propuesta,

        "llm_risk": riesgo_llm,

        "model_only_risk": riesgo_modelo,

        "operational_blockers": (
            operational_blockers(
                contexto_despues
            )
        ),

        "context_revalidated": True,

        "order_authorized": False,

        "executed": False,

        "real_trading": False,

        "total_latency_ms": round(
            (time.perf_counter() - inicio)
            * 1000,
            3
        )
    }


# 7. Diagnostico real

def main():

    print("=" * 60)
    print("FINANCEAI - AGENTE Y MOTOR DE RIESGO")
    print("=" * 60)

    db_antes = database_hash()

    modelo_antes = model_hashes()

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.7",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Operaciones_financieras": False,
        "TE_reevaluado": False
    }

    try:

        with temporary_ollama(
            BASE_DIR /
            "results/agent_risk_ollama.log"
        ):

            with OllamaClient() as cliente:

                print(
                    "Solicitando propuesta a Qwen3...",
                    flush=True
                )

                resultado = preview_live_decision(
                    cliente
                )

        print("\nPROPUESTA ORIGINAL QWEN3")

        print(json.dumps(
            resultado["llm_result"]["decision"],
            indent=4,
            ensure_ascii=False
        ))

        print("\nEVALUACION DE RIESGO DEL LLM")

        print(json.dumps(
            resultado["llm_risk"],
            indent=4,
            ensure_ascii=False
        ))

        print("\nEVALUACION DEL MODELO AISLADO")

        print(json.dumps(
            resultado["model_only_risk"],
            indent=4,
            ensure_ascii=False
        ))

        print("\nRESTRICCIONES OPERATIVAS")

        for motivo in resultado[
            "operational_blockers"
        ]:

            print("-", motivo)

        assert resultado["context_revalidated"]

        assert resultado["executed"] is False

        assert resultado["order_authorized"] is False

        assert resultado["real_trading"] is False

        assert (
            resultado["llm_risk"]["quantity_sats"]
            == 0
        )

        assert (
            resultado["model_only_risk"]["quantity_sats"]
            == 0
        )

        evidencia["Resultado"] = "APROBADO"

        evidencia["Integracion"] = resultado

        print(
            "\nLatencia total:",
            resultado["total_latency_ms"],
            "ms"
        )

    except (
        AgentContextError,
        AgentRiskError,
        DecisionError,
        OllamaError,
        RiskError
    ) as error:

        evidencia["Resultado"] = "REVISAR"

        evidencia["Error"] = {
            "code": getattr(
                error,
                "code",
                type(error).__name__
            ),
            "message": str(error)
        }

        print(
            "\nPropuesta bloqueada:",
            str(error)
        )

    finally:

        assert database_hash() == db_antes

        assert model_hashes() == modelo_antes

        evidencia["Base_datos_intacta"] = True

        evidencia["Modelo_LSTM_intacto"] = True

        ruta = (
            BASE_DIR /
            "results/control_integracion_riesgo_llm.json"
        )

        ruta.write_text(
            json.dumps(
                evidencia,
                indent=4,
                ensure_ascii=False,
                allow_nan=False
            ),
            encoding="utf-8"
        )

    print("\n" + "=" * 60)
    print("FINANCEAI - RESULTADO DE INTEGRACION")
    print("=" * 60)

    print("Base de datos intacta: SI")
    print("Modelo LSTM intacto: SI")
    print("Reentrenamiento: NO")
    print("TE reevaluado: NO")
    print("Ordenes ejecutadas: NO")
    print("Dinero real utilizado: NO")
    print("Evidencia:", ruta.name)

    if evidencia["Resultado"] != "APROBADO":

        raise SystemExit(1)

    print("LSTM + Qwen3 + Riesgo: INTEGRADOS")
    print("Contexto posterior a inferencia: VERIFICADO")
    print("Ejecucion paper en vivo: PENDIENTE")
    print("\nPASO 12.7 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
