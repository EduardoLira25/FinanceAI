import { useEffect, useState } from 'react'

import { Link } from 'react-router-dom'

import {
  Activity,
  Wallet,
  TrendingUp,
  Bot,
  ShieldCheck,
  Database,
  Globe,
  CheckCircle2,
  Clock,
  RefreshCw,
  AlertTriangle,
  Bitcoin,
  ArrowUpRight,
} from 'lucide-react'

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts'

import { getApi, ApiError } from '../services/api'

import {
  normalizeDashboard,
} from '../services/dashboardData'

import type {
  DashboardData,
} from '../services/dashboardData'


const money = new Intl.NumberFormat('es-MX', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function signed(value: number, digits = 2) {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`
}

type DashboardState =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready'
      data: DashboardData
      updatedAt: Date
    }


export default function Dashboard() {

  const [state, setState] =
    useState<DashboardState>({ status: 'loading' })

  const [refresh, setRefresh] = useState(0)

  const [range, setRange] = useState(90)

  const [now, setNow] = useState(
    () => Date.now(),
  )

  useEffect(() => {

    const timer = window.setInterval(
      () => setNow(Date.now()),
      1000,
    )

    return () => window.clearInterval(timer)

  }, [])


  useEffect(() => {

    const controller = new AbortController()

    let disposed = false

    const timeout = window.setTimeout(
      () => controller.abort(),
      20000,
    )

    const signal = controller.signal

    async function load() {

      try {

        const [
          status,
          database,
          model,
          portfolio,
          candles,
          prediction,
          risk,
        ] = await Promise.all([

          getApi('status', {}, signal),

          getApi('database/status', {}, signal),

          getApi('model/status', {}, signal),

          getApi('portfolio', {}, signal),

          getApi(
            'market/candles',
            { symbol: 'BTCUSDT', limit: 90 },
            signal,
          ),

          getApi(
            'predictions/latest', {}, signal,
          ).catch((error: unknown) => {

            if (
              error instanceof ApiError &&
              error.status === 404
            ) {
              return null
            }

            throw error
          }),

          getApi('risk/config', {}, signal),
        ])

        const data = normalizeDashboard({
          status,
          database,
          model,
          portfolio,
          candles,
          prediction,
          risk,
        })

        if (!disposed) {

          setState({
            status: 'ready',
            data,
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


  function reload() {
    setState({ status: 'loading' })
    setRefresh(value => value + 1)
  }


  const data = state.status === 'ready'
    ? state.data
    : null

  const predictionExpired =
    data?.prediction
      ? Date.parse(data.prediction.targetClose) <= now
      : false

  const metrics = [
    {
      label: 'Patrimonio virtual',
      value: data ? money.format(data.equity) : '—',
      detail: 'USDT · Valorado al último cierre',
      icon: Wallet,
      color: '',
    },
    {
      label: 'Rendimiento acumulado',
      value: data ? signed(data.returnPct) : '—',
      detail: 'Respecto al capital inicial',
      icon: TrendingUp,
      color: data && data.returnPct < 0
        ? 'negative'
        : 'positive',
    },
    {
      label: 'Predicción LSTM',
      value: data?.prediction
        ? signed(data.prediction.predictedReturnPct, 4)
        : '—',
      detail: predictionExpired
        ? 'Pronóstico almacenado · Vencido'
        : 'Pronóstico almacenado',
      icon: Activity,
      color: data?.prediction &&
        data.prediction.predictedReturnPct < 0
          ? 'negative'
          : 'positive',
    },
    {
      label: 'Estado del agente',
      value: data?.risk.emergencyStop
        ? 'STOP'
        : data?.portfolioStatus ?? '—',
      detail: 'Estado operativo de la cartera',
      icon: Bot,
      color: data?.portfolioStatus === 'ACTIVE' &&
        !data.risk.emergencyStop
          ? 'positive'
          : 'warning',
    },
  ]

  return (
    <div className="page">

      <div className="page-heading">

        <div>
          <div className="eyebrow">
            FINANCEAI / OVERVIEW
          </div>

          <h1>Dashboard</h1>

          <p>Centro de control financiero inteligente.</p>
        </div>

        <div className="dashboard-actions">

          <button
            className="refresh-button"
            onClick={reload}
            disabled={state.status === 'loading'}
          >
            <RefreshCw size={16} />
            Actualizar
          </button>

          <div className="mode-tag">
            <ShieldCheck size={17} />
            SIMULACIÓN
          </div>

        </div>
      </div>

      {state.status === 'loading' && (
        <div className="notice" role="status">
          <RefreshCw size={19} />
          Consultando información financiera...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          <AlertTriangle size={20} />
          <div>
            <strong>No fue posible obtener los datos</strong>
            <p>
              Verifica la conexión con FastAPI
              y vuelve a actualizar.
            </p>
          </div>
        </div>
      )}

      {state.status === 'ready' && (
        <div className="data-strip">

          <span className="positive">
            <CheckCircle2 size={16} />
            Datos almacenados verificados
          </span>

          <span>
            Consulta: {state.updatedAt.toLocaleString('es-MX')}
          </span>

          <span>
            Última vela: {state.data.latestDate} UTC
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

              <div className={`metric-value ${metric.color}`}>
                {metric.value}
              </div>

              <div className="muted">
                {metric.detail}
              </div>

            </article>
          )
        })}

      </section>

      {data && (
        <>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">

                <div>
                  <h2>Bitcoin / USDT</h2>
                  <p>Cierres diarios históricos · MEXC</p>
                </div>

                <div className="range-buttons">

                  {[7, 30, 90].map(days => (

                    <button
                      key={days}
                      className={range === days
                        ? 'selected'
                        : ''}
                      onClick={() => setRange(days)}
                      aria-pressed={range === days}
                    >
                      {days}D
                    </button>
                  ))}

                </div>
              </div>

              <div className="market-price">

                <Bitcoin size={24} />

                <strong>
                  {money.format(data.latestClose)}
                </strong>

                <span>USDT</span>

              </div>

              <div className="muted">
                Último cierre almacenado, no precio en tiempo real.
              </div>

              <div className="market-chart">

                <ResponsiveContainer
                  width="100%"
                  height="100%"
                >

                  <AreaChart
                    data={data.candles.slice(-range)}
                    margin={{
                      top: 20,
                      left: 8,
                      right: 12,
                      bottom: 5,
                    }}
                  >

                    <defs>
                      <linearGradient
                        id="bitcoinGradient"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="0%"
                          stopColor="#8b83ff"
                          stopOpacity={0.35}
                        />
                        <stop
                          offset="100%"
                          stopColor="#8b83ff"
                          stopOpacity={0.01}
                        />
                      </linearGradient>
                    </defs>

                    <CartesianGrid
                      stroke="#243148"
                      strokeDasharray="3 4"
                      vertical={false}
                    />

                    <XAxis
                      dataKey="date"
                      tick={{ fill: '#95a5bd', fontSize: 10 }}
                      tickFormatter={date =>
                        String(date).slice(5)
                      }
                      axisLine={false}
                      tickLine={false}
                    />

                    <YAxis
                      domain={['auto', 'auto']}
                      tick={{ fill: '#95a5bd', fontSize: 10 }}
                      tickFormatter={value =>
                        `${(Number(value) / 1000).toFixed(1)}k`
                      }
                      axisLine={false}
                      tickLine={false}
                      width={48}
                    />

                    <Tooltip
                      contentStyle={{
                        background: '#172236',
                        border: '1px solid #34435e',
                        borderRadius: 8,
                      }}
                      labelStyle={{ color: '#e7edf8' }}
                      itemStyle={{ color: '#b6b2ff' }}
                    />

                    <Area
                      type="linear"
                      dataKey="close"
                      name="Cierre USDT"
                      stroke="#8b83ff"
                      strokeWidth={2.2}
                      fill="url(#bitcoinGradient)"
                      isAnimationActive={false}
                    />

                  </AreaChart>

                </ResponsiveContainer>

              </div>
            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Componentes del sistema</h2>
                  <p>Información consultada al backend</p>
                </div>
                <Activity size={20} />
              </div>

              {[
                {
                  name: 'MEXC',
                  icon: Globe,
                  detail: 'Historial almacenado disponible',
                  ready: true,
                },
                {
                  name: 'LSTM',
                  icon: Activity,
                  detail: 'Integridad del modelo predictivo',
                  ready: data.modelVerified,
                },
                {
                  name: 'Qwen3:8b',
                  icon: Bot,
                  detail: 'Sin comprobación en esta sesión',
                  ready: false,
                },
                {
                  name: 'Motor de riesgo',
                  icon: ShieldCheck,
                  detail: 'Configuración disponible',
                  ready: true,
                },
                {
                  name: 'SQLite',
                  icon: Database,
                  detail: data.totalCandles !== null
                    ? `${data.totalCandles.toLocaleString('es-MX')} velas`
                    : 'Historial disponible',
                  ready: data.databaseAvailable,
                },
              ].map(item => {

                const Icon = item.icon

                return (
                  <div
                    className="system-row"
                    key={item.name}
                  >

                    <div className="system-icon">
                      <Icon size={18} />
                    </div>

                    <div>
                      <strong>{item.name}</strong>
                      <small>{item.detail}</small>
                    </div>

                    {item.ready
                      ? <CheckCircle2
                          size={16}
                          className="system-pending positive"
                        />
                      : <Clock
                          size={16}
                          className="system-pending"
                        />
                    }

                  </div>
                )
              })}

            </section>

          </div>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Distribución del patrimonio</h2>
                  <p>Valoración al último cierre diario</p>
                </div>
                <Wallet size={20} />
              </div>

              <div className="allocation-amount">
                {money.format(data.equity)}
                <span> USDT</span>
              </div>

              <div
                className="allocation-bar"
                aria-label={
                  `Exposición BTC ${data.exposurePct.toFixed(2)}%`
                }
              >
                <div
                  className="allocation-cash"
                  style={{
                    width: `${100 - data.exposurePct}%`,
                  }}
                />
                <div
                  className="allocation-btc"
                  style={{
                    width: `${data.exposurePct}%`,
                  }}
                />
              </div>

              <div className="detail-row">
                <span>
                  <i className="legend-dot cash-dot" />
                  Efectivo
                </span>
                <strong>
                  {money.format(data.cash)} USDT
                </strong>
              </div>

              <div className="detail-row">
                <span>
                  <i className="legend-dot btc-dot" />
                  Bitcoin
                </span>
                <strong>
                  {data.bitcoin.toFixed(8)} BTC
                </strong>
              </div>

              <div className="detail-row">
                <span>Exposición actual</span>
                <strong>
                  {data.exposurePct.toFixed(2)}%
                </strong>
              </div>

              <div className="muted allocation-note">
                La curva histórica del patrimonio se
                incorporará al conectar el registro de ciclos.
              </div>

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Controles financieros</h2>
                  <p>Configuración vigente de riesgo</p>
                </div>
                <ShieldCheck size={20} />
              </div>

              <div className="detail-row">
                <span>Exposición máxima</span>
                <strong>{data.risk.maxExposurePct}%</strong>
              </div>

              <div className="detail-row">
                <span>Pérdida diaria máxima</span>
                <strong>{data.risk.maxDailyLossPct}%</strong>
              </div>

              <div className="detail-row">
                <span>Antigüedad máxima</span>
                <strong>
                  {data.risk.maxDataAgeSeconds / 60} min
                </strong>
              </div>

              <div className="detail-row">
                <span>Paro de emergencia</span>
                <strong className={
                  data.risk.emergencyStop
                    ? 'negative'
                    : 'positive'
                }>
                  {data.risk.emergencyStop
                    ? 'Activado'
                    : 'Desactivado'}
                </strong>
              </div>

              <Link
                to="/riesgo"
                className="dashboard-link"
              >
                Consultar módulo de riesgo
                <ArrowUpRight size={15} />
              </Link>

            </section>

          </div>

          {data.prediction && (

            <section className="panel forecast-panel">

              <div>
                <div className="eyebrow">
                  MODELO LSTM
                </div>

                <h2>Último pronóstico registrado</h2>

                <p>
                  Horizonte: {
                    new Date(
                      data.prediction.targetClose,
                    ).toLocaleString('es-MX', {
                      timeZone: 'UTC',
                    })
                  } UTC
                </p>

                <p>
                  {predictionExpired
                    ? 'Pronóstico vencido; no utilizar para nuevas operaciones.'
                    : 'Estimación estadística, no garantía de rendimiento.'}
                </p>
              </div>

              <div className="forecast-price">
                <span>Cierre estimado</span>
                <strong>
                  {money.format(
                    data.prediction.predictedPrice,
                  )} USDT
                </strong>
              </div>

              <Link
                to="/predicciones"
                className="dashboard-link"
              >
                Ver predicciones
                <ArrowUpRight size={15} />
              </Link>

            </section>
          )}

        </>
      )}

      <section className="panel audit-panel">
        <div>
          <div className="eyebrow">
            ÚLTIMA AUDITORÍA DOCUMENTADA
          </div>
          <h2>Etapa 12 completada</h2>
          <p>Resultados históricos de desarrollo.</p>
        </div>

        <div className="audit-metric">
          <strong>282/282</strong>
          <span>Pruebas del agente</span>
        </div>

        <div className="audit-metric">
          <strong>95/95</strong>
          <span>Controles aprobados</span>
        </div>
      </section>

    </div>
  )
}
