import { ApiError } from './api'

export type ControlAction =
  | 'activate'
  | 'pause'
  | 'stop'
  | 'run'

export type ControlResult = {
  status: string
  real_trading: false
  changed: boolean | null
  executed: boolean | null
  incident_id: number | null
}

export async function controlAgent(
  action: ControlAction,
): Promise<ControlResult> {

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

  return data as ControlResult
}
