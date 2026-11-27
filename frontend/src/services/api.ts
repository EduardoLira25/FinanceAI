export class ApiError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`FinanceAI: HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
  }
}

export type ReadEndpoint =
  | 'status'
  | 'database/status'
  | 'model/status'
  | 'portfolio'
  | 'portfolio/overview'
  | 'orders/history'
  | 'market/assets'
  | 'market/latest'
  | 'market/candles'
  | 'predictions/latest'
  | 'predictions/history'
  | 'agent/status'
  | 'agent/recovery/status'
  | 'agent/decisions'
  | 'risk/config'
  | 'risk/overview'
  | 'incidents/history'

export async function getApi<T>(
  endpoint: ReadEndpoint,
  params: Record<string, string | number> = {},
  signal?: AbortSignal,
): Promise<T> {

  const query = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value))
  }

  const suffix = query.size ? `?${query}` : ''

  const response = await fetch(
    `/bridge/${endpoint}${suffix}`,
    {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: {
        Accept: 'application/json',
        'X-FinanceAI-Client': 'browser',
      },
      signal,
    },
  )

  if (!response.ok) {
    throw new ApiError(response.status)
  }

  return await response.json() as T
}
