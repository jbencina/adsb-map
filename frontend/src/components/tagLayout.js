/**
 * Greedy placement for callsign tags around plane markers, in screen pixels.
 *
 * Tags are laid out in priority order: the selected aircraft first, then the most
 * recently heard. Each tries a ring of positions around its plane and takes the first
 * that clears every plane footprint, every tag already placed, and the viewport edge.
 * A tag with no free position is left out entirely rather than squeezed in.
 */

const GLYPH_RADIUS = 11 // px from center where the plane glyph ends
const SELECTED_RADIUS = 21 // the selection disc reaches further
const GAP = 12 // leader length: clear space between glyph edge and pill
const FOOTPRINT = 13 // half-size of the box reserved under every plane
const TAG_PAD = 2 // breathing room between neighbouring tags

// Order matters: beside the plane first, then the corners, then above and below
const ANCHORS = [
  [1, 0],
  [-1, 0],
  [1, -1],
  [1, 1],
  [-1, -1],
  [-1, 1],
  [0, -1],
  [0, 1],
]

const overlaps = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/**
 * Top-left corner of a pill placed at `anchor`, with its near edge `d` px from the plane center
 */
function candidate(cx, cy, w, h, [dx, dy], d) {
  if (dx && dy) {
    // Corners: the pill's near corner sits on the ring at distance d
    const off = d * Math.SQRT1_2
    return { x: dx > 0 ? cx + off : cx - off - w, y: dy > 0 ? cy + off : cy - off - h }
  }
  if (dx) return { x: dx > 0 ? cx + d : cx - d - w, y: cy - h / 2 }
  return { x: cx - w / 2, y: dy > 0 ? cy + d : cy - d - h }
}

/**
 * Leader line from the glyph edge to the nearest point on the pill, or null when they touch
 */
function leaderFor(item, pos) {
  const ex = clamp(item.cx, pos.x, pos.x + item.w)
  const ey = clamp(item.cy, pos.y, pos.y + item.h)
  const dx = ex - item.cx
  const dy = ey - item.cy
  const dist = Math.hypot(dx, dy)
  const r0 = item.selected ? SELECTED_RADIUS : GLYPH_RADIUS
  if (dist <= r0 + 2) return null
  return { x1: item.cx + (dx / dist) * r0, y1: item.cy + (dy / dist) * r0, x2: ex, y2: ey }
}

/**
 * Place tags
 *
 * @param {Array<{id: string, cx: number, cy: number, w: number, h: number, selected: boolean, age: number}>} items - One per aircraft, in screen px
 * @param {{width: number, height: number}} viewport - Map size in px
 * @returns {Array} The placed subset, each with `x`, `y` (pill top-left) and `leader`
 */
export function layoutTags(items, { width, height }) {
  const order = [...items].sort((a, b) => b.selected - a.selected || a.age - b.age)
  const footprints = items.map(it => {
    const r = it.selected ? SELECTED_RADIUS : FOOTPRINT
    return { id: it.id, x: it.cx - r, y: it.cy - r, w: 2 * r, h: 2 * r }
  })
  const placed = []
  const out = []
  for (const it of order) {
    const d = (it.selected ? SELECTED_RADIUS : GLYPH_RADIUS) + GAP
    for (const anchor of ANCHORS) {
      const pos = candidate(it.cx, it.cy, it.w, it.h, anchor, d)
      const rect = {
        x: pos.x - TAG_PAD,
        y: pos.y - TAG_PAD,
        w: it.w + 2 * TAG_PAD,
        h: it.h + 2 * TAG_PAD,
      }
      if (rect.x < 0 || rect.y < 0 || rect.x + rect.w > width || rect.y + rect.h > height) continue
      if (footprints.some(f => f.id !== it.id && overlaps(rect, f))) continue
      if (placed.some(p => overlaps(rect, p))) continue
      placed.push(rect)
      out.push({ ...it, x: pos.x, y: pos.y, leader: leaderFor(it, pos) })
      break
    }
  }
  return out
}
