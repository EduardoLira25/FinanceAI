import { replayResults } from '../data/replayResults'
import './ReplayResults.css'

const money = (n: number | null) =>
  n === null
    ? '—'
    : n.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })

export default function ReplayResults({
  showOrders = false,
}: {
  showOrders?: boolean
}) {
  const r = replayResults

  return (
    <section className="fa-replay">
      <header>
        <div>
          <h2>Resultados históricos — Paper Trading</h2>
          <p>BTCUSDT · MEXC · {r.period}</p>
        </div>
        <span className="fa-replay-tag">
          REPLAY HISTÓRICO
        </span>
      </header>

      <p>
        Simulación independiente de la cartera principal.
        Precios históricos reales de MEXC.
        Sin operaciones con dinero real.
      </p>

      <div className="fa-replay-grid">
        {r.portfolios.map(p => (
          <article key={p.strategy}>
            <h3>{p.strategy}</h3>
            <small>PnL acumulado</small>
            <strong className="fa-replay-profit">
              {p.pnl >= 0 ? '+' : ''}{money(p.pnl)} USDT
            </strong>
            <div className="fa-replay-profit">
              {p.returnPct.toFixed(4)}%
            </div>
            <p>Capital inicial: {money(p.initial)}</p>
            <p>Capital final: {money(p.final)}</p>
          </article>
        ))}
      </div>

      <div className="fa-replay-summary">
        {r.cycles} ciclos · 6 órdenes simuladas ·
        2 liquidaciones finales
      </div>

      {showOrders && (
        <div className="fa-replay-table">
          <table>
            <thead>
              <tr>
                <th>Estrategia</th>
                <th>Fecha UTC</th>
                <th>Acción</th>
                <th>BTC</th>
                <th>Precio USDT</th>
                <th>Importe USDT</th>
                <th>Tipo</th>
              </tr>
            </thead>
            <tbody>
              {r.orders.map((o, i) => (
                <tr key={i}>
                  <td>{o.strategy}</td>
                  <td>{o.date}</td>
                  <td>{o.side}</td>
                  <td>
                    {o.quantity === null
                      ? '—'
                      : o.quantity.toFixed(8)}
                  </td>
                  <td>{money(o.price)}</td>
                  <td>{money(o.amount)}</td>
                  <td>{o.type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer>
        Resultados retrospectivos del conjunto de validación.
        No representan ganancias actuales ni garantizan
        rentabilidad futura.
      </footer>
    </section>
  )
}
