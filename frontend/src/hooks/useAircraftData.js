/**
 * Custom hook that holds the live aircraft list
 */

import { useState, useEffect } from 'react'
import { subscribeAircraft } from '../services/api'

/**
 * Hook that subscribes to the aircraft feed
 *
 * Every update is the whole age window, so it replaces the list held; the
 * backend filters by age and the interval sets how often it sends.
 *
 * @param {number} refreshInterval - Seconds between updates
 * @param {number} maxAgeMinutes - Only aircraft seen within this many minutes; a change resubscribes at once
 * @returns {Object} Object containing aircraft data, loading state, error, and last update time
 */
export function useAircraftData(refreshInterval, maxAgeMinutes) {
  const [aircraft, setAircraft] = useState([])
  const [lastUpdate, setLastUpdate] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(
    () =>
      subscribeAircraft(
        { maxAgeSeconds: maxAgeMinutes * 60, intervalSeconds: refreshInterval },
        {
          onUpdate: data => {
            setAircraft(data)
            setLastUpdate(new Date())
            setError(null)
            setLoading(false)
          },
          onError: err => {
            console.error('Aircraft stream:', err)
            setError(err.message)
            setLoading(false)
          },
        }
      ),
    [refreshInterval, maxAgeMinutes]
  )

  return { aircraft, loading, error, lastUpdate }
}
