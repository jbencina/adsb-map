"""Tests for FastAPI endpoints."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from adsb.api import create_app, get_db
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition


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
    aircraft2 = Aircraft(icao24="def456", firstseen=1234567890, lastseen=1234567890, count=1)
    test_session.add(aircraft2)
    test_session.commit()

    response = client.get("/api/icao24")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert "abc123" in data
    assert "def456" in data


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


def test_cors_origins_in_dev_mode(test_db, monkeypatch):
    """CORS middleware is registered when frontend is not bundled (dev mode)."""
    import adsb.api

    monkeypatch.setattr(adsb.api, "frontend_is_bundled", lambda: False)
    app = create_app(test_db)
    client = TestClient(app)

    response = client.get("/api", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_spa_fallback_when_bundled(test_db, monkeypatch, tmp_path):
    """When adsb/static/index.html exists, GET / serves the SPA and /api/foo returns 404."""
    import adsb.api

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html>spa</html>")

    monkeypatch.setattr(adsb.api, "STATIC_DIR", static_dir)
    monkeypatch.setattr(adsb.api, "frontend_is_bundled", lambda: True)

    app = create_app(test_db)
    client = TestClient(app)

    spa = client.get("/")
    assert spa.status_code == 200
    assert "spa" in spa.text

    assert client.get("/api/nonexistent").status_code == 404


def test_config_js_available_in_dev_mode(test_db, monkeypatch):
    """/config.js is registered even when the frontend is not bundled, so the Vite
    proxy in dev doesn't 404 and the SPA's <script src='/config.js'> always works."""
    import adsb.api

    monkeypatch.setenv("MAPBOX_TOKEN", "pk.test_token_value")
    monkeypatch.setattr(adsb.api, "frontend_is_bundled", lambda: False)

    app = create_app(test_db)
    client = TestClient(app)

    response = client.get("/config.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "window.APP_CONFIG" in response.text
    assert "pk.test_token_value" in response.text


def test_config_js_available_in_bundled_mode(test_db, monkeypatch, tmp_path):
    """/config.js works in bundled mode and reads MAPBOX_TOKEN from the environment."""
    import adsb.api

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html>spa</html>")

    monkeypatch.setenv("MAPBOX_TOKEN", "pk.bundled_token")
    monkeypatch.setattr(adsb.api, "STATIC_DIR", static_dir)
    monkeypatch.setattr(adsb.api, "frontend_is_bundled", lambda: True)

    app = create_app(test_db)
    client = TestClient(app)

    response = client.get("/config.js")
    assert response.status_code == 200
    assert "pk.bundled_token" in response.text

    assert client.get("/api/nonexistent").status_code == 404


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
    ],
)
def test_api_endpoints_exist(test_db, endpoint, expected_status):
    """Test that all expected API endpoints exist."""
    app = create_app(test_db)
    client = TestClient(app)

    response = client.get(endpoint)
    assert response.status_code == expected_status


def test_frontend_missing_page_when_not_bundled(test_db, monkeypatch):
    """An unbuilt frontend serves an explanatory 503 at / instead of a bare 404."""
    import adsb.api

    monkeypatch.setattr(adsb.api, "frontend_is_bundled", lambda: False)
    app = create_app(test_db)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "just build" in response.text

    # The API must stay honest rather than being shadowed by the help page.
    assert client.get("/api").status_code == 200
    assert client.get("/api/nonexistent").status_code == 404
