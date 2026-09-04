/**
 * Data access for the SPA. In demo mode every call is answered by the
 * in-browser simulator instead of the backend.
 */

import { API_URL, DEMO_MODE } from '../constants'
import { DemoFleet } from './demo'

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
