"""Tests for the Server-Sent Events feed behind the map."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from adsb.api import create_app, parse_track_cursor, tracks_update
from adsb.models import Aircraft, AircraftPosition
from adsb.stream import sse_event, updates
from tests.helpers import serve


def read_event(lines) -> tuple[str, list | dict]:
    """Consume one SSE event from an iterator of lines; return (id, parsed data)."""
    event_id = None
    data = None
    for line in lines:
        if line == "":
            if data is not None:
                return event_id, json.loads(data)
            continue
        field, _, value = line.partition(":")
        value = value.lstrip(" ")
        if field == "id":
            event_id = value
        elif field == "data":
            data = value
    raise AssertionError("stream ended before a full event arrived")


def test_sse_event_wire_format():
    """One event: id, a fixed event name, one JSON data line, blank-line terminated."""
    assert sse_event({"a": 1}, 1700000000) == b'id: 1700000000\nevent: update\ndata: {"a": 1}\n\n'


def test_parse_track_cursor_ignores_what_the_browser_did_not_get_from_us():
    assert parse_track_cursor(None) is None
    assert parse_track_cursor("") is None
    assert parse_track_cursor("garbage") is None
    assert parse_track_cursor("5000") is None
    assert parse_track_cursor("5000:1700000000") == (5000, 1700000000)


@pytest.mark.asyncio
async def test_updates_threads_the_cursor_from_one_event_to_the_next():
    """The loader sees None first, then whatever cursor it last returned; ids follow."""
    seen = []

    def load(cursor):
        seen.append(cursor)
        return [cursor], str(int(cursor or 0) + 10)

    events = [e async for e in updates(load, cursor=None, interval=0, max_events=3)]

    assert seen == [None, "10", "20"]
    assert events[0] == b"id: 10\nevent: update\ndata: [null]\n\n"
    assert events[2].startswith(b"id: 30\n")


@pytest.mark.asyncio
async def test_updates_runs_load_off_the_event_loop():
    """Blocking SQLite work must not stall other connections."""
    import asyncio
    import threading

    loop_thread = threading.current_thread()
    seen = []

    def load(cursor):
        seen.append(threading.current_thread())
        return [], "1"

    async for _ in updates(load, cursor=None, interval=0, max_events=1):
        pass
    assert seen and seen[0] is not loop_thread
    assert asyncio.get_running_loop()  # still inside the loop


@pytest.fixture
def positions(test_session, aircraft):
    """Three positions for the sample aircraft: two old, one from now."""
    now = int(time.time())
    for ts in (now - 300, now - 200, now):
        test_session.add(
            AircraftPosition(
                aircraft_id=aircraft.id, timestamp=ts, latitude=40.7, longitude=-74.0, altitude=1
            )
        )
    test_session.commit()
    return now


def test_stream_routes_are_discoverable(test_db):
    routes = TestClient(create_app(test_db)).get("/api").json()["routes"]
    assert any(r.startswith("/api/stream/aircraft") for r in routes)
    assert any(r.startswith("/api/stream/tracks") for r in routes)


@pytest.mark.parametrize(
    "path",
    [
        "/api/stream/aircraft?interval=0",
        "/api/stream/aircraft?interval=61",
        "/api/stream/aircraft?max_age=0",
        "/api/stream/tracks?scope=",
        "/api/stream/tracks?scope=nothex",
        "/api/stream/tracks",
    ],
)
def test_stream_rejects_bad_parameters(test_db, path):
    """Validation answers before any streaming starts."""
    assert TestClient(create_app(test_db)).get(path).status_code == 422


def test_aircraft_stream_sends_the_window_every_tick(test_db, test_session, aircraft):
    """Each event is what /api/all would return; a client replaces, never merges."""
    now = int(time.time())
    test_session.add(Aircraft(icao24="old123", firstseen=now - 700, lastseen=now - 600, count=1))
    test_session.commit()

    with serve(create_app(test_db)) as base, httpx.Client(base_url=base, timeout=5) as client:
        with client.stream("GET", "/api/stream/aircraft?max_age=3600&interval=1") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache"
            lines = response.iter_lines()
            first_id, snapshot = read_event(lines)
            assert {a["icao24"] for a in snapshot} == {"abc123", "old123"}
            assert next(a for a in snapshot if a["icao24"] == "abc123")["callsign"] == "TEST123"
            assert int(first_id) >= now

            second_id, again = read_event(lines)
            assert int(second_id) >= int(first_id)
            assert {a["icao24"] for a in again} == {"abc123", "old123"}

        with client.stream("GET", "/api/stream/aircraft?interval=1") as response:
            _, window = read_event(response.iter_lines())
    assert [a["icao24"] for a in window] == ["abc123"]


def test_tracks_stream_snapshot_then_only_new_positions(test_db, test_session, aircraft, positions):
    """Event one is the window; the next tick carries just what was stored since."""
    now = positions
    with serve(create_app(test_db)) as base, httpx.Client(base_url=base, timeout=5) as client:
        with client.stream("GET", "/api/stream/tracks?scope=all&max_age=250&interval=1") as r:
            lines = r.iter_lines()
            first_id, snapshot = read_event(lines)
            assert [p["timestamp"] for p in snapshot["abc123"]] == [now - 200, now]
            newest = (
                test_session.query(AircraftPosition).order_by(AircraftPosition.id.desc()).first()
            )
            assert first_id == f"{newest.id}:{now}"

            test_session.add(
                AircraftPosition(
                    aircraft_id=aircraft.id,
                    timestamp=now + 1,
                    latitude=41.0,
                    longitude=-74.0,
                    altitude=2,
                )
            )
            test_session.commit()

            second_id, delta = read_event(lines)
            assert [p["timestamp"] for p in delta["abc123"]] == [now + 1]
            assert second_id == f"{newest.id + 1}:{now + 1}"

            third_id, quiet = read_event(lines)
    assert quiet == {}
    assert third_id == second_id


def test_tracks_stream_resumes_after_last_event_id(test_db, aircraft, positions):
    """A reconnecting browser gets only the positions stored after the last id it saw."""
    now = positions
    with serve(create_app(test_db)) as base, httpx.Client(base_url=base, timeout=5) as client:
        with client.stream("GET", "/api/stream/tracks?scope=all&max_age=3600") as r:
            first_id, _ = read_event(r.iter_lines())
        newest_id, _ = parse_track_cursor(first_id)
        # The browser last saw the row before the newest, stored at now - 200.
        headers = {"Last-Event-ID": f"{newest_id - 1}:{now - 200}"}
        with client.stream("GET", "/api/stream/tracks?scope=all", headers=headers) as r:
            resumed_id, resumed = read_event(r.iter_lines())
    assert [p["timestamp"] for p in resumed["abc123"]] == [now]
    assert resumed_id == first_id


def test_tracks_stream_for_one_aircraft(test_db, aircraft, positions):
    now = positions
    with serve(create_app(test_db)) as base, httpx.Client(base_url=base, timeout=5) as client:
        with client.stream("GET", "/api/stream/tracks?scope=ABC123&max_age=250") as r:
            _, snapshot = read_event(r.iter_lines())
        assert [p["timestamp"] for p in snapshot["abc123"]] == [now - 200, now]

        # An aircraft not heard yet is an empty update, not an error: it may appear later.
        with client.stream("GET", "/api/stream/tracks?scope=ffffff") as r:
            assert r.status_code == 200
            _, snapshot = read_event(r.iter_lines())
    assert snapshot == {}


def add_position(session, aircraft, timestamp):
    session.add(
        AircraftPosition(
            aircraft_id=aircraft.id, timestamp=timestamp, latitude=40.7, longitude=-74.0, altitude=1
        )
    )
    session.commit()


def test_tracks_update_never_loses_a_position_committed_mid_snapshot(
    test_db, test_session, aircraft, positions
):
    """A row landing between the cursor read and the snapshot is sent twice, not skipped."""
    from sqlalchemy import event

    now = positions
    landed = []

    def land_one(conn, cursor, statement, parameters, context, executemany):
        # The snapshot is the only positions query that joins aircraft; the cursor
        # read before it must already have happened.
        if "aircraft_positions" in statement and "JOIN" in statement and not landed:
            landed.append(True)
            with test_db.get_session() as other:
                add_position(other, aircraft, now + 1)

    event.listen(test_db.engine, "before_cursor_execute", land_one)
    try:
        with test_db.get_session() as session:
            points, cursor = tracks_update(session, None, now - 250)
    finally:
        event.remove(test_db.engine, "before_cursor_execute", land_one)

    assert landed
    assert [p.timestamp for p in points["abc123"]] == [now - 200, now, now + 1]
    with test_db.get_session() as session:
        again, _ = tracks_update(session, cursor, now - 250)
    assert [p.timestamp for p in again["abc123"]] == [now + 1]


def row_id(cursor: str) -> int:
    return parse_track_cursor(cursor)[0]


def test_tracks_update_starts_over_when_ids_are_reused(test_db, test_session, aircraft, positions):
    """After the table is emptied, new rows reuse ids; a stale cursor must not hide them."""
    now = positions
    with test_db.get_session() as session:
        _, cursor = tracks_update(session, None, now - 250)

    test_session.query(AircraftPosition).delete()
    test_session.commit()
    add_position(test_session, aircraft, now + 5)
    assert test_session.query(AircraftPosition).one().id < row_id(cursor)

    with test_db.get_session() as session:
        points, new_cursor = tracks_update(session, cursor, now - 250)
    assert [p.timestamp for p in points["abc123"]] == [now + 5]
    assert row_id(new_cursor) < row_id(cursor)


def test_tracks_update_starts_over_when_reused_ids_pass_the_cursor(
    test_db, test_session, aircraft, positions
):
    """The refill can overtake the old cursor within a tick; the cursor row's timestamp gives it away."""
    now = positions
    with test_db.get_session() as session:
        _, cursor = tracks_update(session, None, now - 250)

    test_session.query(AircraftPosition).delete()
    test_session.commit()
    for i in range(row_id(cursor) + 1):
        add_position(test_session, aircraft, now + 10 + i)
    assert test_session.query(AircraftPosition).count() > row_id(cursor)

    with test_db.get_session() as session:
        points, _ = tracks_update(session, cursor, now - 250)
    assert [p.timestamp for p in points["abc123"]] == [
        now + 10 + i for i in range(row_id(cursor) + 1)
    ]


def test_tracks_update_keeps_its_place_when_only_old_rows_are_cleaned(
    test_db, test_session, aircraft, positions
):
    """The ordinary cleanup deletes old positions; the cursor row survives and nothing is resent."""
    now = positions
    with test_db.get_session() as session:
        _, cursor = tracks_update(session, None, now - 250)

    test_session.query(AircraftPosition).filter(AircraftPosition.timestamp < now).delete()
    test_session.commit()
    add_position(test_session, aircraft, now + 1)

    with test_db.get_session() as session:
        points, _ = tracks_update(session, cursor, now - 250)
    assert [p.timestamp for p in points["abc123"]] == [now + 1]
