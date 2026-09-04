/**
 * Signal strength helpers: turn an aircraft's reception samples into a
 * reading, a fixed quality band, and a colour for the map marker.
 */

import { SIGNAL_COLORS, SIGNAL_LEVELS, SIGNAL_RANGE_MAX, SIGNAL_RANGE_MIN } from './constants'

const hasReading = rssi => typeof rssi === 'number' && Number.isFinite(rssi)

/**
 * Average RSSI over the aircraft's recent reception samples, in dBFS
 *
 * @param {Object} ac - Aircraft from /api/all, with an optional `metadata` list
 * @returns {number|null} Mean rssi, or null when no sample carries one
 */
export function aircraftRssi(ac) {
  const readings = (ac?.metadata ?? []).map(m => m.rssi).filter(hasReading)
  if (readings.length === 0) return null
  return readings.reduce((sum, r) => sum + r, 0) / readings.length
}

/**
 * Quality band for a reading
 *
 * @param {number|null} rssi - Signal level in dBFS
 * @returns {{bars: number, label: string}} Bars lit (0 to 4) and a short label
 */
export function signalLevel(rssi) {
  if (!hasReading(rssi)) return { bars: 0, label: 'No data' }
  const level = SIGNAL_LEVELS.find(l => rssi >= l.min)
  return { bars: level.bars, label: level.label }
}

/**
 * Where a reading falls in the display range, 0 (weak) to 1 (strong)
 *
 * @param {number} rssi - Signal level in dBFS
 * @returns {number} Ratio clamped to 0..1
 */
export function signalRatio(rssi) {
  const ratio = (rssi - SIGNAL_RANGE_MIN) / (SIGNAL_RANGE_MAX - SIGNAL_RANGE_MIN)
  return Math.min(1, Math.max(0, ratio))
}

// sRGB <-> OKLab, so blends between stops keep their brightness instead of turning muddy
const toLinear = c => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const fromLinear = c => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)
const clamp01 = x => Math.min(1, Math.max(0, x))

function hexToOklab(hex) {
  const [r, g, b] = [1, 3, 5].map(i => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255))
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToHex([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
  const hex = rgb.map(c =>
    Math.round(clamp01(fromLinear(c)) * 255)
      .toString(16)
      .padStart(2, '0')
  )
  return `#${hex.join('')}`
}

const STOPS = SIGNAL_COLORS.map(hexToOklab)

/**
 * Marker colour for a reading, blended along the weak-to-strong ramp
 *
 * @param {number|null} rssi - Signal level in dBFS
 * @returns {string|null} CSS hex colour, or null without a reading
 */
export function signalColor(rssi) {
  if (!hasReading(rssi)) return null
  const position = signalRatio(rssi) * (STOPS.length - 1)
  const index = Math.min(Math.floor(position), STOPS.length - 2)
  const t = position - index
  if (t === 0) return SIGNAL_COLORS[index]
  const from = STOPS[index]
  const to = STOPS[index + 1]
  return oklabToHex(from.map((c, i) => c + (to[i] - c) * t))
}
