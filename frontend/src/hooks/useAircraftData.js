/**
 * Custom hook for fetching and managing aircraft data
 */

import { useState, useEffect, useCallback } from 'react'
import { fetchAllAircraft } from '../services/api'

/**
 * Hook to fetch and poll aircraft data
 *
 * @param {number} refreshInterval - Refresh interval in seconds
 * @returns {Object} Object containing aircraft data, loading state, error, and last update time
 */
export function useAircraftData(refreshInterval) {
  const [aircraft, setAircraft] = useState([])
  const [lastUpdate, setLastUpdate] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchAircraft = useCallback(async () => {
    try {
      const data = await fetchAllAircraft()
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
  }, [])

  useEffect(() => {
    // Initial fetch and polling - this setState is intentional
    fetchAircraft()
    const interval = setInterval(fetchAircraft, refreshInterval * 1000)

    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshInterval])

  return { aircraft, loading, error, lastUpdate, refetch: fetchAircraft }
}
