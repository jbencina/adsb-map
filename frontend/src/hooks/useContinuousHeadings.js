/**
 * Custom hook that keeps each aircraft's marker rotation continuous
 */

import { useState } from 'react'
import { continueHeading } from '../heading'

/**
 * Unwrapped heading per aircraft, for CSS-animated rotation.
 *
 * Each update moves an aircraft's angle by the shortest turn from where it
 * was last drawn, so a track crossing north (359 to 1) rotates 2 degrees
 * instead of spinning 358 the other way. Aircraft that leave the list start
 * over from their reported track when they return.
 *
 * @param {Array} aircraft - Aircraft records with `icao24` and `track`
 * @returns {Object} Map of icao24 to unwrapped angle in degrees (null when no track)
 */
export function useContinuousHeadings(aircraft) {
  // Carried over from the previous render (the React "storing information from
  // previous renders" pattern), since the next angle depends on the last one drawn
  const [seen, setSeen] = useState(null)
  const [headings, setHeadings] = useState({})
  if (aircraft !== seen) {
    const next = {}
    aircraft.forEach(ac => {
      if (ac.icao24) next[ac.icao24] = continueHeading(headings[ac.icao24], ac.track)
    })
    setSeen(aircraft)
    setHeadings(next)
    return next
  }
  return headings
}
