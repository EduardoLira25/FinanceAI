import ReplayResults from '../components/ReplayResults'
import { useState } from 'react'

import {
  ArrowLeftRight,
  RefreshCw,
  Database,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'

import { useFinanceRead } from '../hooks/useFinanceRead'

import {
  money,
  utcDate,
} from '../services/portfolioData'

import type {
  OrderHistory,
} from '../services/portfolioData'

const PAGE_SIZE = 20

const statusLabels: Record<string, string> = {
  FILLED: 'Ejecutada',
  PENDING: 'Pendiente',
  REJECTED: 'Rechazada',
  CANCELLED: 'Cancelada',
}

function OrdersOriginal() {

  const [side, setSide] = useState('ALL')

  const [filter, setFilter] = useState('ALL')

  const [page, setPage] = useState(0)

  const params: Record<string, string | number> = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }

  if (side !== 'ALL') params.side = side

  if (filter !== 'ALL') params.status = filter

  const { state, refresh } =
    useFinanceRead<OrderHistory>(
      'orders/history', params,
    )

  const data = state.status === 'ready'
    ? state.data
    : null

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / ORDERS
          </div>
          <h1>Operaciones</h1>
          <p>Historial de compras y ventas simuladas.</p>
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

      <div className="data-strip">
        <span className="positive">PAPER TRADING</span>
        <span>Cartera principal · BTC/USDT</span>
      </div>

      <section className="panel">

        <div className="panel-heading">
          <div>
            <h2>Historial de órdenes</h2>
            <p>
              {data
                ? `${data.total} órdenes con los filtros seleccionados`
                : 'Registro persistido en SQLite'}
            </p>
          </div>
          <ArrowLeftRight size={22} />
        </div>

        <div className="order-filters">

          <label>
            Tipo de operación
            <select
              value={side}
              onChange={event => {
                setSide(event.target.value)
                setPage(0)
              }}
            >
              <option value="ALL">Todas</option>
              <option value="BUY">Compras</option>
              <option value="SELL">Ventas</option>
            </select>
          </label>

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
              <option value="FILLED">Ejecutadas</option>
              <option value="PENDING">Pendientes</option>
              <option value="REJECTED">Rechazadas</option>
              <option value="CANCELLED">Canceladas</option>
            </select>
          </label>

        </div>

        {state.status === 'loading' && (
          <div className="notice" role="status">
            Consultando operaciones...
          </div>
        )}

        {state.status === 'error' && (
          <div className="notice error-notice" role="alert">
            No fue posible consultar las operaciones.
          </div>
        )}

        {data && (

          <>

            {data.orders.length === 0 ? (

              <div className="chart-placeholder">

                <div className="empty-icon">
                  <Database size={34} />
                </div>

                <strong>Sin órdenes disponibles</strong>

                <p>
                  No existen operaciones que coincidan
                  con los filtros seleccionados.
                </p>

              </div>

            ) : (

              <div className="market-table-scroll">

                <table className="market-table">

                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Ejecución UTC</th>
                      <th>Activo</th>
                      <th>Tipo</th>
                      <th>Cantidad BTC</th>
                      <th>Precio USDT</th>
                      <th>Importe USDT</th>
                      <th>Comisión</th>
                      <th>Deslizamiento</th>
                      <th>Estado</th>
                      <th>Ciclo</th>
                    </tr>
                  </thead>

                  <tbody>

                    {data.orders.map(order => (
                      <tr key={order.id}>
                        <td>#{order.id}</td>
                        <td>
                          {utcDate(order.filled_at_utc)}
                        </td>
                        <td>{order.symbol}</td>
                        <td className={
                          order.side === 'BUY'
                            ? 'positive'
                            : 'negative'
                        }>
                          {order.side}
                        </td>
                        <td>
                          {order.quantity_btc.toFixed(8)}
                        </td>
                        <td>{money(order.price_usdt)}</td>
                        <td>{money(order.notional_usdt)}</td>
                        <td>{money(order.fee_usdt)}</td>
                        <td>{money(order.slippage_usdt)}</td>
                        <td>
                          {statusLabels[order.status]}
                        </td>
                        <td>#{order.cycle_id}</td>
                      </tr>
                    ))}

                  </tbody>

                </table>

              </div>

            )}

            <div className="pagination-controls">

              <button
                className="refresh-button"
                disabled={page === 0}
                onClick={() =>
                  setPage(n => Math.max(0, n - 1))
                }
              >
                <ChevronLeft size={16} />
                Anterior
              </button>

              <span>
                Página {page + 1} de {
                  Math.max(
                    1,
                    Math.ceil(data.total / PAGE_SIZE),
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

          </>
        )}

      </section>

      <div className="notice">
        <ArrowLeftRight size={20} />
        <div>
          <strong>Operaciones exclusivamente simuladas</strong>
          <p>
            Las decisiones HOLD aparecen en Agente IA.
            Aquí solo se muestran órdenes registradas.
          </p>
        </div>
      </div>

    </div>
  )
}


export default function Orders() {
  return (
    <>
      <OrdersOriginal />
      <ReplayResults showOrders />
    </>
  )
}
