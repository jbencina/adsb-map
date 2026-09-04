import PropTypes from 'prop-types'

// Four bars of rising height, like a phone's reception indicator
const BAR_HEIGHTS = [5, 8, 11, 14]

/**
 * Reception indicator: `bars` of four are lit
 *
 * @param {Object} props - Component props
 * @param {number} props.bars - Bars to light, 0 to 4
 * @param {string} props.label - Accessible description of the level
 * @returns {JSX.Element} The indicator
 */
function SignalBars({ bars, label }) {
  return (
    <svg className="signal-bars" viewBox="0 0 21 14" role="img" aria-label={label}>
      {BAR_HEIGHTS.map((h, i) => (
        <rect
          key={h}
          className={i < bars ? 'lit' : undefined}
          x={i * 5.5}
          y={14 - h}
          width="4"
          height={h}
          rx="1"
        />
      ))}
    </svg>
  )
}

SignalBars.propTypes = {
  bars: PropTypes.number.isRequired,
  label: PropTypes.string.isRequired,
}

export default SignalBars
