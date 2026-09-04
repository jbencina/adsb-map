"""Tests for FastAPI endpoints."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from adsb.api import (
    MAX_METADATA_RECORDS,
    aircraft_since_stmt,
    create_app,
    get_db,
    latest_metadata_stmt,
    track_stmt,
    tracks_stmt,
)
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition
from adsb.traffic import (
    buckets_stmt,
    hour_of,
    minute_of,
    record_batch,
    top_lifetime_stmt,
    top_window_stmt,
)
from tests.helpers import add_metadata, query_plan, statements_containing


@pytest.fixture
def client(test_db, test_session):
    """
    Create a test client for the API.

    Parameters
    ----------
    test_db : Database
        Test database fixture
    test_session : Session
        Test database session for setup

    Returns
    -------
    TestClient
        FastAPI test client
    """
    # Commit any pending changes before creating the app
    test_session.commit()
    app = create_app(test_db)
    return TestClient(app)


def test_api_root_endpoint(client):
    """Test the API discovery endpoint."""
    response = client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "routes" in data


def test_get_all_aircraft_empty(client):
    """Test getting all aircraft when database is empty."""
    response = client.get("/api/all")
    assert response.status_code == 200
    assert response.json() == []


def test_get_all_aircraft_with_data(test_session, client, aircraft):
    """Test getting all aircraft with data."""
    # Add some metadata
    for i in range(2):
        metadata = AircraftMetadata(
            aircraft_id=aircraft.id,
            system_timestamp=1234567890.0 + i,
            nanoseconds=500000000 + i,
            rssi=-20.0,
            serial=123456,
        )
        test_session.add(metadata)
    test_session.commit()

    response = client.get("/api/all")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["icao24"] == "abc123"
    assert data[0]["callsign"] == "TEST123"
    assert data[0]["latitude"] == 40.7
    assert data[0]["count"] == 5
    assert len(data[0]["metadata"]) == 2


def test_get_icao24_addresses(test_session, client, aircraft):
    """Test getting all ICAO addresses."""
    now = int(time.time())
    aircraft2 = Aircraft(icao24="def456", firstseen=now, lastseen=now, count=1)
    test_session.add(aircraft2)
    test_session.commit()

    response = client.get("/api/icao24")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert "abc123" in data
    assert "def456" in data


@pytest.fixture
def old_and_new(test_session, aircraft):
    """The sample aircraft plus one last seen ten minutes ago."""
    now = int(time.time())
    test_session.add(Aircraft(icao24="old123", firstseen=now - 700, lastseen=now - 600, count=1))
    test_session.commit()


def test_all_hides_aircraft_older_than_stale_timeout_by_default(client, old_and_new):
    """Without max_age, /api/all and /api/icao24 show only currently tracked aircraft."""
    assert [a["icao24"] for a in client.get("/api/all").json()] == ["abc123"]
    assert client.get("/api/icao24").json() == ["abc123"]


def test_all_max_age_widens_the_window(client, old_and_new):
    """max_age (seconds) brings older aircraft back instead of them being gone for good."""
    assert {a["icao24"] for a in client.get("/api/all?max_age=3600").json()} == {"abc123", "old123"}
    assert set(client.get("/api/icao24?max_age=3600").json()) == {"abc123", "old123"}
    assert [a["icao24"] for a in client.get("/api/all?max_age=300").json()] == ["abc123"]


def test_all_max_age_must_be_positive(client):
    assert client.get("/api/all?max_age=0").status_code == 422
    assert client.get("/api/all?max_age=-5").status_code == 422


def test_create_app_stale_timeout_sets_default_window(test_db, test_session, old_and_new):
    """The backend's --stale-timeout is the default max_age."""
    client = TestClient(create_app(test_db, stale_timeout=3600))
    assert {a["icao24"] for a in client.get("/api/all").json()} == {"abc123", "old123"}


def test_get_track_not_found(client):
    """Test getting track for non-existent aircraft."""
    response = client.get("/api/track?icao24=notfound")
    assert response.status_code == 200
    assert response.json() == []


def test_get_track_with_data(test_session, client, aircraft):
    """Test getting track with position data."""
    # Add positions
    for i in range(3):
        position = AircraftPosition(
            aircraft_id=aircraft.id,
            timestamp=1234567890 + i,
            latitude=40.7 + i * 0.1,
            longitude=-74.0 + i * 0.1,
            altitude=10000 + i * 100,
        )
        test_session.add(position)
    test_session.commit()

    response = client.get("/api/track?icao24=abc123")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["timestamp"] == 1234567890
    assert data[2]["latitude"] == pytest.approx(40.9, rel=0.01)


def test_get_track_with_since_filter(test_session, client, aircraft):
    """Test getting track with since timestamp filter."""
    # Add positions
    for i in range(5):
        position = AircraftPosition(
            aircraft_id=aircraft.id,
            timestamp=1234567890 + i,
            latitude=40.7,
            longitude=-74.0,
            altitude=10000,
        )
        test_session.add(position)
    test_session.commit()

    # Filter to only get positions since timestamp 1234567892
    response = client.get("/api/track?icao24=abc123&since=1234567892")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3  # Should only get positions at 1234567892, 1234567893, 1234567894


def test_get_tracks_groups_positions_by_icao24(test_session, test_db, client, aircraft):
    """/api/tracks returns every aircraft's positions since the cutoff, keyed by icao24."""
    now = int(time.time())
    other = Aircraft(icao24="def456", firstseen=now - 100, lastseen=now, count=1)
    test_session.add(other)
    test_session.commit()
    for i in range(3):
        for a, lat in ((aircraft, 40.7), (other, 51.5)):
            test_session.add(
                AircraftPosition(
                    aircraft_id=a.id,
                    timestamp=now - 20 + i,
                    latitude=lat + i * 0.1,
                    longitude=-74.0,
                    altitude=10000,
                )
            )
    test_session.commit()

    with statements_containing(test_db.engine, "aircraft_positions") as seen:
        response = client.get("/api/tracks?max_age=60")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"abc123", "def456"}
    assert [p["timestamp"] for p in data["abc123"]] == [now - 20, now - 19, now - 18]
    assert data["def456"][2]["latitude"] == pytest.approx(51.7)
    assert len(seen) == 1, seen


def test_get_tracks_since_is_incremental(test_session, client, aircraft):
    """`since` overrides the window so the map can ask only for what it has not seen."""
    now = int(time.time())
    for i in range(5):
        test_session.add(
            AircraftPosition(
                aircraft_id=aircraft.id,
                timestamp=now - 4 + i,
                latitude=40.7,
                longitude=-74.0,
            )
        )
    test_session.commit()

    data = client.get(f"/api/tracks?since={now - 1}").json()
    assert [p["timestamp"] for p in data["abc123"]] == [now - 1, now]


def test_get_tracks_omits_aircraft_without_positions(client, aircraft):
    """Mode-S-only aircraft have nothing to draw and do not appear at all."""
    assert client.get("/api/tracks").json() == {}


def test_get_sensors(test_session, client, aircraft):
    """Test getting sensor information."""
    # Add metadata with different serials
    metadata1 = AircraftMetadata(
        aircraft_id=aircraft.id,
        system_timestamp=1234567890.0,
        nanoseconds=500000000,
        serial=123456,
    )
    metadata2 = AircraftMetadata(
        aircraft_id=aircraft.id,
        system_timestamp=1234567891.0,
        nanoseconds=500000001,
        serial=789012,
    )
    test_session.add(metadata1)
    test_session.add(metadata2)
    test_session.commit()

    response = client.get("/api/sensors")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    serials = [sensor["serial"] for sensor in data]
    assert 123456 in serials
    assert 789012 in serials


def test_get_db_not_initialized(monkeypatch):
    """Test get_db raises error when database not initialized."""
    import adsb.api

    # Temporarily set db_instance to None
    monkeypatch.setattr(adsb.api, "db_instance", None)

    with pytest.raises(RuntimeError, match="Database not initialized"):
        get_db()


def test_create_app_with_network_client(test_db):
    """Test creating app with network client for lifespan handling."""
    # Mock network client
    mock_client = MagicMock()
    mock_client.stop = MagicMock()

    app = create_app(test_db, network_client=mock_client)

    assert app is not None
    assert app.title == "ADS-B API"


def test_lifespan_shutdown_with_network_client(test_db):
    """Test that lifespan event is properly configured with network client."""
    # Mock network client
    mock_client = MagicMock()
    mock_client.stop = MagicMock()

    app = create_app(test_db, network_client=mock_client)

    # Verify lifespan is configured
    assert app.router.lifespan_context is not None

    # Test client works normally
    client = TestClient(app)
    response = client.get("/api")
    assert response.status_code == 200
    client.close()


def test_lifespan_shutdown_without_network_client(test_db):
    """Test that lifespan event works without network client."""
    app = create_app(test_db, network_client=None)
    client = TestClient(app)

    # Make a request to ensure app starts
    response = client.get("/api")
    assert response.status_code == 200

    # Close the test client (triggers lifespan shutdown)
    # Should not raise any errors
    client.close()


def test_database_session_rollback_on_exception(test_db):
    """Test that database session rolls back on exception."""
    # Force an exception during session usage
    with pytest.raises(Exception):
        with test_db.get_session() as session:
            # Add an invalid operation that will cause an error
            session.execute("INVALID SQL STATEMENT")

    # Session should have been rolled back and closed
    # Next session should work fine
    with test_db.get_session() as session:
        count = session.query(Aircraft).count()
        assert count >= 0  # Should work


def test_max_metadata_records_constant(test_db):
    """Test that MAX_METADATA_RECORDS constant is used."""
    from adsb.api import MAX_METADATA_RECORDS

    assert MAX_METADATA_RECORDS == 4
    assert isinstance(MAX_METADATA_RECORDS, int)


@pytest.mark.parametrize(
    "endpoint,expected_status",
    [
        ("/api", 200),
        ("/api/all", 200),
        ("/api/icao24", 200),
        ("/api/track?icao24=abc123", 200),  # Returns empty list for not found
        ("/api/sensors", 200),
        ("/api/stats", 200),
    ],
)
def test_api_endpoints_exist(test_db, endpoint, expected_status):
    """Test that all expected API endpoints exist."""
    app = create_app(test_db)
    client = TestClient(app)

    response = client.get(endpoint)
    assert response.status_code == expected_status


def test_api_index_credits_aircraft_database(client):
    """ODC-By asks that the credit travel with the data, so /api carries it."""
    data = client.get("/api").json()
    credit = data["aircraft_db"]
    assert credit["source"] == "Mictronics aircraft database"
    assert credit["license"] == "ODC-By 1.0"
    assert credit["distributed_by"] == "wiedehopf/tar1090-db"
    assert credit["source_url"].startswith("https://")
    assert credit["license_url"].startswith("https://")


def test_backend_root_is_api_index(client):
    """The backend has no UI, so / explains the API instead of 404ing."""
    root = client.get("/")
    assert root.status_code == 200
    assert root.json() == client.get("/api").json()
    assert "/api/all" in root.json()["routes"]
    assert "adsb start frontend" in root.json()["map_ui"]

    assert client.get("/config.js").status_code == 404
    assert client.get("/api/nonexistent").status_code == 404


def test_backend_has_no_cors(client):
    """Browsers reach the API through `adsb start frontend`'s proxy, never directly."""
    response = client.get("/api", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_all_metadata_is_newest_first_and_capped(test_session, client):
    """Each aircraft carries its newest MAX_METADATA_RECORDS rows, newest first."""
    now = int(time.time())
    a1 = Aircraft(icao24="aaa111", firstseen=now, lastseen=now, count=1)
    a2 = Aircraft(icao24="bbb222", firstseen=now, lastseen=now, count=1)
    old = Aircraft(icao24="old333", firstseen=now - 900, lastseen=now - 900, count=1)
    test_session.add_all([a1, a2, old])
    test_session.flush()
    add_metadata(test_session, a1.id, [now - 3, now - 5, now - 1, now - 6, now - 2, now - 4])
    add_metadata(test_session, a2.id, [now - 7, now - 8])
    add_metadata(test_session, old.id, [now - 1])  # newest row of all, but out of window
    test_session.commit()

    data = client.get("/api/all?max_age=300").json()

    by_icao = {a["icao24"]: [m["system_timestamp"] for m in a["metadata"]] for a in data}
    assert set(by_icao) == {"aaa111", "bbb222"}
    assert by_icao["aaa111"] == [now - 1, now - 2, now - 3, now - 4]
    assert len(by_icao["aaa111"]) == MAX_METADATA_RECORDS
    assert by_icao["bbb222"] == [now - 7, now - 8]


def test_all_metadata_ties_break_on_newest_row(test_session, client):
    """Frames from one socket read share a timestamp; the latest-inserted rows must win."""
    now = int(time.time())
    a = Aircraft(icao24="tie111", firstseen=now, lastseen=now, count=1)
    test_session.add(a)
    test_session.flush()
    add_metadata(test_session, a.id, [now - 1.0] * 6)
    test_session.commit()

    data = client.get("/api/all?max_age=300").json()

    assert [m["nanoseconds"] for m in data[0]["metadata"]] == [5, 4, 3, 2]


def test_all_uses_bounded_number_of_queries(test_db, test_session, client):
    """Regression: /api/all once ran one unindexed metadata query per aircraft.

    On an overnight database (2M metadata rows, 75 aircraft in the window) that
    took 7 seconds per poll. The metadata must come from a single statement.
    """
    now = int(time.time())
    aircraft = [
        Aircraft(icao24=f"ac{i:04d}", firstseen=now, lastseen=now, count=1) for i in range(5)
    ]
    test_session.add_all(aircraft)
    test_session.flush()
    for i, a in enumerate(aircraft):
        # Interleave timestamps across aircraft so "newest" is not "highest id".
        add_metadata(test_session, a.id, [now - 1000 + j * 5 + i for j in range(10)])
    test_session.commit()

    with statements_containing(test_db.engine, "aircraft_metadata") as seen:
        response = client.get("/api/all?max_age=300")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    for a in data:
        assert [m["nanoseconds"] for m in a["metadata"]] == [9, 8, 7, 6]
    assert len(seen) == 1, seen


@pytest.mark.parametrize(
    ("stmt", "index"),
    [
        # An ORDER BY id on this one once made SQLite scan every aircraft ever seen.
        (aircraft_since_stmt(cutoff=0), "ix_aircraft_lastseen"),
        (latest_metadata_stmt(cutoff=0), "ix_aircraft_metadata_aircraft_id_system_timestamp"),
        (track_stmt(aircraft_id=1, since=0), "ix_aircraft_positions_aircraft_id_timestamp"),
        (tracks_stmt(since=0), "ix_aircraft_positions_timestamp"),
        # /api/stats: the minute table is keyed by its INTEGER PRIMARY KEY (rowid)
        (buckets_stmt(since=0, interval=900), "USING INTEGER PRIMARY KEY"),
        (top_window_stmt(since_hour=0, limit=10), "ix_aircraft_hourly_hour"),
    ],
    ids=[
        "aircraft_since",
        "latest_metadata",
        "track",
        "tracks",
        "stats_buckets",
        "stats_top_window",
    ],
)
def test_hot_statements_seek_their_index(test_db, stmt, index):
    """The statements behind /api/all and /api/track must seek, never scan, a table."""
    plan = query_plan(test_db.engine, stmt)

    assert any(index in step for step in plan), plan
    assert not any(step.startswith("SCAN ") for step in plan), plan


def test_stats_buckets_are_aligned_and_zero_filled(test_db, test_session):
    now = int(time.time())
    a = Aircraft(icao24="aaa111", firstseen=now - 7200, lastseen=now, callsign="ONE", count=50)
    b = Aircraft(
        icao24="bbb222", firstseen=now - 7200, lastseen=now - 60, callsign="TWO", count=900
    )
    test_session.add_all([a, b])
    test_session.commit()
    record_batch(
        test_session,
        {minute_of(now): (10, 2), minute_of(now - 120): (4, 5)},
        {(a.id, hour_of(now)): 12, (b.id, hour_of(now)): 2},
    )
    test_session.commit()
    client = TestClient(create_app(test_db))

    r = client.get("/api/stats?window=3600&interval=600&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert data["window"] == 3600 and data["interval"] == 600
    assert len(data["buckets"]) == 6
    assert all(bucket["start"] % 600 == 0 for bucket in data["buckets"])
    assert data["buckets"][-1]["start"] + 600 >= data["now"]
    assert sum(bucket["messages"] for bucket in data["buckets"]) == 14
    assert max(bucket["aircraft"] for bucket in data["buckets"]) == 5
    assert data["aircraft_seen"] == 2
    assert [t["icao24"] for t in data["top_window"]] == ["aaa111", "bbb222"]
    assert data["top_window"][0]["messages"] == 12
    assert [t["icao24"] for t in data["top_lifetime"]] == ["bbb222", "aaa111"]
    assert data["top_lifetime"][0]["messages"] == 900
    assert data["top_lifetime"][0]["callsign"] == "TWO"


def test_stats_rejects_interval_that_does_not_divide_window(client):
    assert client.get("/api/stats?window=3600&interval=700").status_code == 422


def test_stats_empty_database_returns_full_zero_grid(client):
    data = client.get("/api/stats").json()
    assert len(data["buckets"]) == 96
    assert data["top_window"] == [] and data["top_lifetime"] == []
    assert data["aircraft_seen"] == 0


def test_stats_uses_a_bounded_number_of_queries(test_db, test_session):
    """Four statements no matter how many aircraft or minutes are stored."""
    now = int(time.time())
    for i in range(5):
        test_session.add(Aircraft(icao24=f"c0000{i}", firstseen=now, lastseen=now, count=i))
    test_session.commit()
    client = TestClient(create_app(test_db))
    with statements_containing(test_db.engine, "SELECT") as seen:
        assert client.get("/api/stats").status_code == 200
    assert len(seen) == 4, seen


def test_lifetime_top_list_walks_the_count_index(test_db):
    """ORDER BY count DESC LIMIT n reads n index entries, not every aircraft ever seen."""
    plan = query_plan(test_db.engine, top_lifetime_stmt(limit=10))
    assert any("USING INDEX ix_aircraft_count" in step for step in plan), plan
    assert not any("TEMP B-TREE" in step for step in plan), plan
