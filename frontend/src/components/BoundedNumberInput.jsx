import { useEffect, useState } from 'react'
import PropTypes from 'prop-types'
import { parseBounded } from '../parseBounded'

/**
 * A number input whose numeric value only changes when the typed text is a whole
 * number within range.
 *
 * Keeping the typed text in local state means clearing the box does not snap it
 * to "0" (which then reads back as "020" when you type), and callers never see
 * transient out-of-range values such as 0 while a number is being typed. On blur
 * the text is normalised to the committed value.
 *
 * @param {Object} props
 * @param {number} props.value - Committed value
 * @param {Function} props.onChange - Called with each new valid whole number
 * @param {number} props.min - Smallest accepted value
 * @param {number} props.max - Largest accepted value
 */
function BoundedNumberInput({ value, onChange, min, max, ...inputProps }) {
  const [text, setText] = useState(String(value))

  // Follow external changes to the value, but leave the text alone while it
  // still parses to the current value (e.g. "05" while the value is 5).
  useEffect(() => {
    if (parseBounded(text, min, max) !== value) setText(String(value))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <input
      {...inputProps}
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      value={text}
      onChange={e => {
        setText(e.target.value)
        const n = parseBounded(e.target.value, min, max)
        if (n !== null && n !== value) onChange(n)
      }}
      onBlur={() => setText(String(value))}
    />
  )
}

BoundedNumberInput.propTypes = {
  value: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  min: PropTypes.number.isRequired,
  max: PropTypes.number.isRequired,
}

export default BoundedNumberInput
