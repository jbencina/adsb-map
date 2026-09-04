import { describe, expect, test } from 'bun:test'
import { aircraftRssi, signalColor, signalLevel, signalRatio } from './signal'

const withMetadata = samples => ({ metadata: samples.map(rssi => ({ rssi })) })

describe('aircraftRssi', () => {
  test('averages the rssi of the reception samples', () => {
    expect(aircraftRssi(withMetadata([-10, -20]))).toBe(-15)
  })

  test('ignores samples without a signal level', () => {
    expect(aircraftRssi(withMetadata([-10, null, -30]))).toBe(-20)
  })

  test('is null when no sample carries a signal level', () => {
    expect(aircraftRssi(withMetadata([null, null]))).toBeNull()
    expect(aircraftRssi({ metadata: [] })).toBeNull()
    expect(aircraftRssi({})).toBeNull()
  })
})

describe('signalLevel', () => {
  test.each([
    [-5, 4, 'Strong'],
    [-15, 4, 'Strong'],
    [-15.1, 3, 'Good'],
    [-22, 3, 'Good'],
    [-22.1, 2, 'Fair'],
    [-30, 2, 'Fair'],
    [-30.1, 1, 'Weak'],
    [-45, 1, 'Weak'],
  ])('%p dBFS is %p bars (%s)', (rssi, bars, label) => {
    expect(signalLevel(rssi)).toEqual({ bars, label })
  })

  test('has no bars without a reading', () => {
    expect(signalLevel(null)).toEqual({ bars: 0, label: 'No data' })
    expect(signalLevel(undefined)).toEqual({ bars: 0, label: 'No data' })
  })
})

describe('signalRatio', () => {
  test('maps the display range onto 0..1 and clamps outside it', () => {
    expect(signalRatio(-36)).toBe(0)
    expect(signalRatio(-8)).toBe(1)
    expect(signalRatio(-22)).toBeCloseTo(0.5)
    expect(signalRatio(-60)).toBe(0)
    expect(signalRatio(0)).toBe(1)
  })
})

describe('signalColor', () => {
  test('is the weak colour at the bottom of the range and the strong colour at the top', () => {
    expect(signalColor(-40)).toBe('#ff3b30')
    expect(signalColor(-5)).toBe('#34c759')
  })

  test('passes through the middle stop halfway up the range', () => {
    expect(signalColor(-22)).toBe('#ff9500')
  })

  test('blends between stops without collapsing to grey', () => {
    // Between orange and green: stays bright, lands on a yellow-green rather than olive
    const [r, g, b] = [1, 3, 5].map(i => parseInt(signalColor(-15).slice(i, i + 2), 16))
    expect(g).toBeGreaterThan(170)
    expect(r + g).toBeGreaterThan(300)
    expect(b).toBeLessThan(80)
  })

  test('is null without a reading', () => {
    expect(signalColor(null)).toBeNull()
  })
})
