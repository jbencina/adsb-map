/**
 * Heading helpers for animated marker rotation.
 *
 * The marker's CSS transition interpolates the raw `rotate()` value, so a
 * track that wraps from 359 to 1 degrees would spin almost a full circle the
 * long way round. Keeping an "unwrapped" angle per aircraft, which only ever
 * moves by the shortest signed turn, lets the transition take the short way.
 */

const hasTrack = track => typeof track === 'number' && Number.isFinite(track)

/**
 * Signed shortest rotation from one bearing to another, in (-180, 180].
 *
 * @param {number} from - Starting angle in degrees, any range
 * @param {number} to - Target angle in degrees, any range
 * @returns {number} Degrees to turn; positive is clockwise
 */
export function shortestTurn(from, to) {
  const delta = (((to - from) % 360) + 540) % 360
  return delta - 180 === -180 ? 180 : delta - 180
}

/**
 * Continue an unwrapped heading toward a newly reported track.
 *
 * @param {number|null|undefined} previous - Last unwrapped angle, or null on first sight
 * @param {number|null|undefined} track - Reported track in 0..360
 * @returns {number|null} New unwrapped angle, or null when there is no track
 */
export function continueHeading(previous, track) {
  if (!hasTrack(track)) return null
  if (!hasTrack(previous)) return track
  return previous + shortestTurn(previous, track)
}
