/**
 * Dead-reckoning helpers for smooth marker motion between updates.
 *
 * Positions arrive whenever the server ticks, which may be every second or
 * every minute, and unchanged positions are resent in between. Rather than
 * tween from one report to the next, which stalls or gets cut short when the
 * cadence changes, each frame draws the aircraft where its reported speed and
 * track say it should be by now.
 */

import { MOTION_BLEND_MS, MOTION_MAX_PROJECT_MS } from './constants'

const KNOTS_TO_MPS = 0.514444
const EARTH_RADIUS_M = 6371000
const DEG = Math.PI / 180

const isNum = value => typeof value === 'number' && Number.isFinite(value)

// Shortest signed way round for a longitude difference (a fix crossing the antimeridian)
const wrapLongitude = delta => (Math.abs(delta) > 180 ? delta - Math.sign(delta) * 360 : delta)

/**
 * Where an aircraft is after flying straight from a fix for a while.
 *
 * @param {Object} fix - `latitude`, `longitude` in degrees, `groundspeed` in knots, `track` in degrees
 * @param {number} elapsedMs - Time since the fix
 * @returns {{latitude: number, longitude: number}} Projected position, or the fix when it cannot move
 */
export function projectPosition(fix, elapsedMs) {
  const { latitude, longitude, groundspeed, track } = fix
  if (!isNum(groundspeed) || !isNum(track) || !(elapsedMs > 0)) return { latitude, longitude }
  const distance = (groundspeed * KNOTS_TO_MPS * elapsedMs) / 1000
  const north = (distance * Math.cos(track * DEG)) / EARTH_RADIUS_M / DEG
  const east = (distance * Math.sin(track * DEG)) / EARTH_RADIUS_M / DEG
  return {
    latitude: latitude + north,
    longitude: longitude + east / Math.cos(latitude * DEG),
  }
}

/**
 * Where to draw an aircraft right now.
 *
 * The fix is projected forward, capped so a silent aircraft does not sail off
 * indefinitely, and the correction offset recorded when the fix arrived is
 * faded out so the marker slides onto the new fix instead of jumping.
 *
 * @param {Object} motion - Record from `updateMotion`
 * @param {number} now - Current time in ms, same clock as the record
 * @param {Object} [options]
 * @param {number} [options.blendMs] - Time over which the offset fades
 * @param {number} [options.maxProjectMs] - Longest time to project past the fix
 * @returns {{latitude: number, longitude: number}}
 */
export function displayPosition(
  motion,
  now,
  { blendMs = MOTION_BLEND_MS, maxProjectMs = MOTION_MAX_PROJECT_MS } = {}
) {
  const projected = projectPosition(motion, Math.min(now - motion.fixAt, maxProjectMs))
  const remaining = 1 - Math.min(Math.max((now - motion.offsetAt) / blendMs, 0), 1)
  if (remaining === 0) return projected
  return {
    latitude: projected.latitude + motion.offsetLat * remaining,
    longitude: projected.longitude + motion.offsetLon * remaining,
  }
}

/**
 * Fold a fresh report into an aircraft's motion record.
 *
 * The server resends an unchanged position every tick, and there is no
 * per-position timestamp, so a report only counts as a new fix when its
 * coordinates differ from the last one. Velocity is kept with the fix it
 * came with: applying a newer speed or track across the time already
 * projected would jump the marker.
 *
 * @param {Object|undefined} previous - Last record for this aircraft, if any
 * @param {Object} ac - Aircraft report with `latitude`, `longitude`, `groundspeed`, `track`, `lastseen`
 * @param {number} now - Current time in ms since the epoch
 * @param {Object} [options]
 * @param {number} [options.blendMs] - Passed through to `displayPosition`
 * @param {number} [options.maxProjectMs] - Reports last heard longer ago than this start out held
 * @returns {Object} Motion record for `displayPosition`
 */
export function updateMotion(previous, ac, now, options = {}) {
  const { latitude, longitude, groundspeed, track } = ac
  if (previous && previous.latitude === latitude && previous.longitude === longitude) {
    return previous
  }
  const record = {
    latitude,
    longitude,
    groundspeed,
    track,
    fixAt: now,
    offsetLat: 0,
    offsetLon: 0,
    offsetAt: now,
  }
  if (previous) {
    const drawn = displayPosition(previous, now, options)
    record.offsetLat = drawn.latitude - latitude
    record.offsetLon = wrapLongitude(drawn.longitude - longitude)
  } else {
    const { maxProjectMs = MOTION_MAX_PROJECT_MS } = options
    if (isNum(ac.lastseen) && now - ac.lastseen * 1000 > maxProjectMs) record.groundspeed = null
  }
  return record
}

/**
 * Fold a whole update into the fleet's motion records.
 *
 * @param {Map<string, Object>} previous - icao24 to motion record from the last update
 * @param {Array} aircraft - Aircraft reports with positions
 * @param {number} now - Current time in ms since the epoch
 * @param {Object} [options] - See `updateMotion`
 * @returns {Map<string, Object>} Records for exactly the aircraft listed
 */
export function updateMotions(previous, aircraft, now, options) {
  const next = new Map()
  aircraft.forEach(ac => {
    next.set(ac.icao24, updateMotion(previous.get(ac.icao24), ac, now, options))
  })
  return next
}

/**
 * The aircraft list as it should be drawn this frame.
 *
 * @param {Map<string, Object>} records - From `updateMotions`
 * @param {Array} aircraft - The reports the records were built from
 * @param {number} now - Current time in ms since the epoch
 * @param {Object} [options] - See `displayPosition`
 * @returns {Array} Copies with `latitude`/`longitude` moved; untracked entries pass through
 */
export function smoothAircraft(records, aircraft, now, options) {
  return aircraft.map(ac => {
    const motion = records.get(ac.icao24)
    return motion ? { ...ac, ...displayPosition(motion, now, options) } : ac
  })
}
