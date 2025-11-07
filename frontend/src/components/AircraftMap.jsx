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
  TRACK_WIDTH,
  TRACK_OPACITY,
} from '../constants'
import './AircraftMap.css'

/**
 * Map component that displays aircraft positions and tracks
 *
 * @param {Object} props - Component props
 * @param {Array} props.aircraft - Array of aircraft objects from the API
 * @param {string} props.mapboxToken - MapBox API token
 * @param {Object} props.tracks - Map of icao24 to array of position points
 * @param {boolean} props.showTracks - Whether to display tracks
 * @param {string} props.theme - Current theme ('light' or 'dark')
 * @returns {JSX.Element} The map component
 */
function AircraftMap({
  aircraft,
  mapboxToken,
  tracks = {},
  showTracks = false,
  maxAgeMinutes = 5,
  onTrackingAircraft,
  theme = 'light',
}) {
  const mapRef = useRef(null)
  const [selectedAircraft, setSelectedAircraft] = useState(null)
  const [selectedAircraftTrack, setSelectedAircraftTrack] = useState(null)
  const [loadingTrack, setLoadingTrack] = useState(false)
  const [viewport, setViewport] = useState(DEFAULT_MAP_CENTER)

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
   * The airplane emoji points right (east) by default, so subtract 90° to align correctly
   *
   * @param {number} track - Aircraft track in degrees
   * @returns {string} CSS transform string
   */
  const getAircraftRotation = track => {
    return track !== null && track !== undefined ? `rotate(${track - 90}deg)` : 'rotate(-90deg)'
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
   * Calculate color based on aircraft age
   * Fades from full red (#e74c3c) to light red (#ffb3a8) based on maxAgeMinutes
   *
   * @param {number} lastseen - Unix timestamp of last seen
   * @returns {string} CSS color string
   */
  const getAircraftColor = lastseen => {
    if (!lastseen) return '#e74c3c' // Full red if no timestamp

    const currentTime = Math.floor(Date.now() / 1000)
    const ageInSeconds = currentTime - lastseen
    const ageInMinutes = ageInSeconds / 60

    // Linear interpolation from full red to light red
    // 0 minutes = #e74c3c (231, 76, 60)
    // maxAgeMinutes = #ffb3a8 (255, 179, 168)
    const ratio = Math.min(ageInMinutes / maxAgeMinutes, 1)

    const r = Math.round(231 + (255 - 231) * ratio)
    const g = Math.round(76 + (179 - 76) * ratio)
    const b = Math.round(60 + (168 - 60) * ratio)

    return `rgb(${r}, ${g}, ${b})`
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
  const validAircraft = aircraft.filter(a => a.latitude && a.longitude)

  // Select map style based on theme
  const mapStyle = theme === 'dark' ? MAP_STYLE_DARK : MAP_STYLE_LIGHT

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
      >
        {/* Render all aircraft tracks (only when not showing selected aircraft track) */}
        {showTracks && !selectedAircraftTrack && (
          <Source id="aircraft-tracks" type="geojson" data={tracksGeoJSON}>
            <Layer
              id="tracks-layer"
              type="line"
              paint={{
                'line-color': TRACK_COLOR,
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
            >
              <Layer
                id="selected-track-layer"
                type="line"
                paint={{
                  'line-color': '#f39c12', // Orange color for selected track
                  'line-width': 2,
                  'line-opacity': 0.7,
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
                  'circle-radius': [
                    'interpolate',
                    ['linear'],
                    ['zoom'],
                    5,
                    2, // At zoom 5: 2px
                    10,
                    2, // At zoom 10: 3px
                    15,
                    2, // At zoom 15: 4px
                  ],
                  'circle-color': '#f39c12',
                  'circle-opacity': 0.95,
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
            onClick={e => {
              e.originalEvent.stopPropagation()
              setSelectedAircraft(ac)
            }}
          >
            <div
              className="aircraft-marker"
              style={{
                transform: getAircraftRotation(ac.track),
                color: getAircraftColor(ac.lastseen),
              }}
              title={
                [
                  cleanCallsign(ac.callsign) || ac.icao24,
                  ac.registration ? `(${ac.registration})` : null,
                  ac.typecode ? `- ${ac.typecode}` : null,
                ]
                  .filter(Boolean)
                  .join(' ')
              }
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
              ✈
            </div>
          </Marker>
        ))}
      </Map>

      {/* Sidebar for aircraft details */}
      <div className={`aircraft-sidebar ${selectedAircraft ? 'active' : ''}`}>
        {selectedAircraft ? (
          <>
            <div className="sidebar-header">
              <h3>
                {cleanCallsign(selectedAircraft.callsign)}
                {loadingTrack && <span className="loading-indicator"> Loading...</span>}
              </h3>
              <button
                className="close-button"
                onClick={() => setSelectedAircraft(null)}
                aria-label="Close aircraft details"
              >
                ×
              </button>
            </div>
            <div className="sidebar-content">
              <div className="info-group">
                <div className="info-section-title">Aircraft Details</div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/>
                    </svg>
                    ICAO24
                  </span>
                  <span className="value">{selectedAircraft.icao24}</span>
                </div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                    </svg>
                    Registration
                  </span>
                  <span className="value">{selectedAircraft.registration || 'N/A'}</span>
                </div>

                {selectedAircraft.type_description && (
                  <div className="info-row">
                    <span className="label">
                      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                      </svg>
                      Aircraft
                    </span>
                    <span className="value">{selectedAircraft.type_description}</span>
                  </div>
                )}

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/>
                    </svg>
                    Type
                  </span>
                  <span className="value">{selectedAircraft.typecode || 'N/A'}</span>
                </div>
              </div>

              <div className="divider"></div>

              <div className="info-group">
                <div className="info-section-title">Flight Data</div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 11l5-5m0 0l5 5m-5-5v12"/>
                    </svg>
                    Altitude
                  </span>
                  <span className="value highlight">{formatAltitude(selectedAircraft.altitude)} ft</span>
                </div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                    Ground Speed
                  </span>
                  <span className="value highlight">{formatSpeed(selectedAircraft.groundspeed)} kts</span>
                </div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"/>
                    </svg>
                    Vertical Rate
                  </span>
                  <span className="value">{selectedAircraft.vertical_rate || 'N/A'} ft/min</span>
                </div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
                    </svg>
                    Track
                  </span>
                  <span className="value">{selectedAircraft.track?.toFixed(1) || 'N/A'}°</span>
                </div>

                <div className="info-row">
                  <span className="label">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                    </svg>
                    Squawk
                  </span>
                  <span className="value">{selectedAircraft.squawk || 'N/A'}</span>
                </div>

                {selectedAircraftTrack && (
                  <div className="info-row">
                    <span className="label">
                      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
                      </svg>
                      Track Points
                    </span>
                    <span className="value">{selectedAircraftTrack.length}</span>
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="sidebar-placeholder">
            <p>Click an aircraft to view details</p>
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
  maxAgeMinutes: PropTypes.number,
  onTrackingAircraft: PropTypes.func,
  theme: PropTypes.oneOf(['light', 'dark']),
}

AircraftMap.defaultProps = {
  tracks: {},
  showTracks: false,
  maxAgeMinutes: 5,
  onTrackingAircraft: null,
  theme: 'light',
}

export default AircraftMap
