"""
Traffic aggregates behind the history view.

Per-message rows (``aircraft_metadata``) are trimmed to an hour and arrive at
over a million an hour, so a day of history is kept as two small tables
instead: messages and distinct aircraft per minute, and messages per aircraft
per hour. The network client upserts deltas for every batch it decodes.
"""

import time

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from adsb.models import AircraftHourly, AircraftMetadata, TrafficMinute

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
