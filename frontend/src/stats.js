/**
 * Pure helpers for the history view: number and time formatting, axis ticks.
 */

export const INTERVAL_OPTIONS = [
  { value: 300, label: '5 min' },
  { value: 900, label: '15 min' },
  { value: 3600, label: '1 h' },
]

export const HISTORY_WINDOW = 86400 // seconds shown in the history view

/** `1,234` below ten thousand, then `12.3k` / `1.23M`. */
export function formatCount(n) {
  if (n < 10000) return n.toLocaleString('en-US')
  if (n < 1e6) return `${(n / 1e3).toFixed(1).replace(/\.0$/, '')}k`
  return `${(n / 1e6).toFixed(2).replace(/\.?0+$/, '')}M`
}

/** Smallest of 1, 2, 5 × 10^k that is at least `max`; 1 for empty data. */
export function niceMax(max) {
  if (!(max > 0)) return 1
  const pow = 10 ** Math.floor(Math.log10(max))
  for (const m of [1, 2, 5, 10]) if (m * pow >= max) return m * pow
  return 10 * pow
}

// Seconds between x-axis labels for each bucket size; all divide a day evenly.
const TICK_EVERY = { 300: 3600, 900: 3 * 3600, 3600: 4 * 3600 }

const hourLabel = seconds =>
  new Date(seconds * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

/** Bucket indexes that get an x-axis label, on round UTC hours. */
export function timeTicks(buckets, interval) {
  const every = TICK_EVERY[interval] || 4 * 3600
  return buckets
    .map((b, index) => ({ index, start: b.start }))
    .filter(({ start }) => start % every === 0)
    .map(({ index, start }) => ({ index, label: hourLabel(start) }))
}

/** `just now`, `4 min ago`, `3 h ago`, `2 d ago`. */
export function relativeTime(seconds, now = Date.now() / 1000) {
  const age = Math.max(0, now - seconds)
  if (age < 60) return 'just now'
  if (age < 3600) return `${Math.floor(age / 60)} min ago`
  if (age < 86400) return `${Math.floor(age / 3600)} h ago`
  return `${Math.floor(age / 86400)} d ago`
}

/** `9:00 AM – 9:15 AM`, for bar tooltips. */
export function bucketRange(start, interval) {
  return `${hourLabel(start)} – ${hourLabel(start + interval)}`
}
