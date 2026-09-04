import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AircraftMap from './components/AircraftMap'
import HistoryOverlay from './components/HistoryOverlay'
import { useAircraftData } from './hooks/useAircraftData'
import { useAircraftTracks } from './hooks/useAircraftTracks'
import { useFilteredAircraft } from './hooks/useFilteredAircraft'
import { hasPosition } from './aircraft'
import BoundedNumberInput from './components/BoundedNumberInput'
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
  const [showLabels, setShowLabels] = useState(true)
  const [shadeBySignal, setShadeBySignal] = useState(false)
  const [selectedIcao24, setSelectedIcao24] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef(null)
  const [showHistory, setShowHistory] = useState(false)
  const historyButtonRef = useRef(null)

  // The history view is a layer over the map; closing it hands focus back to its button
  const closeHistory = useCallback(() => {
    setShowHistory(false)
    historyButtonRef.current?.focus()
  }, [])

  // Theme management
  const { themePreference, appliedTheme, setTheme } = useTheme()

  // Fetch aircraft data with polling; the backend filters by age server-side
  const { aircraft, loading, error, lastUpdate } = useAircraftData(refreshInterval, maxAgeMinutes)

  // Re-apply the age filter locally so aircraft drop off between polls
  const filteredAircraft = useFilteredAircraft(aircraft, maxAgeMinutes)

  // The header counts what the map draws; position-less aircraft are still tracked but invisible
  const onMapCount = useMemo(() => filteredAircraft.filter(hasPosition).length, [filteredAircraft])

  // Track lines from the backend's stored positions, polled only while something draws them
  const { tracks, loaded: tracksLoaded } = useAircraftTracks(
    showTracks || selectedIcao24 !== null,
    refreshInterval,
    maxAgeMinutes
  )

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
                <span className="aircraft-count" aria-label={`${onMapCount} aircraft on the map`}>
                  <span className={`live-dot ${error ? 'stale' : ''}`} aria-hidden="true" />
                  {onMapCount} aircraft
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
              ref={historyButtonRef}
              className={`toolbar-button ${showHistory ? 'open' : ''}`}
              onClick={() => {
                setShowSettings(false)
                setShowHistory(true)
              }}
              aria-label="Show history"
              aria-expanded={showHistory}
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.75"
                  d="M3 12a9 9 0 1 0 3-6.7M3 4v4.5h4.5M12 7v5l3.5 2"
                />
              </svg>
            </button>

            <button
              className={`toolbar-button settings-gear ${showSettings ? 'open' : ''}`}
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
                    <BoundedNumberInput
                      id="refresh-interval"
                      min={REFRESH_INTERVAL_MIN}
                      max={REFRESH_INTERVAL_MAX}
                      value={refreshInterval}
                      onChange={setRefreshInterval}
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
                    <BoundedNumberInput
                      id="max-age"
                      min={MAX_AGE_MIN}
                      max={MAX_AGE_MAX}
                      value={maxAgeMinutes}
                      onChange={setMaxAgeMinutes}
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

                <div className="control-row show-labels-toggle">
                  <label htmlFor="show-labels">Show callsigns</label>
                  <input
                    id="show-labels"
                    className="switch"
                    type="checkbox"
                    role="switch"
                    checked={showLabels}
                    onChange={e => setShowLabels(e.target.checked)}
                    aria-label="Toggle aircraft callsign labels"
                    aria-checked={showLabels}
                  />
                </div>

                <div className="control-row shade-by-signal-toggle">
                  <label htmlFor="shade-by-signal">Shade by signal</label>
                  <input
                    id="shade-by-signal"
                    className="switch"
                    type="checkbox"
                    role="switch"
                    checked={shadeBySignal}
                    onChange={e => setShadeBySignal(e.target.checked)}
                    aria-label="Toggle shading aircraft markers by signal strength"
                    aria-checked={shadeBySignal}
                  />
                </div>

                <div className="control-row show-tracks-toggle">
                  <label htmlFor="show-tracks">Show tracks</label>
                  <input
                    id="show-tracks"
                    className="switch"
                    type="checkbox"
                    role="switch"
                    checked={showTracks}
                    onChange={e => setShowTracks(e.target.checked)}
                    aria-label="Toggle aircraft flight path tracks"
                    aria-checked={showTracks}
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
          tracksLoaded={tracksLoaded}
          showTracks={showTracks}
          showLabels={showLabels}
          shadeBySignal={shadeBySignal}
          maxAgeMinutes={maxAgeMinutes}
          onSelectAircraft={setSelectedIcao24}
          theme={appliedTheme}
        />
      </main>
      {showHistory && <HistoryOverlay onClose={closeHistory} />}
    </div>
  )
}

export default App
