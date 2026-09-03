/**
 * Application constants and configuration
 */

// API Configuration
// Runtime config (window.APP_CONFIG from /config.js) takes precedence over build-time
// env vars so a single bundled wheel can serve any user without a per-token rebuild.
// An empty API_URL means same-origin: the server hosting this page (adsb start backend, adsb start frontend,
// or the Vite dev proxy) forwards /api/* to the backend.
const runtime = (typeof window !== 'undefined' && window.APP_CONFIG) || {}
export const API_URL = (runtime.apiUrl || import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')
export const MAPBOX_TOKEN = runtime.mapboxToken || import.meta.env.VITE_MAPBOX_TOKEN || ''
// Demo mode answers API calls from an in-browser simulator; no backend is contacted.
export const DEMO_MODE = Boolean(runtime.demo)

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
// Light and dark map styles need different blues to hold the same contrast
export const TRACK_COLOR = '#0071e3'
export const TRACK_COLOR_DARK = '#3b9cff'
export const TRACK_WIDTH = 1.5
export const TRACK_OPACITY = 0.55
export const SELECTED_TRACK_COLOR = '#0071e3'
export const SELECTED_TRACK_COLOR_DARK = '#3b9cff'
export const SELECTED_TRACK_WIDTH = 2.5

// Aircraft Marker Configuration
// Top-down airliner silhouette in a 24x24 box, nose pointing up (north).
export const AIRCRAFT_GLYPH =
  'M12 1.5c.9 0 1.4 1.1 1.5 2.1l.2 5.4 8.8 5v2.2l-8.8-2.6-.2 5.6 2.3 1.8v1.6L12 21.5l-3.8 1.1V21l2.3-1.8-.2-5.6-8.8 2.6V14l8.8-5 .2-5.4c.1-1 .6-2.1 1.5-2.1z'
export const AIRCRAFT_MARKER_SIZE = 28

// Default Values
export const DEFAULT_REFRESH_INTERVAL = 1 // seconds
export const DEFAULT_MAX_AGE_MINUTES = 5 // minutes

// Value Ranges
export const REFRESH_INTERVAL_MIN = 1
export const REFRESH_INTERVAL_MAX = 60
export const MAX_AGE_MIN = 1
export const MAX_AGE_MAX = 60
