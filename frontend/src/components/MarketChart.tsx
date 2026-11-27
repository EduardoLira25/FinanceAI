import type { MarketCandle } from '../services/marketData'

type Props = {
  candles: MarketCandle[]
  mode: 'candles' | 'line'
  showSma: boolean
  selectedDate: string
  onSelect: (date: string) => void
}

export default function MarketChart({
  candles,
  mode,
  showSma,
  selectedDate,
  onSelect,
}: Props) {

  if (!candles.length) return null

  const W = 960
  const H = 390

  const left = 15
  const right = 875
  const top = 20
  const bottom = 270

  const step = (right - left) / candles.length

  const bodyWidth = Math.max(
    1,
    Math.min(17, step * 0.68),
  )

  const prices = candles.flatMap(c => [
    c.high,
    c.low,
    ...(showSma && c.sma20 !== null
      ? [c.sma20]
      : []),
  ])

  const min = Math.min(...prices)
  const max = Math.max(...prices)

  const padding = Math.max(
    (max - min) * 0.07,
    max * 0.001,
  )

  const lo = Math.max(0, min - padding)
  const hi = max + padding

  const y = (price: number) =>
    top + (hi - price) / (hi - lo) * (bottom - top)

  const x = (index: number) =>
    left + (index + 0.5) * step

  const volumeMax = Math.max(
    1,
    ...candles.map(c => c.volume),
  )

  const selectedIndex = candles.findIndex(
    c => c.date === selectedDate,
  )

  const active = selectedIndex >= 0
    ? selectedIndex
    : candles.length - 1

  const line = candles.map(
    (c, i) =>
      `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(c.close)}`,
  ).join(' ')

  const smaLine = candles
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.sma20 !== null)
    .map(({ c, i }, index) =>
      `${index === 0 ? 'M' : 'L'} ${x(i)} ${y(c.sma20!)}`,
    ).join(' ')

  const ticks = Array.from(
    { length: 5 },
    (_, i) => lo + (hi - lo) * i / 4,
  )

  const dateIndices = [...new Set(
    Array.from(
      { length: Math.min(5, candles.length) },
      (_, i) => Math.round(
        i * (candles.length - 1) /
        Math.max(1, Math.min(5, candles.length) - 1),
      ),
    ),
  )]

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="market-svg"
      role="img"
      aria-label="Gráfica de precios diarios y volumen de Bitcoin"
      onPointerMove={event => {
        const rect =
          event.currentTarget.getBoundingClientRect()

        const px =
          (event.clientX - rect.left) / rect.width * W

        const index = Math.max(
          0,
          Math.min(
            candles.length - 1,
            Math.floor((px - left) / step),
          ),
        )

        onSelect(candles[index].date)
      }}
    >

      {ticks.map(price => (
        <g key={price}>
          <line
            x1={left}
            x2={right}
            y1={y(price)}
            y2={y(price)}
            stroke="#243148"
            strokeDasharray="4 5"
          />
          <text
            x={right + 12}
            y={y(price) + 4}
            fill="#95a5bd"
            fontSize="12"
          >
            {(price / 1000).toFixed(1)}k
          </text>
        </g>
      ))}

      {mode === 'candles' &&
        candles.map((c, i) => {

          const color = c.close >= c.open
            ? '#34d399'
            : '#f87171'

          return (
            <g key={c.date}>
              <line
                x1={x(i)}
                x2={x(i)}
                y1={y(c.high)}
                y2={y(c.low)}
                stroke={color}
                strokeWidth="1.3"
              />

              <rect
                x={x(i) - bodyWidth / 2}
                y={Math.min(y(c.open), y(c.close))}
                width={bodyWidth}
                height={Math.max(
                  1.3,
                  Math.abs(y(c.open) - y(c.close)),
                )}
                fill={color}
              />
            </g>
          )
        })
      }

      {mode === 'line' && (
        <path
          d={line}
          fill="none"
          stroke="#8b83ff"
          strokeWidth="2"
        />
      )}

      {showSma && (
        <path
          d={smaLine}
          fill="none"
          stroke="#fbbf24"
          strokeWidth="1.8"
        />
      )}

      <text
        x={left}
        y="293"
        fill="#95a5bd"
        fontSize="11"
      >
        Volumen BTC
      </text>

      {candles.map((c, i) => {

        const height = c.volume / volumeMax * 51

        return (
          <rect
            key={c.date}
            x={x(i) - bodyWidth / 2}
            y={352 - height}
            width={bodyWidth}
            height={height}
            fill={
              c.close >= c.open
                ? '#34d399'
                : '#f87171'
            }
            opacity="0.45"
          />
        )
      })}

      <line
        x1={x(active)}
        x2={x(active)}
        y1={top}
        y2="352"
        stroke="#b6b2ff"
        strokeDasharray="4 4"
      />

      <circle
        cx={x(active)}
        cy={y(candles[active].close)}
        r="3.5"
        fill="#b6b2ff"
      />

      {dateIndices.map((i, index) => (
        <text
          key={candles[i].date}
          x={x(i)}
          y="376"
          fill="#95a5bd"
          fontSize="11"
          textAnchor={
            index === 0 ? 'start'
              : index === dateIndices.length - 1
                ? 'end'
                : 'middle'
          }
        >
          {candles[i].date}
        </text>
      ))}

    </svg>
  )
}
