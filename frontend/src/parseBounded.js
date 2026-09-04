/**
 * Parse a typed value as a whole number within [min, max].
 *
 * @param {string} text - Raw input text
 * @param {number} min - Smallest accepted value
 * @param {number} max - Largest accepted value
 * @returns {number|null} The number, or null if the text is not (yet) a valid value
 */
export function parseBounded(text, min, max) {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const n = Number(trimmed)
  return n >= min && n <= max ? n : null
}
