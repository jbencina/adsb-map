/**
 * Application constants and configuration
 */

// API Configuration
// Runtime config (window.APP_CONFIG from /config.js) takes precedence over build-time
// env vars so a single bundled wheel can serve any user without a per-token rebuild.
// An empty API_URL means same-origin: the server hosting this page (adsb serve, adsb ui,
// or the Vite dev proxy) forwards /api/* to the backend.
const runtime = (typeof window !== 'undefined' && window.APP_CONFIG) || {}
export const API_URL = (runtime.apiUrl || import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')
export const MAPBOX_TOKEN = runtime.mapboxToken || import.meta.env.VITE_MAPBOX_TOKEN || ''

// Map Configuration
export const DEFAULT_MAP_CENTER = {
  longitude: -123.0,
  latitude: 38.0,
  zoom: 7,
}

export const INITIAL_ZOOM = 8

export const MAP_STYLE_LIGHT = 'mapbox://styles/mapbox/light-v11'
export const MAP_STYLE_DARK = 'mapbox://styles/mapbox/dark-v11'

// Legacy export for backwards compatibility
export const MAP_STYLE = MAP_STYLE_LIGHT

// Track Configuration
export const MAX_TRACK_POINTS = 500
export const TRACK_MIN_DISTANCE_CHANGE = 0.001 // ~100 meters in degrees

// Track Display Configuration
export const TRACK_COLOR = '#3498db'
export const TRACK_WIDTH = 2
export const TRACK_OPACITY = 0.6

// Aircraft Marker Configuration
export const AIRCRAFT_MARKER_COLOR = '#e74c3c'
export const AIRCRAFT_MARKER_SIZE = 24
export const AIRCRAFT_MARKER_SIZE_HOVER = 28

// Default Values
export const DEFAULT_REFRESH_INTERVAL = 1 // seconds
export const DEFAULT_MAX_AGE_MINUTES = 5 // minutes

// Value Ranges
export const REFRESH_INTERVAL_MIN = 1
export const REFRESH_INTERVAL_MAX = 60
export const MAX_AGE_MIN = 1
export const MAX_AGE_MAX = 60
