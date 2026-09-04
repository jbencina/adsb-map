import { describe, expect, test } from 'bun:test'
import { shortestTurn, continueHeading } from './heading'

describe('shortestTurn', () => {
  test('small changes are returned as-is', () => {
    expect(shortestTurn(90, 100)).toBe(10)
    expect(shortestTurn(100, 90)).toBe(-10)
  })

  test('crossing north takes the short way round', () => {
    expect(shortestTurn(359, 1)).toBe(2)
    expect(shortestTurn(1, 359)).toBe(-2)
    expect(shortestTurn(350, 10)).toBe(20)
  })

  test('a reversal is at most a half turn', () => {
    expect(Math.abs(shortestTurn(0, 180))).toBe(180)
    expect(shortestTurn(90, 270)).toBe(180)
  })

  test('accepts unwrapped angles outside 0..360', () => {
    expect(shortestTurn(719, 1)).toBe(2)
    expect(shortestTurn(-1, 1)).toBe(2)
  })
})

describe('continueHeading', () => {
  test('starts at the reported track when there is no history', () => {
    expect(continueHeading(null, 45)).toBe(45)
    expect(continueHeading(undefined, 350)).toBe(350)
  })

  test('keeps the unwrapped angle continuous across north', () => {
    // 359 -> 1 must animate +2 degrees, not -358
    expect(continueHeading(359, 1)).toBe(361)
    expect(continueHeading(361, 359)).toBe(359)
    expect(continueHeading(2, 358)).toBe(-2)
  })

  test('is a no-op when the track has not changed', () => {
    expect(continueHeading(361, 1)).toBe(361)
  })

  test('drops to null when the track is unknown', () => {
    expect(continueHeading(120, null)).toBeNull()
    expect(continueHeading(120, undefined)).toBeNull()
  })
})
