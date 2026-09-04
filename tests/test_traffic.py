"""Tests for the per-minute / per-aircraft-hour traffic aggregates."""

import time

from sqlalchemy import inspect, select

from adsb.models import Aircraft, AircraftHourly, TrafficMinute
from adsb.traffic import (
    TRAFFIC_RETENTION,
    backfill_traffic,
    fill_buckets,
    hour_of,
    minute_of,
    purge_traffic,
    record_batch,
)
from tests.helpers import add_metadata


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


def test_backfill_seeds_minutes_and_hours_from_metadata(test_db, aircraft):
    base = 1_788_556_200.0  # on a minute boundary
    with test_db.get_session() as session:
        add_metadata(session, aircraft.id, [base, base + 10.5, base + 61])
    with test_db.get_session() as session:
        assert backfill_traffic(session) is True
    with test_db.get_session() as session:
        rows = {r.minute: (r.messages, r.aircraft) for r in session.query(TrafficMinute)}
        assert rows == {int(base): (2, 1), int(base) + 60: (1, 1)}
        hourly = session.get(AircraftHourly, (aircraft.id, hour_of(base)))
        assert hourly.messages == 3


def test_backfill_is_a_no_op_when_aggregates_exist(test_db, aircraft):
    with test_db.get_session() as session:
        add_metadata(session, aircraft.id, [1_788_556_200.0])
        record_batch(session, {1_700_000_000: (9, 9)}, {})
    with test_db.get_session() as session:
        assert backfill_traffic(session) is False
        assert session.query(TrafficMinute).count() == 1


def test_backfill_is_a_no_op_without_metadata(test_db):
    with test_db.get_session() as session:
        assert backfill_traffic(session) is False


def test_fill_buckets_zero_fills_and_aligns():
    rows = [(1200, 5, 2)]  # (bucket start, messages, aircraft)
    out = fill_buckets(rows, since=600, end=1800, interval=600)
    assert out == [
        {"start": 600, "messages": 0, "aircraft": 0},
        {"start": 1200, "messages": 5, "aircraft": 2},
    ]
