import {
  ShieldCheck,
  AlertTriangle,
  Clock,
  Wallet,
  RefreshCw,
  Activity,
} from 'lucide-react'

import { Link } from 'react-router-dom'

import { useFinanceRead } from '../hooks/useFinanceRead'

import {
  money,
  utcDate,
} from '../services/portfolioData'

import {
  blockerLabels,
} from '../services/riskData'

import type {
  RiskOverview,
} from '../services/riskData'

export default function Risk() {

  const { state, refresh } =
    useFinanceRead<RiskOverview>('risk/overview')

  const data = state.status === 'ready'
    ? state.data : null

  const r = data?.current

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / RISK MANAGEMENT
          </div>
          <h1>Riesgo</h1>
          <p>Protección del patrimonio y límites financieros.</p>
        </div>

        <button
          className="refresh-button"
          disabled={state.status === 'loading'}
          onClick={refresh}
        >
          <RefreshCw size={16} />
          Actualizar
        </button>
      </div>

      {state.status === 'loading' && (
        <div className="notice" role="status">
          Consultando configuración...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          No fue posible consultar el motor de riesgo.
        </div>
      )}

      {data && r && (
        <>

          <div className="data-strip">
            <span className="positive">
              PAPER TRADING · Configuración persistida
            </span>
            <span>Versión {r.version}</span>
            <span>Cartera: {data.portfolio_status}</span>
          </div>

          <section className="metrics-grid">
            {[
              {
                label: 'Exposición máxima',
                value: `${r.max_exposure_pct}%`,
                detail: 'Límite de nuevas compras',
                icon: ShieldCheck,
              },
              {
                label: 'Límite de pérdida diaria',
                value: `${r.max_daily_loss_pct}%`,
                detail: 'Bloqueo de nuevas compras',
                icon: Activity,
              },
              {
                label: 'Antigüedad máxima',
                value: `${r.max_data_age_seconds / 60} min`,
                detail: 'Desde el cierre de la vela',
                icon: Clock,
              },
              {
                label: 'Orden mínima',
                value: `${money(r.min_order_usdt)} USDT`,
                detail: 'Importe mínimo simulado',
                icon: Wallet,
              },
            ].map(item => {

              const Icon = item.icon

              return (
                <article
                  className="metric-card"
                  key={item.label}
                >
                  <div className="metric-top">
                    <span>{item.label}</span>
                    <div className="metric-icon">
                      <Icon size={19} />
                    </div>
                  </div>
                  <div className="metric-value">
                    {item.value}
                  </div>
                  <div className="muted">{item.detail}</div>
                </article>
              )
            })}
          </section>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Exposición financiera</h2>
                  <p>Valoración al último cierre almacenado.</p>
                </div>
                <Activity size={20} />
              </div>

              <div className="allocation-amount">
                {data.exposure_pct === null
                  ? '—'
                  : `${data.exposure_pct.toFixed(2)}%`}
              </div>

              {data.exposure_pct !== null && (
                <div className="risk-exposure-track">
                  <div
                    className="risk-exposure-fill"
                    style={{
                      width: `${Math.min(
                        100, Math.max(0, data.exposure_pct),
                      )}%`,
                      background:
                        data.exposure_pct > r.max_exposure_pct
                          ? '#f87171' : '#34d399',
                    }}
                  />
                  <div
                    className="risk-limit-marker"
                    style={{
                      left: `${r.max_exposure_pct}%`,
                    }}
                  />
                </div>
              )}

              <div className="detail-row">
                <span>Límite configurado</span>
                <strong>{r.max_exposure_pct}%</strong>
              </div>

              <div className="detail-row">
                <span>Valor de Bitcoin</span>
                <strong>
                  {money(data.position_value_usdt)} USDT
                </strong>
              </div>

              <div className="detail-row">
                <span>Patrimonio virtual</span>
                <strong>{money(data.equity_usdt)} USDT</strong>
              </div>

              <div className="detail-row">
                <span>Referencia UTC</span>
                <strong>{data.reference_date ?? '—'}</strong>
              </div>

              <p>
                La exposición puede superar el límite
                por cambios en el precio de una posición
                existente.
              </p>

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Restricciones operativas</h2>
                  <p>Bloqueos detectados en esta consulta.</p>
                </div>
                <ShieldCheck size={20} />
              </div>

              <div className="detail-row">
                <span>Paro de emergencia</span>
                <strong className={
                  r.emergency_stop ? 'negative' : 'positive'
                }>
                  {r.emergency_stop
                    ? 'Activado' : 'Desactivado'}
                </strong>
              </div>

              <div className="detail-row">
                <span>Antigüedad de datos al consultar</span>
                <strong>
                  {data.data_age_seconds === null
                    ? '—'
                    : `${(
                        data.data_age_seconds / 60
                      ).toFixed(1)} min`}
                </strong>
              </div>

              {data.known_blockers.length > 0 ? (

                <div className="risk-blockers">
                  {data.known_blockers.map(code => (
                    <div key={code}>
                      <AlertTriangle size={17} />
                      {blockerLabels[code] ?? code}
                    </div>
                  ))}
                </div>

              ) : (

                <p className="positive allocation-note">
                  Sin bloqueos conocidos en esta consulta.
                </p>

              )}

              <p>
                Esto no constituye una autorización.
                El motor de riesgo revalida cotización,
                saldo, límites y estado antes de ejecutar.
              </p>

              <Link className="dashboard-link" to="/agente">
                Ir al control del agente
              </Link>

            </section>
          </div>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Configuración vigente</h2>
                <p>Reglas financieras de la versión {r.version}.</p>
              </div>
              <ShieldCheck size={20} />
            </div>

            {[
              ['Comisión simulada', `${r.fee_pct}%`],
              ['Deslizamiento configurado', `${r.slippage_pct}%`],
              ['Umbral de predicción', `${r.prediction_threshold_pct}%`],
              ['Apalancamiento', 'No permitido'],
              ['Ventas en corto', 'No permitidas'],
              ['Capital', 'Exclusivamente virtual'],
            ].map(([label, value]) => (
              <div className="detail-row" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}

          </section>

          <section className="panel">

            <div className="panel-heading">
              <div>
                <h2>Historial de configuraciones</h2>
                <p>Versiones registradas en SQLite.</p>
              </div>
            </div>

            <div className="market-table-scroll">
              <table className="market-table">
                <thead>
                  <tr>
                    <th>Versión</th>
                    <th>Creación UTC</th>
                    <th>Exposición máx.</th>
                    <th>Pérdida diaria</th>
                    <th>Antigüedad</th>
                    <th>Orden mínima</th>
                    <th>Comisión</th>
                    <th>Paro</th>
                  </tr>
                </thead>
                <tbody>
                  {data.versions.map(v => (
                    <tr key={v.version}>
                      <td>
                        v{v.version}
                        {v.version === r.version
                          ? ' · Vigente' : ''}
                      </td>
                      <td>{utcDate(v.created_at_utc)}</td>
                      <td>{v.max_exposure_pct}%</td>
                      <td>{v.max_daily_loss_pct}%</td>
                      <td>{v.max_data_age_seconds / 60} min</td>
                      <td>{money(v.min_order_usdt)}</td>
                      <td>{v.fee_pct}%</td>
                      <td className={
                        v.emergency_stop ? 'negative' : ''
                      }>
                        {v.emergency_stop ? 'Activo' : 'Inactivo'}
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
              <strong>Protección financiera determinista</strong>
              <p>
                Los límites no garantizan que las pérdidas
                nunca los superen. Qwen3 no puede modificar
                estos controles ni autorizar órdenes por sí solo.
              </p>
            </div>
          </div>

        </>
      )}

    </div>
  )
}
