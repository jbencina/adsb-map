import { useEffect, useState } from 'react'
import PropTypes from 'prop-types'
import { layoutTags } from './tagLayout'

// Must match .tag in AircraftMap.css so the layout pass knows each pill's size
const TAG_FONT = "600 10.5px -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif"
const TAG_LETTER_SPACING = 0.3 // px per character, from the CSS letter-spacing
const TAG_PAD_X = 7
const TAG_HEIGHT = 19

let measureCtx = null

/**
 * Width of a label in px, as the pill will render it
 *
 * @param {string} text - Label text
 * @returns {number} Width in px
 */
function measure(text) {
  if (!measureCtx) {
    measureCtx = document.createElement('canvas').getContext('2d')
    measureCtx.font = TAG_FONT
  }
  return Math.ceil(measureCtx.measureText(text).width + text.length * TAG_LETTER_SPACING)
}

/**
 * Callsign tags beside each plane, with a thin leader line back to the glyph.
 *
 * Positions are recomputed in screen space on every map move and data refresh, so
 * tags follow their planes and never overlap one another or another plane.
 *
 * @param {Object} props - Component props
 * @param {Object} props.map - The mapbox-gl map instance, once loaded
 * @param {Array} props.aircraft - Aircraft with valid positions
 * @param {string|null} props.selectedId - icao24 of the selected aircraft
 * @param {number} props.maxAgeMinutes - Age at which a contact expires, for the fade
 * @param {boolean} props.visible - Whether tags are shown at all
 * @returns {JSX.Element|null} The tag overlay
 */
function AircraftTags({ map, aircraft, selectedId, maxAgeMinutes, visible }) {
  const [tags, setTags] = useState([])

  useEffect(() => {
    if (!map || !visible) {
      setTags([])
      return undefined
    }
    const compute = () => {
      const canvas = map.getCanvas()
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const now = Math.floor(Date.now() / 1000)
      const items = aircraft.map(ac => {
        const label = ac.callsign?.replace(/_+$/, '') || ac.icao24.toUpperCase()
        const point = map.project([ac.longitude, ac.latitude])
        const age = ac.lastseen ? Math.min((now - ac.lastseen) / 60 / maxAgeMinutes, 1) : 0
        return {
          id: ac.icao24,
          label,
          cx: point.x,
          cy: point.y,
          w: measure(label) + TAG_PAD_X * 2 + 2,
          h: TAG_HEIGHT,
          selected: ac.icao24 === selectedId,
          age,
        }
      })
      setTags(layoutTags(items, { width, height }))
    }
    compute()
    map.on('move', compute)
    map.on('resize', compute)
    return () => {
      map.off('move', compute)
      map.off('resize', compute)
    }
  }, [map, aircraft, selectedId, maxAgeMinutes, visible])

  if (!visible || tags.length === 0) return null

  return (
    <div className="tag-layer" aria-hidden="true">
      <svg className="tag-leaders">
        {tags.map(
          t =>
            t.leader && (
              <line
                key={t.id}
                className={t.selected ? 'selected' : ''}
                x1={t.leader.x1}
                y1={t.leader.y1}
                x2={t.leader.x2}
                y2={t.leader.y2}
              />
            )
        )}
      </svg>
      {tags.map(t => (
        <div
          key={t.id}
          className={`tag ${t.selected ? 'selected' : ''}`}
          style={{ transform: `translate(${t.x}px, ${t.y}px)`, width: t.w, '--age': t.age }}
        >
          {t.label}
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
