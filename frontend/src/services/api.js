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
 * Fetches track history for a specific aircraft
 *
 * @param {string} icao24 - Aircraft ICAO24 identifier
 * @returns {Promise<Array>} Array of track position objects
 * @throws {Error} If the API request fails
 */
export async function fetchAircraftTrack(icao24) {
  if (fleet) return fleet.track(icao24)
  return getJson(`/api/track?icao24=${encodeURIComponent(icao24)}`)
}
