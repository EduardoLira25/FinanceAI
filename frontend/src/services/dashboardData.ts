type JsonObject = Record<string, unknown>

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

function unwrap(value: unknown, key: string) {

  const root = object(value)

  return typeof root[key] === 'object' &&
    root[key] !== null &&
    !Array.isArray(root[key])
    ? object(root[key])
    : root
}

export type MarketPoint = {
  date: string
  close: number
}

export type DashboardData = {
  cash: number
  initialCash: number
  bitcoin: number
  positionValue: number
  equity: number
  returnPct: number
  exposurePct: number
  portfolioStatus: string
  latestClose: number
  latestDate: string
  candles: MarketPoint[]
  totalCandles: number | null
  modelVerified: boolean
  databaseAvailable: boolean
  prediction: {
    predictedReturnPct: number
    predictedPrice: number
    targetClose: string
    generatedAt: string
  } | null
  risk: {
    maxExposurePct: number
    maxDailyLossPct: number
    maxDataAgeSeconds: number
    emergencyStop: boolean
  }
}

export function normalizeDashboard(
  payload: JsonObject,
): DashboardData {

  const status = object(payload.status)

  if (status.real_trading !== false) {
    throw new Error('Modo financiero incompatible')
  }

  const portfolio = unwrap(
    payload.portfolio, 'portfolio',
  )

  const cash = numeric(
    portfolio.cash ?? portfolio.cash_usdt,
  )

  const initialCash = numeric(
    portfolio.initial_cash ??
    portfolio.initial_cash_usdt,
  )

  if (cash < 0 || initialCash <= 0) {
    throw new Error('Capital incompatible')
  }

  if (!Array.isArray(portfolio.positions)) {
    throw new Error('Posiciones no disponibles')
  }

  let bitcoin = 0

  for (const item of portfolio.positions) {

    const position = object(item)

    if (position.symbol !== 'BTCUSDT') {
      throw new Error('Activo incompatible')
    }

    const quantity = numeric(
      position.quantity ?? position.quantity_btc,
    )

    if (quantity < 0) {
      throw new Error('Posición inválida')
    }

    bitcoin += quantity
  }

  const portfolioStatus = String(portfolio.status)

  if (!['ACTIVE', 'PAUSED', 'STOPPED'].includes(
    portfolioStatus,
  )) {
    throw new Error('Estado de cartera incompatible')
  }

  const market = object(payload.candles)

  const rows =
    market.candles ??
    market.data ??
    market.items ??
    market.results

  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error('Historial de mercado no disponible')
  }

  const candles = rows.map((row): MarketPoint => {

    const candle = object(row)
    const close = numeric(candle.close)

    if (close <= 0) {
      throw new Error('Precio de cierre inválido')
    }

    let date = candle.date

    if (typeof date !== 'string') {

      if (typeof candle.open_time === 'number') {

        date = new Date(
          candle.open_time * 1000,
        ).toISOString().slice(0, 10)

      } else if (typeof candle.open_time === 'string') {

        date = candle.open_time.slice(0, 10)
      }
    }

    if (
      typeof date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      !Number.isFinite(Date.parse(date))
    ) {
      throw new Error('Fecha de mercado inválida')
    }

    return { date, close }

  }).sort((a, b) => a.date.localeCompare(b.date))

  if (new Set(candles.map(c => c.date)).size !== candles.length) {
    throw new Error('Velas duplicadas')
  }

  const latest = candles[candles.length - 1]

  const positionValue = bitcoin * latest.close
  const equity = cash + positionValue

  const returnPct =
    (equity / initialCash - 1) * 100

  const exposurePct =
    equity > 0 ? positionValue / equity * 100 : 0

  const database = unwrap(
    payload.database, 'database',
  )

  const model = unwrap(payload.model, 'model')

  const risk = unwrap(payload.risk, 'risk')

  let prediction: DashboardData['prediction'] = null

  if (payload.prediction !== null) {

    const p = unwrap(
      payload.prediction, 'prediction',
    )

    const predictedPrice = numeric(p.predicted_price)

    const predictedReturnPct = numeric(
      p.predicted_return_pct,
    )

    if (
      predictedPrice <= 0 ||
      typeof p.target_close_utc !== 'string' ||
      typeof p.generated_at_utc !== 'string' ||
      !Number.isFinite(Date.parse(p.target_close_utc)) ||
      !Number.isFinite(Date.parse(p.generated_at_utc))
    ) {
      throw new Error('Predicción incompatible')
    }

    prediction = {
      predictedPrice,
      predictedReturnPct,
      targetClose: p.target_close_utc,
      generatedAt: p.generated_at_utc,
    }
  }

  const total =
    database.historical_candles ??
    market.total

  const maxExposurePct = numeric(
    risk.max_exposure_pct,
  )

  const maxDailyLossPct = numeric(
    risk.max_daily_loss_pct,
  )

  const maxDataAgeSeconds = numeric(
    risk.max_data_age_seconds,
  )

  if (
    maxExposurePct < 0 ||
    maxExposurePct > 100 ||
    maxDailyLossPct < 0 ||
    maxDailyLossPct > 100 ||
    maxDataAgeSeconds <= 0 ||
    typeof risk.emergency_stop !== 'boolean'
  ) {
    throw new Error('Configuración de riesgo inválida')
  }

  return {
    cash,
    initialCash,
    bitcoin,
    positionValue,
    equity,
    returnPct,
    exposurePct,
    portfolioStatus,
    latestClose: latest.close,
    latestDate: latest.date,
    candles,
    totalCandles:
      typeof total === 'number' ? total : null,
    modelVerified: model.integrity_verified === true,
    databaseAvailable: database.status === 'ok',
    prediction,
    risk: {
      maxExposurePct,
      maxDailyLossPct,
      maxDataAgeSeconds,
      emergencyStop: risk.emergency_stop,
    },
  }
}
