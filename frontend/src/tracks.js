/**
 * Track lines for the map. There is one source: the positions the backend
 * stores, fetched in bulk from /api/tracks. The overview draws every line and
 * the selected aircraft's line is the same data highlighted, so the two can
 * never disagree.
 *
 * A track is an array of [lon, lat, timestamp] points, oldest first.
 */

/**
 * Fold freshly fetched positions into the tracks held so far.
 *
 * Points already held are skipped, so the poll can ask for positions since its
 * newest timestamp inclusive without doubling that second. Points older than
 * the cutoff are dropped, as are aircraft left with nothing to draw.
 *
 * @param {Object} prev - Tracks held so far, icao24 to points
 * @param {Object} fresh - /api/tracks response, icao24 to position objects
 * @param {number} cutoff - Unix timestamp; points before it are pruned
 * @returns {Object} New tracks object; `prev` is not mutated
 */
export function mergeTracks(prev, fresh, cutoff) {
  const next = {}
  const ids = new Set([...Object.keys(prev), ...Object.keys(fresh)])
  ids.forEach(icao24 => {
    const held = prev[icao24] ?? []
    const last = held.length ? held[held.length - 1][2] : -Infinity
    const added = (fresh[icao24] ?? [])
      .filter(p => p.timestamp > last)
      .map(p => [p.longitude, p.latitude, p.timestamp])
    const points = [...held, ...added].filter(p => p[2] >= cutoff)
    if (points.length) next[icao24] = points
  })
  return next
}

/**
 * Newest timestamp held across all tracks; the next poll asks for positions since it.
 *
 * @param {Object} tracks - icao24 to points
 * @returns {number|null} Unix timestamp, or null with no points
 */
export function newestTimestamp(tracks) {
  let newest = null
  Object.values(tracks).forEach(points => {
    const last = points[points.length - 1]?.[2]
    if (last !== undefined && (newest === null || last > newest)) newest = last
  })
  return newest
}
