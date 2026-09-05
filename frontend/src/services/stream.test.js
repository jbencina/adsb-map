import { afterEach, beforeEach, describe, expect, test } from 'bun:test'
import { openStream } from './stream'

const realEventSource = globalThis.EventSource

/** A stand-in for the browser's EventSource that the tests drive by hand. */
class FakeEventSource {
  constructor(url) {
    this.url = url
    this.readyState = FakeEventSource.CONNECTING
    this.listeners = {}
    this.closed = false
    FakeEventSource.instances.push(this)
  }

  addEventListener(name, fn) {
    this.listeners[name] = fn
  }

  emit(name, data) {
    this.listeners[name]({ data })
  }

  fail(readyState) {
    this.readyState = readyState
    this.onerror?.({})
  }

  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }
}

FakeEventSource.CONNECTING = 0
FakeEventSource.OPEN = 1
FakeEventSource.CLOSED = 2
FakeEventSource.instances = []

beforeEach(() => {
  FakeEventSource.instances = []
  globalThis.EventSource = FakeEventSource
})

afterEach(() => {
  globalThis.EventSource = realEventSource
})

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

describe('openStream', () => {
  test('opens the url and hands each update to the caller parsed', () => {
    const updates = []
    openStream('/api/stream/aircraft?interval=1', { onUpdate: d => updates.push(d) })

    const [source] = FakeEventSource.instances
    expect(source.url).toBe('/api/stream/aircraft?interval=1')
    source.emit('update', '[{"icao24":"abc123"}]')
    source.emit('update', '[]')

    expect(updates).toEqual([[{ icao24: 'abc123' }], []])
  })

  test('closing stops the stream', () => {
    const close = openStream('/x', { onUpdate: () => {} })
    close()
    expect(FakeEventSource.instances[0].closed).toBe(true)
  })

  test('reports a dropped connection but leaves the browser to retry it', () => {
    const errors = []
    openStream('/x', { onUpdate: () => {}, onError: e => errors.push(e) })

    FakeEventSource.instances[0].fail(FakeEventSource.CONNECTING)

    expect(errors).toHaveLength(1)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  test('reopens after the browser gives up, which it does on a 502 from the proxy', async () => {
    const errors = []
    openStream('/x', { onUpdate: () => {}, onError: e => errors.push(e) }, { retryDelayMs: 1 })

    FakeEventSource.instances[0].fail(FakeEventSource.CLOSED)
    await sleep(5)

    expect(FakeEventSource.instances).toHaveLength(2)
    expect(FakeEventSource.instances[1].url).toBe('/x')
  })

  test('does not reopen once closed by the caller', async () => {
    const close = openStream('/x', { onUpdate: () => {} }, { retryDelayMs: 1 })
    FakeEventSource.instances[0].fail(FakeEventSource.CLOSED)
    close()
    await sleep(5)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  test('closing after a reopen closes the new stream, not the dead one', async () => {
    const close = openStream('/x', { onUpdate: () => {} }, { retryDelayMs: 1 })
    FakeEventSource.instances[0].fail(FakeEventSource.CLOSED)
    await sleep(5)
    close()
    expect(FakeEventSource.instances[1].closed).toBe(true)
  })

  test('a malformed event is an error, not a crash', () => {
    const errors = []
    openStream('/x', { onUpdate: () => {}, onError: e => errors.push(e) })
    FakeEventSource.instances[0].emit('update', 'not json')
    expect(errors).toHaveLength(1)
  })
})
