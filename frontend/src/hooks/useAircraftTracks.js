/**
 * Custom hook that holds every aircraft's track line, fed from /api/tracks
 */

import { useEffect, useState } from 'react'
import { fetchAircraftTracks } from '../services/api'
import { mergeTracks, newestTimestamp } from '../tracks'

/**
 * Track lines for the map, one per aircraft, from the positions the backend stores.
 *
 * While enabled it seeds every line from the age window, then polls for new
 * positions since the newest one it holds. Nothing is sampled or thinned in the
 * browser, so the overview lines and the selected aircraft's line are the same
 * data. Widening the window reseeds; narrowing it prunes.
 *
 * @param {boolean} enabled - Poll only while lines are shown or an aircraft is selected
 * @param {number} refreshInterval - Poll interval in seconds
 * @param {number} maxAgeMinutes - Window to seed from and prune to
 * @returns {{tracks: Object, loaded: boolean}} icao24 to [lon, lat, timestamp] points,
 *   and whether the first fetch since enabling has completed
 */
export function useAircraftTracks(enabled, refreshInterval, maxAgeMinutes) {
  const [tracks, setTracks] = useState({})
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) {
      setTracks({})
      setLoaded(false)
      return undefined
    }
    let cancelled = false
    let held = {}
    // The first poll after enabling (or a window change) starts from scratch
    let seeded = false

    const poll = async () => {
      const cutoff = Math.floor(Date.now() / 1000) - maxAgeMinutes * 60
      const since = seeded ? (newestTimestamp(held) ?? cutoff) : cutoff
      try {
        const fresh = await fetchAircraftTracks(Math.max(since, cutoff))
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
  }, [enabled, refreshInterval, maxAgeMinutes])

  return { tracks, loaded }
}
