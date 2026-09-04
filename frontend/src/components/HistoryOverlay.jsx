import { useEffect, useRef, useState } from 'react'
import PropTypes from 'prop-types'
import BarChart from './BarChart'
import TopAircraftTable from './TopAircraftTable'
import { useStats } from '../hooks/useStats'
import { INTERVAL_OPTIONS, formatCount } from '../stats'
import './HistoryOverlay.css'

const DEFAULT_INTERVAL = 900

/**
 * Full-screen history view over the map. The map keeps running underneath;
 * Escape or the X closes it.
 *
 * @param {Object} props
 * @param {Function} props.onClose - Called to dismiss the view
 */
function HistoryOverlay({ onClose }) {
  const [interval, setInterval] = useState(DEFAULT_INTERVAL)
  const { stats, loading, error } = useStats(true, interval)
  const closeRef = useRef(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const buckets = stats?.buckets ?? []
  const messages = buckets.reduce((sum, b) => sum + b.messages, 0)
  const peak = buckets.reduce((max, b) => Math.max(max, b.aircraft), 0)
  const now = stats?.now ?? Math.floor(Date.now() / 1000)

  return (
    <div className="history" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <div className="history-scroll">
        <div className="history-inner">
          <header className="history-header">
            <div>
              <h2 id="history-title">History</h2>
              <p className="history-subtitle">
                Last 24 hours
                {stats && <> · updated {new Date(now * 1000).toLocaleTimeString()}</>}
                {loading && <span className="loading-indicator"> Refreshing…</span>}
                {error && (
                  <span className="history-error" role="alert">
                    {' '}
                    {error}
                  </span>
                )}
              </p>
            </div>
            <div className="history-actions">
              <div className="segmented" role="radiogroup" aria-label="Chart interval">
                {INTERVAL_OPTIONS.map(opt => (
                  <label
                    key={opt.value}
                    className={`segment ${interval === opt.value ? 'selected' : ''}`}
                  >
                    <input
                      type="radio"
                      name="history-interval"
                      value={opt.value}
                      checked={interval === opt.value}
                      onChange={() => setInterval(opt.value)}
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
              <button
                ref={closeRef}
                className="close-button"
                onClick={onClose}
                aria-label="Close history"
              >
                <svg
                  viewBox="0 0 12 12"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M2 2l8 8M10 2l-8 8" />
                </svg>
              </button>
            </div>
          </header>

          <div className="history-strip">
            <div className="stat">
              <div className="stat-value">{formatCount(messages)}</div>
              <div className="stat-label">Messages</div>
            </div>
            <div className="stat">
              <div className="stat-value">{peak}</div>
              <div className="stat-label">Peak aircraft in a minute</div>
            </div>
            <div className="stat">
              <div className="stat-value">{stats?.aircraft_seen ?? 0}</div>
              <div className="stat-label">Aircraft heard</div>
            </div>
          </div>

          <section className="history-card">
            <h3 className="info-section-title">Message volume</h3>
            <BarChart buckets={buckets} interval={interval} valueKey="messages" unit="messages" />
          </section>

          <section className="history-card">
            <h3 className="info-section-title">Aircraft tracked</h3>
            <p className="card-note">Most aircraft heard in any one minute of each interval</p>
            <BarChart buckets={buckets} interval={interval} valueKey="aircraft" unit="aircraft" />
          </section>

          <div className="history-tables">
            <section className="history-card">
              <h3 className="info-section-title">Top aircraft · last 24 hours</h3>
              <TopAircraftTable rows={stats?.top_window ?? []} now={now} />
            </section>
            <section className="history-card">
              <h3 className="info-section-title">Top aircraft · all time</h3>
              <TopAircraftTable rows={stats?.top_lifetime ?? []} now={now} />
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

HistoryOverlay.propTypes = {
  onClose: PropTypes.func.isRequired,
}

export default HistoryOverlay
