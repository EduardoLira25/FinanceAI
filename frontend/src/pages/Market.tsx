import { useEffect, useState } from 'react'

import {
  Bitcoin,
  Activity,
  TrendingUp,
  BarChart3,
  RefreshCw,
  AlertTriangle,
} from 'lucide-react'

import { getApi } from '../services/api'

import {
  normalizeMarket,
} from '../services/marketData'

import type {
  MarketCandle,
} from '../services/marketData'

import MarketChart from '../components/MarketChart'

const money = new Intl.NumberFormat('es-MX', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function price(value: number | null) {
  return value === null
    ? '—'
    : money.format(value)
}

function pct(value: number | null) {

  if (value === null) return '—'

  const percent = value * 100

  return `${percent > 0 ? '+' : ''}${percent.toFixed(4)}%`
}

type State =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready'
      candles: MarketCandle[]
      updatedAt: Date
    }

export default function Market() {

  const [state, setState] =
    useState<State>({ status: 'loading' })

  const [refresh, setRefresh] = useState(0)

  const [range, setRange] = useState(90)

  const [mode, setMode] =
    useState<'candles' | 'line'>('candles')

  const [showSma, setShowSma] = useState(true)

  const [selectedDate, setSelectedDate] =
    useState('')

  useEffect(() => {

    let disposed = false

    const controller = new AbortController()

    const timeout = window.setTimeout(
      () => controller.abort(),
      20000,
    )

    async function load() {

      try {

        const response = await getApi(
          'market/candles',
          {
            symbol: 'BTCUSDT',
            limit: 385,
          },
          controller.signal,
        )

        const candles = normalizeMarket(response)

        if (!disposed) {

          setState({
            status: 'ready',
            candles,
            updatedAt: new Date(),
          })
        }

      } catch {

        if (!disposed) {
          setState({ status: 'error' })
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

  }, [refresh])

  const candles = state.status === 'ready'
    ? state.candles
    : []

  const visible = candles.slice(-range)

  const latest = candles.at(-1)

  const selected = visible.find(
    c => c.date === selectedDate,
  ) ?? latest

  const metrics = [
    {
      label: 'Último cierre',
      value: latest ? price(latest.close) : '—',
      detail: 'BTC/USDT',
      icon: Bitcoin,
      color: '',
    },
    {
      label: 'Rendimiento diario',
      value: pct(latest?.dailyReturn ?? null),
      detail: 'Cierre respecto al día anterior',
      icon: TrendingUp,
      color: (latest?.dailyReturn ?? 0) < 0
        ? 'negative'
        : 'positive',
    },
    {
      label: 'SMA 20',
      value: price(latest?.sma20 ?? null),
      detail: 'Media móvil de 20 cierres',
      icon: Activity,
      color: '',
    },
    {
      label: 'Volatilidad diaria',
      value: latest?.volatility20 != null
        ? `${(latest.volatility20 * 100).toFixed(4)}%`
        : '—',
      detail: '20 rendimientos · No anualizada',
      icon: BarChart3,
      color: 'warning',
    },
  ]

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / MARKET
          </div>
          <h1>Mercado</h1>
          <p>
            Análisis histórico de Bitcoin y sus
            indicadores financieros.
          </p>
        </div>

        <button
          className="refresh-button"
          disabled={state.status === 'loading'}
          onClick={() => {
            setState({ status: 'loading' })
            setRefresh(n => n + 1)
          }}
        >
          <RefreshCw size={16} />
          Actualizar
        </button>
      </div>

      {state.status === 'loading' && (
        <div className="notice" role="status">
          Consultando historial financiero...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          <AlertTriangle size={20} />
          No fue posible cargar las velas de mercado.
        </div>
      )}

      {state.status === 'ready' && (
        <div className="data-strip">
          <span className="positive">
            MEXC · Historial almacenado
          </span>
          <span>
            Última vela: {latest?.date} UTC
          </span>
          <span>
            Consulta: {
              state.updatedAt.toLocaleString('es-MX')
            }
          </span>
        </div>
      )}

      <section className="metrics-grid">
        {metrics.map(metric => {

          const Icon = metric.icon

          return (
            <article
              className="metric-card"
              key={metric.label}
            >
              <div className="metric-top">
                <span>{metric.label}</span>
                <div className="metric-icon">
                  <Icon size={19} />
                </div>
              </div>

              <div
                className={`metric-value ${metric.color}`}
              >
                {metric.value}
              </div>

              <div className="muted">
                {metric.detail}
              </div>
            </article>
          )
        })}
      </section>

      {latest && selected && (
        <>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Bitcoin / USDT</h2>
                <p>
                  Velas diarias cerradas · MEXC · UTC
                </p>
              </div>
              <Bitcoin size={25} color="#f4a940" />
            </div>

            <div className="market-toolbar">

              <div className="range-buttons">
                {[7, 30, 90, 180, 365].map(days => (
                  <button
                    key={days}
                    className={
                      range === days ? 'selected' : ''
                    }
                    aria-pressed={range === days}
                    onClick={() => {
                      setRange(days)
                      setSelectedDate('')
                    }}
                  >
                    {days}D
                  </button>
                ))}
              </div>

              <div className="range-buttons">

                <button
                  className={
                    mode === 'candles' ? 'selected' : ''
                  }
                  onClick={() => setMode('candles')}
                  aria-pressed={mode === 'candles'}
                >
                  Velas
                </button>

                <button
                  className={
                    mode === 'line' ? 'selected' : ''
                  }
                  onClick={() => setMode('line')}
                  aria-pressed={mode === 'line'}
                >
                  Línea
                </button>

                <button
                  className={showSma ? 'selected' : ''}
                  onClick={() => setShowSma(v => !v)}
                  aria-pressed={showSma}
                >
                  SMA 20
                </button>

              </div>

            </div>

            <div className="market-ohlc">

              <label>
                Vela consultada

                <select
                  value={selected.date}
                  onChange={event =>
                    setSelectedDate(event.target.value)
                  }
                >
                  {visible.map(c => (
                    <option
                      key={c.date}
                      value={c.date}
                    >
                      {c.date}
                    </option>
                  ))}
                </select>
              </label>

              {[
                ['Apertura', selected.open],
                ['Máximo', selected.high],
                ['Mínimo', selected.low],
                ['Cierre', selected.close],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <span>{label}</span>
                  <strong>{price(Number(value))}</strong>
                </div>
              ))}

            </div>

            <MarketChart
              candles={visible}
              mode={mode}
              showSma={showSma}
              selectedDate={selected.date}
              onSelect={setSelectedDate}
            />

            <div className="market-legend">
              <span className="positive">● Alcista</span>
              <span className="negative">● Bajista</span>
              {showSma && (
                <span className="warning">━ SMA 20</span>
              )}
              <span>Precios históricos, no cotización en vivo.</span>
            </div>

          </section>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Indicadores técnicos</h2>
                  <p>
                    Misma definición utilizada por el LSTM.
                  </p>
                </div>
                <Activity size={20} />
              </div>

              <div className="detail-row">
                <span>Fecha analizada</span>
                <strong>{selected.date} UTC</strong>
              </div>

              <div className="detail-row">
                <span>Rendimiento diario</span>
                <strong>{pct(selected.dailyReturn)}</strong>
              </div>

              <div className="detail-row">
                <span>Distancia respecto a SMA 20</span>
                <strong className={
                  (selected.smaDistance20 ?? 0) < 0
                    ? 'negative'
                    : 'positive'
                }>
                  {pct(selected.smaDistance20)}
                </strong>
              </div>

              <div className="detail-row">
                <span>Volatilidad de 20 rendimientos</span>
                <strong>
                  {selected.volatility20 === null
                    ? '—'
                    : `${(selected.volatility20 * 100).toFixed(4)}%`}
                </strong>
              </div>

              <div className="detail-row">
                <span>Volumen diario</span>
                <strong>
                  {money.format(selected.volume)} BTC
                </strong>
              </div>

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Información del mercado</h2>
                  <p>Origen y frecuencia de los datos.</p>
                </div>
                <Bitcoin size={20} />
              </div>

              <div className="detail-row">
                <span>Activo</span>
                <strong>BTCUSDT</strong>
              </div>

              <div className="detail-row">
                <span>Exchange</span>
                <strong>MEXC</strong>
              </div>

              <div className="detail-row">
                <span>Temporalidad</span>
                <strong>1 día</strong>
              </div>

              <div className="detail-row">
                <span>Velas visualizadas</span>
                <strong>{visible.length}</strong>
              </div>

              <div className="detail-row">
                <span>Historial consultado</span>
                <strong>{candles.length} velas</strong>
              </div>

              <div className="muted allocation-note">
                Actualizar consulta nuevamente SQLite.
                No genera órdenes ni sincroniza el mercado.
              </div>

            </section>

          </div>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Historial reciente</h2>
                <p>Últimas 20 velas del periodo mostrado.</p>
              </div>
            </div>

            <div className="market-table-scroll">

              <table className="market-table">

                <thead>
                  <tr>
                    <th>Fecha UTC</th>
                    <th>Apertura</th>
                    <th>Máximo</th>
                    <th>Mínimo</th>
                    <th>Cierre</th>
                    <th>Variación</th>
                    <th>SMA 20</th>
                    <th>Volumen BTC</th>
                  </tr>
                </thead>

                <tbody>
                  {visible.slice(-20).reverse().map(c => (
                    <tr key={c.date}>
                      <td>{c.date}</td>
                      <td>{price(c.open)}</td>
                      <td>{price(c.high)}</td>
                      <td>{price(c.low)}</td>
                      <td>{price(c.close)}</td>

                      <td className={
                        (c.dailyReturn ?? 0) < 0
                          ? 'negative'
                          : 'positive'
                      }>
                        {pct(c.dailyReturn)}
                      </td>

                      <td>{price(c.sma20)}</td>
                      <td>{money.format(c.volume)}</td>
                    </tr>
                  ))}
                </tbody>

              </table>

            </div>

          </section>

        </>
      )}

    </div>
  )
}
