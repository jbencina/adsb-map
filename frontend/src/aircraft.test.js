import { describe, expect, test } from 'bun:test'
import { cleanCallsign, hasPosition } from './aircraft'

describe('hasPosition', () => {
  test('true when both coordinates are numbers', () => {
    expect(hasPosition({ latitude: 40.7, longitude: -74.0 })).toBe(true)
  })

  test('true at the equator and prime meridian', () => {
    expect(hasPosition({ latitude: 0, longitude: 0 })).toBe(true)
  })

  test('false for Mode-S-only aircraft with no position', () => {
    expect(hasPosition({ latitude: null, longitude: null })).toBe(false)
    expect(hasPosition({})).toBe(false)
    expect(hasPosition({ latitude: 40.7 })).toBe(false)
  })
})

describe('cleanCallsign', () => {
  test('drops the padding underscores and handles missing values', () => {
    expect(cleanCallsign('N7894G__')).toBe('N7894G')
    expect(cleanCallsign('SKW5702_')).toBe('SKW5702')
    expect(cleanCallsign('UAL123')).toBe('UAL123')
    expect(cleanCallsign(null)).toBe('')
    expect(cleanCallsign('____')).toBe('')
  })
})
