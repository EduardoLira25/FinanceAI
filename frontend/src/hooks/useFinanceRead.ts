import { useEffect, useState } from 'react'

import { getApi } from '../services/api'
import type { ReadEndpoint } from '../services/api'

type Result<T> =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: T }

export function useFinanceRead<T>(
  endpoint: ReadEndpoint,
  params: Record<string, string | number> = {},
) {

  const [revision, setRevision] = useState(0)

  const query = JSON.stringify(params)
  const key = `${endpoint}:${query}:${revision}`

  const [result, setResult] = useState<{
    key: string
    state: Result<T>
  }>({
    key: '',
    state: { status: 'loading' },
  })

  useEffect(() => {

    const controller = new AbortController()
    let disposed = false

    const timeout = window.setTimeout(
      () => controller.abort(), 20000,
    )

    async function load() {

      try {

        const data = await getApi<T & {
          real_trading: boolean
        }>(
          endpoint,
          JSON.parse(query),
          controller.signal,
        )

        if (
          !data ||
          data.real_trading !== false
        ) {
          throw new Error('Modo incompatible')
        }

        if (!disposed) {

          setResult({
            key,
            state: { status: 'ready', data },
          })
        }

      } catch {

        if (!disposed) {

          setResult({
            key,
            state: { status: 'error' },
          })
        }

      } finally {

        window.clearTimeout(timeout)
      }
    }

    void load()

    return () => {
      disposed = true
      controller.abort()
      window.clearTimeout(timeout)
    }

  }, [endpoint, query, key])

  const state: Result<T> = result.key === key
    ? result.state
    : { status: 'loading' }

  return {
    state,
    refresh: () => setRevision(n => n + 1),
  }
}
