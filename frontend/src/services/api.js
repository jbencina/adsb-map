/**
 * Data access for the SPA: one-off fetches and live subscriptions. In demo
 * mode every call is answered by the in-browser simulator instead of the backend.
 */

import { API_URL, DEMO_MODE } from '../constants'
import { DemoFleet } from './demo'
import { openStream } from './stream'

const fleet = DEMO_MODE ? new DemoFleet() : null

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`)
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  return response.json()
}

/**
 * Fetches all aircraft state vectors seen within the given window.
 *
 * The backend keeps every aircraft it has ever decoded and filters by age on
 * request, so widening the window brings older aircraft back.
 *
 * @param {number} maxAgeSeconds - Only aircraft seen within this many seconds
 * @returns {Promise<Array>} Array of aircraft objects
 * @throws {Error} If the API request fails
 */
export async function fetchAllAircraft(maxAgeSeconds) {
  if (fleet) return fleet.advance(Date.now()).all()
  return getJson(`/api/all?max_age=${encodeURIComponent(maxAgeSeconds)}`)
}

/**
 * Fetches the stored positions of every aircraft since a timestamp
 *
 * The one source for track lines on the map. Positions are retained
 * indefinitely, so the first call bounds `since` to the age window; later
 * calls pass the newest timestamp held and get only what is new.
 *
 * @param {number} sinceSeconds - Unix timestamp; only positions at or after it
 * @returns {Promise<Object>} icao24 to array of position objects, oldest first
 * @throws {Error} If the API request fails
 */
export async function fetchAircraftTracks(sinceSeconds) {
  if (fleet) return fleet.tracks(sinceSeconds)
  return getJson(`/api/tracks?since=${encodeURIComponent(sinceSeconds)}`)
}

/**
 * Fetches the stored positions of one aircraft since a timestamp
 *
 * Same positions as `fetchAircraftTracks`, keyed the same way, so the map can
 * hold a single line without pulling the whole fleet's when the overview is off.
 *
 * @param {string} icao24 - ICAO 24-bit address
 * @param {number} sinceSeconds - Unix timestamp; only positions at or after it
 * @returns {Promise<Object>} icao24 to array of position objects, or empty with none
 * @throws {Error} If the API request fails
 */
export async function fetchAircraftTrack(icao24, sinceSeconds) {
  const points = fleet
    ? fleet.track(icao24, sinceSeconds)
    : await getJson(
        `/api/track?icao24=${encodeURIComponent(icao24)}&since=${encodeURIComponent(sinceSeconds)}`
      )
  return points.length ? { [icao24]: points } : {}
}

/**
 * Fetches track positions for a scope: every aircraft, or just one
 *
 * @param {string} scope - `'all'` for the fleet, otherwise an icao24
 * @param {number} sinceSeconds - Unix timestamp; only positions at or after it
 * @returns {Promise<Object>} icao24 to array of position objects
 */
export function fetchTracks(scope, sinceSeconds) {
  return scope === 'all'
    ? fetchAircraftTracks(sinceSeconds)
    : fetchAircraftTrack(scope, sinceSeconds)
}

/**
 * Fetches the traffic history behind the history view
 *
 * @param {{window: number, interval: number, limit: number}} params - Seconds of
 *   history, bucket size in seconds (must divide the window), rows per top list
 * @returns {Promise<Object>} Buckets and top-aircraft lists, shaped like /api/stats
 * @throws {Error} If the API request fails
 */
export async function fetchStats({ window, interval, limit }) {
  if (fleet) return fleet.stats({ window, interval, limit })
  const query = new URLSearchParams({ window, interval, limit })
  return getJson(`/api/stats?${query}`)
}

/**
 * Demo stand-in for a stream: produce a payload now and then every interval.
 *
 * @param {number} intervalSeconds - Seconds between updates
 * @param {function(): any} produce - Builds the next payload from the simulator
 * @param {{onUpdate: function(any): void}} handlers
 * @returns {function(): void} Stops the updates
 */
function simulateStream(intervalSeconds, produce, { onUpdate }) {
  const emit = () => onUpdate(produce())
  emit()
  const timer = setInterval(emit, intervalSeconds * 1000)
  return () => clearInterval(timer)
}

/**
 * Subscribes to the aircraft feed: the /api/all window, resent every interval.
 *
 * Every update is the whole list, so replace what is held rather than merge.
 *
 * @param {{maxAgeSeconds: number, intervalSeconds: number}} params - Age window and cadence
 * @param {{onUpdate: function(Array): void, onError?: function(Error): void}} handlers
 * @returns {function(): void} Unsubscribes
 */
export function subscribeAircraft({ maxAgeSeconds, intervalSeconds }, handlers) {
  if (fleet) {
    return simulateStream(intervalSeconds, () => fleet.advance(Date.now()).all(), handlers)
  }
  const query = new URLSearchParams({ max_age: maxAgeSeconds, interval: intervalSeconds })
  return openStream(`${API_URL}/api/stream/aircraft?${query}`, handlers)
}

/**
 * Subscribes to stored positions: the window first, then only new points each interval.
 *
 * Updates are shaped like /api/tracks and append to what is held; the backend
 * never repeats a point, and a reconnect resumes from the last one delivered.
 *
 * @param {{scope: string, maxAgeSeconds: number, intervalSeconds: number}} params -
 *   `'all'` or an icao24, the age window for the first update, and the cadence
 * @param {{onUpdate: function(Object): void, onError?: function(Error): void}} handlers
 * @returns {function(): void} Unsubscribes
 */
export function subscribeTracks({ scope, maxAgeSeconds, intervalSeconds }, handlers) {
  if (fleet) {
    // Ask from the window, then from the last update; the hook drops repeats.
    let since = Math.floor(Date.now() / 1000) - maxAgeSeconds
    return simulateStream(
      intervalSeconds,
      () => {
        const points = scope === 'all' ? fleet.tracks(since) : fleet.track(scope, since)
        since = Math.floor(Date.now() / 1000)
        return scope === 'all' || !points.length ? points : { [scope]: points }
      },
      handlers
    )
  }
  const query = new URLSearchParams({ scope, max_age: maxAgeSeconds, interval: intervalSeconds })
  return openStream(`${API_URL}/api/stream/tracks?${query}`, handlers)
}
