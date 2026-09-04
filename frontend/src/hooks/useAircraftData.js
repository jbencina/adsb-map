/**
 * Custom hook for fetching and managing aircraft data
 */

import { useState, useEffect, useCallback } from 'react'
import { fetchAllAircraft } from '../services/api'

/**
 * Hook to fetch and poll aircraft data
 *
 * @param {number} refreshInterval - Refresh interval in seconds
 * @param {number} maxAgeMinutes - Only aircraft seen within this many minutes; a change refetches at once
 * @returns {Object} Object containing aircraft data, loading state, error, and last update time
 */
export function useAircraftData(refreshInterval, maxAgeMinutes) {
  const [aircraft, setAircraft] = useState([])
  const [lastUpdate, setLastUpdate] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchAircraft = useCallback(async () => {
    try {
      const data = await fetchAllAircraft(maxAgeMinutes * 60)
      setAircraft(data)
      setLastUpdate(new Date())
      setError(null)
      setLoading(false)
      return data
    } catch (err) {
      console.error('Error fetching aircraft data:', err)
      setError(err.message)
      setLoading(false)
      return null
    }
  }, [maxAgeMinutes])

  useEffect(() => {
    // Initial fetch and polling - this setState is intentional.
    // Re-runs when the window changes so older aircraft appear without waiting a tick.
    fetchAircraft()
    const interval = setInterval(fetchAircraft, refreshInterval * 1000)

    return () => clearInterval(interval)
  }, [refreshInterval, fetchAircraft])

  return { aircraft, loading, error, lastUpdate, refetch: fetchAircraft }
}
