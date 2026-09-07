/**
 * Custom hook that glides markers between position updates
 */

import { useEffect, useRef, useState } from 'react'
import { smoothAircraft, updateMotions } from '../motion'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

/**
 * The aircraft list redrawn every animation frame by dead reckoning.
 *
 * Each aircraft is projected along its reported track at its reported speed
 * from the last position that actually changed, so motion stays continuous
 * whatever the update interval. When the viewer prefers reduced motion the
 * list is returned as-is and nothing animates.
 *
 * @param {Array} aircraft - Aircraft records with positions
 * @returns {Array} Copies with `latitude`/`longitude` where each should be drawn now
 */
export function useSmoothedAircraft(aircraft) {
  const records = useRef(new Map())
  const [shown, setShown] = useState(aircraft)
  const [still] = useState(
    () => typeof matchMedia === 'function' && matchMedia(REDUCED_MOTION).matches
  )

  // Fold each update in before the next frame draws (effects run in order)
  useEffect(() => {
    records.current = updateMotions(records.current, aircraft, Date.now())
  }, [aircraft])

  useEffect(() => {
    if (still || aircraft.length === 0) {
      setShown(aircraft)
      return undefined
    }
    let frame
    const draw = () => {
      setShown(smoothAircraft(records.current, aircraft, Date.now()))
      frame = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(frame)
  }, [aircraft, still])

  return still ? aircraft : shown
}
