import { afterEach, describe, expect, test } from 'bun:test'
import { fetchAircraftTrack, fetchAircraftTracks, fetchStats, fetchTracks } from './api'

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

describe('fetchAircraftTracks', () => {
  test('asks only for positions since the given timestamp', async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => ({}) }
    }

    await fetchAircraftTracks(1700000000)

    expect(calls).toHaveLength(1)
    expect(calls[0].endsWith('/api/tracks?since=1700000000')).toBe(true)
  })
})

describe('fetchAircraftTrack', () => {
  test('asks for one aircraft since the given timestamp', async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => [] }
    }

    await fetchAircraftTrack('abc123', 1700000000)

    expect(calls).toHaveLength(1)
    expect(calls[0].endsWith('/api/track?icao24=abc123&since=1700000000')).toBe(true)
  })

  test('returns the points keyed by icao24, shaped like /api/tracks', async () => {
    const points = [{ timestamp: 1700000001, latitude: 40, longitude: -74, altitude: 3000 }]
    globalThis.fetch = async () => ({ ok: true, json: async () => points })

    expect(await fetchAircraftTrack('abc123', 1700000000)).toEqual({ abc123: points })
  })

  test('omits the aircraft when it has no positions', async () => {
    globalThis.fetch = async () => ({ ok: true, json: async () => [] })

    expect(await fetchAircraftTrack('abc123', 1700000000)).toEqual({})
  })
})

describe('fetchTracks', () => {
  test("fetches every aircraft for the 'all' scope", async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => ({}) }
    }

    await fetchTracks('all', 1700000000)

    expect(calls[0].endsWith('/api/tracks?since=1700000000')).toBe(true)
  })

  test('fetches only the named aircraft for an icao24 scope', async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => [] }
    }

    await fetchTracks('abc123', 1700000000)

    expect(calls[0].endsWith('/api/track?icao24=abc123&since=1700000000')).toBe(true)
  })
})

describe('fetchStats', () => {
  test('requests /api/stats with window, interval and limit', async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => ({ buckets: [] }) }
    }

    await fetchStats({ window: 86400, interval: 900, limit: 10 })

    expect(calls).toHaveLength(1)
    expect(calls[0].endsWith('/api/stats?window=86400&interval=900&limit=10')).toBe(true)
  })
})
