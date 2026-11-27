import { useEffect, useState } from 'react'

import {
  Activity,
  Brain,
  Clock,
  TrendingUp,
  Bitcoin,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react'

import { getApi } from '../services/api'

import {
  normalizePredictions,
  getPredictionStatus,
} from '../services/predictionData'

import type {
  PredictionData,
  Prediction,
} from '../services/predictionData'


const money = new Intl.NumberFormat('es-MX', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function price(value: number | null) {
  return value === null ? '—' : money.format(value)
}

function pct(value: number | null) {

  if (value === null) return '—'

  return `${value > 0 ? '+' : ''}${value.toFixed(4)}%`
}

function utc(value: string) {
  return new Date(value).toLocaleString('es-MX', {
    timeZone: 'UTC',
  }) + ' UTC'
}

function observationLabel(p: Prediction, now: number) {

  if (p.observation_status === 'OBSERVED') {
    return 'Observado'
  }

  if (
    p.observation_status === 'WAITING_SYNC' ||
    now >= Date.parse(p.target_close_utc)
  ) {
    return 'Cierre por sincronizar'
  }

  return 'Pendiente de cierre'
}

type State =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: PredictionData }

export default function Predictions() {

  const [state, setState] =
    useState<State>({ status: 'loading' })

  const [refresh, setRefresh] = useState(0)

  const [selectedId, setSelectedId] =
    useState<number | null>(null)

  const [now, setNow] = useState(() => Date.now())

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

        const [history, model, risk] =
          await Promise.all([
            getApi(
              'predictions/history',
              { limit: 100 },
              signal,
            ),
            getApi('model/status', {}, signal),
            getApi('risk/config', {}, signal),
          ])

        const data = normalizePredictions(
          history, model, risk,
        )

        if (!disposed) {
          setState({ status: 'ready', data })
          setNow(Date.now())
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

  const data = state.status === 'ready'
    ? state.data
    : null

  const latest = data?.predictions[0]

  const selected = data?.predictions.find(
    p => p.id === selectedId,
  ) ?? latest

  const temporal = selected && data
    ? getPredictionStatus(
        selected, now, data.maxDataAgeSeconds,
      )
    : null

  const signal = selected && data
    ? selected.predicted_return_pct >
        data.threshold * 100
      ? 'BUY'
      : 'SELL'
    : '—'

  const metrics = [
    {
      label: 'Precio de referencia',
      value: selected
        ? price(selected.reference_close)
        : '—',
      detail: 'USDT · Último cierre de referencia',
      icon: Bitcoin,
      color: '',
    },
    {
      label: 'Precio pronosticado',
      value: selected
        ? price(selected.predicted_price)
        : '—',
      detail: 'USDT · Estimación del LSTM',
      icon: TrendingUp,
      color: '',
    },
    {
      label: 'Rendimiento esperado',
      value: pct(
        selected?.predicted_return_pct ?? null,
      ),
      detail: 'Pronóstico diario',
      icon: Activity,
      color: (selected?.predicted_return_pct ?? 0) < 0
        ? 'negative'
        : 'positive',
    },
    {
      label: 'Señal cuantitativa',
      value: signal,
      detail: 'No equivale a una orden',
      icon: Brain,
      color: signal === 'BUY'
        ? 'positive'
        : signal === 'SELL'
          ? 'negative'
          : '',
    },
  ]

  const observed = data?.predictions.filter(
    p => p.observation_status === 'OBSERVED',
  ) ?? []

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / PREDICTIONS
          </div>
          <h1>Predicciones</h1>
          <p>
            Pronósticos diarios del modelo LSTM.
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
          Consultando predicciones...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          <AlertTriangle size={20} />
          No fue posible consultar las predicciones.
        </div>
      )}

      {data && !selected && (
        <div className="notice">
          Todavía no existen predicciones registradas.
        </div>
      )}

      {selected && temporal && (
        <div className="data-strip">

          <span>
            Referencia: {selected.reference_date} UTC
          </span>

          <span className={
            temporal.expired ? 'warning' : 'positive'
          }>
            <Clock size={16} />
            {temporal.expired
              ? 'Pronóstico vencido'
              : 'Horizonte vigente'}
          </span>

          <span className={
            temporal.outsideWindow
              ? 'warning'
              : 'positive'
          }>
            {temporal.outsideWindow
              ? 'Fuera de ventana operativa'
              : 'Dentro de ventana temporal'}
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

      {selected && data && (

        <>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Pronóstico de precio</h2>
                  <p>
                    Comparación entre referencia,
                    estimación y resultado observado.
                  </p>
                </div>
                <TrendingUp size={20} />
              </div>

              <div className="prediction-comparison">

                <div className="prediction-point">
                  <span>Referencia</span>
                  <strong>
                    {price(selected.reference_close)}
                  </strong>
                  <small>USDT</small>
                </div>

                <div className="prediction-connector">
                  <TrendingUp size={22} />
                  <span>
                    {pct(selected.predicted_return_pct)}
                  </span>
                </div>

                <div className="prediction-point estimated">
                  <span>Estimación</span>
                  <strong>
                    {price(selected.predicted_price)}
                  </strong>
                  <small>USDT</small>
                </div>

              </div>

              <div className="detail-row">
                <span>Cierre realmente observado</span>
                <strong>
                  {selected.observed_close === null
                    ? observationLabel(selected, now)
                    : `${price(selected.observed_close)} USDT`}
                </strong>
              </div>

              <div className="detail-row">
                <span>Rendimiento observado</span>
                <strong>
                  {pct(selected.observed_return_pct)}
                </strong>
              </div>

              <div className="detail-row">
                <span>Error absoluto del pronóstico</span>
                <strong>
                  {selected.absolute_error_pp === null
                    ? 'Pendiente'
                    : `${selected.absolute_error_pp.toFixed(4)} p.p.`}
                </strong>
              </div>

              <div className="muted allocation-note">
                El precio pronosticado es una estimación
                estadística y no garantiza ganancias.
              </div>

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Modelo predictivo</h2>
                  <p>LSTM entrenado y congelado</p>
                </div>
                <Brain size={20} />
              </div>

              {[
                ['Identificador', 'TEC_B_LSTM_S42'],
                ['Versión', data.modelVersion],
                ['Arquitectura', 'LSTM'],
                [
                  'Dimensión de entrada',
                  `${data.windowSize} × ${data.featureCount}`,
                ],
                ['Parámetros entrenables', '1,425'],
                ['Horizonte', '1 día'],
                [
                  'Umbral cuantitativo',
                  pct(data.threshold * 100),
                ],
              ].map(([label, value]) => (

                <div className="detail-row" key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}

              <div className="detail-row">
                <span>Integridad</span>
                <strong className={
                  data.modelVerified
                    ? 'positive'
                    : 'warning'
                }>
                  {data.modelVerified
                    ? 'Verificada'
                    : 'No verificada'}
                </strong>
              </div>

            </section>

          </div>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Información temporal</h2>
                  <p>Fechas de emisión y horizonte</p>
                </div>
                <Clock size={20} />
              </div>

              <div className="detail-row">
                <span>ID de predicción</span>
                <strong>#{selected.id}</strong>
              </div>

              <div className="detail-row">
                <span>Generación efectiva</span>
                <strong>{utc(selected.generated_at_utc)}</strong>
              </div>

              <div className="detail-row">
                <span>Inicio del horizonte</span>
                <strong>{utc(selected.target_open_utc)}</strong>
              </div>

              <div className="detail-row">
                <span>Fin del horizonte</span>
                <strong>{utc(selected.target_close_utc)}</strong>
              </div>

              <div className="detail-row">
                <span>Tiempo de inferencia</span>
                <strong>
                  {selected.inference_ms === null
                    ? 'No disponible'
                    : `${(selected.inference_ms / 1000).toFixed(3)} s`}
                </strong>
              </div>

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Variables del modelo</h2>
                  <p>Características de entrada congeladas</p>
                </div>
                <Activity size={20} />
              </div>

              <div className="prediction-feature">
                <strong>01 · Return</strong>
                <p>Rendimiento diario cierre a cierre.</p>
              </div>

              <div className="prediction-feature">
                <strong>02 · SMA Distance 20</strong>
                <p>
                  Distancia relativa entre el cierre
                  y su media móvil de 20 días.
                </p>
              </div>

              <div className="prediction-feature">
                <strong>03 · Volatility 20</strong>
                <p>
                  Desviación estándar muestral de
                  20 rendimientos diarios.
                </p>
              </div>

            </section>

          </div>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Historial de predicciones</h2>
                <p>
                  {data.total} registradas ·
                  {observed.length} observadas entre las
                  {data.predictions.length} mostradas
                </p>
              </div>
            </div>

            <div className="market-table-scroll">

              <table className="market-table">

                <thead>
                  <tr>
                    <th>Referencia UTC</th>
                    <th>Pronóstico</th>
                    <th>Precio estimado</th>
                    <th>Cierre observado</th>
                    <th>Error (p.p.)</th>
                    <th>Estado</th>
                    <th>Detalle</th>
                  </tr>
                </thead>

                <tbody>

                  {data.predictions.map(p => (

                    <tr key={p.id}>

                      <td>{p.reference_date}</td>

                      <td className={
                        p.predicted_return_pct < 0
                          ? 'negative'
                          : 'positive'
                      }>
                        {pct(p.predicted_return_pct)}
                      </td>

                      <td>{price(p.predicted_price)}</td>

                      <td>{price(p.observed_close)}</td>

                      <td>
                        {p.absolute_error_pp === null
                          ? '—'
                          : p.absolute_error_pp.toFixed(4)}
                      </td>

                      <td>{observationLabel(p, now)}</td>

                      <td>
                        <button
                          className="refresh-button"
                          aria-pressed={p.id === selected.id}
                          onClick={() => {
                            setSelectedId(p.id)
                            window.scrollTo({
                              top: 0,
                              behavior: 'auto',
                            })
                          }}
                        >
                          Ver #{p.id}
                        </button>
                      </td>

                    </tr>
                  ))}

                </tbody>

              </table>

            </div>

          </section>

          <div className="notice">
            <ShieldCheck size={20} />
            <div>
              <strong>Pronósticos exclusivamente informativos</strong>
              <p>
                La señal cuantitativa no autoriza operaciones.
                Qwen3 y el motor de riesgo participan en
                la decisión del agente.
              </p>
            </div>
          </div>

        </>
      )}

    </div>
  )
}
