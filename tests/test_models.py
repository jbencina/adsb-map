"""Tests for database models."""

from adsb.models import Aircraft, AircraftMetadata, AircraftPosition


def test_create_aircraft(test_session):
    """Test creating an aircraft record."""
    aircraft = Aircraft(icao24="abc123", firstseen=1234567890, lastseen=1234567890, count=0)
    test_session.add(aircraft)
    test_session.commit()

    retrieved = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert retrieved is not None
    assert retrieved.icao24 == "abc123"
    assert retrieved.count == 0


def test_aircraft_with_position(test_session, aircraft):
    """Test creating aircraft with position data."""
    position = AircraftPosition(
        aircraft_id=aircraft.id,
        timestamp=1234567890,
        latitude=40.7,
        longitude=-74.0,
        altitude=10000,
    )
    test_session.add(position)
    test_session.commit()

    retrieved = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert len(retrieved.positions) == 1
    assert retrieved.positions[0].latitude == 40.7


def test_aircraft_with_metadata(test_session, aircraft):
    """Test creating aircraft with reception metadata."""
    metadata = AircraftMetadata(
        aircraft_id=aircraft.id,
        system_timestamp=1234567890.5,
        nanoseconds=500000000,
        rssi=-20.5,
        serial=123456,
    )
    test_session.add(metadata)
    test_session.commit()

    retrieved = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert len(retrieved.reception_metadata) == 1
    assert retrieved.reception_metadata[0].rssi == -20.5
    assert retrieved.reception_metadata[0].serial == 123456
