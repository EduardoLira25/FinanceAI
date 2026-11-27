import json
import math
import hashlib

from datetime import (
    datetime,
    date,
    time,
    timedelta,
    timezone
)

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    AwareDatetime,
    model_validator
)

from backend.app.core.config import BASE_DIR

from backend.app.services.risk import (
    MICROS,
    SATOSHIS,
    price_to_micros
)

PROMPT_VERSION = "1.0.0"


SYSTEM_PROMPT = """
IDENTIDAD

Eres el agente de analisis financiero de FinanceAI.
Trabajas exclusivamente en una simulacion academica
de Paper Trading de Bitcoin contra USDT.

OBJETIVO

Analizar el pronostico del modelo LSTM y el contexto
financiero disponible para proponer una decision prudente.

Tu objetivo es contribuir al rendimiento ajustado por
riesgo y preservar el capital virtual.

No debes garantizar ganancias ni presentar el pronostico
como un resultado futuro seguro.

ACCIONES PERMITIDAS

BUY: proponer una compra de Bitcoin.
HOLD: mantener la cartera sin ejecutar operaciones.
SELL: proponer una venta de Bitcoin disponible.

REGLAS OBLIGATORIAS

1. Utiliza exclusivamente los datos proporcionados
   por el backend de FinanceAI.

2. No inventes precios, noticias, indicadores, eventos
   ni informacion financiera externa.

3. No utilices informacion posterior al instante
   de decision indicado en el contexto.

4. El pronostico LSTM es una estimacion incierta.
   Una prediccion positiva no garantiza una subida.

5. Considera conjuntamente el rendimiento pronosticado,
   la tendencia reciente, la distancia respecto a SMA,
   la volatilidad y la exposicion de la cartera.

6. El umbral del modelo es una referencia de la estrategia
   cuantitativa. No estas obligado a copiar su decision.

7. Si la cartera no esta activa, propone HOLD.

8. Si el paro de emergencia esta activado, propone HOLD.

9. Si los datos superan la antiguedad permitida,
   propone HOLD.

10. Si no existe efectivo disponible, no propongas BUY.

11. Si no existe Bitcoin disponible, no propongas SELL.

12. No se permiten ventas en corto ni apalancamiento.

13. Considera los limites de exposicion y perdida diaria.
    No asumas que una operacion esta autorizada.

14. El ultimo precio de cierre es una referencia historica,
    no necesariamente una cotizacion ejecutable actual.

15. No determines cantidades, precios de ejecucion,
    comisiones definitivas ni tamanos de orden.

16. El motor de riesgo determinista tiene la autoridad
    final sobre cualquier operacion propuesta.

17. No solicites credenciales ni acceso a cuentas reales.

18. Cuando exista incertidumbre importante o informacion
    insuficiente, considera HOLD.

FORMATO OBLIGATORIO

Devuelve exclusivamente un objeto JSON con cuatro campos:

{
    "action": "BUY, HOLD o SELL",
    "symbol": "BTCUSDT",
    "candle_date": "AAAA-MM-DD",
    "rationale": "Justificacion financiera breve en espanol"
}

La fecha candle_date debe coincidir exactamente con
la fecha de apertura de la ultima vela cerrada.

La justificacion debe tener entre 1 y 240 caracteres.
No incluyas Markdown, campos adicionales, instrucciones
ejecutables ni texto fuera del JSON.

Tu respuesta representa solamente una propuesta.
Nunca una orden ejecutada.
""".strip()


class FinancialContext(BaseModel):

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True
    )

    symbol: Literal["BTCUSDT"] = "BTCUSDT"

    mode: Literal["PAPER_LIVE", "REPLAY"]

    candle_date: date

    as_of_utc: AwareDatetime

    reference_close: FiniteFloat = Field(gt=0)

    predicted_return: FiniteFloat = Field(gt=-1)

    returns_20: tuple[FiniteFloat, ...] = Field(
        min_length=20,
        max_length=20
    )

    sma_distance_20: FiniteFloat

    volatility_20: FiniteFloat = Field(ge=0)

    cash_micros: int = Field(ge=0)

    quantity_sats: int = Field(ge=0)

    day_start_equity_micros: int | None = Field(
        default=None,
        gt=0
    )

    portfolio_status: Literal[
        "ACTIVE", "PAUSED", "STOPPED"
    ]

    max_exposure_bps: int = Field(
        ge=0,
        le=10000
    )

    max_daily_loss_bps: int = Field(
        ge=0,
        le=10000
    )

    max_data_age_seconds: int = Field(gt=0)

    min_order_micros: int = Field(gt=0)

    fee_bps: int = Field(ge=0, le=10000)

    slippage_bps: int = Field(ge=0, le=10000)

    prediction_threshold: FiniteFloat = Field(gt=0)

    emergency_stop: bool

    @property
    def candle_close(self):

        return datetime.combine(
            self.candle_date,
            time.min,
            tzinfo=timezone.utc
        ) + timedelta(days=1)

    @model_validator(mode="after")
    def validar_contexto(self):

        if self.as_of_utc.utcoffset() != timedelta(0):

            raise ValueError(
                "La fecha de decision debe estar en UTC."
            )

        if not (
            self.candle_close
            <= self.as_of_utc
            < self.candle_close + timedelta(days=1)
        ):

            raise ValueError(
                "Instante fuera del horizonte objetivo."
            )

        if (
            self.mode == "REPLAY"
            and self.as_of_utc != self.candle_close
        ):

            raise ValueError(
                "Replay debe decidir al cierre de referencia."
            )

        if any(
            retorno <= -1
            for retorno in self.returns_20
        ):

            raise ValueError(
                "Rendimientos historicos invalidos."
            )

        precio_estimado = (
            self.reference_close
            * (1 + self.predicted_return)
        )

        if (
            not math.isfinite(precio_estimado)
            or precio_estimado <= 0
        ):

            raise ValueError(
                "Precio pronosticado invalido."
            )

        return self


# 2. Construir contexto financiero para el LLM

def build_context_data(context):

    precio_micros = price_to_micros(
        context.reference_close
    )

    valor_posicion = (
        context.quantity_sats
        * precio_micros
        // SATOSHIS
    )

    equity = (
        context.cash_micros
        + valor_posicion
    )

    exposicion = (
        valor_posicion / equity * 100
        if equity > 0 else 0.0
    )

    edad = int((
        context.as_of_utc
        - context.candle_close
    ).total_seconds())

    return {
        "prompt_version": PROMPT_VERSION,

        "mode": context.mode,

        "real_trading": False,

        "symbol": context.symbol,

        "interval": "1d",

        "timezone": "UTC",

        "candle_date": (
            context.candle_date.isoformat()
        ),

        "candle_close_utc": (
            context.candle_close.isoformat()
        ),

        "decision_as_of_utc": (
            context.as_of_utc.isoformat()
        ),

        "target_date": (
            context.candle_close.date().isoformat()
        ),

        "data_age_seconds": edad,

        "market": {
            "reference_close_usdt": (
                context.reference_close
            ),
            "price_type": "LAST_CLOSED_CANDLE",
            "execution_quote_available": False
        },

        "forecast": {
            "model": "TEC_B_LSTM_S42",
            "version": "1.0.0",
            "horizon_days": 1,
            "predicted_return_pct": (
                context.predicted_return * 100
            ),
            "predicted_close_usdt": (
                context.reference_close
                * (1 + context.predicted_return)
            ),
            "threshold_pct": (
                context.prediction_threshold * 100
            )
        },

        "technical_indicators": {
            "returns_20_pct_oldest_to_newest": [
                valor * 100
                for valor in context.returns_20
            ],
            "sma_distance_20_pct": (
                context.sma_distance_20 * 100
            ),
            "volatility_20_pct": (
                context.volatility_20 * 100
            ),
            "volatility_definition": (
                "Sample standard deviation of "
                "20 daily returns, not annualized"
            )
        },

        "portfolio": {
            "status": context.portfolio_status,
            "cash_usdt": (
                context.cash_micros / MICROS
            ),
            "bitcoin_quantity": (
                context.quantity_sats / SATOSHIS
            ),
            "position_value_at_close_usdt": (
                valor_posicion / MICROS
            ),
            "equity_at_close_usdt": (
                equity / MICROS
            ),
            "exposure_at_close_pct": exposicion,
            "day_start_equity_usdt": (
                context.day_start_equity_micros / MICROS
                if context.day_start_equity_micros
                    is not None
                else None
            )
        },

        "risk": {
            "max_exposure_pct": (
                context.max_exposure_bps / 100
            ),
            "max_daily_loss_pct": (
                context.max_daily_loss_bps / 100
            ),
            "max_data_age_seconds": (
                context.max_data_age_seconds
            ),
            "data_is_stale": (
                edad > context.max_data_age_seconds
            ),
            "min_order_usdt": (
                context.min_order_micros / MICROS
            ),
            "fee_pct": context.fee_bps / 100,
            "slippage_pct": context.slippage_bps / 100,
            "emergency_stop": context.emergency_stop,
            "short_selling": False,
            "leverage": False
        }
    }


def build_messages(context):

    datos = build_context_data(context)

    contenido = (
        "Analiza el siguiente contexto financiero y "
        "devuelve una propuesta BUY, HOLD o SELL "
        "siguiendo las instrucciones del sistema.\n\n"
        + json.dumps(
            datos,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )
    )

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": contenido
        }
    ]


def prompt_sha256():

    return hashlib.sha256(
        SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()


# 3. Contexto sintetico para pruebas

def synthetic_context():

    return FinancialContext(
        mode="PAPER_LIVE",
        candle_date=date(2024, 1, 1),
        as_of_utc=datetime(
            2024, 1, 2, 0, 10,
            tzinfo=timezone.utc
        ),
        reference_close=50000.0,
        predicted_return=0.004,
        returns_20=tuple(
            [-0.005, 0.01] * 10
        ),
        sma_distance_20=0.015,
        volatility_20=0.00769483764,
        cash_micros=50000 * MICROS,
        quantity_sats=0,
        day_start_equity_micros=50000 * MICROS,
        portfolio_status="ACTIVE",
        max_exposure_bps=2500,
        max_daily_loss_bps=200,
        max_data_age_seconds=3600,
        min_order_micros=10 * MICROS,
        fee_bps=0,
        slippage_bps=0,
        prediction_threshold=0.001,
        emergency_stop=False
    )


def main():

    print("=" * 60)
    print("FINANCEAI - PROMPT FINANCIERO")
    print("=" * 60)

    contexto = synthetic_context()

    datos = build_context_data(contexto)

    mensajes = build_messages(contexto)

    print("Version del prompt:", PROMPT_VERSION)

    print("SHA256 del prompt:", prompt_sha256())

    print("Mensajes preparados:", len(mensajes))

    print("\nCONTEXTO FINANCIERO SINTETICO:\n")

    print(json.dumps(
        datos,
        indent=4,
        ensure_ascii=False,
        allow_nan=False
    ))

    evidencia = {
        "Proyecto": "FinanceAI",
        "Etapa": "12.4",
        "Fecha_UTC": datetime.now(
            timezone.utc
        ).isoformat(),
        "Resultado": "APROBADO",
        "Prompt_version": PROMPT_VERSION,
        "SHA256_prompt": prompt_sha256(),
        "Acciones_permitidas": [
            "BUY", "HOLD", "SELL"
        ],
        "Contexto_sintetico": datos,
        "Mensajes": mensajes,
        "Inferencia_LLM_ejecutada": False,
        "Operaciones_financieras": False
    }

    ruta = (
        BASE_DIR /
        "results/control_prompt_financiero.json"
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
    print("FINANCEAI - RESULTADO DEL PROMPT")
    print("=" * 60)

    print("Prompt financiero: CONFIGURADO")
    print("Validacion de entrada: INCORPORADA")
    print("Restricciones financieras: INCORPORADAS")
    print("Control temporal: INCORPORADO")
    print("Formato de respuesta: DEFINIDO")
    print("Inferencia LLM: PENDIENTE")
    print("Datos utilizados: SINTETICOS")
    print("Base de datos modificada: NO")
    print("Modelo LSTM modificado: NO")
    print("TE reevaluado: NO")
    print("Operaciones financieras: NO")
    print("Evidencia:", ruta.name)

    print("\nPASO 12.4 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
