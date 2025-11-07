/**
 * Custom hook for managing aircraft track history
 */

import { useState, useCallback, useEffect } from 'react'
import { MAX_TRACK_POINTS, TRACK_MIN_DISTANCE_CHANGE } from '../constants'

/**
 * Hook to manage aircraft track history
 *
 * @param {Array} aircraft - Array of aircraft objects
 * @param {number} maxAgeMinutes - Maximum age for tracks in minutes
 * @returns {Object} Object containing tracks
 */
export function useAircraftTracks(aircraft, maxAgeMinutes) {
  const [tracks, setTracks] = useState({}) // Map of icao24 -> array of [lon, lat, timestamp]

  /**
   * Update track history with new aircraft positions
   *
   * @param {Array} aircraftData - Array of aircraft objects
   */
  const updateTracks = useCallback(
    aircraftData => {
      setTracks(prevTracks => {
        const newTracks = { ...prevTracks }
        const timestamp = Date.now()

        aircraftData.forEach(ac => {
          // Only record positions with valid coordinates
          // Use explicit type checks to handle latitude/longitude of 0 (equator/prime meridian)
          if (typeof ac.latitude === 'number' && typeof ac.longitude === 'number' && ac.icao24) {
            const position = [ac.longitude, ac.latitude, timestamp]

            if (!newTracks[ac.icao24]) {
              newTracks[ac.icao24] = [position]
            } else {
              // Check if position has changed significantly (avoid duplicate points)
              const lastPos = newTracks[ac.icao24][newTracks[ac.icao24].length - 1]
              const lonDiff = Math.abs(lastPos[0] - position[0])
              const latDiff = Math.abs(lastPos[1] - position[1])

              // Only add if position changed by more than the minimum distance threshold
              if (lonDiff > TRACK_MIN_DISTANCE_CHANGE || latDiff > TRACK_MIN_DISTANCE_CHANGE) {
                newTracks[ac.icao24] = [...newTracks[ac.icao24], position]

                // Limit track points to prevent memory issues
                if (newTracks[ac.icao24].length > MAX_TRACK_POINTS) {
                  newTracks[ac.icao24] = newTracks[ac.icao24].slice(-MAX_TRACK_POINTS)
                }
              }
            }
          }
        })

        // Clean up tracks for aircraft not seen recently (older than maxAgeMinutes * 2)
        const currentTime = Math.floor(Date.now() / 1000)
        const maxAgeSeconds = maxAgeMinutes * 60 * 2

        Object.keys(newTracks).forEach(icao24 => {
          const aircraft = aircraftData.find(ac => ac.icao24 === icao24)
          if (!aircraft) {
            // Check if track is too old
            const lastPoint = newTracks[icao24][newTracks[icao24].length - 1]
            const ageSeconds = currentTime - lastPoint[2] / 1000
            if (ageSeconds > maxAgeSeconds) {
              delete newTracks[icao24]
            }
          }
        })

        return newTracks
      })
    },
    [maxAgeMinutes]
  )

  // Update tracks when aircraft data changes
  useEffect(() => {
    if (aircraft.length > 0) {
      // Updating tracks based on aircraft data - this setState is intentional
      updateTracks(aircraft)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aircraft])

  return { tracks }
}
