/**
 * Custom hook that holds the map's track lines, fed from the stored positions
 */

import { useEffect, useState } from 'react'
import { fetchTracks } from '../services/api'
import { mergeTracks, newestTimestamp } from '../tracks'

/**
 * Track lines for the map from the positions the backend stores.
 *
 * The scope is `'all'` while the overview is shown, so one bulk fetch feeds
 * every line and the selected aircraft's highlight alike; with the overview
 * off it is just the selected icao24, so a click pulls one aircraft's positions
 * rather than the fleet's. Either way it seeds from the age window, then polls
 * for new positions since the newest one it holds. Nothing is sampled or
 * thinned in the browser. Widening the window reseeds; narrowing it prunes.
 *
 * @param {string|null} scope - `'all'`, an icao24, or null to hold nothing
 * @param {number} refreshInterval - Poll interval in seconds
 * @param {number} maxAgeMinutes - Window to seed from and prune to
 * @returns {{tracks: Object, loaded: boolean}} icao24 to [lon, lat, timestamp] points,
 *   and whether the first fetch for this scope has completed
 */
export function useAircraftTracks(scope, refreshInterval, maxAgeMinutes) {
  const [tracks, setTracks] = useState({})
  const [loaded, setLoaded] = useState(false)

  // A new scope starts from scratch so another aircraft's line never shows; a
  // window or interval change keeps the lines up until the reseed replaces them
  useEffect(() => {
    setTracks({})
    setLoaded(false)
  }, [scope])

  useEffect(() => {
    if (!scope) return undefined
    let cancelled = false
    let held = {}
    let seeded = false

    const poll = async () => {
      const cutoff = Math.floor(Date.now() / 1000) - maxAgeMinutes * 60
      const since = seeded ? (newestTimestamp(held) ?? cutoff) : cutoff
      try {
        const fresh = await fetchTracks(scope, Math.max(since, cutoff))
        if (cancelled) return
        held = mergeTracks(seeded ? held : {}, fresh, cutoff)
        seeded = true
        setTracks(held)
        setLoaded(true)
      } catch (err) {
        if (!cancelled) console.error('Error fetching aircraft tracks:', err)
      }
    }

    poll()
    const interval = setInterval(poll, refreshInterval * 1000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [scope, refreshInterval, maxAgeMinutes])

  return { tracks, loaded }
}
