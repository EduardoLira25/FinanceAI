import './SchedulerPanel.css'

export type SchedulerInfo = {
  installed: boolean
  loaded: boolean | null
  configuration_matches: boolean
  inspection_available: boolean
  scheduler_enabled: boolean
  schedule_local: string
  schedule_utc: string
  execution_window_utc: string
  next_scheduled_at_utc: string | null
  attempts_per_day: number
  attempts_recorded: number
  latest_attempt: {
    date_utc: string
    status: string
    started_at_utc?: string | null
    finished_at_utc?: string | null
    supervisor_status?: string | null
    executed?: boolean | null
    error_type?: string | null
  } | null
  review_required: boolean
  pending_receipts: string[]
  mode: string
  real_trading: boolean
}

type SchedulerAgent = {
  portfolio_status: string
  scheduler_enabled: boolean
  scheduler_operational?: boolean
  scheduler?: SchedulerInfo
}

type Props = {
  agent?: SchedulerAgent | null
}

function formatDate(value?: string | null) {

  if (!value) return 'Sin registros'

  const fecha = new Date(value)

  if (Number.isNaN(fecha.getTime())) {
    return 'Fecha no disponible'
  }

  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'America/Mexico_City',
  }).format(fecha)
}

function portfolioLabel(status: string) {

  switch (status) {
    case 'ACTIVE': return 'Activa'
    case 'PAUSED': return 'Pausada'
    case 'STOPPED': return 'Detenida'
    default: return status
  }
}

function attemptLabel(status: string) {

  switch (status) {
    case 'FINISHED': return 'Finalizado'
    case 'STARTED': return 'En curso o interrumpido'
    case 'FAILED': return 'Fallido'
    case 'REVIEWED': return 'Revisado'
    case 'INVALID_RECEIPT': return 'Registro inválido'
    default: return status
  }
}

export default function SchedulerPanel({ agent }: Props) {

  const scheduler = agent?.scheduler

  if (!agent || !scheduler) {

    return (
      <section className="fa-scheduler-panel">
        <h2>Automatización diaria</h2>
        <p>Estado del programador no disponible.</p>
      </section>
    )
  }

  const operational =
    agent.scheduler_operational === true

  const enabled = agent.scheduler_enabled

  const latest = scheduler.latest_attempt

  const serviceStatus = !scheduler.inspection_available
    ? 'Consulta no disponible'
    : !scheduler.installed
      ? 'Sin instalar'
      : !scheduler.configuration_matches
        ? 'Configuración diferente'
        : scheduler.loaded
          ? 'Instalado y cargado'
          : 'Instalado, no cargado'

  const enabledLabel = enabled
    ? 'Habilitada'
    : 'Deshabilitada'

  return (
    <section
      className="fa-scheduler-panel"
      aria-label="Automatización diaria"
    >

      <header className="fa-scheduler-header">

        <div>
          <h2>Automatización diaria</h2>
          <p>Programador nativo de macOS · launchd</p>
        </div>

        <span
          className={
            'fa-scheduler-badge ' +
            (enabled ? 'is-enabled' : 'is-disabled')
          }
        >
          {enabledLabel}
        </span>

      </header>

      <div className="fa-scheduler-times">

        <div className="fa-scheduler-time">
          <span>Horario local</span>
          <strong>{scheduler.schedule_local}</strong>
          <small>Hora del centro de México</small>
        </div>

        <div className="fa-scheduler-time">
          <span>Horario UTC</span>
          <strong>{scheduler.schedule_utc}</strong>
          <small>Todos los días</small>
        </div>

      </div>

      <dl className="fa-scheduler-details">

        <div>
          <dt>Servicio launchd</dt>
          <dd>{serviceStatus}</dd>
        </div>

        <div>
          <dt>Cartera principal</dt>
          <dd>{portfolioLabel(agent.portfolio_status)}</dd>
        </div>

        <div>
          <dt>Estado operativo</dt>
          <dd>
            {operational
              ? 'Controles previos favorables'
              : 'No autorizado'}
          </dd>
        </div>

        <div>
          <dt>Ventana de inicio UTC</dt>
          <dd>{scheduler.execution_window_utc}</dd>
        </div>

        <div>
          <dt>Máximo de intentos diarios</dt>
          <dd>{scheduler.attempts_per_day}</dd>
        </div>

        <div>
          <dt>Intentos registrados</dt>
          <dd>{scheduler.attempts_recorded}</dd>
        </div>

        <div>
          <dt>Último intento</dt>
          <dd>
            {latest
              ? attemptLabel(latest.status)
              : 'Sin registros'}
          </dd>
        </div>

        <div>
          <dt>Fecha del último intento</dt>
          <dd>
            {formatDate(latest?.started_at_utc)}
          </dd>
        </div>

        <div>
          <dt>Resultado del supervisor</dt>
          <dd>
            {latest?.supervisor_status ?? 'Sin registros'}
          </dd>
        </div>

        <div>
          <dt>Última ejecución de orden</dt>
          <dd>
            {latest?.executed === true
              ? 'Sí'
              : latest?.executed === false
                ? 'No'
                : 'Sin información'}
          </dd>
        </div>

        <div>
          <dt>Siguiente horario programado</dt>
          <dd>
            {enabled
              ? formatDate(scheduler.next_scheduled_at_utc)
              : 'Pendiente de habilitar'}
          </dd>
        </div>

        <div>
          <dt>Registros pendientes de revisión</dt>
          <dd>{scheduler.pending_receipts.length}</dd>
        </div>

      </dl>

      {scheduler.review_required && (

        <div
          className="fa-scheduler-warning"
          role="status"
        >

          <strong>
            El programador requiere revisión
          </strong>

          <p>
            Un intento está en curso, fue interrumpido
            o necesita revisión técnica.
          </p>

          <p>
            Registros: {
              scheduler.pending_receipts.join(', ')
            }
          </p>

          <p>
            Si no hay un proceso activo, pausa la cartera
            y revisa el registro mediante Terminal.
            No se repetirá automáticamente el mismo día.
          </p>

        </div>
      )}

      <div className="fa-scheduler-security">

        <strong>
          {scheduler.real_trading === false
            ? 'Paper Trading · Dinero virtual'
            : 'Estado financiero no verificado'}
        </strong>

        <p>
          La automatización respeta el supervisor,
          el motor de riesgo y el paro de emergencia.
          Requiere que la Mac esté disponible.
        </p>

      </div>

    </section>
  )
}
