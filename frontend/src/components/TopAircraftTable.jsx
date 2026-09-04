import PropTypes from 'prop-types'
import { cleanCallsign } from '../aircraft'
import { formatCount, relativeTime } from '../stats'

/**
 * Three columns: aircraft, messages, last seen.
 *
 * @param {Object} props
 * @param {Array} props.rows - /api/stats top-list rows, best first
 * @param {number} props.now - Server time in seconds, for the relative ages
 */
function TopAircraftTable({ rows, now }) {
  if (rows.length === 0) return <p className="table-empty">Nothing heard yet</p>
  return (
    <table className="top-table">
      <thead>
        <tr>
          <th scope="col">Aircraft</th>
          <th scope="col" className="num">
            Messages
          </th>
          <th scope="col" className="num">
            Last seen
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const name = cleanCallsign(r.callsign) || r.registration || r.icao24.toUpperCase()
          const detail = [r.registration, r.typecode].filter(d => d && d !== name).join(' · ')
          return (
            <tr key={r.icao24}>
              <td>
                <span className="rank">{i + 1}</span>
                <span className="ident">
                  <span className="name">{name}</span>
                  <span className="detail">{detail || r.icao24}</span>
                </span>
              </td>
              <td className="num">{formatCount(r.messages)}</td>
              <td className="num" title={new Date(r.lastseen * 1000).toLocaleString()}>
                {relativeTime(r.lastseen, now)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

TopAircraftTable.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  now: PropTypes.number.isRequired,
}

export default TopAircraftTable
