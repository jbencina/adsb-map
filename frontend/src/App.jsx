import { useState } from 'react'
import AircraftMap from './components/AircraftMap'
import { useAircraftData } from './hooks/useAircraftData'
import { useAircraftTracks } from './hooks/useAircraftTracks'
import { useFilteredAircraft } from './hooks/useFilteredAircraft'
import { useTheme } from './hooks/useTheme'
import {
  MAPBOX_TOKEN,
  DEFAULT_REFRESH_INTERVAL,
  DEFAULT_MAX_AGE_MINUTES,
  REFRESH_INTERVAL_MIN,
  REFRESH_INTERVAL_MAX,
  MAX_AGE_MIN,
  MAX_AGE_MAX,
} from './constants'
import './App.css'

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

  // Theme management
  const { themePreference, appliedTheme, setTheme } = useTheme()

  // Fetch aircraft data with polling
  const { aircraft, loading, error, lastUpdate } = useAircraftData(refreshInterval)

  // Filter aircraft based on age
  const filteredAircraft = useFilteredAircraft(aircraft, maxAgeMinutes)

  // Track aircraft flight paths
  const { tracks } = useAircraftTracks(aircraft, maxAgeMinutes)

  return (
    <div className="app">
      <header className="header" role="banner">
        <div className="header-top">
          <h1>ADSB Aircraft Tracker</h1>
          <button
            className="settings-button"
            onClick={() => setShowSettings(!showSettings)}
            aria-label={showSettings ? 'Hide settings' : 'Show settings'}
            aria-expanded={showSettings}
          >
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
          </button>
        </div>
        <div className="status" role="status" aria-live="polite">
          {loading ? (
            <span className="loading" aria-label="Loading aircraft data">
              Loading aircraft data...
            </span>
          ) : (
            <>
              <span
                className="aircraft-count"
                aria-label={`${filteredAircraft.length} aircraft currently tracked`}
              >
                {filteredAircraft.length} aircraft tracked
              </span>
              {lastUpdate && (
                <span
                  className="last-update"
                  aria-label={`Last update at ${lastUpdate.toLocaleTimeString()}`}
                >
                  Last update: {lastUpdate.toLocaleTimeString()}
                </span>
              )}
              {error && (
                <span className="error" role="alert" aria-label={`Error: ${error}`}>
                  Error: {error}
                </span>
              )}
            </>
          )}
        </div>
        {showSettings && (
          <div className="controls" role="group" aria-label="Map controls">
          <div className="refresh-interval-input">
            <label htmlFor="refresh-interval">Refresh Interval (seconds): </label>
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
            <span id="refresh-interval-desc" className="sr-only">
              How often to fetch new aircraft data, between {REFRESH_INTERVAL_MIN} and{' '}
              {REFRESH_INTERVAL_MAX} seconds
            </span>
          </div>
          <div className="max-age-input">
            <label htmlFor="max-age">Max Age (minutes): </label>
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
            <span id="max-age-desc" className="sr-only">
              Only show aircraft seen within this many minutes, between {MAX_AGE_MIN} and{' '}
              {MAX_AGE_MAX}
            </span>
          </div>
          <div className="show-tracks-toggle">
            <label htmlFor="show-tracks" className={isTrackingAircraft ? 'disabled' : ''}>
              <input
                id="show-tracks"
                type="checkbox"
                checked={showTracks}
                onChange={e => setShowTracks(e.target.checked)}
                aria-label="Toggle aircraft flight path tracks"
                aria-checked={showTracks}
                disabled={isTrackingAircraft}
              />
              Show Tracks
              {isTrackingAircraft && (
                <span className="disabled-hint"> (disabled while viewing aircraft track)</span>
              )}
            </label>
          </div>
          <div className="theme-toggle">
            <label htmlFor="theme-select">Theme: </label>
            <select
              id="theme-select"
              value={themePreference}
              onChange={e => setTheme(e.target.value)}
              aria-label="Select theme preference"
            >
              <option value="auto">Auto</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
            <span className="theme-indicator" aria-live="polite" aria-label={`Current theme: ${appliedTheme}`}>
              ({appliedTheme})
            </span>
          </div>
        </div>
        )}
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
