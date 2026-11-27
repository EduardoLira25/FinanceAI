import { useState } from 'react'

import {
  PlayCircle,
  PauseCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'

import {
  controlAgent,
} from '../services/agentControl'

import type {
  ControlAction,
} from '../services/agentControl'

type Props = {
  portfolioStatus: string
  emergencyStop: boolean
  recoveryRequired: boolean
  onRefresh: () => void
}

const confirmations: Record<ControlAction, string> = {
  activate:
    '¿Activar la cartera virtual? Esto no iniciará un ciclo.',
  pause:
    '¿Pausar las nuevas operaciones simuladas?',
  stop:
    '¿Activar el paro de emergencia? Requerirá revisión manual.',
  run:
    '¿Ejecutar un ciclo supervisado con capital exclusivamente virtual?',
}

export default function AgentControls({
  portfolioStatus,
  emergencyStop,
  recoveryRequired,
  onRefresh,
}: Props) {

  const [running, setRunning] = useState(false)

  const [commandBusy, setCommandBusy] =
    useState(false)

  const [message, setMessage] = useState('')

  const [failed, setFailed] = useState(false)

  const active = portfolioStatus === 'ACTIVE'

  const stopped =
    portfolioStatus === 'STOPPED' ||
    emergencyStop

  async function execute(action: ControlAction) {

    if (!window.confirm(confirmations[action])) {
      return
    }

    if (action === 'run') {
      setRunning(true)
    } else {
      setCommandBusy(true)
    }

    setFailed(false)
    setMessage('Procesando solicitud...')

    try {

      const result = await controlAgent(action)

      setMessage(
        `Resultado: ${result.status}` +
        (result.executed === true
          ? ' · Orden virtual registrada.'
          : ''),
      )

    } catch {

      setFailed(true)

      setMessage(
        'Resultado no confirmado. Revisa el estado ' +
        'y el historial antes de repetir la solicitud.',
      )

    } finally {

      if (action === 'run') {
        setRunning(false)
      } else {
        setCommandBusy(false)
      }

      onRefresh()
    }
  }

  return (
    <section className="panel">

      <div className="panel-heading">
        <div>
          <h2>Control operativo</h2>
          <p>Administración de la cartera virtual.</p>
        </div>
        <ShieldCheck size={22} />
      </div>

      <div className="agent-controls">

        <button
          className="agent-control activate-control"
          disabled={
            active || stopped || recoveryRequired ||
            commandBusy || running
          }
          onClick={() => void execute('activate')}
        >
          <PlayCircle size={24} />
          Activar agente
        </button>

        <button
          className="agent-control pause-control"
          disabled={
            stopped || !active || commandBusy
          }
          onClick={() => void execute('pause')}
        >
          <PauseCircle size={24} />
          Pausar agente
        </button>

        <button
          className="agent-control run-control"
          disabled={
            !active || stopped || recoveryRequired ||
            running || commandBusy
          }
          onClick={() => void execute('run')}
        >
          <RefreshCw size={24} />
          {running ? 'Ejecutando...' : 'Ejecutar ciclo'}
        </button>

        <button
          className="agent-control stop-control"
          disabled={stopped || commandBusy}
          onClick={() => void execute('stop')}
        >
          <ShieldAlert size={24} />
          Paro de emergencia
        </button>

      </div>

      {message && (
        <div
          className={
            `control-feedback ${failed ? 'negative' : ''}`
          }
          role="status"
        >
          {message}
        </div>
      )}

      {running && (
        <p>
          Consultando el mercado y el agente.
          No repitas la solicitud mientras esté activa.
          Puedes solicitar una pausa o un paro de emergencia.
        </p>
      )}

      {recoveryRequired && (
        <p className="warning">
          Existen incidentes pendientes de recuperación.
          La activación está bloqueada.
        </p>
      )}

      {stopped && (
        <p className="negative">
          Paro activo. La reactivación está bloqueada
          hasta realizar una revisión manual.
        </p>
      )}

      <p className="allocation-note">
        Activar no inicia operaciones automáticamente.
        Todos los ciclos pasan por el supervisor
        y el motor de riesgo. Exclusivamente Paper Trading.
      </p>

    </section>
  )
}
