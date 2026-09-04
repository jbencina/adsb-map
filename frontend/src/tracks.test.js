import { describe, expect, test } from 'bun:test'
import { mergeTracks, newestTimestamp } from './tracks'

const point = (ts, lat = 40, lon = -74) => ({ timestamp: ts, latitude: lat, longitude: lon })

describe('mergeTracks', () => {
  test('converts fresh positions into [lon, lat, timestamp] points', () => {
    const merged = mergeTracks({}, { abc123: [point(100, 40.1, -74.2)] }, 0)
    expect(merged).toEqual({ abc123: [[-74.2, 40.1, 100]] })
  })

  test('appends only points newer than what the aircraft already has', () => {
    const prev = { abc123: [[-74, 40, 100]] }
    // 100 comes back again because the poll asks for since=100 inclusive
    const merged = mergeTracks(prev, { abc123: [point(100), point(101)] }, 0)
    expect(merged.abc123.map(p => p[2])).toEqual([100, 101])
  })

  test('prunes points older than the cutoff and drops aircraft left empty', () => {
    const prev = {
      abc123: [
        [-74, 40, 10],
        [-74, 40, 50],
      ],
      old999: [[-74, 40, 5]],
    }
    const merged = mergeTracks(prev, {}, 20)
    expect(merged).toEqual({ abc123: [[-74, 40, 50]] })
  })

  test('does not mutate the previous tracks', () => {
    const prev = { abc123: [[-74, 40, 100]] }
    mergeTracks(prev, { abc123: [point(101)] }, 0)
    expect(prev.abc123).toHaveLength(1)
  })
})

describe('newestTimestamp', () => {
  test('is the latest point across all aircraft', () => {
    const tracks = {
      a: [
        [0, 0, 5],
        [0, 0, 9],
      ],
      b: [[0, 0, 7]],
    }
    expect(newestTimestamp(tracks)).toBe(9)
  })

  test('is null when there are no points', () => {
    expect(newestTimestamp({})).toBeNull()
  })
})
