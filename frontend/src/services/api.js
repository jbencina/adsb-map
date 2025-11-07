/**
 * API service for fetching aircraft data
 */

import { API_URL } from '../constants'

/**
 * Fetches all aircraft from the API
 *
 * @returns {Promise<Array>} Array of aircraft objects
 * @throws {Error} If the API request fails
 */
export async function fetchAllAircraft() {
  const response = await fetch(`${API_URL}/all`)

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  const data = await response.json()
  return data
}

/**
 * Fetches a single aircraft by ICAO24 identifier
 *
 * @param {string} icao24 - Aircraft ICAO24 identifier
 * @returns {Promise<Object>} Aircraft object
 * @throws {Error} If the API request fails
 */
export async function fetchAircraftByIcao(icao24) {
  const response = await fetch(`${API_URL}/aircraft/${icao24}`)

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  const data = await response.json()
  return data
}

/**
 * Fetches track history for a specific aircraft
 *
 * @param {string} icao24 - Aircraft ICAO24 identifier
 * @returns {Promise<Array>} Array of track position objects
 * @throws {Error} If the API request fails
 */
export async function fetchAircraftTrack(icao24) {
  const response = await fetch(`${API_URL}/track?icao24=${icao24}`)

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  const data = await response.json()
  return data
}
