import { describe, expect, test } from 'bun:test'
import { parseBounded } from './parseBounded'

describe('parseBounded', () => {
  test('accepts whole numbers inside the range', () => {
    expect(parseBounded('20', 1, 60)).toBe(20)
    expect(parseBounded('1', 1, 60)).toBe(1)
    expect(parseBounded('60', 1, 60)).toBe(60)
    expect(parseBounded(' 5 ', 1, 60)).toBe(5)
  })

  test('rejects an empty or partially typed value', () => {
    expect(parseBounded('', 1, 60)).toBeNull()
    expect(parseBounded('-', 1, 60)).toBeNull()
    expect(parseBounded('2.', 1, 60)).toBeNull()
  })

  test('rejects values outside the range so they are never committed', () => {
    expect(parseBounded('0', 1, 60)).toBeNull()
    expect(parseBounded('61', 1, 60)).toBeNull()
    expect(parseBounded('-5', 1, 60)).toBeNull()
  })

  test('rejects non-integers', () => {
    expect(parseBounded('2.5', 1, 60)).toBeNull()
    expect(parseBounded('abc', 1, 60)).toBeNull()
  })
})
