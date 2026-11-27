# Agente de inteligencia artificial

## 1. Propósito

El agente combina un pronóstico cuantitativo con un
modelo de lenguaje local para proponer acciones
financieras dentro de un sistema de Paper Trading.

## 2. Modelo cuantitativo

| Parámetro | Valor |
|---|---|
| Modelo | TEC_B_LSTM_S42 |
| Versión | 1.0.0 |
| Activo | BTCUSDT |
| Ventana | 20 |
| Forma de entrada | `[None, 20, 3]` |
| Variables | `['Return', 'SMA_Distance_20', 'Volatility_20']` |
| Parámetros | 1425 |
| Umbral | 0.001 |

El modelo estima el rendimiento del siguiente día.

Utiliza rendimientos históricos, distancia relativa
a la media móvil y volatilidad móvil.

Se utilizan 40 cierres consecutivos para construir
las 20 observaciones de entrada con indicadores técnicos.

No se realiza entrenamiento durante la operación
del agente.

## 3. Modelo de lenguaje

| Característica | Configuración |
|---|---|
| Modelo | qwen3:8b |
| Servidor | Ollama |
| Versión verificada | 0.40.18 |
| Ejecución | Local |
| Contexto | 4096 |
| Solicitudes paralelas | 1 |
| Modelos cargados simultáneamente | 1 |

El prompt incluye contexto temporal, pronóstico,
indicadores técnicos, cartera y restricciones de riesgo.

## 4. Decisiones estructuradas

Ejemplo exclusivamente ilustrativo del formato esperado:

```json
{
  "action": "HOLD",
  "symbol": "BTCUSDT",
  "candle_date": "2024-11-04",
  "rationale": "Mantener la posición según el contexto."
}
```

Las acciones admitidas son:

- BUY: propuesta de compra.
- SELL: propuesta de venta.
- HOLD: mantener el estado financiero.

El ejemplo no corresponde a una decisión histórica real.

## 5. Validación

El sistema comprueba la estructura JSON, el activo,
la fecha de referencia y la coherencia financiera.

Una respuesta inválida no se transforma automáticamente
en una operación autorizada.

El supervisor conserva el control del ciclo y el
motor de riesgo determina la autorización final.

## 6. Información temporal

El agente debe utilizar velas cerradas y datos disponibles
en el momento de la decisión.

La cotización utilizada para la ejecución en PAPER_LIVE
se obtiene después de consultar al LLM.

En REPLAY se utiliza una apertura histórica idealizada.
Ambas modalidades no deben confundirse.

## 7. Simulación comparativa

Se ejecutaron 30 ciclos para cada una de las tres
estrategias principales.

- MODEL_ONLY.
- LLM.
- BUY_HOLD.

La estrategia LLM completó 30 inferencias válidas
de Qwen3 sin fallos técnicos durante el replay.

## 8. Límites científicos

La evaluación de la integración corresponde a un
periodo retrospectivo del conjunto VA.

El conocimiento incorporado en Qwen3 puede ser
posterior a las fechas históricas.

Los resultados no constituyen una demostración
de capacidad predictiva fuera de muestra del LLM.
