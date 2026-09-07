import { describe, expect, test } from 'bun:test'
import {
  projectPosition,
  displayPosition,
  updateMotion,
  updateMotions,
  smoothAircraft,
} from './motion'

// 360 knots is 6 nautical miles a minute, so 10 seconds covers one nautical
// mile, which is one minute of latitude (1/60 of a degree)
const ONE_MINUTE_DEG = 1 / 60

describe('projectPosition', () => {
  test('moves a northbound aircraft one minute of latitude per nautical mile', () => {
    const fix = { latitude: 40, longitude: -74, groundspeed: 360, track: 0 }
    const moved = projectPosition(fix, 10000)
    expect(moved.latitude).toBeCloseTo(40 + ONE_MINUTE_DEG, 4)
    expect(moved.longitude).toBeCloseTo(-74, 6)
  })
})

describe('projectPosition at latitude', () => {
  test('stretches eastward travel by the cosine of the latitude', () => {
    const fix = { latitude: 60, longitude: 10, groundspeed: 360, track: 90 }
    const moved = projectPosition(fix, 10000)
    // cos(60) is 0.5, so a nautical mile spans two minutes of longitude here
    expect(moved.longitude).toBeCloseTo(10 + 2 * ONE_MINUTE_DEG, 4)
    expect(moved.latitude).toBeCloseTo(60, 6)
  })
})

describe('projectPosition without velocity', () => {
  test('holds at the fix when groundspeed or track is unknown', () => {
    expect(
      projectPosition({ latitude: 40, longitude: -74, groundspeed: null, track: 90 }, 5000)
    ).toEqual({
      latitude: 40,
      longitude: -74,
    })
    expect(
      projectPosition({ latitude: 40, longitude: -74, groundspeed: 300, track: undefined }, 5000)
    ).toEqual({
      latitude: 40,
      longitude: -74,
    })
  })

  test('holds at the fix before any time has passed', () => {
    const fix = { latitude: 40, longitude: -74, groundspeed: 300, track: 45 }
    expect(projectPosition(fix, 0)).toEqual({ latitude: 40, longitude: -74 })
    expect(projectPosition(fix, -100)).toEqual({ latitude: 40, longitude: -74 })
  })
})

describe('displayPosition', () => {
  const motion = {
    latitude: 40,
    longitude: -74,
    groundspeed: 360,
    track: 0,
    fixAt: 1000,
    offsetLat: 0.01,
    offsetLon: -0.02,
    offsetAt: 1000,
  }
  const options = { blendMs: 1000, maxProjectMs: 30000 }

  test('starts at the projected fix plus the whole correction offset', () => {
    const shown = displayPosition(motion, 1000, options)
    expect(shown.latitude).toBeCloseTo(40.01, 8)
    expect(shown.longitude).toBeCloseTo(-74.02, 8)
  })

  test('fades the offset away linearly over the blend window', () => {
    const shown = displayPosition(motion, 1500, options)
    const projected = projectPosition(motion, 500)
    expect(shown.latitude).toBeCloseTo(projected.latitude + 0.005, 8)
    expect(shown.longitude).toBeCloseTo(projected.longitude - 0.01, 8)
  })

  test('is exactly the projected position once the blend has finished', () => {
    expect(displayPosition(motion, 11000, options)).toEqual(projectPosition(motion, 10000))
  })

  test('stops projecting forward after the cap', () => {
    const atCap = displayPosition(motion, 1000 + 30000, options)
    const wellPast = displayPosition(motion, 1000 + 90000, options)
    expect(wellPast).toEqual(atCap)
  })
})

describe('updateMotion', () => {
  const options = { blendMs: 1000, maxProjectMs: 30000 }
  const now = 1700000000000
  const report = { latitude: 40, longitude: -74, groundspeed: 360, track: 0, lastseen: now / 1000 }

  test('anchors a first sighting at its reported position with no correction', () => {
    const motion = updateMotion(undefined, report, now, options)
    expect(motion).toEqual({
      latitude: 40,
      longitude: -74,
      groundspeed: 360,
      track: 0,
      fixAt: now,
      offsetLat: 0,
      offsetLon: 0,
      offsetAt: now,
    })
  })

  test('holds a first sighting that was last heard longer ago than the projection cap', () => {
    const stale = { ...report, lastseen: (now - 31000) / 1000 }
    const motion = updateMotion(undefined, stale, now, options)
    expect(displayPosition(motion, now + 10000, options)).toEqual({ latitude: 40, longitude: -74 })
  })

  test('keeps the record, velocity included, while the position is unchanged', () => {
    const previous = updateMotion(undefined, report, now, options)
    const later = { ...report, groundspeed: 200, track: 90, lastseen: (now + 5000) / 1000 }
    expect(updateMotion(previous, later, now + 5000, options)).toBe(previous)
  })

  test('records the gap between where it was drawn and the new fix', () => {
    const previous = updateMotion(undefined, report, now, options)
    const drawn = displayPosition(previous, now + 5000, options)
    const next = { ...report, latitude: 40.02, longitude: -74.001, track: 10 }
    const motion = updateMotion(previous, next, now + 5000, options)
    expect(motion.fixAt).toBe(now + 5000)
    expect(motion.offsetAt).toBe(now + 5000)
    expect(motion.track).toBe(10)
    expect(motion.offsetLat).toBeCloseTo(drawn.latitude - 40.02, 10)
    expect(motion.offsetLon).toBeCloseTo(drawn.longitude + 74.001, 10)
    // Continuity: the first frame after the new fix draws exactly where the last one did
    expect(displayPosition(motion, now + 5000, options)).toEqual(drawn)
  })
})

describe('updateMotions', () => {
  const options = { blendMs: 1000, maxProjectMs: 30000 }
  const now = 1700000000000
  const a = {
    icao24: 'a1',
    latitude: 40,
    longitude: -74,
    groundspeed: 300,
    track: 0,
    lastseen: now / 1000,
  }
  const b = {
    icao24: 'b2',
    latitude: 41,
    longitude: -73,
    groundspeed: 250,
    track: 90,
    lastseen: now / 1000,
  }

  test('keeps records for aircraft still listed and drops the rest', () => {
    const first = updateMotions(new Map(), [a, b], now, options)
    const second = updateMotions(first, [a], now + 1000, options)
    expect(second.get('a1')).toBe(first.get('a1'))
    expect(second.has('b2')).toBe(false)
  })
})

describe('smoothAircraft', () => {
  const options = { blendMs: 1000, maxProjectMs: 30000 }
  const now = 1700000000000
  const a = {
    icao24: 'a1',
    callsign: 'TEST1',
    latitude: 40,
    longitude: -74,
    groundspeed: 360,
    track: 0,
    lastseen: now / 1000,
  }

  test('replaces only the coordinates with the displayed position', () => {
    const records = updateMotions(new Map(), [a], now, options)
    const [shown] = smoothAircraft(records, [a], now + 10000, options)
    expect(shown.callsign).toBe('TEST1')
    expect(shown.groundspeed).toBe(360)
    expect(shown.latitude).toBeCloseTo(40 + ONE_MINUTE_DEG, 4)
    expect(shown.longitude).toBeCloseTo(-74, 6)
  })

  test('passes an aircraft through untouched when it has no record', () => {
    const [shown] = smoothAircraft(new Map(), [a], now + 10000, options)
    expect(shown).toBe(a)
  })
})
