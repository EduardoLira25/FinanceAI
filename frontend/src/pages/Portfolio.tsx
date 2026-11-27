import ReplayResults from '../components/ReplayResults'
import {
  Wallet,
  Bitcoin,
  TrendingUp,
  ShieldCheck,
  RefreshCw,
  Activity,
} from 'lucide-react'

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts'

import { useFinanceRead } from '../hooks/useFinanceRead'

import {
  money,
  percent,
} from '../services/portfolioData'

import type {
  PortfolioOverview,
} from '../services/portfolioData'


function PortfolioOriginal() {

  const { state, refresh } =
    useFinanceRead<PortfolioOverview>(
      'portfolio/overview',
    )

  const p = state.status === 'ready'
    ? state.data
    : null

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / PORTFOLIO
          </div>
          <h1>Cartera</h1>
          <p>
            Patrimonio y distribución del capital virtual.
          </p>
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
          Consultando patrimonio...
        </div>
      )}

      {state.status === 'error' && (
        <div className="notice error-notice" role="alert">
          No fue posible consultar la cartera.
        </div>
      )}

      {p && (
        <>

          <div className="data-strip">
            <span className="positive">
              PAPER TRADING
            </span>
            <span>Estado: {p.status}</span>
            <span>
              Valoración al cierre: {p.reference_date} UTC
            </span>
          </div>

          <section className="metrics-grid">

            {[
              {
                label: 'Patrimonio total',
                value: money(p.equity),
                detail: 'USDT · Último cierre almacenado',
                icon: Wallet,
                color: '',
              },
              {
                label: 'Rendimiento acumulado',
                value: percent(p.return_pct),
                detail: 'Respecto al capital inicial',
                icon: TrendingUp,
                color: p.return_pct < 0
                  ? 'negative' : 'positive',
              },
              {
                label: 'Efectivo disponible',
                value: money(p.cash),
                detail: 'USDT',
                icon: Wallet,
                color: '',
              },
              {
                label: 'Posición Bitcoin',
                value: p.bitcoin_quantity.toFixed(8),
                detail: 'BTC',
                icon: Bitcoin,
                color: '',
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

                  <div
                    className={`metric-value ${item.color}`}
                  >
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
                  <h2>Evolución del patrimonio</h2>
                  <p>
                    Valoraciones diarias persistidas en SQLite.
                  </p>
                </div>
                <Activity size={20} />
              </div>

              {p.valuations.length === 0 ? (

                <div className="chart-placeholder">
                  <div className="empty-icon">
                    <TrendingUp size={32} />
                  </div>
                  <strong>
                    Sin valoraciones históricas
                  </strong>
                  <p>
                    Capital inicial: {money(p.initial_cash)} USDT.
                    La curva se construirá cuando existan cierres
                    de ciclos registrados.
                  </p>
                </div>

              ) : (

                <>

                  <div className="market-chart">

                    <ResponsiveContainer
                      width="100%"
                      height="100%"
                    >
                      <LineChart data={p.valuations}>

                        <CartesianGrid
                          stroke="#243148"
                          strokeDasharray="3 4"
                          vertical={false}
                        />

                        <XAxis
                          dataKey="date"
                          tickFormatter={value =>
                            String(value).slice(0, 10)
                          }
                          tick={{
                            fill: '#95a5bd',
                            fontSize: 10,
                          }}
                        />

                        <YAxis
                          domain={['auto', 'auto']}
                          tick={{
                            fill: '#95a5bd',
                            fontSize: 10,
                          }}
                        />

                        <Tooltip
                          contentStyle={{
                            background: '#172236',
                            border: '1px solid #34435e',
                          }}
                          labelStyle={{ color: '#e7edf8' }}
                          itemStyle={{ color: '#b6b2ff' }}
                        />

                        <Line
                          type="linear"
                          dataKey="equity"
                          name="Patrimonio USDT"
                          stroke="#8b83ff"
                          strokeWidth={2}
                          dot={p.valuations.length < 10}
                          isAnimationActive={false}
                        />

                      </LineChart>
                    </ResponsiveContainer>

                  </div>

                  <p>
                    {p.valuations.length} valoraciones diarias
                    mostradas de {p.total_valuations}.
                  </p>

                </>

              )}

            </section>

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Distribución de activos</h2>
                  <p>Efectivo y exposición a Bitcoin</p>
                </div>
                <Wallet size={20} />
              </div>

              <div className="portfolio-allocation">

                <div
                  className="portfolio-ring"
                  style={{
                    background: p.equity > 0
                      ? `conic-gradient(
                          #f4a940 ${p.exposure_pct}%,
                          #34d399 ${p.exposure_pct}% 100%
                        )`
                      : '#243148',
                  }}
                >
                  <div>
                    <strong>
                      {p.equity > 0
                        ? (100 - p.exposure_pct).toFixed(1)
                        : '0'}%
                    </strong>
                    <span>Efectivo</span>
                  </div>
                </div>

                <div>
                  <div className="detail-row">
                    <span className="positive">USDT</span>
                    <strong>{money(p.cash)}</strong>
                  </div>
                  <div className="detail-row">
                    <span style={{ color: '#f4a940' }}>
                      BTC
                    </span>
                    <strong>
                      {money(p.position_value)} USDT
                    </strong>
                  </div>
                </div>

              </div>

              <div className="detail-row">
                <span>Exposición BTC</span>
                <strong>{p.exposure_pct.toFixed(2)}%</strong>
              </div>

              <div className="detail-row">
                <span>Capital inicial</span>
                <strong>{money(p.initial_cash)} USDT</strong>
              </div>

            </section>

          </div>

          <div className="dashboard-grid">

            <section className="panel">

              <div className="panel-heading">
                <div>
                  <h2>Posición financiera</h2>
                  <p>Valoración de la posición existente.</p>
                </div>
                <Bitcoin size={20} />
              </div>

              {[
                ['Cantidad BTC', p.bitcoin_quantity.toFixed(8)],
                ['Precio de referencia', money(p.reference_price) + ' USDT'],
                ['Valor de la posición', money(p.position_value) + ' USDT'],
                ['Costo de adquisición', money(p.cost_basis) + ' USDT'],
                ['Resultado no realizado', money(p.unrealized_pnl) + ' USDT'],
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
                  <h2>Estadísticas de operación</h2>
                  <p>Información de la cartera principal.</p>
                </div>
                <ShieldCheck size={20} />
              </div>

              {[
                ['Órdenes ejecutadas', p.filled_orders],
                ['Compras', p.buys],
                ['Ventas', p.sells],
                ['Comisiones', money(p.fees_usdt) + ' USDT'],
                ['Deslizamiento registrado', money(p.slippage_usdt) + ' USDT'],
                [
                  'Drawdown máximo registrado',
                  p.max_recorded_drawdown_pct === null
                    ? 'Sin historial'
                    : p.max_recorded_drawdown_pct.toFixed(2) + '%',
                ],
              ].map(([label, value]) => (
                <div className="detail-row" key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}

            </section>

          </div>

          <div className="notice">
            <ShieldCheck size={20} />
            <div>
              <strong>Patrimonio exclusivamente virtual</strong>
              <p>
                La valoración utiliza el último cierre almacenado.
                No representa una cotización de mercado en tiempo real.
              </p>
            </div>
          </div>

        </>
      )}

    </div>
  )
}


export default function Portfolio() {
  return (
    <>
      <PortfolioOriginal />
      <ReplayResults />
    </>
  )
}
