/**
 * One long-lived subscription to a backend event stream.
 *
 * The browser's EventSource does the heavy lifting: it reconnects by itself
 * when a connection drops and sends the last event id it saw, so a stream
 * with a cursor resumes where it stopped. What it will not do is retry after
 * a non-200 reply, and that is exactly what the UI proxy answers while the
 * backend is down, so a closed stream is reopened here on a timer.
 */

/** Wait between reopen attempts once the browser has given up. */
export const RETRY_DELAY_MS = 3000

/**
 * Subscribe to `update` events at a URL until the returned function is called.
 *
 * @param {string} url - Stream URL
 * @param {Object} handlers
 * @param {function(any): void} handlers.onUpdate - Called with each event's parsed JSON
 * @param {function(Error): void} [handlers.onError] - Called on a dropped or refused connection
 * @param {Object} [options]
 * @param {number} [options.retryDelayMs] - Delay before reopening a stream the browser closed
 * @returns {function(): void} Closes the stream
 */
export function openStream(url, { onUpdate, onError }, { retryDelayMs = RETRY_DELAY_MS } = {}) {
  let source = null
  let retry = null
  let closed = false

  const connect = () => {
    source = new EventSource(url)
    source.addEventListener('update', event => {
      try {
        onUpdate(JSON.parse(event.data))
      } catch (err) {
        onError?.(err)
      }
    })
    source.onerror = () => {
      onError?.(new Error('Lost the connection to the backend'))
      if (source.readyState === EventSource.CLOSED && !closed) {
        retry = setTimeout(connect, retryDelayMs)
      }
    }
  }

  connect()
  return () => {
    closed = true
    clearTimeout(retry)
    source.close()
  }
}
