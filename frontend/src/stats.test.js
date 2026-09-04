import { describe, expect, test } from 'bun:test'
import {
  bucketRange,
  formatCount,
  gridValues,
  msUntilNextMinute,
  niceMax,
  relativeTime,
  timeTicks,
} from './stats'

describe('formatCount', () => {
  test('groups thousands below 10k and abbreviates above', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(1234)).toBe('1,234')
    expect(formatCount(12345)).toBe('12.3k')
    expect(formatCount(20000)).toBe('20k')
    expect(formatCount(1234567)).toBe('1.23M')
  })
})

describe('niceMax', () => {
  test('rounds up to 1, 2, 3 or 5 times a power of ten', () => {
    expect(niceMax(0)).toBe(1)
    expect(niceMax(7)).toBe(10)
    expect(niceMax(24)).toBe(30)
    expect(niceMax(95)).toBe(100)
    expect(niceMax(130)).toBe(200)
    expect(niceMax(430)).toBe(500)
    expect(niceMax(500)).toBe(500)
    expect(niceMax(12000)).toBe(20000)
  })
})

describe('gridValues', () => {
  test('lands gridlines on round numbers', () => {
    expect(gridValues(0)).toEqual([0, 1])
    expect(gridValues(24)).toEqual([0, 10, 20, 30])
    expect(gridValues(95)).toEqual([0, 20, 40, 60, 80, 100])
    expect(gridValues(130)).toEqual([0, 50, 100, 150, 200])
    expect(gridValues(430)).toEqual([0, 100, 200, 300, 400, 500])
  })
})

describe('timeTicks', () => {
  const start = Date.UTC(2026, 8, 4, 0, 0) / 1000
  const grid = (n, step) => Array.from({ length: n }, (_, i) => ({ start: start + i * step }))

  test('labels every 3 hours for 15-minute buckets, on the hour', () => {
    const ticks = timeTicks(grid(96, 900), 900)
    expect(ticks.length).toBe(8)
    expect(ticks[0].index).toBe(0)
    expect(ticks[1].index).toBe(12)
    expect(typeof ticks[0].label).toBe('string')
  })

  test('labels every 2 hours for 5-minute buckets and every 4 hours for hourly', () => {
    expect(timeTicks(grid(288, 300), 300).length).toBe(12)
    expect(timeTicks(grid(24, 3600), 3600).length).toBe(6)
  })
})

describe('relativeTime', () => {
  test('describes seconds, minutes, hours and days', () => {
    const now = 1000000
    expect(relativeTime(now - 20, now)).toBe('just now')
    expect(relativeTime(now - 240, now)).toBe('4 min ago')
    expect(relativeTime(now - 3 * 3600 - 12 * 60 - 10, now)).toBe('3h 12m ago')
    expect(relativeTime(now - 3 * 3600, now)).toBe('3h 0m ago')
    expect(relativeTime(now - 86400 - 10, now)).toBe('1 day ago')
    expect(relativeTime(now - 2 * 86400, now)).toBe('2 days ago')
  })
})

describe('msUntilNextMinute', () => {
  test('lands just after the next minute boundary', () => {
    expect(msUntilNextMinute(60000 * 5 + 15000)).toBe(45500)
    expect(msUntilNextMinute(60000 * 5)).toBe(60500)
  })
})

describe('bucketRange', () => {
  test('formats a start and end time', () => {
    const s = bucketRange(Date.UTC(2026, 8, 4, 9, 0) / 1000, 900)
    expect(s).toMatch(/\d{1,2}:\d{2}.*–.*\d{1,2}:\d{2}/)
  })
})
