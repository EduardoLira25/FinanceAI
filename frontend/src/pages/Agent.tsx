import SchedulerPanel, { type SchedulerInfo } from '../components/SchedulerPanel'
import AgentControls from '../components/AgentControls'
import { useEffect, useState } from 'react'

import {
  Bot,
  Activity,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  Database,
  Globe,
  Clock,
  CheckCircle2,
  Brain,
} from 'lucide-react'

import { getApi } from '../services/api'

type Decision = {
  id: number
  cycle_id: number
  cycle_status: string
  candle_date: string
  proposed_action: string
  authorized_action: string
  rationale: string
  risk_approved: boolean
  risk_reasons: string[]
  llm_model: string | null
  latency_ms: number | null
  created_at_utc: string
  order_id: number | null
}

type AgentStatus = {
  portfolio_status: string
  emergency_stop: boolean
  recovery_required: boolean
  pending_incidents: number
  total_cycles: number
  completed_cycles: number
  rejected_cycles: number
  filled_orders: number
  scheduler_enabled: boolean
  scheduler_operational?: boolean
  scheduler?: SchedulerInfo
  real_trading: boolean
  checked_at_utc: string
  ollama: {
    available: boolean
    identity_verified: boolean
    expected_model: string
    expected_version: string
    server_version: string | null
    status: string
  }
}

type DecisionHistory = {
  total: number
  decisions: Decision[]
  real_trading: boolean
}

type State =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready'
      agent: AgentStatus
      history: DecisionHistory
    }

function actionColor(action: string) {
  return action === 'BUY'
    ? 'positive'
    : action === 'SELL'
      ? 'negative'
      : 'warning'
}

export default function Agent() {

  const [state, setState] =
    useState<State>({ status: 'loading' })

  const [refresh, setRefresh] = useState(0)

  useEffect(() => {

    let disposed = false

    const controller = new AbortController()

    const timeout = window.setTimeout(
      () => controller.abort(),
      20000,
    )

    async function load() {

      try {

        const [agent, history] = await Promise.all([
          getApi<AgentStatus>(
            'agent/status', {}, controller.signal,
          ),
          getApi<DecisionHistory>(
            'agent/decisions',
            { limit: 100 },
            controller.signal,
          ),
        ])

        if (
          agent.real_trading !== false ||
          history.real_trading !== false ||
          !Array.isArray(history.decisions) ||
          !agent.ollama ||
          !['ACTIVE', 'PAUSED', 'STOPPED'].includes(
            agent.portfolio_status,
          ) ||
          ![
            agent.total_cycles,
            agent.pending_incidents,
            agent.filled_orders,
            agent.completed_cycles,
            agent.rejected_cycles,
            history.total,
          ].every(n => Number.isInteger(n) && n >= 0)
        ) {
          throw new Error('Estado incompatible')
        }

        if (!disposed) {
          setState({
            status: 'ready',
            agent,
            history,
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

  const agent = state.status === 'ready'
    ? state.agent
    : null

  const history = state.status === 'ready'
    ? state.history
    : null

  const latest = history?.decisions[0]

  const operationalStatus = agent?.emergency_stop
    ? 'EMERGENCY STOP'
    : agent?.recovery_required
      ? 'RECOVERY REQUIRED'
      : agent?.portfolio_status ?? '—'

  const metrics = [
    {
      label: 'Estado de cartera',
      value: operationalStatus,
      icon: ShieldCheck,
      detail: 'Estado operativo persistido',
      color: operationalStatus === 'ACTIVE'
        ? 'positive' : 'warning',
    },
    {
      label: 'Modelo de lenguaje',
      value: agent?.ollama.expected_model ?? '—',
      icon: Bot,
      detail: agent?.ollama.identity_verified
        ? 'Identidad verificada'
        : 'Modelo configurado',
      color: '',
    },
    {
      label: 'Ciclos registrados',
      value: agent?.total_cycles ?? '—',
      icon: Activity,
      detail: 'Cartera principal',
      color: '',
    },
    {
      label: 'Incidentes pendientes',
      value: agent?.pending_incidents ?? '—',
      icon: AlertTriangle,
      detail: 'Registro de errores',
      color: agent?.pending_incidents
        ? 'negative' : '',
    },
  ]

  return (
    <div className="page">

      <div className="page-heading">

        <div>
          <div className="eyebrow">
            FINANCEAI / AI AGENT
          </div>

          <h1>Agente IA</h1>

          <p>
            Monitoreo del agente inteligente y sus
            decisiones financieras.
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
          Consultando estado del agente...
        </div>
      )}

      {state.status === 'error' && (
        <div
          className="notice error-notice"
          role="alert"
        >
          <AlertTriangle size={20} />
          No fue posible consultar el agente.
        </div>
      )}

      {agent && (
        <div className="data-strip">
          <span className="positive">
            PAPER TRADING · Capital virtual
          </span>
          <span>
            Programación diaria no habilitada
          </span>
          <span>
            Consulta: {
              new Date(
                agent.checked_at_utc,
              ).toLocaleString('es-MX')
            }
          </span>
        </div>
      )}

      <section className="metrics-grid">

        {metrics.map(metric => {

          const Icon = metric.icon

          return (
            <article
              key={metric.label}
              className="metric-card"
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

      {agent && history && (
        <>

          <>
          <AgentControls
            portfolioStatus={agent.portfolio_status}
            emergencyStop={agent.emergency_stop}
            recoveryRequired={agent.recovery_required}
            onRefresh={() => setRefresh(n => n + 1)}
          />
            <SchedulerPanel agent={agent} />
          </>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Motor de inteligencia artificial</h2>
                  <p>Comprobación local de Ollama.</p>
                </div>
                <Bot size={24} />
              </div>

              <div className="agent-service">

                <div className="agent-service-icon">
                  <Bot size={34} />
                </div>

                <div>
                  <h2>{agent.ollama.expected_model}</h2>

                  <p className={
                    agent.ollama.identity_verified
                      ? 'positive'
                      : 'warning'
                  }>
                    {agent.ollama.identity_verified
                      ? 'Disponible e identidad verificada'
                      : agent.ollama.available
                        ? 'Servidor disponible, identidad no verificada'
                        : 'Servidor local no disponible'}
                  </p>
                </div>

              </div>

              <div className="detail-row">
                <span>Versión esperada de Ollama</span>
                <strong>
                  {agent.ollama.expected_version}
                </strong>
              </div>

              <div className="detail-row">
                <span>Versión detectada</span>
                <strong>
                  {agent.ollama.server_version ?? '—'}
                </strong>
              </div>

              <div className="detail-row">
                <span>Identidad del modelo</span>
                <strong className={
                  agent.ollama.identity_verified
                    ? 'positive'
                    : 'warning'
                }>
                  {agent.ollama.identity_verified
                    ? 'Verificada'
                    : 'Sin verificar'}
                </strong>
              </div>

              <div className="detail-row">
                <span>Programación diaria</span>
                <strong>No habilitada</strong>
              </div>

              <p className="allocation-note">
                La consulta verifica disponibilidad
                e identidad. No inicia Ollama,
                no carga el modelo ni genera inferencias.
              </p>

            </section>

            <section className="panel">

              <div className="panel-heading">

                <div>
                  <h2>Flujo de decisión</h2>
                  <p>Arquitectura implementada.</p>
                </div>

                <Activity size={20} />

              </div>

              {[
                {
                  icon: Globe,
                  name: '01 · MEXC',
                  detail: 'Velas cerradas y cotizaciones',
                },
                {
                  icon: Brain,
                  name: '02 · LSTM',
                  detail: 'Pronóstico cuantitativo',
                },
                {
                  icon: Bot,
                  name: '03 · Qwen3',
                  detail: 'Propuesta BUY, HOLD o SELL',
                },
                {
                  icon: ShieldCheck,
                  name: '04 · Motor de riesgo',
                  detail: 'Autorización independiente',
                },
                {
                  icon: Database,
                  name: '05 · SQLite',
                  detail: 'Persistencia financiera',
                },
              ].map(item => {

                const Icon = item.icon

                return (
                  <div className="system-row" key={item.name}>
                    <div className="system-icon">
                      <Icon size={19} />
                    </div>
                    <div>
                      <strong>{item.name}</strong>
                      <small>{item.detail}</small>
                    </div>
                  </div>
                )
              })}

            </section>

          </div>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Última decisión registrada</h2>
                  <p>Exclusivamente de la cartera principal.</p>
                </div>
                <Bot size={20} />
              </div>

              {latest ? (

                <>

                  <div className="prediction-comparison">

                    <div className="prediction-point">
                      <span>Propuesta Qwen3</span>
                      <strong className={
                        actionColor(latest.proposed_action)
                      }>
                        {latest.proposed_action}
                      </strong>
                    </div>

                    <div className="prediction-connector">
                      <ShieldCheck size={25} />
                    </div>

                    <div className="prediction-point">
                      <span>Acción autorizada</span>
                      <strong className={
                        actionColor(latest.authorized_action)
                      }>
                        {latest.authorized_action}
                      </strong>
                    </div>

                  </div>

                  <div className="agent-rationale">
                    <strong>Justificación del LLM</strong>
                    <p>{latest.rationale}</p>
                  </div>

                  <div className="detail-row">
                    <span>Evaluación de riesgo</span>
                    <strong>
                      {latest.risk_approved
                        ? 'Aprobada'
                        : 'Rechazada'}
                    </strong>
                  </div>

                  <div className="detail-row">
                    <span>Latencia</span>
                    <strong>
                      {latest.latency_ms === null
                        ? '—'
                        : `${(latest.latency_ms / 1000).toFixed(3)} s`}
                    </strong>
                  </div>

                  <div className="detail-row">
                    <span>Vela de referencia</span>
                    <strong>
                      {latest.candle_date} UTC
                    </strong>
                  </div>

                  <div className="agent-rationale">
                    <strong>Motivos de riesgo</strong>
                    <p>
                      {latest.risk_reasons.join(' · ')
                        || 'No disponibles'}
                    </p>
                  </div>

                </>

              ) : (

                <div className="chart-placeholder">

                  <div className="empty-icon">
                    <Clock size={32} />
                  </div>

                  <strong>Sin decisiones registradas</strong>

                  <p>
                    Los diagnósticos anteriores se
                    realizaron en copias temporales.
                  </p>

                </div>

              )}

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Resumen operativo</h2>
                  <p>Actividad persistida en SQLite.</p>
                </div>
                <Database size={20} />
              </div>

              {[
                ['Ciclos totales', agent.total_cycles],
                ['Completados', agent.completed_cycles],
                ['Rechazados', agent.rejected_cycles],
                ['Órdenes ejecutadas', agent.filled_orders],
                ['Incidentes pendientes', agent.pending_incidents],
              ].map(([label, value]) => (
                <div
                  className="detail-row"
                  key={String(label)}
                >
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}

              <div className="detail-row">
                <span>Paro de emergencia</span>
                <strong className={
                  agent.emergency_stop
                    ? 'negative'
                    : 'positive'
                }>
                  {agent.emergency_stop
                    ? 'Activado'
                    : 'Desactivado'}
                </strong>
              </div>

            </section>

          </div>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Historial de decisiones</h2>
                <p>
                  {history.total} decisiones registradas
                  · Hasta 100 mostradas
                </p>
              </div>
            </div>

            {history.decisions.length === 0 ? (

              <div className="chart-placeholder">
                <Database size={28} />
                <strong>No hay decisiones disponibles</strong>
                <p>
                  Aquí aparecerán los ciclos del agente
                  cuando se habilite su operación.
                </p>
              </div>

            ) : (

              <div className="market-table-scroll">

                <table className="market-table">
                  <thead>
                    <tr>
                      <th>Ciclo</th>
                      <th>Vela UTC</th>
                      <th>Propuesta</th>
                      <th>Autorizada</th>
                      <th>Riesgo</th>
                      <th>Latencia</th>
                      <th>Orden</th>
                    </tr>
                  </thead>

                  <tbody>

                    {history.decisions.map(d => (
                      <tr key={d.id}>
                        <td>#{d.cycle_id}</td>
                        <td>{d.candle_date}</td>
                        <td className={
                          actionColor(d.proposed_action)
                        }>
                          {d.proposed_action}
                        </td>
                        <td className={
                          actionColor(d.authorized_action)
                        }>
                          {d.authorized_action}
                        </td>
                        <td>
                          {d.risk_approved
                            ? 'Aprobado'
                            : 'Rechazado'}
                        </td>
                        <td>
                          {d.latency_ms === null
                            ? '—'
                            : `${(d.latency_ms / 1000).toFixed(2)} s`}
                        </td>
                        <td>
                          {d.order_id === null
                            ? 'Sin orden'
                            : `#${d.order_id}`}
                        </td>
                      </tr>
                    ))}

                  </tbody>
                </table>

              </div>

            )}

          </section>

          <div className="notice">

            <CheckCircle2 size={20} />

            <div>
              <strong>Modo exclusivamente simulado</strong>
              <p>
                Los controles administran exclusivamente
                la cartera virtual. No existen órdenes
                conectadas a una cuenta real.
              </p>
            </div>

          </div>

        </>
      )}

    </div>
  )
}
