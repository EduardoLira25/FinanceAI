import { useState } from 'react'

import {
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
} from 'lucide-react'

import { useFinanceRead } from '../hooks/useFinanceRead'

import {
  requestRecovery,
} from '../services/recovery'

import type {
  RecoveryStatus,
} from '../services/recovery'

type Props = {
  onRefresh: () => void
}

export default function RecoveryControls({
  onRefresh,
}: Props) {

  const { state, refresh } =
    useFinanceRead<RecoveryStatus>(
      'agent/recovery/status',
    )

  const [reason, setReason] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)

  const data = state.status === 'ready'
    ? state.data : null

  const validReason =
    reason.trim().length >= 10 &&
    reason.trim().length <= 240

  async function execute(action: 'recover' | 'reset') {

    if (
      !data || busy || !validReason || !reviewed ||
      (action === 'recover' && !data.can_recover) ||
      (action === 'reset' && !data.can_reset)
    ) return

    const confirmation = action === 'recover'
      ? '¿Confirmar la revisión de los incidentes y habilitar la cartera virtual? No se iniciará un ciclo.'
      : '¿Restablecer el paro de emergencia? La cartera quedará pausada.'

    if (!window.confirm(confirmation)) return

    setBusy(true)
    setFailed(false)
    setMessage('Procesando intervención...')

    try {

      const result = await requestRecovery(
        action,
        reason,
        action === 'recover'
          ? data.pending_incident_ids
          : [],
      )

      setMessage(`Resultado confirmado: ${result.status}`)

      setReason('')
      setReviewed(false)

    } catch {

      setFailed(true)
      setReviewed(false)

      setMessage(
        'Resultado no confirmado. Consulta nuevamente ' +
        'el estado antes de repetir la intervención.',
      )

    } finally {

      setBusy(false)
      refresh()
      onRefresh()
    }
  }

  return (
    <section className="panel">

      <div className="panel-heading">
        <div>
          <h2>Recuperación manual</h2>
          <p>
            Intervención humana y restablecimiento controlado.
          </p>
        </div>
        <ShieldCheck size={23} />
      </div>

      {state.status === 'loading' && (
        <p role="status">
          Consultando estado de recuperación...
        </p>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          No fue posible consultar la recuperación.
        </div>
      )}

      {data && (
        <>

          <div className="detail-row">
            <span>Estado de cartera</span>
            <strong>{data.portfolio_status}</strong>
          </div>

          <div className="detail-row">
            <span>Paro de emergencia</span>
            <strong className={
              data.emergency_stop ? 'negative' : 'positive'
            }>
              {data.emergency_stop
                ? 'Activado' : 'Desactivado'}
            </strong>
          </div>

          <div className="detail-row">
            <span>Incidentes pendientes</span>
            <strong>{data.pending_count}</strong>
          </div>

          <div className="detail-row">
            <span>Ciclos incompletos</span>
            <strong>{data.incomplete_cycles}</strong>
          </div>

          {data.pending_incident_ids.length > 0 && (
            <p>
              Incidentes por revisar: {
                data.pending_incident_ids
                  .map(id => `#${id}`)
                  .join(', ')
              }
            </p>
          )}

          {!data.can_recover && !data.can_reset && (
            <div className="notice">
              <ShieldCheck size={20} />
              {data.pending_count === 0 &&
                data.incomplete_cycles === 0
                ? 'No se requiere ninguna intervención.'
                : 'La recuperación requiere revisión adicional.'}
            </div>
          )}

          {data.non_recoverable_count > 0 && (
            <p className="warning">
              Existen incidentes que requieren revisión técnica
              fuera del mecanismo de recuperación del supervisor.
              No se habilitará la cartera desde esta pantalla.
            </p>
          )}

          {data.incomplete_cycles > 0 && (
            <p className="warning">
              Existen ciclos incompletos. La recuperación
              automática desde esta pantalla está bloqueada.
            </p>
          )}

          {data.pending_count > 100 && (
            <p className="warning">
              Se requiere revisión técnica de los registros.
            </p>
          )}

        </>
      )}

      <div className="recovery-form">

        <label htmlFor="recovery-reason">
          Motivo de la intervención
        </label>

        <textarea
          id="recovery-reason"
          value={reason}
          maxLength={240}
          disabled={
            busy ||
            !data ||
            (!data.can_recover && !data.can_reset)
          }
          onChange={event => {
            setReason(event.target.value)
            setReviewed(false)
          }}
          placeholder="Describe el fallo revisado y la acción correctiva realizada..."
          rows={4}
        />

        <small>{reason.length}/240 caracteres</small>

        <label className="review-confirmation">

          <input
            type="checkbox"
            checked={reviewed}
            disabled={
              busy ||
              !data ||
              (!data.can_recover && !data.can_reset)
            }
            onChange={event =>
              setReviewed(event.target.checked)
            }
          />

          Confirmo que revisé los incidentes y las
          condiciones que originaron el bloqueo.

        </label>

      </div>

      <div className="recovery-buttons">

        <button
          className="agent-control activate-control"
          disabled={
            busy || !data?.can_recover ||
            !validReason || !reviewed
          }
          onClick={() => void execute('recover')}
        >
          <ShieldCheck size={24} />
          Recuperar agente
        </button>

        <button
          className="agent-control stop-control"
          disabled={
            busy || !data?.can_reset ||
            !validReason || !reviewed
          }
          onClick={() => void execute('reset')}
        >
          <ShieldAlert size={24} />
          Restablecer paro de emergencia
        </button>

      </div>

      {message && (
        <div
          role="status"
          className={
            `control-feedback ${failed ? 'negative' : ''}`
          }
        >
          {message}
        </div>
      )}

      <button
        className="refresh-button recovery-refresh"
        disabled={busy || state.status === 'loading'}
        onClick={() => {
          setReviewed(false)
          refresh()
          onRefresh()
        }}
      >
        <RefreshCw size={16} />
        Consultar estado
      </button>

      <p className="allocation-note">
        Restablecer un paro no activa la cartera,
        no elimina incidentes ni inicia operaciones.
        Recuperar incidentes requiere una revisión explícita.
      </p>

    </section>
  )
}
