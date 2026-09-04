/**
 * Helpers for aircraft records returned by /api/all.
 */

/**
 * Whether an aircraft can be drawn on the map.
 *
 * Mode-S-only replies (altitude, squawk) never carry a position, so those
 * aircraft are tracked but invisible. Everything that counts or renders
 * "aircraft on the map" must agree on this one test.
 *
 * @param {Object} ac - Aircraft record
 * @returns {boolean}
 */
export const hasPosition = ac => typeof ac.latitude === 'number' && typeof ac.longitude === 'number'
