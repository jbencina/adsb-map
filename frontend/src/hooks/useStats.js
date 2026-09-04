/**
 * Loads /api/stats for the history view while it is open.
 */

import { useEffect, useState } from 'react'
import { fetchStats } from '../services/api'
import { HISTORY_WINDOW } from '../stats'

const REFRESH_MS = 60000
const TOP_LIMIT = 10

/**
 * Hook to fetch the traffic history and refresh it once a minute
 *
 * @param {boolean} open - Fetch only while the view is showing
 * @param {number} interval - Bucket size in seconds; a change refetches at once
 * @returns {{stats: Object|null, loading: boolean, error: string|null}}
 */
export function useStats(open, interval) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return undefined
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const data = await fetchStats({ window: HISTORY_WINDOW, interval, limit: TOP_LIMIT })
        if (cancelled) return
        setStats(data)
        setError(null)
      } catch (err) {
        console.error('Error fetching traffic history:', err)
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [open, interval])

  return { stats, loading, error }
}
