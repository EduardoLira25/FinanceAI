import { ApiError } from './api'

export type RecoveryStatus = {
  portfolio_status: string
  emergency_stop: boolean
  pending_incident_ids: number[]
  pending_count: number
  non_recoverable_count: number
  incomplete_cycles: number
  can_recover: boolean
  can_reset: boolean
  risk_version: number
  real_trading: false
}

export async function requestRecovery(
  action: 'recover' | 'reset',
  reason: string,
  ids: number[],
): Promise<{ status: string; real_trading: false }> {

  const response = await fetch(
    `/control/agent/${action}`,
    {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-FinanceAI-Client': 'browser',
      },
      body: JSON.stringify({
        confirm: 'PAPER_ONLY',
        reason: reason.trim(),
        incident_ids: ids,
      }),
    },
  )

  if (!response.ok) {
    throw new ApiError(response.status)
  }

  const data = await response.json()

  if (
    data.real_trading !== false ||
    typeof data.status !== 'string'
  ) {
    throw new Error('Respuesta incompatible')
  }

  return data
}
