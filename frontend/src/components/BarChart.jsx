import PropTypes from 'prop-types'
import { bucketRange, formatCount, gridValues, timeTicks } from '../stats'

/**
 * One bar per bucket, heights as percentages of a rounded axis maximum.
 * Plain HTML so nothing needs measuring: the row of bars is a flex container
 * and the gridlines are positioned from the bottom.
 *
 * @param {Object} props
 * @param {Array<{start: number}>} props.buckets - Full grid, oldest first
 * @param {number} props.interval - Bucket size in seconds
 * @param {'messages'|'aircraft'} props.valueKey - Which field to draw
 * @param {string} props.unit - Noun for tooltips and the accessible label
 */
function BarChart({ buckets, interval, valueKey, unit }) {
  const grid = gridValues(Math.max(0, ...buckets.map(b => b[valueKey])))
  const max = grid.at(-1)
  const total = buckets.reduce((sum, b) => sum + b[valueKey], 0)
  const ticks = timeTicks(buckets, interval)
  const label = `${unit} per ${interval >= 3600 ? 'hour' : `${interval / 60} minutes`} over the last day`

  return (
    <div className="chart" role="img" aria-label={label}>
      <div className="chart-plot">
        {grid.map(v => (
          <div key={v} className="chart-grid" style={{ bottom: `${(v / max) * 100}%` }}>
            <span>{formatCount(v)}</span>
          </div>
        ))}
        <div className="chart-bars">
          {buckets.map((b, i) => (
            <div
              key={b.start}
              className={`chart-bar ${i === buckets.length - 1 ? 'current' : ''}`}
              style={{ height: `${(b[valueKey] / max) * 100}%` }}
              title={`${bucketRange(b.start, interval)}\n${b[valueKey].toLocaleString()} ${unit}`}
            />
          ))}
        </div>
        {total === 0 && <div className="chart-empty">No traffic recorded yet</div>}
      </div>
      <div className="chart-axis">
        {ticks.map(t => (
          <span key={t.index} style={{ left: `${((t.index + 0.5) / buckets.length) * 100}%` }}>
            {t.label}
          </span>
        ))}
      </div>
    </div>
  )
}

BarChart.propTypes = {
  buckets: PropTypes.arrayOf(PropTypes.object).isRequired,
  interval: PropTypes.number.isRequired,
  valueKey: PropTypes.oneOf(['messages', 'aircraft']).isRequired,
  unit: PropTypes.string.isRequired,
}

export default BarChart
