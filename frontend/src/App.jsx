import { useEffect, useRef, useState } from 'react'
import AircraftMap from './components/AircraftMap'
import { useAircraftData } from './hooks/useAircraftData'
import { useAircraftTracks } from './hooks/useAircraftTracks'
import { useFilteredAircraft } from './hooks/useFilteredAircraft'
import { useTheme } from './hooks/useTheme'
import {
  MAPBOX_TOKEN,
  DEMO_MODE,
  DEFAULT_REFRESH_INTERVAL,
  DEFAULT_MAX_AGE_MINUTES,
  REFRESH_INTERVAL_MIN,
  REFRESH_INTERVAL_MAX,
  MAX_AGE_MIN,
  MAX_AGE_MAX,
  AIRCRAFT_GLYPH,
} from './constants'
import './App.css'

const THEME_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

/**
 * Main application component that fetches aircraft data and displays it on a map
 *
 * @returns {JSX.Element} The main app component
 */
function App() {
  const [refreshInterval, setRefreshInterval] = useState(DEFAULT_REFRESH_INTERVAL)
  const [maxAgeMinutes, setMaxAgeMinutes] = useState(DEFAULT_MAX_AGE_MINUTES)
  const [showTracks, setShowTracks] = useState(false)
  const [isTrackingAircraft, setIsTrackingAircraft] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef(null)

  // Theme management
  const { themePreference, appliedTheme, setTheme } = useTheme()

  // Fetch aircraft data with polling
  const { aircraft, loading, error, lastUpdate } = useAircraftData(refreshInterval)

  // Filter aircraft based on age
  const filteredAircraft = useFilteredAircraft(aircraft, maxAgeMinutes)

  // Track aircraft flight paths
  const { tracks } = useAircraftTracks(aircraft, maxAgeMinutes)

  // Close the settings popover on Escape or on a click outside it
  useEffect(() => {
    if (!showSettings) return undefined
    const onKey = e => {
      if (e.key === 'Escape') setShowSettings(false)
    }
    const onPointer = e => {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) setShowSettings(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [showSettings])

  return (
    <div className="app">
      <header className="header" role="banner">
        <div className="toolbar">
          <div className="brand">
            <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
              <path d={AIRCRAFT_GLYPH} />
            </svg>
            <h1>ADSB Aircraft Tracker</h1>
          </div>

          <div className="status" role="status" aria-live="polite">
            {loading ? (
              <span className="loading" aria-label="Loading aircraft data">
                Loading aircraft data…
              </span>
            ) : (
              <>
                <span
                  className="aircraft-count"
                  aria-label={`${filteredAircraft.length} aircraft currently tracked`}
                >
                  <span className={`live-dot ${error ? 'stale' : ''}`} aria-hidden="true" />
                  {filteredAircraft.length} aircraft
                </span>
                {lastUpdate && (
                  <span
                    className="last-update"
                    aria-label={`Last update at ${lastUpdate.toLocaleTimeString()}`}
                  >
                    Updated {lastUpdate.toLocaleTimeString()}
                  </span>
                )}
                {error && (
                  <span className="error" role="alert" aria-label={`Error: ${error}`}>
                    {error}
                  </span>
                )}
                {DEMO_MODE && (
                  <span className="demo-badge" title="Simulated aircraft; no backend connected">
                    Demo data
                  </span>
                )}
              </>
            )}
          </div>

          <div className="settings" ref={settingsRef}>
            <button
              className={`settings-button ${showSettings ? 'open' : ''}`}
              onClick={() => setShowSettings(!showSettings)}
              aria-label={showSettings ? 'Hide settings' : 'Show settings'}
              aria-expanded={showSettings}
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.75"
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.75"
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
            </button>

            {showSettings && (
              <div className="controls" role="group" aria-label="Map controls">
                <div className="control-row refresh-interval-input">
                  <label htmlFor="refresh-interval">Refresh interval</label>
                  <div className="field">
                    <input
                      id="refresh-interval"
                      type="number"
                      min={REFRESH_INTERVAL_MIN}
                      max={REFRESH_INTERVAL_MAX}
                      value={refreshInterval}
                      onChange={e => setRefreshInterval(Number(e.target.value))}
                      aria-label="Set refresh interval in seconds"
                      aria-describedby="refresh-interval-desc"
                    />
                    <span className="unit" aria-hidden="true">
                      sec
                    </span>
                  </div>
                  <span id="refresh-interval-desc" className="sr-only">
                    How often to fetch new aircraft data, between {REFRESH_INTERVAL_MIN} and{' '}
                    {REFRESH_INTERVAL_MAX} seconds
                  </span>
                </div>

                <div className="control-row max-age-input">
                  <label htmlFor="max-age">Max age</label>
                  <div className="field">
                    <input
                      id="max-age"
                      type="number"
                      min={MAX_AGE_MIN}
                      max={MAX_AGE_MAX}
                      value={maxAgeMinutes}
                      onChange={e => setMaxAgeMinutes(Number(e.target.value))}
                      aria-label="Set maximum age of aircraft data in minutes"
                      aria-describedby="max-age-desc"
                    />
                    <span className="unit" aria-hidden="true">
                      min
                    </span>
                  </div>
                  <span id="max-age-desc" className="sr-only">
                    Only show aircraft seen within this many minutes, between {MAX_AGE_MIN} and{' '}
                    {MAX_AGE_MAX}
                  </span>
                </div>

                <div
                  className={`control-row show-tracks-toggle ${isTrackingAircraft ? 'disabled' : ''}`}
                >
                  <label htmlFor="show-tracks">
                    Show tracks
                    {isTrackingAircraft && (
                      <span className="disabled-hint">
                        Unavailable while an aircraft is selected
                      </span>
                    )}
                  </label>
                  <input
                    id="show-tracks"
                    className="switch"
                    type="checkbox"
                    role="switch"
                    checked={showTracks}
                    onChange={e => setShowTracks(e.target.checked)}
                    aria-label="Toggle aircraft flight path tracks"
                    aria-checked={showTracks}
                    disabled={isTrackingAircraft}
                  />
                </div>

                <div className="control-row theme-toggle">
                  <span className="control-label" id="theme-label">
                    Theme
                    <span
                      className="theme-indicator"
                      aria-live="polite"
                      aria-label={`Current theme: ${appliedTheme}`}
                    >
                      {themePreference === 'auto'
                        ? `Following system, ${appliedTheme}`
                        : `Always ${appliedTheme}`}
                    </span>
                  </span>
                  <div className="segmented" role="radiogroup" aria-labelledby="theme-label">
                    {THEME_OPTIONS.map(opt => (
                      <label
                        key={opt.value}
                        className={`segment ${themePreference === opt.value ? 'selected' : ''}`}
                      >
                        <input
                          type="radio"
                          name="theme"
                          value={opt.value}
                          checked={themePreference === opt.value}
                          onChange={() => setTheme(opt.value)}
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>
      <main role="main">
        <AircraftMap
          aircraft={filteredAircraft}
          mapboxToken={MAPBOX_TOKEN}
          tracks={tracks}
          showTracks={showTracks}
          maxAgeMinutes={maxAgeMinutes}
          onTrackingAircraft={setIsTrackingAircraft}
          theme={appliedTheme}
        />
      </main>
    </div>
  )
}

export default App
