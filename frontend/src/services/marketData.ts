export type MarketCandle = {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  dailyReturn: number | null
  sma20: number | null
  smaDistance20: number | null
  volatility20: number | null
}

type JsonObject = Record<string, unknown>

function object(value: unknown): JsonObject {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new Error('Objeto inválido')
  }

  return value as JsonObject
}

function numeric(value: unknown): number {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value)
  ) {
    throw new Error('Valor de mercado inválido')
  }

  return value
}

export function normalizeMarket(
  payload: unknown,
): MarketCandle[] {

  const root = object(payload)

  const rows =
    root.candles ??
    root.data ??
    root.items ??
    root.results

  if (!Array.isArray(rows) || rows.length < 21) {
    throw new Error('Historial insuficiente')
  }

  const candles: MarketCandle[] = rows.map(item => {

    const row = object(item)

    let date = row.date

    if (typeof date !== 'string') {

      if (typeof row.open_time === 'number') {
        date = new Date(
          row.open_time * 1000,
        ).toISOString().slice(0, 10)
      } else if (typeof row.open_time === 'string') {
        date = row.open_time.slice(0, 10)
      }
    }

    if (
      typeof date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      !Number.isFinite(Date.parse(date)) ||
      new Date(date).toISOString().slice(0, 10) !== date
    ) {
      throw new Error('Fecha inválida')
    }

    const open = numeric(row.open)
    const high = numeric(row.high)
    const low = numeric(row.low)
    const close = numeric(row.close)
    const volume = numeric(row.volume)

    if (
      Math.min(open, high, low, close) <= 0 ||
      high < Math.max(open, close, low) ||
      low > Math.min(open, close, high) ||
      volume < 0
    ) {
      throw new Error('Vela OHLCV inválida')
    }

    return {
      date,
      open,
      high,
      low,
      close,
      volume,
      dailyReturn: null,
      sma20: null,
      smaDistance20: null,
      volatility20: null,
    }
  })

  candles.sort(
    (a, b) => a.date.localeCompare(b.date),
  )

  for (let i = 0; i < candles.length; i++) {

    const candle = candles[i]

    if (i > 0) {

      const previous = candles[i - 1]

      if (
        Date.parse(candle.date) -
        Date.parse(previous.date) !== 86400000
      ) {
        throw new Error(
          'Historial duplicado o discontinuo',
        )
      }

      candle.dailyReturn =
        candle.close / previous.close - 1
    }

    if (i >= 19) {

      const window = candles.slice(i - 19, i + 1)

      candle.sma20 = window.reduce(
        (sum, c) => sum + c.close,
        0,
      ) / 20

      candle.smaDistance20 =
        candle.close / candle.sma20 - 1
    }

    if (i >= 20) {

      const returns = candles
        .slice(i - 19, i + 1)
        .map(c => c.dailyReturn as number)

      const mean = returns.reduce(
        (sum, r) => sum + r,
        0,
      ) / 20

      const variance = returns.reduce(
        (sum, r) => sum + (r - mean) ** 2,
        0,
      ) / 19

      candle.volatility20 = Math.sqrt(variance)
    }
  }

  return candles
}
