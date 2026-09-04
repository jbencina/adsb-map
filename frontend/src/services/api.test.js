import { afterEach, describe, expect, test } from 'bun:test'
import { fetchAircraftTracks } from './api'

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
