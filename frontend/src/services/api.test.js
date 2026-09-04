import { afterEach, describe, expect, test } from 'bun:test'
import { fetchAircraftTrack } from './api'

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

describe('fetchAircraftTrack', () => {
  test('bounds the track to the requested window via since', async () => {
    const calls = []
    globalThis.fetch = async url => {
      calls.push(url)
      return { ok: true, json: async () => [] }
    }

    await fetchAircraftTrack('abc123', 1700000000)

    expect(calls).toHaveLength(1)
    expect(calls[0].endsWith('/api/track?icao24=abc123&since=1700000000')).toBe(true)
  })
})
