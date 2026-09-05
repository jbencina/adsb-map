/**
 * Custom hook that holds the map's track lines, fed from the stored positions
 */

import { useEffect, useState } from 'react'
import { subscribeTracks } from '../services/api'
import { mergeTracks } from '../tracks'

/**
 * Track lines for the map from the positions the backend stores.
 *
 * The scope is `'all'` while the overview is shown, so one stream feeds every
 * line and the selected aircraft's highlight alike; with the overview off it
 * is just the selected icao24, so a click streams one aircraft's positions
 * rather than the fleet's. Either way the first update is the age window and
 * later ones are only new positions. Nothing is sampled or thinned in the
 * browser. Widening the window resubscribes; narrowing it prunes.
 *
 * @param {string|null} scope - `'all'`, an icao24, or null to hold nothing
 * @param {number} refreshInterval - Seconds between updates
 * @param {number} maxAgeMinutes - Window to seed from and prune to
 * @returns {{tracks: Object, loaded: boolean}} icao24 to [lon, lat, timestamp] points,
 *   and whether the first update for this scope has arrived
 */
export function useAircraftTracks(scope, refreshInterval, maxAgeMinutes) {
  const [tracks, setTracks] = useState({})
  const [loaded, setLoaded] = useState(false)

  // A new scope starts from scratch so another aircraft's line never shows; a
  // window or interval change keeps the lines up until the new window replaces them
  useEffect(() => {
    setTracks({})
    setLoaded(false)
  }, [scope])

  useEffect(() => {
    if (!scope) return undefined
    let held = {}
    return subscribeTracks(
      { scope, maxAgeSeconds: maxAgeMinutes * 60, intervalSeconds: refreshInterval },
      {
        onUpdate: fresh => {
          const cutoff = Math.floor(Date.now() / 1000) - maxAgeMinutes * 60
          held = mergeTracks(held, fresh, cutoff)
          setTracks(held)
          setLoaded(true)
        },
        onError: err => console.error('Aircraft track stream:', err),
      }
    )
  }, [scope, refreshInterval, maxAgeMinutes])

  return { tracks, loaded }
}
