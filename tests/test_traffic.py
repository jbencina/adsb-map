"""Tests for the per-minute / per-aircraft-hour traffic aggregates."""

import time

from sqlalchemy import inspect, select

from adsb.models import Aircraft, AircraftHourly, TrafficMinute
from adsb.traffic import (
    TRAFFIC_RETENTION,
    hour_of,
    minute_of,
    purge_traffic,
    record_batch,
)


def test_minute_and_hour_floor_to_integer_seconds():
    assert minute_of(1788556190.73) == 1788556140
    assert hour_of(1788556190.73) == 1788555600


def test_record_batch_accumulates_messages_and_keeps_max_aircraft(test_db, aircraft):
    minute = minute_of(time.time())
    hour = hour_of(time.time())
    with test_db.get_session() as session:
        record_batch(session, {minute: (5, 3)}, {(aircraft.id, hour): 5})
    with test_db.get_session() as session:
        record_batch(session, {minute: (2, 2)}, {(aircraft.id, hour): 2})
    with test_db.get_session() as session:
        row = session.get(TrafficMinute, minute)
        assert (row.messages, row.aircraft) == (7, 3)
        hourly = session.get(AircraftHourly, (aircraft.id, hour))
        assert hourly.messages == 7


def test_record_batch_with_nothing_is_a_no_op(test_db):
    with test_db.get_session() as session:
        record_batch(session, {}, {})
        assert session.execute(select(TrafficMinute)).all() == []


def test_purge_traffic_drops_rows_older_than_retention(test_db, aircraft):
    now = time.time()
    old = minute_of(now - TRAFFIC_RETENTION - 120)
    fresh = minute_of(now)
    with test_db.get_session() as session:
        record_batch(
            session,
            {old: (1, 1), fresh: (1, 1)},
            {(aircraft.id, hour_of(old)): 1, (aircraft.id, hour_of(now)): 1},
        )
    with test_db.get_session() as session:
        removed = purge_traffic(session, now=now)
        assert removed == 2
        assert [r.minute for r in session.execute(select(TrafficMinute)).scalars()] == [fresh]
        hours = [r.hour for r in session.execute(select(AircraftHourly)).scalars()]
        assert hours == [hour_of(now)]


def test_aircraft_count_is_indexed(test_db):
    names = {ix["name"] for ix in inspect(test_db.engine).get_indexes("aircraft")}
    assert "ix_aircraft_count" in names
    assert Aircraft.count.property.columns[0].index is True
