"""Periodic console status line for `adsb start backend`.

The decoder thread and the API are silent when things are working, which makes
"is it receiving anything?" hard to answer from the terminal. A small daemon
thread prints one line per interval with feed health, decode rates, and how
many aircraft are currently tracked.
"""

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy import func

from adsb.database import Database
from adsb.models import Aircraft
from adsb.network import ADSBNetworkClient

logger = logging.getLogger("adsb.status")


def tracked_counts(database: Database) -> tuple[int, int]:
    """Return (aircraft currently tracked, of which have a position)."""
    with database.get_session() as session:
        total = session.query(func.count(Aircraft.id)).scalar() or 0
        with_pos = (
            session.query(func.count(Aircraft.id))
            .filter(Aircraft.latitude.isnot(None), Aircraft.longitude.isnot(None))
            .scalar()
            or 0
        )
    return total, with_pos


def format_status(
    *,
    feed: str | None,
    stats: dict | None,
    tracked: int,
    tracked_with_position: int,
    interval: float,
    now: float | None = None,
) -> str:
    """
    Render one status line.

    Parameters
    ----------
    feed : str or None
        Human-readable feed description (``host:port (beast)``) or None if no
        data source is configured
    stats : dict or None
        Output of :meth:`ADSBNetworkClient.snapshot`, or None without a feed
    tracked, tracked_with_position : int
        Aircraft rows in the database, and those with a decoded position
    interval : float
        Seconds covered by ``stats["interval"]`` (for the rate)
    now : float, optional
        Current time, injectable for tests
    """
    tracking = f"tracking {tracked} ac ({tracked_with_position} w/ pos)"
    if feed is None or stats is None:
        return f"no data source | {tracking}"

    now = time.time() if now is None else now
    last = stats["last_message_at"]
    if last is None:
        health = "no data yet"
    else:
        age = now - last
        health = "last msg <1s ago" if age < 1 else f"last msg {age:.0f}s ago"
        if age > 30:
            health += " (feed stalled?)"

    iv, total = stats["interval"], stats["total"]
    rate = iv["messages_received"] / interval if interval > 0 else 0.0
    window = (
        f"{iv['messages_received']:,} msgs ({rate:.0f}/s), "
        f"{iv['positions_decoded']:,} pos, {iv['aircraft_seen']} ac"
    )
    problems = []
    if iv["messages_invalid"]:
        problems.append(f"{iv['messages_invalid']} invalid")
    if iv["errors"]:
        problems.append(f"{iv['errors']} errors")
    if problems:
        window += " [" + ", ".join(problems) + "]"

    totals = (
        f"total {total['messages_processed']:,} msgs, "
        f"{total['positions_decoded']:,} pos, {total['aircraft_seen']} ac"
    )
    return f"feed {feed} | {health} | {interval:g}s: {window} | {tracking} | {totals}"


class StatusReporter:
    """
    Daemon thread that emits a status line every ``interval`` seconds.

    Parameters
    ----------
    database : Database
        For the tracked-aircraft counts
    client : ADSBNetworkClient or None
        Feed to report on; None renders a "no data source" line
    interval : float
        Seconds between lines
    emit : callable, optional
        Where lines go; defaults to the ``adsb.status`` logger
    """

    def __init__(
        self,
        database: Database,
        client: ADSBNetworkClient | None,
        interval: float = 10.0,
        emit: Callable[[str], None] | None = None,
    ):
        self.database = database
        self.client = client
        self.interval = interval
        self.emit = emit or logger.info
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="adsb-status", daemon=True)

    @property
    def feed(self) -> str | None:
        if self.client is None:
            return None
        return f"{self.client.host}:{self.client.port} ({self.client.datatype})"

    def tick(self) -> str:
        """Build and emit one status line (also used directly by tests)."""
        stats = self.client.snapshot() if self.client is not None else None
        tracked, with_pos = tracked_counts(self.database)
        line = format_status(
            feed=self.feed,
            stats=stats,
            tracked=tracked,
            tracked_with_position=with_pos,
            interval=self.interval,
        )
        self.emit(line)
        return line

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as e:  # never let a stats hiccup kill the reporter
                logger.warning("status line failed: %s", e)

    def start(self) -> "StatusReporter":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
