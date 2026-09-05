"""Server-Sent Events behind the map's live feed.

A stream is one long-lived ``text/event-stream`` per subscription. Its first
event is the snapshot the matching REST endpoint would return for the age
window; what follows depends on the feed. Each connection runs its own query
loop: simple, and no more database work per tab than the polling it replaces,
minus the HTTP round trips.

The browser's ``EventSource`` reconnects by itself and sends the id of the last
event it saw, so a feed with a cursor can resume where the old stream stopped.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from starlette.concurrency import run_in_threadpool

#: Response headers for an event stream. Proxies (nginx in particular) buffer
#: responses by default, which would turn the stream back into a delayed poll.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

MEDIA_TYPE = "text/event-stream"


def sse_event(payload, event_id: str | int) -> bytes:
    """One ``update`` event carrying ``payload`` as JSON, tagged with ``event_id``."""
    return f"id: {event_id}\nevent: update\ndata: {json.dumps(payload)}\n\n".encode()


async def updates(
    load: Callable[[str | None], tuple[object, str]],
    *,
    cursor: str | None,
    interval: float,
    max_events: int | None = None,
) -> AsyncIterator[bytes]:
    """
    Yield one event per tick from a cursor-driven loader.

    ``load`` takes the cursor from the previous event (None for the first, which
    is the snapshot) and returns the payload plus the cursor to send as the
    event id. The cursor is an opaque string to this loop; a feed that can
    resume gives it meaning. ``load`` does blocking database work and runs in
    a worker thread.
    Starlette cancels this generator when the client goes away, so nothing here
    watches for disconnects. An event goes out even when nothing changed, so a
    quiet feed is distinguishable from a dead connection.

    Parameters
    ----------
    load : callable
        ``cursor -> (payload, next_cursor)``; the payload must be JSON-serialisable
    cursor : str, optional
        Where to start: None for a fresh snapshot, else a resumed event id
    interval : float
        Seconds between ticks
    max_events : int, optional
        Stop after this many events (tests only; a live stream never ends)
    """
    sent = 0
    while max_events is None or sent < max_events:
        payload, cursor = await run_in_threadpool(load, cursor)
        yield sse_event(payload, cursor)
        sent += 1
        if max_events is None or sent < max_events:
            await asyncio.sleep(interval)
