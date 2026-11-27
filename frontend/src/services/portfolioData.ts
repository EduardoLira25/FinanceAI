export type Valuation = {
  id: number
  date: string
  cash: number
  position_value: number
  equity: number
  drawdown_pct: number
}

export type PortfolioOverview = {
  name: string
  status: string
  currency: string
  initial_cash: number
  cash: number
  bitcoin_quantity: number
  position_value: number
  cost_basis: number
  unrealized_pnl: number
  equity: number
  return_pct: number
  exposure_pct: number
  reference_price: number
  reference_date: string
  reference_close_utc: string
  max_recorded_drawdown_pct: number | null
  total_snapshots: number
  total_valuations: number
  valuations: Valuation[]
  filled_orders: number
  buys: number
  sells: number
  fees_usdt: number
  slippage_usdt: number
  real_trading: false
}

export type PaperOrder = {
  id: number
  cycle_id: number
  symbol: string
  side: 'BUY' | 'SELL'
  status: 'FILLED' | 'PENDING' | 'REJECTED' | 'CANCELLED'
  quantity_btc: number
  price_usdt: number | null
  notional_usdt: number | null
  fee_usdt: number
  slippage_usdt: number
  reference_date: string
  created_at_utc: string
  filled_at_utc: string | null
  execution_source: string | null
}

export type OrderHistory = {
  orders: PaperOrder[]
  total: number
  returned: number
  offset: number
  limit: number
  has_more: boolean
  real_trading: false
}

const formatter = new Intl.NumberFormat('es-MX', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function money(value: number | null) {
  return value === null ? '—' : formatter.format(value)
}

export function percent(value: number | null) {
  if (value === null) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function utcDate(value: string | null) {

  if (value === null) return '—'

  return new Date(value).toLocaleString('es-MX', {
    timeZone: 'UTC',
  }) + ' UTC'
}
