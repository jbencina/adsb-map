/**
 * Loads /api/stats for the history view while it is open.
 */

import { useEffect, useState } from 'react'
import { fetchStats } from '../services/api'
import { HISTORY_WINDOW, msUntilNextMinute } from '../stats'

const TOP_LIMIT = 10

/**
 * Hook to fetch the traffic history and refresh it at the top of every minute,
 * when the backend's per-minute aggregates roll over
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
    let timer
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
        if (!cancelled) {
          setLoading(false)
          timer = setTimeout(load, msUntilNextMinute())
        }
      }
    }
    load()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, interval])

  return { stats, loading, error }
}
