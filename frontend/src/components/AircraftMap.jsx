import { useRef, useEffect, useState, useMemo } from 'react'
import PropTypes from 'prop-types'
import Map, { Marker, Source, Layer } from 'react-map-gl'
import { fetchAircraftTrack } from '../services/api'
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
} from '../constants'
import AircraftTags from './AircraftTags'
import './AircraftMap.css'

/**
 * Map component that displays aircraft positions and tracks
 *
 * @param {Object} props - Component props
 * @param {Array} props.aircraft - Array of aircraft objects from the API
 * @param {string} props.mapboxToken - MapBox API token
 * @param {Object} props.tracks - Map of icao24 to array of position points
 * @param {boolean} props.showTracks - Whether to display tracks
 * @param {boolean} props.showLabels - Whether to draw a callsign tag beside each aircraft
 * @param {string} props.theme - Current theme ('light' or 'dark')
 * @returns {JSX.Element} The map component
 */
function AircraftMap({
  aircraft,
  mapboxToken,
  tracks = {},
  showTracks = false,
  showLabels = false,
  maxAgeMinutes = 5,
  onTrackingAircraft,
  theme = 'light',
}) {
  const mapRef = useRef(null)
  const [selectedAircraft, setSelectedAircraft] = useState(null)
  const [selectedAircraftTrack, setSelectedAircraftTrack] = useState(null)
  const [loadingTrack, setLoadingTrack] = useState(false)
  const [viewport, setViewport] = useState(DEFAULT_MAP_CENTER)
  const [mapInstance, setMapInstance] = useState(null)

  // Track if we've done initial centering
  const [hasInitialized, setHasInitialized] = useState(false)

  // Auto-center map on first aircraft load
  useEffect(() => {
    if (!hasInitialized && aircraft.length > 0 && mapRef.current) {
      // Calculate center of all aircraft
      const validAircraft = aircraft.filter(a => a.latitude && a.longitude)
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
   * Get the rotation angle for the aircraft icon based on track
   * Aircraft track is 0° for north, 90° for east, etc.
   * The marker glyph points up (north) by default, so the track maps directly to rotation
   *
   * @param {number} track - Aircraft track in degrees
   * @returns {string} CSS transform string
   */
  const getAircraftRotation = track => {
    return track !== null && track !== undefined ? `rotate(${track}deg)` : 'rotate(0deg)'
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
   * How far a marker has aged toward maxAgeMinutes, 0 (just heard) to 1 (about to expire).
   * The stylesheet blends the marker's ink toward gray by this amount.
   *
   * @param {number} lastseen - Unix timestamp of last seen
   * @returns {number} Age ratio between 0 and 1
   */
  const getAircraftAge = lastseen => {
    if (!lastseen) return 0
    const ageInMinutes = (Math.floor(Date.now() / 1000) - lastseen) / 60
    return Math.min(ageInMinutes / maxAgeMinutes, 1)
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

  // Fetch detailed track when an aircraft is selected
  useEffect(() => {
    if (selectedAircraft) {
      setLoadingTrack(true)
      fetchAircraftTrack(selectedAircraft.icao24)
        .then(trackData => {
          setSelectedAircraftTrack(trackData)
          setLoadingTrack(false)
          // Notify parent that we're tracking an aircraft
          if (onTrackingAircraft) {
            onTrackingAircraft(true)
          }
        })
        .catch(error => {
          console.error('Error fetching aircraft track:', error)
          setLoadingTrack(false)
        })
    } else {
      setSelectedAircraftTrack(null)
      // Notify parent that we're no longer tracking
      if (onTrackingAircraft) {
        onTrackingAircraft(false)
      }
    }
  }, [selectedAircraft, onTrackingAircraft])

  // Filter aircraft with valid positions
  const validAircraft = useMemo(() => aircraft.filter(a => a.latitude && a.longitude), [aircraft])

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
    if (!selectedAircraftTrack || selectedAircraftTrack.length < 2) {
      return {
        type: 'FeatureCollection',
        features: [],
      }
    }

    // Convert track positions to coordinates [lon, lat]
    const coordinates = selectedAircraftTrack
      .filter(pos => pos.longitude !== null && pos.latitude !== null)
      .map(pos => [pos.longitude, pos.latitude])

    if (coordinates.length < 2) {
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
          properties: { icao24: selectedAircraft?.icao24 },
          geometry: {
            type: 'LineString',
            coordinates,
          },
        },
      ],
    }
  }, [selectedAircraftTrack, selectedAircraft])

  /**
   * Convert selected aircraft track to GeoJSON Points for the dots
   * Memoized to avoid recalculating on every render
   */
  const selectedTrackPointsGeoJSON = useMemo(() => {
    if (!selectedAircraftTrack || selectedAircraftTrack.length === 0) {
      return {
        type: 'FeatureCollection',
        features: [],
      }
    }

    // Create a Point feature for each position
    const features = selectedAircraftTrack
      .filter(pos => pos.longitude !== null && pos.latitude !== null)
      .map((pos, index) => ({
        type: 'Feature',
        properties: {
          icao24: selectedAircraft?.icao24,
          timestamp: pos.timestamp,
          index,
        },
        geometry: {
          type: 'Point',
          coordinates: [pos.longitude, pos.latitude],
        },
      }))

    return {
      type: 'FeatureCollection',
      features,
    }
  }, [selectedAircraftTrack, selectedAircraft])

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
        {/* Render all aircraft tracks (only when not showing selected aircraft track) */}
        {showTracks && !selectedAircraftTrack && (
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
        {selectedAircraftTrack && (
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

        {validAircraft.map(ac => (
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
              className={`aircraft-marker ${selectedAircraft?.icao24 === ac.icao24 ? 'selected' : ''}`}
              style={{
                transform: getAircraftRotation(ac.track),
                '--age': getAircraftAge(ac.lastseen),
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
        ))}
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
      <div className={`aircraft-sidebar ${selectedAircraft ? 'active' : ''}`}>
        {selectedAircraft ? (
          <>
            <div className="sidebar-header">
              <h3>
                <span>{cleanCallsign(selectedAircraft.callsign)}</span>
                <span className="sidebar-subtitle">
                  {selectedAircraft.registration && <b>{selectedAircraft.registration}</b>}
                  {selectedAircraft.type_description && (
                    <span>{selectedAircraft.type_description}</span>
                  )}
                  {!selectedAircraft.type_description && selectedAircraft.typecode && (
                    <span>{selectedAircraft.typecode}</span>
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
                    {formatAltitude(selectedAircraft.altitude)}
                    <small>ft</small>
                  </div>
                  <span className="stat-label">Altitude</span>
                </div>
                <div className="stat">
                  <div className="stat-value">
                    {formatSpeed(selectedAircraft.groundspeed)}
                    <small>kts</small>
                  </div>
                  <span className="stat-label">Speed</span>
                </div>
                <div className="stat">
                  <div className="stat-value">
                    {selectedAircraft.vertical_rate ? (
                      <svg
                        className="dir"
                        viewBox="0 0 10 10"
                        aria-label={selectedAircraft.vertical_rate > 0 ? 'Climbing' : 'Descending'}
                        style={{
                          transform: selectedAircraft.vertical_rate > 0 ? 'none' : 'rotate(180deg)',
                        }}
                      >
                        <path d="M5 1l4.5 6h-9z" />
                      </svg>
                    ) : null}
                    {formatVerticalRate(selectedAircraft.vertical_rate)}
                    <small>ft/min</small>
                  </div>
                  <span className="stat-label">Vertical rate</span>
                </div>
              </div>

              <div className="info-group">
                <div className="info-section-title">Aircraft</div>
                <div className="info-row">
                  <span className="label">ICAO 24</span>
                  <span className="value">{selectedAircraft.icao24}</span>
                </div>
                <div className="info-row">
                  <span className="label">Registration</span>
                  <span className="value">{selectedAircraft.registration || 'N/A'}</span>
                </div>
                {selectedAircraft.type_description && (
                  <div className="info-row">
                    <span className="label">Aircraft</span>
                    <span className="value">{selectedAircraft.type_description}</span>
                  </div>
                )}
                <div className="info-row">
                  <span className="label">Type</span>
                  <span className="value">{selectedAircraft.typecode || 'N/A'}</span>
                </div>
              </div>

              <div className="divider"></div>

              <div className="info-group">
                <div className="info-section-title">Flight</div>
                <div className="info-row">
                  <span className="label">Track</span>
                  <span className="value">
                    {selectedAircraft.track !== null && selectedAircraft.track !== undefined && (
                      <svg
                        className="heading"
                        viewBox="0 0 12 12"
                        aria-hidden="true"
                        style={{ transform: `rotate(${selectedAircraft.track}deg)` }}
                      >
                        <path d="M6 1.5v9M2.5 5L6 1.5 9.5 5" />
                      </svg>
                    )}
                    {selectedAircraft.track?.toFixed(1) || 'N/A'}°
                  </span>
                </div>
                <div className="info-row">
                  <span className="label">Squawk</span>
                  <span className="value">{selectedAircraft.squawk || 'N/A'}</span>
                </div>
              </div>

              {selectedAircraftTrack && (
                <p className="track-footnote">{selectedAircraftTrack.length} track points</p>
              )}
            </div>
          </>
        ) : (
          <div className="sidebar-placeholder">
            <p>Select an aircraft to view details</p>
          </div>
        )}
      </div>
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
    })
  ).isRequired,
  mapboxToken: PropTypes.string.isRequired,
  tracks: PropTypes.objectOf(PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.number))),
  showTracks: PropTypes.bool,
  showLabels: PropTypes.bool,
  maxAgeMinutes: PropTypes.number,
  onTrackingAircraft: PropTypes.func,
  theme: PropTypes.oneOf(['light', 'dark']),
}

AircraftMap.defaultProps = {
  tracks: {},
  showTracks: false,
  showLabels: false,
  maxAgeMinutes: 5,
  onTrackingAircraft: null,
  theme: 'light',
}

export default AircraftMap
