import { useRef, useEffect, useState, useMemo } from 'react'
import PropTypes from 'prop-types'
import Map, { Marker, Source, Layer } from 'react-map-gl'
import {
  DEFAULT_MAP_CENTER,
  INITIAL_ZOOM,
  MAP_STYLE_LIGHT,
  MAP_STYLE_DARK,
  TRACK_COLOR,
  TRACK_COLOR_DARK,
  TRACK_WIDTH,
  TRACK_OPACITY,
  SELECTED_TRACK_COLOR,
  SELECTED_TRACK_COLOR_DARK,
  SELECTED_TRACK_WIDTH,
  AIRCRAFT_GLYPH,
  SIGNAL_COLORS,
  AIRCRAFT_DB_CREDIT,
} from '../constants'
import { hasPosition } from '../aircraft'
import { aircraftRssi, signalColor, signalLevel } from '../signal'
import { useContinuousHeadings } from '../hooks/useContinuousHeadings'
import AircraftTags from './AircraftTags'
import SignalBars from './SignalBars'
import './AircraftMap.css'

/**
 * Map component that displays aircraft positions and tracks
 *
 * @param {Object} props - Component props
 * @param {Array} props.aircraft - Array of aircraft objects from the API
 * @param {string} props.mapboxToken - MapBox API token
 * @param {Object} props.tracks - Map of icao24 to array of [lon, lat, timestamp] points
 * @param {boolean} props.tracksLoaded - Whether `tracks` reflects at least one fetch
 * @param {boolean} props.showTracks - Whether to display every aircraft's track
 * @param {boolean} props.showLabels - Whether to draw a callsign tag beside each aircraft
 * @param {boolean} props.shadeBySignal - Whether to colour each marker by its signal strength
 * @param {Function} props.onSelectAircraft - Called with the selected icao24, or null
 * @param {string} props.theme - Current theme ('light' or 'dark')
 * @returns {JSX.Element} The map component
 */
function AircraftMap({
  aircraft,
  mapboxToken,
  tracks = {},
  tracksLoaded = false,
  showTracks = false,
  showLabels = false,
  shadeBySignal = false,
  maxAgeMinutes = 5,
  onSelectAircraft,
  theme = 'light',
}) {
  const mapRef = useRef(null)
  const [selectedAircraft, setSelectedAircraft] = useState(null)
  const [viewport, setViewport] = useState(DEFAULT_MAP_CENTER)
  const [mapInstance, setMapInstance] = useState(null)

  // Track if we've done initial centering
  const [hasInitialized, setHasInitialized] = useState(false)

  // Auto-center map on first aircraft load
  useEffect(() => {
    if (!hasInitialized && aircraft.length > 0 && mapRef.current) {
      // Calculate center of all aircraft
      const validAircraft = aircraft.filter(hasPosition)
      if (validAircraft.length > 0) {
        const avgLat = validAircraft.reduce((sum, a) => sum + a.latitude, 0) / validAircraft.length
        const avgLon = validAircraft.reduce((sum, a) => sum + a.longitude, 0) / validAircraft.length

        // One-time initialization of viewport - this is intentional
        setViewport({
          longitude: avgLon,
          latitude: avgLat,
          zoom: INITIAL_ZOOM,
        })
        setHasInitialized(true)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aircraft.length, hasInitialized])

  /**
   * Get the rotation for an aircraft glyph
   * Track is 0° for north, 90° for east, etc., and the glyph points up (north) by default,
   * so the angle maps directly to rotation. Callers pass the unwrapped heading rather than
   * the raw track so the CSS transition turns the short way across north.
   *
   * @param {number|null} heading - Unwrapped heading in degrees
   * @returns {string} CSS transform string
   */
  const getAircraftRotation = heading => {
    return heading !== null && heading !== undefined ? `rotate(${heading}deg)` : 'rotate(0deg)'
  }

  /**
   * Format altitude with thousands separator
   *
   * @param {number} altitude - Altitude in feet
   * @returns {string} Formatted altitude string
   */
  const formatAltitude = altitude => {
    return altitude?.toLocaleString() || 'N/A'
  }

  /**
   * Format speed to one decimal place
   *
   * @param {number} speed - Speed value
   * @returns {string} Formatted speed string
   */
  const formatSpeed = speed => {
    return speed?.toFixed(1) || 'N/A'
  }

  /**
   * Clean callsign by removing trailing underscores
   *
   * @param {string} callsign - Aircraft callsign
   * @returns {string} Cleaned callsign
   */
  const cleanCallsign = callsign => {
    return callsign?.replace(/_+$/, '') || 'Unknown'
  }

  /**
   * Format vertical rate magnitude with thousands separator; direction is shown as a glyph
   *
   * @param {number} rate - Vertical rate in ft/min
   * @returns {string} Formatted rate string
   */
  const formatVerticalRate = rate => {
    if (rate === null || rate === undefined) return 'N/A'
    return Math.abs(rate).toLocaleString()
  }

  /**
   * Format a signal level with a typographic minus sign
   *
   * @param {number} rssi - Signal level in dBFS
   * @returns {string} Formatted level
   */
  const formatRssi = rssi => rssi.toFixed(1).replace('-', '\u2212')

  // Filter aircraft with valid positions
  const validAircraft = useMemo(() => aircraft.filter(hasPosition), [aircraft])

  // Rotation that only ever turns the short way, so headings crossing north do not spin
  const headings = useContinuousHeadings(validAircraft)

  // The selection is a snapshot from click time; the card reads the live record so it keeps
  // updating, and falls back to the snapshot once the aircraft has aged out of the list
  const selected = useMemo(
    () => aircraft.find(a => a.icao24 === selectedAircraft?.icao24) ?? selectedAircraft,
    [aircraft, selectedAircraft]
  )
  const selectedRssi = selected ? aircraftRssi(selected) : null
  const selectedSignal = signalLevel(selectedRssi)
  const selectedIcao24 = selected?.icao24 ?? null

  // The parent polls track lines while something draws them, so tell it what is selected
  useEffect(() => {
    if (onSelectAircraft) onSelectAircraft(selectedIcao24)
  }, [selectedIcao24, onSelectAircraft])

  // The selected aircraft's line is the same data as the overview, just highlighted
  const selectedTrack = selectedIcao24 ? (tracks[selectedIcao24] ?? null) : null
  const loadingTrack = selectedIcao24 !== null && !tracksLoaded

  // Select map style and track colors based on theme
  const isDark = theme === 'dark'
  const mapStyle = isDark ? MAP_STYLE_DARK : MAP_STYLE_LIGHT
  const trackColor = isDark ? TRACK_COLOR_DARK : TRACK_COLOR
  const selectedTrackColor = isDark ? SELECTED_TRACK_COLOR_DARK : SELECTED_TRACK_COLOR
  const trackCasingColor = isDark ? '#000000' : '#ffffff'

  /**
   * Convert tracks data to GeoJSON format for MapBox
   * Memoized to avoid recalculating on every render
   */
  const tracksGeoJSON = useMemo(() => {
    const features = []

    Object.entries(tracks).forEach(([icao24, points]) => {
      if (points.length >= 2) {
        // Convert points to GeoJSON LineString
        const coordinates = points.map(p => [p[0], p[1]])
        features.push({
          type: 'Feature',
          properties: { icao24 },
          geometry: {
            type: 'LineString',
            coordinates,
          },
        })
      }
    })

    return {
      type: 'FeatureCollection',
      features,
    }
  }, [tracks])

  /**
   * Convert selected aircraft track to GeoJSON LineString for the track line
   * Memoized to avoid recalculating on every render
   */
  const selectedTrackLineGeoJSON = useMemo(() => {
    if (!selectedTrack || selectedTrack.length < 2) {
      return {
        type: 'FeatureCollection',
        features: [],
      }
    }

    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { icao24: selectedIcao24 },
          geometry: {
            type: 'LineString',
            coordinates: selectedTrack.map(p => [p[0], p[1]]),
          },
        },
      ],
    }
  }, [selectedTrack, selectedIcao24])

  /**
   * Convert selected aircraft track to GeoJSON Points for the dots
   * Memoized to avoid recalculating on every render
   */
  const selectedTrackPointsGeoJSON = useMemo(() => {
    if (!selectedTrack || selectedTrack.length === 0) {
      return {
        type: 'FeatureCollection',
        features: [],
      }
    }

    // Create a Point feature for each position
    const features = selectedTrack.map(([lon, lat, timestamp], index) => ({
      type: 'Feature',
      properties: { icao24: selectedIcao24, timestamp, index },
      geometry: {
        type: 'Point',
        coordinates: [lon, lat],
      },
    }))

    return {
      type: 'FeatureCollection',
      features,
    }
  }, [selectedTrack, selectedIcao24])

  if (!mapboxToken) {
    return (
      <div className="map-placeholder" role="alert">
        <p>Please enter your MapBox API token above to display the map</p>
      </div>
    )
  }

  return (
    <div className="map-container" role="region" aria-label="Aircraft tracking map">
      <Map
        ref={mapRef}
        {...viewport}
        onMove={evt => setViewport(evt.viewState)}
        mapboxAccessToken={mapboxToken}
        style={{ width: '100%', height: '100%' }}
        mapStyle={mapStyle}
        onLoad={e => setMapInstance(e.target)}
      >
        {/* Every aircraft's track; the selected one is drawn again on top, highlighted */}
        {showTracks && (
          <Source id="aircraft-tracks" type="geojson" data={tracksGeoJSON}>
            <Layer
              id="tracks-layer"
              type="line"
              paint={{
                'line-color': trackColor,
                'line-width': TRACK_WIDTH,
                'line-opacity': TRACK_OPACITY,
              }}
            />
          </Source>
        )}

        {/* Render selected aircraft detailed track */}
        {selectedTrack && (
          <>
            {/* Track line */}
            <Source
              id="selected-aircraft-track-line"
              type="geojson"
              data={selectedTrackLineGeoJSON}
              lineMetrics
            >
              <Layer
                id="selected-track-casing"
                type="line"
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
                paint={{
                  'line-color': trackCasingColor,
                  'line-width': SELECTED_TRACK_WIDTH + 2,
                  'line-opacity': 0.5,
                }}
              />
              <Layer
                id="selected-track-layer"
                type="line"
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
                paint={{
                  'line-color': selectedTrackColor,
                  'line-width': SELECTED_TRACK_WIDTH,
                  // Fade into the past so the line also reads as a direction
                  'line-gradient': [
                    'interpolate',
                    ['linear'],
                    ['line-progress'],
                    0,
                    isDark ? 'rgba(59, 156, 255, 0.2)' : 'rgba(0, 113, 227, 0.2)',
                    1,
                    selectedTrackColor,
                  ],
                }}
              />
            </Source>
            {/* Track points as circles - size increases with zoom for visibility */}
            <Source
              id="selected-aircraft-track-points"
              type="geojson"
              data={selectedTrackPointsGeoJSON}
            >
              <Layer
                id="selected-track-points"
                type="circle"
                paint={{
                  // Individual reports only surface once zoomed in enough to separate them
                  'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 0, 11, 2, 15, 3],
                  'circle-color': trackCasingColor,
                  'circle-stroke-color': selectedTrackColor,
                  'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 9, 0, 11, 1.5],
                  'circle-opacity': 0.9,
                }}
              />
            </Source>
          </>
        )}

        {validAircraft.map(ac => {
          const fill = shadeBySignal ? signalColor(aircraftRssi(ac)) : null
          return (
            <Marker
              key={ac.icao24}
              longitude={ac.longitude}
              latitude={ac.latitude}
              anchor="center"
              style={{ zIndex: selectedAircraft?.icao24 === ac.icao24 ? 2 : 1 }}
              onClick={e => {
                e.originalEvent.stopPropagation()
                setSelectedAircraft(ac)
              }}
            >
              <div
                className={[
                  'aircraft-marker',
                  selectedAircraft?.icao24 === ac.icao24 ? 'selected' : '',
                  fill ? 'shaded' : '',
                ].join(' ')}
                style={{
                  transform: getAircraftRotation(headings[ac.icao24]),
                  ...(fill && { '--marker-fill': fill }),
                }}
                title={[
                  cleanCallsign(ac.callsign) || ac.icao24,
                  ac.registration ? `(${ac.registration})` : null,
                  ac.typecode ? `- ${ac.typecode}` : null,
                ]
                  .filter(Boolean)
                  .join(' ')}
                role="button"
                tabIndex={0}
                aria-label={`Aircraft ${ac.callsign || ac.icao24} at ${formatAltitude(ac.altitude)} feet`}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setSelectedAircraft(ac)
                  }
                }}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d={AIRCRAFT_GLYPH} />
                </svg>
              </div>
            </Marker>
          )
        })}
      </Map>

      {/* Callsign tags with leader lines, laid out in screen space beneath the plane markers */}
      <AircraftTags
        map={mapInstance}
        aircraft={validAircraft}
        selectedId={selectedAircraft?.icao24 ?? null}
        maxAgeMinutes={maxAgeMinutes}
        visible={showLabels}
      />

      {/* Detail card for the selected aircraft */}
      <div className={`aircraft-sidebar ${selected ? 'active' : ''}`}>
        {selected ? (
          <>
            <div className="sidebar-header">
              <h3>
                <span>{cleanCallsign(selected.callsign)}</span>
                <span className="sidebar-subtitle">
                  {selected.registration && <b>{selected.registration}</b>}
                  {selected.type_description && <span>{selected.type_description}</span>}
                  {!selected.type_description && selected.typecode && (
                    <span>{selected.typecode}</span>
                  )}
                </span>
                {loadingTrack && <span className="loading-indicator">Loading track…</span>}
              </h3>
              <button
                className="close-button"
                onClick={() => setSelectedAircraft(null)}
                aria-label="Close aircraft details"
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
            <div className="sidebar-content">
              <div className="flight-strip" role="group" aria-label="Flight data">
                <div className="stat">
                  <div className="stat-value">
                    {formatAltitude(selected.altitude)}
                    <small>ft</small>
                  </div>
                  <span className="stat-label">Altitude</span>
                </div>
                <div className="stat">
                  <div className="stat-value">
                    {formatSpeed(selected.groundspeed)}
                    <small>kts</small>
                  </div>
                  <span className="stat-label">Speed</span>
                </div>
                <div className="stat">
                  <div className="stat-value">
                    {selected.vertical_rate ? (
                      <svg
                        className="dir"
                        viewBox="0 0 10 10"
                        aria-label={selected.vertical_rate > 0 ? 'Climbing' : 'Descending'}
                        style={{
                          transform: selected.vertical_rate > 0 ? 'none' : 'rotate(180deg)',
                        }}
                      >
                        <path d="M5 1l4.5 6h-9z" />
                      </svg>
                    ) : null}
                    {formatVerticalRate(selected.vertical_rate)}
                    <small>ft/min</small>
                  </div>
                  <span className="stat-label">Vertical rate</span>
                </div>
              </div>

              <div className="info-group">
                <div className="info-section-title">Aircraft</div>
                <div className="info-row">
                  <span className="label">ICAO 24</span>
                  <span className="value">{selected.icao24}</span>
                </div>
                <div className="info-row">
                  <span className="label">Registration</span>
                  <span className="value">{selected.registration || 'N/A'}</span>
                </div>
                {selected.type_description && (
                  <div className="info-row">
                    <span className="label">Aircraft</span>
                    <span className="value">{selected.type_description}</span>
                  </div>
                )}
                <div className="info-row">
                  <span className="label">Type</span>
                  <span className="value">{selected.typecode || 'N/A'}</span>
                </div>
              </div>

              <div className="divider"></div>

              <div className="info-group">
                <div className="info-section-title">Flight</div>
                <div
                  className="info-row"
                  title="Ground track from the latest velocity report; the line on the map is drawn from position reports, so the two can differ slightly"
                >
                  <span className="label">Track</span>
                  <span className="value">
                    {selected.track !== null && selected.track !== undefined && (
                      <svg
                        className="heading"
                        viewBox="0 0 12 12"
                        aria-hidden="true"
                        style={{
                          transform: `rotate(${headings[selected.icao24] ?? selected.track}deg)`,
                        }}
                      >
                        <path d="M6 1.5v9M2.5 5L6 1.5 9.5 5" />
                      </svg>
                    )}
                    {selected.track?.toFixed(1) || 'N/A'}°
                  </span>
                </div>
                <div className="info-row">
                  <span className="label">Squawk</span>
                  <span className="value">{selected.squawk || 'N/A'}</span>
                </div>
              </div>

              <div className="info-group">
                <div className="info-section-title">Reception</div>
                <div className="info-row">
                  <span className="label">Signal</span>
                  <span className="value signal">
                    <SignalBars
                      bars={selectedSignal.bars}
                      label={`Signal strength ${selectedSignal.label.toLowerCase()}`}
                    />
                    {selectedSignal.label}
                  </span>
                </div>
                {selectedRssi !== null && (
                  <div className="info-row">
                    <span className="label">RSSI</span>
                    <span className="value">{formatRssi(selectedRssi)} dBFS</span>
                  </div>
                )}
              </div>

              {selectedTrack && (
                <p className="track-footnote">
                  {selectedTrack.length} track points in the last {maxAgeMinutes} min
                </p>
              )}
              {tracksLoaded && !selectedTrack && (
                <p className="track-footnote">No positions in the last {maxAgeMinutes} min</p>
              )}
              {(selected.registration || selected.typecode || selected.type_description) && (
                <p className="track-footnote credit">
                  Registration and type: {AIRCRAFT_DB_CREDIT.text}{' '}
                  <a href={AIRCRAFT_DB_CREDIT.url} target="_blank" rel="noreferrer">
                    {AIRCRAFT_DB_CREDIT.license}
                  </a>
                </p>
              )}
            </div>
          </>
        ) : null}
      </div>

      {/* Colour key while markers are shaded by signal strength */}
      {shadeBySignal && (
        <div
          className="signal-legend"
          role="img"
          aria-label="Marker colour shows signal strength, from weak to strong"
        >
          <span>Weak</span>
          <span
            className="signal-legend-ramp"
            style={{ background: `linear-gradient(90deg, ${SIGNAL_COLORS.join(', ')})` }}
          />
          <span>Strong</span>
        </div>
      )}
    </div>
  )
}

AircraftMap.propTypes = {
  aircraft: PropTypes.arrayOf(
    PropTypes.shape({
      icao24: PropTypes.string.isRequired,
      callsign: PropTypes.string,
      latitude: PropTypes.number,
      longitude: PropTypes.number,
      altitude: PropTypes.number,
      groundspeed: PropTypes.number,
      track: PropTypes.number,
      vertical_rate: PropTypes.number,
      squawk: PropTypes.string,
      registration: PropTypes.string,
      typecode: PropTypes.string,
      type_description: PropTypes.string,
      lastseen: PropTypes.number,
      metadata: PropTypes.arrayOf(PropTypes.shape({ rssi: PropTypes.number })),
    })
  ).isRequired,
  mapboxToken: PropTypes.string.isRequired,
  tracks: PropTypes.objectOf(PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.number))),
  tracksLoaded: PropTypes.bool,
  showTracks: PropTypes.bool,
  showLabels: PropTypes.bool,
  shadeBySignal: PropTypes.bool,
  maxAgeMinutes: PropTypes.number,
  onSelectAircraft: PropTypes.func,
  theme: PropTypes.oneOf(['light', 'dark']),
}

AircraftMap.defaultProps = {
  tracks: {},
  tracksLoaded: false,
  showTracks: false,
  showLabels: false,
  shadeBySignal: false,
  maxAgeMinutes: 5,
  onSelectAircraft: null,
  theme: 'light',
}

export default AircraftMap
