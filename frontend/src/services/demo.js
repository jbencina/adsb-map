/**
 * In-browser stand-in for the backend, used when demo mode is on.
 *
 * A fixed fleet flies dead-reckoned paths around the default map center and
 * turns for home when it drifts out of range, so the map never empties. The
 * shapes returned match the backend's /api/all and /api/track responses.
 */

import { DEFAULT_MAP_CENTER } from '../constants'

const FLEET_SIZE = 24
const RANGE_DEG = 1.5 // distance from center that triggers a turn for home
const HISTORY_SECONDS = 15 * 60
const HISTORY_STEP = 5 // seconds between recorded track points
const RSSI_SAMPLES = 4 // reception samples kept per aircraft, like /api/all
const RSSI_NEAR = -10 // dBFS overhead ...
const RSSI_FAR = -34 // ... and at the edge of range
const MISSED_UPDATE_RATE = 0.05 // per-second chance a contact is not heard this tick
const TURN_RATE = 2 // deg/s while turning
const AIRLINES = ['UAL', 'SWA', 'DAL', 'AAL', 'ASA', 'SKW', 'JBU', 'FDX', 'UPS']
const AIRLINE_TYPES = ['B738', 'A320', 'A21N', 'B77W', 'B789', 'E75L', 'CRJ9']
const GA_TYPES = ['C172', 'PC12', 'SR22', 'BE36']
const LETTERS = 'ABCDEFGHJKLMNPRSTUVWXYZ'

// Deterministic PRNG so a reload reproduces the same fleet.
const mulberry32 = seed => () => {
  seed = (seed + 0x6d2b79f5) | 0
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}

const pick = (rand, items) => items[Math.floor(rand() * items.length)]
const between = (rand, lo, hi) => lo + rand() * (hi - lo)
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x))
const toRad = deg => (deg * Math.PI) / 180
const toDeg = rad => (rad * 180) / Math.PI
// Signed shortest rotation from `from` to `to`, in (-180, 180].
const turnTo = (from, to) => ((to - from + 540) % 360) - 180

function makeAircraft(rand, index, now) {
  const ga = rand() < 0.25
  const n = 100 + Math.floor(rand() * 900)
  const registration = `N${n}${pick(rand, LETTERS)}${pick(rand, LETTERS)}`
  const nowSeconds = Math.floor(now / 1000)
  return {
    ac: {
      icao24: (0xa00000 + index * 4099 + Math.floor(rand() * 4000)).toString(16),
      firstseen: nowSeconds - HISTORY_SECONDS,
      lastseen: nowSeconds,
      callsign: ga ? registration : `${pick(rand, AIRLINES)}${n}`,
      registration,
      typecode: pick(rand, ga ? GA_TYPES : AIRLINE_TYPES),
      type_description: null,
      squawk: ga ? '1200' : String(1000 + Math.floor(rand() * 6777)).replace(/[89]/g, '7'),
      latitude: DEFAULT_MAP_CENTER.latitude + between(rand, -RANGE_DEG, RANGE_DEG),
      longitude: DEFAULT_MAP_CENTER.longitude + between(rand, -RANGE_DEG, RANGE_DEG),
      altitude: ga ? between(rand, 2500, 9500) : between(rand, 24000, 41000),
      groundspeed: ga ? between(rand, 90, 170) : between(rand, 380, 500),
      vertical_rate: 0,
      track: rand() * 360,
      count: 0,
      metadata: [],
    },
    band: ga ? [1500, 12000] : [20000, 43000], // altitude floor/ceiling
    history: [],
    lastRecorded: -Infinity,
    turning: 0, // -1 / 0 / +1
    homing: false,
  }
}

export class DemoFleet {
  constructor({ size = FLEET_SIZE, seed = 1, now = Date.now() } = {}) {
    this.rand = mulberry32(seed)
    this.entries = Array.from({ length: size }, (_, i) => makeAircraft(this.rand, i, now))
    // A couple of contacts with no position, as a real feed always has.
    for (const e of this.entries.slice(-2)) Object.assign(e.ac, { latitude: null, longitude: null })
    // Pre-roll so every aircraft has a track the moment the map opens.
    this.lastTick = now - HISTORY_SECONDS * 1000
    for (let t = this.lastTick; t < now; t += HISTORY_STEP * 1000) this.advance(t, { gaps: false })
    this.advance(now, { gaps: false })
  }

  /** Move the fleet forward to `now` (ms) and return the fleet for chaining. */
  advance(now, { gaps = true } = {}) {
    const dt = clamp((now - this.lastTick) / 1000, 0, 60)
    this.lastTick = now
    for (const e of this.entries) {
      if (gaps && this.rand() < MISSED_UPDATE_RATE * dt) continue
      this.move(e, dt)
      this.hear(e, now)
    }
    return this
  }

  move(e, dt) {
    const { ac } = e
    if (ac.latitude === null) return
    const step = (ac.groundspeed * dt) / 3600 / 60 // degrees of latitude
    ac.latitude += step * Math.cos(toRad(ac.track))
    ac.longitude += (step * Math.sin(toRad(ac.track))) / Math.cos(toRad(ac.latitude))
    ac.track = (ac.track + e.turning * TURN_RATE * dt + 360) % 360
    ac.altitude = clamp(ac.altitude + (ac.vertical_rate * dt) / 60, ...e.band)
    if (e.band.includes(ac.altitude)) ac.vertical_rate = 0

    const dLat = DEFAULT_MAP_CENTER.latitude - ac.latitude
    const dLon = (DEFAULT_MAP_CENTER.longitude - ac.longitude) * Math.cos(toRad(ac.latitude))
    const home = turnTo(ac.track, (toDeg(Math.atan2(dLon, dLat)) + 360) % 360)
    if (Math.hypot(dLat, dLon) > RANGE_DEG) {
      e.homing = true
      e.turning = Math.sign(home)
    } else if (e.homing && Math.abs(home) < 5) {
      e.homing = false
      e.turning = 0
    } else if (!e.homing) {
      // Occasional random turns and climbs/descents keep the picture lively.
      if (this.rand() < 0.01 * dt) e.turning = e.turning ? 0 : pick(this.rand, [-1, 1])
      if (this.rand() < 0.01 * dt) {
        ac.vertical_rate = ac.vertical_rate ? 0 : pick(this.rand, [-1500, -800, 800, 1500])
      }
    }
  }

  hear(e, now) {
    const { ac } = e
    ac.lastseen = Math.floor(now / 1000)
    ac.count += 1
    if (ac.latitude === null) return
    // Signal falls off with distance from the receiver at the map center, plus a little noise
    const dLat = ac.latitude - DEFAULT_MAP_CENTER.latitude
    const dLon = (ac.longitude - DEFAULT_MAP_CENTER.longitude) * Math.cos(toRad(ac.latitude))
    const reach = clamp(Math.hypot(dLat, dLon) / RANGE_DEG, 0, 1)
    const rssi = RSSI_NEAR + (RSSI_FAR - RSSI_NEAR) * reach + between(this.rand, -2, 2)
    ac.metadata.unshift({ system_timestamp: ac.lastseen, nanoseconds: 0, rssi, serial: null })
    ac.metadata.length = Math.min(ac.metadata.length, RSSI_SAMPLES)
    if (now - e.lastRecorded < HISTORY_STEP * 1000) return
    e.lastRecorded = now
    e.history.push({
      timestamp: ac.lastseen,
      latitude: ac.latitude,
      longitude: ac.longitude,
      altitude: Math.round(ac.altitude),
    })
    const cutoff = ac.lastseen - HISTORY_SECONDS
    while (e.history.length && e.history[0].timestamp < cutoff) e.history.shift()
  }

  /** Current state vectors, shaped like /api/all. */
  all() {
    return this.entries.map(({ ac }) => ({
      ...ac,
      metadata: ac.metadata.map(m => ({ ...m, rssi: Math.round(m.rssi * 10) / 10 })),
      altitude: Math.round(ac.altitude),
      groundspeed: Math.round(ac.groundspeed),
      track: Math.round(ac.track * 10) / 10,
    }))
  }

  /** Trajectory for one aircraft, shaped like /api/track. */
  track(icao24, sinceSeconds = 0) {
    const entry = this.entries.find(e => e.ac.icao24 === icao24)
    return entry ? entry.history.filter(p => p.timestamp >= sinceSeconds) : []
  }
}
