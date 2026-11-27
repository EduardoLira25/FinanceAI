type JsonObject = Record<string, unknown>

export type Prediction = {
  id: number
  symbol: string
  model_version: string
  reference_date: string
  reference_close: number
  predicted_price: number
  predicted_return_pct: number
  generated_at_utc: string
  target_open_utc: string
  target_close_utc: string
  inference_ms: number | null
  observed_close: number | null
  observed_return_pct: number | null
  absolute_error_pp: number | null
  observation_status: 'OBSERVED' | 'PENDING' | 'WAITING_SYNC'
}

function object(value: unknown): JsonObject {

  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new Error('Respuesta incompatible')
  }

  return value as JsonObject
}

function numeric(value: unknown): number {

  if (
    typeof value !== 'number' ||
    !Number.isFinite(value)
  ) {
    throw new Error('Valor financiero inválido')
  }

  return value
}

function nullable(value: unknown) {
  return value === null ? null : numeric(value)
}

function timestamp(value: unknown): string {

  if (
    typeof value !== 'string' ||
    !Number.isFinite(Date.parse(value))
  ) {
    throw new Error('Fecha incompatible')
  }

  return value
}

export function normalizePredictions(
  history: unknown,
  model: unknown,
  risk: unknown,
) {

  const root = object(history)

  const modelRoot = object(model)
  const riskRoot = object(risk)

  const m = modelRoot.model &&
    typeof modelRoot.model === 'object'
      ? object(modelRoot.model)
      : modelRoot

  const r = riskRoot.risk &&
    typeof riskRoot.risk === 'object'
      ? object(riskRoot.risk)
      : riskRoot

  if (
    root.real_trading !== false ||
    root.symbol !== 'BTCUSDT' ||
    !Array.isArray(root.predictions)
  ) {
    throw new Error('Historial incompatible')
  }

  const predictions: Prediction[] =
    root.predictions.map(value => {

      const p = object(value)

      const status = p.observation_status

      if (
        p.symbol !== 'BTCUSDT' ||
        p.model_version !== '1.0.0' ||
        typeof p.reference_date !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(p.reference_date) ||
        (
          status !== 'OBSERVED' &&
          status !== 'PENDING' &&
          status !== 'WAITING_SYNC'
        )
      ) {
        throw new Error('Predicción incompatible')
      }

      const prediction: Prediction = {
        id: numeric(p.id),
        symbol: p.symbol,
        model_version: p.model_version,
        reference_date: p.reference_date,
        reference_close: numeric(p.reference_close),
        predicted_price: numeric(p.predicted_price),
        predicted_return_pct: numeric(p.predicted_return_pct),
        generated_at_utc: timestamp(p.generated_at_utc),
        target_open_utc: timestamp(p.target_open_utc),
        target_close_utc: timestamp(p.target_close_utc),
        inference_ms: nullable(p.inference_ms),
        observed_close: nullable(p.observed_close),
        observed_return_pct: nullable(p.observed_return_pct),
        absolute_error_pp: nullable(p.absolute_error_pp),
        observation_status: status,
      }

      const start = Date.parse(prediction.target_open_utc)
      const end = Date.parse(prediction.target_close_utc)
      const generated = Date.parse(prediction.generated_at_utc)

      if (
        prediction.reference_close <= 0 ||
        prediction.predicted_price <= 0 ||
        end - start !== 86400000 ||
        generated < start ||
        generated >= end ||
        (
          status === 'OBSERVED' &&
          (
            prediction.observed_close === null ||
            prediction.observed_close <= 0 ||
            prediction.observed_return_pct === null ||
            prediction.absolute_error_pp === null
          )
        ) ||
        (
          status !== 'OBSERVED' &&
          (
            prediction.observed_close !== null ||
            prediction.observed_return_pct !== null ||
            prediction.absolute_error_pp !== null
          )
        )
      ) {
        throw new Error('Datos predictivos inconsistentes')
      }

      const expectedPrice =
        prediction.reference_close *
        (1 + prediction.predicted_return_pct / 100)

      if (
        Math.abs(
          expectedPrice - prediction.predicted_price,
        ) > 1e-6
      ) {
        throw new Error('Pronóstico inconsistente')
      }

      return prediction
    })

  const threshold = numeric(r.prediction_threshold)
  const maxDataAgeSeconds = numeric(r.max_data_age_seconds)
  const total = numeric(root.total)

  if (
    threshold <= 0 ||
    maxDataAgeSeconds <= 0 ||
    !Number.isInteger(total) ||
    total < predictions.length
  ) {
    throw new Error('Configuración incompatible')
  }

  return {
    predictions,
    total,
    threshold,
    maxDataAgeSeconds,
    modelVersion: String(m.version ?? '1.0.0'),
    windowSize: numeric(m.window_size),
    featureCount: numeric(m.feature_count),
    modelVerified: m.integrity_verified === true,
  }
}

export type PredictionData =
  ReturnType<typeof normalizePredictions>

export function getPredictionStatus(
  prediction: Prediction,
  now: number,
  maxAgeSeconds: number,
) {

  const start = Date.parse(
    prediction.target_open_utc,
  )

  const end = Date.parse(
    prediction.target_close_utc,
  )

  const ageSeconds = (now - start) / 1000

  return {
    expired: now >= end,
    dataAgeSeconds: ageSeconds,
    outsideWindow:
      ageSeconds < 0 ||
      ageSeconds > maxAgeSeconds ||
      now >= end,
  }
}
