import { useEffect, useState } from 'react'
import { getApi } from '../services/api'

type Connection = 'checking' | 'connected' | 'offline'

export function useBackendStatus() {

  const [connection, setConnection] =
    useState<Connection>('checking')

  useEffect(() => {

    let disposed = false

    let timer: number | undefined

    let controller: AbortController | undefined

    async function check() {

      controller = new AbortController()

      const timeout = window.setTimeout(
        () => controller?.abort(),
        10000,
      )

      try {

        const status = await getApi<{
          real_trading: boolean
        }>('status', {}, controller.signal)

        if (status.real_trading !== false) {
          throw new Error('Modo incompatible')
        }

        if (!disposed) {
          setConnection('connected')
        }

      } catch {

        if (!disposed) {
          setConnection('offline')
        }

      } finally {

        window.clearTimeout(timeout)

        if (!disposed) {
          timer = window.setTimeout(check, 30000)
        }
      }
    }

    void check()

    return () => {

      disposed = true

      controller?.abort()

      window.clearTimeout(timer)
    }

  }, [])

  return connection
}
