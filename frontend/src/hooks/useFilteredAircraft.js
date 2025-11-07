/**
 * Custom hook for filtering aircraft by age
 */

import { useMemo } from 'react'

/**
 * Hook to filter aircraft based on last seen time
 *
 * @param {Array} aircraft - Array of aircraft objects
 * @param {number} maxAgeMinutes - Maximum age in minutes
 * @returns {Array} Filtered array of aircraft
 */
export function useFilteredAircraft(aircraft, maxAgeMinutes) {
  return useMemo(() => {
    // We intentionally use Date.now() here to filter based on current time
    const currentTime = Math.floor(Date.now() / 1000) // Current time in Unix timestamp
    return aircraft.filter(ac => {
      if (!ac.lastseen) return true // Include if no lastseen data
      const ageInSeconds = currentTime - ac.lastseen
      const ageInMinutes = ageInSeconds / 60
      return ageInMinutes <= maxAgeMinutes
    })
  }, [aircraft, maxAgeMinutes])
}
