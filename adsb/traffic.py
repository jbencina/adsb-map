"""
Traffic aggregates behind the history view.

Per-message rows (``aircraft_metadata``) are trimmed to an hour and arrive at
over a million an hour, so a day of history is kept as two small tables
instead: messages and distinct aircraft per minute, and messages per aircraft
per hour. The network client upserts deltas for every batch it decodes.
"""

import time

from sqlalchemy import Select, delete, desc, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from adsb.models import Aircraft, AircraftHourly, AircraftMetadata, TrafficMinute

TRAFFIC_RETENTION = 7 * 86400  # seconds of aggregate history kept


def minute_of(ts: float) -> int:
    """Epoch seconds floored to the minute."""
    return int(ts) // 60 * 60


def hour_of(ts: float) -> int:
    """Epoch seconds floored to the hour."""
    return int(ts) // 3600 * 3600


def record_batch(
    session: Session,
    minutes: dict[int, tuple[int, int]],
    hourly: dict[tuple[int, int], int],
) -> None:
    """
    Add one batch's traffic to the aggregates.

    Parameters
    ----------
    session : Session
        Open session; the caller commits
    minutes : dict
        ``{minute: (messages, aircraft)}``. ``messages`` is a delta and is
        added to the stored row; ``aircraft`` is the caller's count of
        distinct aircraft heard so far in that minute and replaces the stored
        value when larger. Within one process the caller keeps an exact set;
        across a restart the larger partial count wins.
    hourly : dict
        ``{(aircraft_id, hour): messages}`` deltas
    """
    if minutes:
        stmt = sqlite_insert(TrafficMinute).values(
            [{"minute": m, "messages": c, "aircraft": a} for m, (c, a) in minutes.items()]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TrafficMinute.minute],
            set_={
                "messages": TrafficMinute.messages + stmt.excluded.messages,
                # SQLite's two-argument scalar max()
                "aircraft": func.max(TrafficMinute.aircraft, stmt.excluded.aircraft),
            },
        )
        session.execute(stmt)
    if hourly:
        stmt = sqlite_insert(AircraftHourly).values(
            [{"aircraft_id": a, "hour": h, "messages": c} for (a, h), c in hourly.items()]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AircraftHourly.aircraft_id, AircraftHourly.hour],
            set_={"messages": AircraftHourly.messages + stmt.excluded.messages},
        )
        session.execute(stmt)


def purge_traffic(
    session: Session, now: float | None = None, retention: int = TRAFFIC_RETENTION
) -> int:
    """Delete aggregate rows older than ``retention`` seconds; returns rows removed."""
    cutoff = (time.time() if now is None else now) - retention
    removed = 0
    for model, column in (
        (TrafficMinute, TrafficMinute.minute),
        (AircraftHourly, AircraftHourly.hour),
    ):
        result = session.execute(
            delete(model).where(column < cutoff).execution_options(synchronize_session=False)
        )
        removed += result.rowcount
    return removed


def backfill_traffic(session: Session) -> bool:
    """
    Seed empty aggregates from whatever reception metadata is still retained.

    Runs once at backend start so an upgraded install shows its last hour of
    history straight away instead of an empty chart. Returns True if it wrote.
    """
    if session.execute(select(TrafficMinute.minute).limit(1)).first() is not None:
        return False
    if session.execute(select(func.count()).select_from(AircraftMetadata)).scalar() == 0:
        return False
    session.execute(
        text(
            "INSERT INTO traffic_minutes (minute, messages, aircraft) "
            "SELECT (CAST(system_timestamp AS INTEGER) / 60) * 60, COUNT(*), "
            "COUNT(DISTINCT aircraft_id) FROM aircraft_metadata GROUP BY 1"
        )
    )
    session.execute(
        text(
            "INSERT INTO aircraft_hourly (aircraft_id, hour, messages) "
            "SELECT aircraft_id, (CAST(system_timestamp AS INTEGER) / 3600) * 3600, COUNT(*) "
            "FROM aircraft_metadata GROUP BY 1, 2"
        )
    )
    return True


def buckets_stmt(since: int, interval: int) -> Select:
    """
    Per-bucket totals since ``since``: sum of messages, max of per-minute aircraft.

    ``minute`` is the table's INTEGER PRIMARY KEY, so the range is a rowid seek.
    Floor division (SQLAlchemy 2 renders plain ``/`` as true division).
    """
    bucket = (TrafficMinute.minute // interval) * interval
    return (
        select(
            bucket.label("start"),
            func.sum(TrafficMinute.messages),
            func.max(TrafficMinute.aircraft),
        )
        .where(TrafficMinute.minute >= since)
        .group_by(bucket)
        .order_by(bucket)
    )


def aircraft_seen_stmt(since_hour: int) -> Select:
    """Distinct aircraft with any traffic in hours at or after ``since_hour``."""
    return select(func.count(func.distinct(AircraftHourly.aircraft_id))).where(
        AircraftHourly.hour >= since_hour
    )


def top_window_stmt(since_hour: int, limit: int) -> Select:
    """``(Aircraft, messages)`` ranked by messages in hours at or after ``since_hour``."""
    total = func.sum(AircraftHourly.messages).label("messages")
    return (
        select(Aircraft, total)
        .join(AircraftHourly, AircraftHourly.aircraft_id == Aircraft.id)
        .where(AircraftHourly.hour >= since_hour)
        .group_by(Aircraft.id)
        .order_by(desc(total))
        .limit(limit)
    )


def top_lifetime_stmt(limit: int) -> Select:
    """Aircraft ranked by lifetime message count, via the ``count`` index."""
    return select(Aircraft).order_by(Aircraft.count.desc()).limit(limit)


def grid_bounds(now: int, window: int, interval: int) -> tuple[int, int]:
    """
    ``(since, end)`` of the bucket grid covering ``window`` seconds up to ``now``.

    ``end`` is the end of the interval that contains ``now``, so the last bucket
    is always the current, partial one, even when ``now`` sits exactly on a
    boundary (then it is the bucket that has just begun).
    """
    end = (now // interval + 1) * interval
    return end - window, end


def fill_buckets(rows, since: int, end: int, interval: int) -> list[dict]:
    """Expand sparse ``(start, messages, aircraft)`` rows into a full zero-filled grid."""
    by_start = {int(start): (int(m), int(a)) for start, m, a in rows}
    out = []
    for start in range(since, end, interval):
        messages, aircraft = by_start.get(start, (0, 0))
        out.append({"start": start, "messages": messages, "aircraft": aircraft})
    return out
