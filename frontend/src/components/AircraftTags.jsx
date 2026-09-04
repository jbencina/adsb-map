import { useEffect, useRef } from 'react'
import PropTypes from 'prop-types'
import { layoutTags } from './tagLayout'

// Must match .tag in AircraftMap.css so the layout pass knows each pill's size
const TAG_FONT = "600 10.5px -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif"
const TAG_LETTER_SPACING = 0.3 // px per character, from the CSS letter-spacing
const TAG_PAD_X = 7
const TAG_HEIGHT = 19

let measureCtx = null
const widthCache = new Map()

/**
 * Width of a pill for a label, in px
 *
 * @param {string} text - Label text
 * @returns {number} Width in px
 */
function pillWidth(text) {
  if (!widthCache.has(text)) {
    if (!measureCtx) {
      measureCtx = document.createElement('canvas').getContext('2d')
      measureCtx.font = TAG_FONT
    }
    const w = measureCtx.measureText(text).width + text.length * TAG_LETTER_SPACING
    widthCache.set(text, Math.ceil(w) + TAG_PAD_X * 2 + 2)
  }
  return widthCache.get(text)
}

const labelFor = ac => ac.callsign?.replace(/_+$/, '') || ac.icao24.toUpperCase()

/**
 * How far a contact has aged toward expiry, 0 (just heard) to 1 (about to expire)
 *
 * @param {Object} ac - Aircraft with a `lastseen` unix timestamp
 * @param {number} maxAgeMinutes - Age at which a contact expires
 * @param {number} now - Current unix time in seconds
 * @returns {number} Age ratio between 0 and 1
 */
const ageOf = (ac, maxAgeMinutes, now) =>
  ac.lastseen ? Math.min((now - ac.lastseen) / 60 / maxAgeMinutes, 1) : 0

/**
 * Callsign tags beside each plane, with a thin leader line back to the glyph.
 *
 * React owns one pill and one leader per aircraft; their positions are written
 * straight to the DOM from the map's move event, in the same frame Mapbox moves
 * its markers, so the tags never trail the planes during a pan.
 *
 * @param {Object} props - Component props
 * @param {Object} props.map - The mapbox-gl map instance, once loaded
 * @param {Array} props.aircraft - Aircraft with valid positions
 * @param {string|null} props.selectedId - icao24 of the selected aircraft
 * @param {number} props.maxAgeMinutes - Age at which a contact expires; fresher tags are placed first
 * @param {boolean} props.visible - Whether tags are shown at all
 * @returns {JSX.Element|null} The tag overlay
 */
function AircraftTags({ map, aircraft, selectedId, maxAgeMinutes, visible }) {
  const layerRef = useRef(null)

  useEffect(() => {
    const layer = layerRef.current
    if (!map || !visible || !layer) return undefined

    const pills = new Map()
    const leaders = new Map()
    layer.querySelectorAll('.tag').forEach(el => pills.set(el.dataset.id, el))
    layer.querySelectorAll('line').forEach(el => leaders.set(el.dataset.id, el))

    const place = () => {
      const canvas = map.getCanvas()
      const now = Math.floor(Date.now() / 1000)
      const items = aircraft.map(ac => {
        const label = labelFor(ac)
        const point = map.project([ac.longitude, ac.latitude])
        return {
          id: ac.icao24,
          label,
          cx: point.x,
          cy: point.y,
          w: pillWidth(label),
          h: TAG_HEIGHT,
          selected: ac.icao24 === selectedId,
          age: ageOf(ac, maxAgeMinutes, now),
        }
      })
      const placed = layoutTags(items, { width: canvas.clientWidth, height: canvas.clientHeight })
      const shown = new Set()
      for (const t of placed) {
        shown.add(t.id)
        const pill = pills.get(t.id)
        pill.hidden = false
        pill.style.width = `${t.w}px`
        pill.style.transform = `translate(${t.x}px, ${t.y}px)`
        const line = leaders.get(t.id)
        if (t.leader) {
          line.setAttribute('x1', t.leader.x1)
          line.setAttribute('y1', t.leader.y1)
          line.setAttribute('x2', t.leader.x2)
          line.setAttribute('y2', t.leader.y2)
          line.setAttribute('visibility', 'visible')
        } else {
          line.setAttribute('visibility', 'hidden')
        }
      }
      pills.forEach((pill, id) => {
        if (shown.has(id)) return
        pill.hidden = true
        leaders.get(id).setAttribute('visibility', 'hidden')
      })
    }

    place()
    map.on('move', place)
    map.on('resize', place)
    return () => {
      map.off('move', place)
      map.off('resize', place)
    }
  }, [map, aircraft, selectedId, maxAgeMinutes, visible])

  if (!visible) return null

  return (
    <div className="tag-layer" ref={layerRef} aria-hidden="true">
      <svg className="tag-leaders">
        {aircraft.map(ac => (
          <line
            key={ac.icao24}
            data-id={ac.icao24}
            className={ac.icao24 === selectedId ? 'selected' : ''}
            visibility="hidden"
          />
        ))}
      </svg>
      {aircraft.map(ac => (
        <div
          key={ac.icao24}
          data-id={ac.icao24}
          className={`tag ${ac.icao24 === selectedId ? 'selected' : ''}`}
          hidden
        >
          {labelFor(ac)}
        </div>
      ))}
    </div>
  )
}

AircraftTags.propTypes = {
  map: PropTypes.object,
  aircraft: PropTypes.array.isRequired,
  selectedId: PropTypes.string,
  maxAgeMinutes: PropTypes.number.isRequired,
  visible: PropTypes.bool.isRequired,
}

AircraftTags.defaultProps = {
  map: null,
  selectedId: null,
}

export default AircraftTags
