export type RiskConfig = {
  version: number
  max_exposure_pct: number
  max_daily_loss_pct: number
  max_data_age_seconds: number
  min_order_usdt: number
  fee_pct: number
  slippage_pct: number
  prediction_threshold_pct: number
  emergency_stop: boolean
  created_at_utc: string
}

export type RiskOverview = {
  portfolio_status: string
  current: RiskConfig
  versions: RiskConfig[]
  exposure_pct: number | null
  position_value_usdt: number | null
  equity_usdt: number | null
  reference_date: string | null
  reference_close_utc: string | null
  data_age_seconds: number | null
  known_blockers: string[]
  pending_incidents: number
  checked_at_utc: string
  real_trading: false
}

export type Incident = {
  id: number
  cycle_id: number | null
  component: string
  error_type: string
  message: string
  cause: string | null
  corrective_action: string | null
  retry_count: number
  resolved: boolean
  created_at_utc: string
  resolved_at_utc: string | null
}

export type SystemLog = {
  id: number
  cycle_id: number | null
  level: string
  component: string
  message: string
  created_at_utc: string
}

export type IncidentHistory = {
  total: number
  pending: number
  resolved: number
  filtered_total: number
  has_more: boolean
  incidents: Incident[]
  system_logs: SystemLog[]
  recovery_required: boolean
  real_trading: false
}

export const blockerLabels: Record<string, string> = {
  PORTFOLIO_NOT_ACTIVE: 'Cartera no activa',
  EMERGENCY_STOP: 'Paro de emergencia activo',
  RECOVERY_REQUIRED: 'Recuperación requerida',
  MISSING_CANDLE: 'No hay una vela disponible',
  STALE_CANDLE: 'Datos fuera de la ventana operativa',
}
