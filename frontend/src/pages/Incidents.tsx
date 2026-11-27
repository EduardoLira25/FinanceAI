import RecoveryControls from '../components/RecoveryControls'
import { useState } from 'react'

import {
  AlertTriangle,
  CheckCircle2,
  ShieldCheck,
  Database,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Clock,
} from 'lucide-react'

import { useFinanceRead } from '../hooks/useFinanceRead'

import { utcDate } from '../services/portfolioData'

import type {
  IncidentHistory,
} from '../services/riskData'

const PAGE_SIZE = 20

export default function Incidents() {

  const [filter, setFilter] = useState('ALL')
  const [page, setPage] = useState(0)

  const { state, refresh } =
    useFinanceRead<IncidentHistory>(
      'incidents/history',
      {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: filter,
      },
    )

  const data = state.status === 'ready'
    ? state.data : null

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / INCIDENT MANAGEMENT
          </div>
          <h1>Incidentes</h1>
          <p>Supervisión, errores y recuperación del sistema.</p>
        </div>

        <button
          className="refresh-button"
          onClick={refresh}
          disabled={state.status === 'loading'}
        >
          <RefreshCw size={16} />
          Actualizar
        </button>
      </div>

      {state.status === 'loading' && (
        <div className="notice" role="status">
          Consultando registro de incidentes...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          No fue posible consultar los incidentes.
        </div>
      )}

      {data && (
        <>

          <div className="data-strip">
            <span>Registro de la base principal</span>
            <span className={
              data.recovery_required ? 'warning' : 'positive'
            }>
              {data.recovery_required
                ? 'Recuperación requerida'
                : 'Sin incidentes pendientes'}
            </span>
          </div>

          <section className="metrics-grid">
            {[
              {
                label: 'Incidentes totales',
                value: data.total,
                icon: Database,
                color: '',
              },
              {
                label: 'Pendientes',
                value: data.pending,
                icon: AlertTriangle,
                color: data.pending ? 'negative' : 'positive',
              },
              {
                label: 'Resueltos',
                value: data.resolved,
                icon: CheckCircle2,
                color: 'positive',
              },
              {
                label: 'Recuperación requerida',
                value: data.recovery_required ? 'Sí' : 'No',
                icon: ShieldCheck,
                color: data.recovery_required
                  ? 'warning' : 'positive',
              },
            ].map(item => {

              const Icon = item.icon

              return (
                <article
                  key={item.label}
                  className="metric-card"
                >
                  <div className="metric-top">
                    <span>{item.label}</span>
                    <div className="metric-icon">
                      <Icon size={19} />
                    </div>
                  </div>
                  <div className={`metric-value ${item.color}`}>
                    {item.value}
                  </div>
                  <div className="muted">Registro persistido</div>
                </article>
              )
            })}
          </section>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Historial de incidentes</h2>
                <p>{data.filtered_total} registros filtrados.</p>
              </div>
              <AlertTriangle size={21} />
            </div>

            <div className="order-filters">
              <label>
                Estado
                <select
                  value={filter}
                  onChange={event => {
                    setFilter(event.target.value)
                    setPage(0)
                  }}
                >
                  <option value="ALL">Todos</option>
                  <option value="PENDING">Pendientes</option>
                  <option value="RESOLVED">Resueltos</option>
                </select>
              </label>
            </div>

            {data.incidents.length === 0 ? (

              <div className="chart-placeholder">
                <div className="empty-icon">
                  <CheckCircle2 size={34} />
                </div>
                <strong>Sin incidentes disponibles</strong>
                <p>
                  No hay incidentes que coincidan
                  con el filtro seleccionado.
                </p>
              </div>

            ) : (

              <div className="incident-list">

                {data.incidents.map(item => (
                  <details key={item.id} className="incident-card">

                    <summary>
                      <div>
                        <strong>
                          #{item.id} · {item.error_type}
                        </strong>
                        <small>
                          {item.component} · {utcDate(
                            item.created_at_utc,
                          )}
                        </small>
                      </div>

                      <span className={
                        item.resolved ? 'positive' : 'warning'
                      }>
                        {item.resolved ? 'Resuelto' : 'Pendiente'}
                      </span>
                    </summary>

                    <div className="agent-rationale">
                      <strong>Descripción</strong>
                      <p>{item.message}</p>
                    </div>

                    <div className="agent-rationale">
                      <strong>Causa registrada</strong>
                      <p>{item.cause ?? 'No documentada'}</p>
                    </div>

                    <div className="agent-rationale">
                      <strong>Acción correctiva</strong>
                      <p>
                        {item.corrective_action ?? 'Pendiente'}
                      </p>
                    </div>

                    <div className="detail-row">
                      <span>Reintentos registrados</span>
                      <strong>{item.retry_count}</strong>
                    </div>

                    <div className="detail-row">
                      <span>Ciclo relacionado</span>
                      <strong>{item.cycle_id ?? '—'}</strong>
                    </div>

                    <div className="detail-row">
                      <span>Fecha de resolución</span>
                      <strong>
                        {utcDate(item.resolved_at_utc)}
                      </strong>
                    </div>

                  </details>
                ))}

              </div>

            )}

            <div className="pagination-controls">
              <button
                className="refresh-button"
                disabled={page === 0}
                onClick={() => setPage(n => Math.max(0, n - 1))}
              >
                <ChevronLeft size={16} />
                Anterior
              </button>

              <span>
                Página {page + 1} de {
                  Math.max(
                    1,
                    Math.ceil(data.filtered_total / PAGE_SIZE),
                  )
                }
              </span>

              <button
                className="refresh-button"
                disabled={!data.has_more}
                onClick={() => setPage(n => n + 1)}
              >
                Siguiente
                <ChevronRight size={16} />
              </button>
            </div>

          </section>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Actividad del sistema</h2>
                <p>Últimos 20 eventos registrados.</p>
              </div>
              <Clock size={20} />
            </div>

            {data.system_logs.length === 0 ? (
              <p>Sin eventos registrados.</p>
            ) : (
              <div className="incident-list">
                {data.system_logs.map(log => (
                  <details className="incident-card" key={log.id}>
                    <summary>
                      <div>
                        <strong>{log.component}</strong>
                        <small>{utcDate(log.created_at_utc)}</small>
                      </div>
                      <span className={
                        log.level === 'ERROR'
                          ? 'negative'
                          : log.level === 'WARNING'
                            ? 'warning' : ''
                      }>
                        {log.level}
                      </span>
                    </summary>
                    <div className="agent-rationale">
                      <p>{log.message}</p>
                    </div>
                  </details>
                ))}
              </div>
            )}

          </section>



        </>
      )}

      <RecoveryControls onRefresh={refresh} />

    </div>
  )
}
