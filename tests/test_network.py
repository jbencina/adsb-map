"""Tests for network client."""

import time
from unittest.mock import patch

from adsb.models import Aircraft
from adsb.network import ADSBNetworkClient, start_network_client


def test_network_client_initialization(test_db):
    """Test network client initialization."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        stale_timeout=60,
        cleanup_interval=30,
        lat_ref=40.7,
        lon_ref=-74.0,
    )

    assert client.database == test_db
    assert client.stale_timeout == 60
    assert client.cleanup_interval == 30
    assert client.lat_ref == 40.7
    assert client.lon_ref == -74.0


def test_network_client_stop(test_db):
    """Test network client stop method."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
    )

    # Should set stop event
    client.stop()
    assert client._stop_event.is_set()


def test_handle_messages(test_db):
    """Test message handling."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        lat_ref=40.7,
        lon_ref=-74.0,
    )

    # Mock valid ADS-B message
    messages = [
        ("8D4840D6202CC371C32CE0576098", time.time()),
    ]

    # Process messages
    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode", return_value=1):
                    with patch("pyModeS.adsb.callsign", return_value="TEST123"):
                        client.handle_messages(messages)

    # Check aircraft was created
    with test_db.get_session() as session:
        aircraft = session.query(Aircraft).filter_by(icao24="4840d6").first()
        assert aircraft is not None
        assert aircraft.callsign == "TEST123"


def test_handle_messages_invalid_length(test_db):
    """Test handling messages with invalid length."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
    )

    # Messages with invalid length
    messages = [
        ("8D4840", time.time()),  # Too short
        ("8D4840D6202CC371C32CE0576098FFFF", time.time()),  # Too long
    ]

    # Should skip these messages
    client.handle_messages(messages)

    # No aircraft should be created
    with test_db.get_session() as session:
        count = session.query(Aircraft).count()
        assert count == 0


def test_handle_messages_with_cleanup(test_db):
    """Test message handling with periodic cleanup."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        stale_timeout=1,
        cleanup_interval=0,  # Force cleanup every time
    )

    # Create old aircraft
    with test_db.get_session() as session:
        old_aircraft = Aircraft(
            icao24="old123",
            firstseen=int(time.time()) - 100,
            lastseen=int(time.time()) - 100,
            count=1,
        )
        session.add(old_aircraft)

    # Process a message (should trigger cleanup)
    messages = [
        ("8D4840D6202CC371C32CE0576098", time.time()),
    ]

    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode", return_value=1):
                    client.handle_messages(messages)

    # Old aircraft should be removed
    with test_db.get_session() as session:
        old = session.query(Aircraft).filter_by(icao24="old123").first()
        assert old is None

        # New aircraft should exist
        new = session.query(Aircraft).filter_by(icao24="4840d6").first()
        assert new is not None


def test_start_network_client(test_db):
    """Test starting network client in background thread."""
    # Mock the TcpClient.run method to prevent actual network connection
    with patch.object(ADSBNetworkClient, "run") as mock_run:
        client = start_network_client(
            host="localhost",
            port="30005",
            rawtype="beast",
            database=test_db,
            stale_timeout=60,
            lat_ref=40.7,
            lon_ref=-74.0,
        )

        assert isinstance(client, ADSBNetworkClient)
        assert client.lat_ref == 40.7
        assert client.lon_ref == -74.0

        # Give thread time to start
        time.sleep(0.1)

        # run should have been called (thread started)
        assert mock_run.called


def test_network_client_with_decoder_exception(test_db):
    """Test network client handling decoder exceptions."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
    )

    # Mock message that causes decoder exception
    messages = [
        ("8D4840D6202CC371C32CE0576098", time.time()),
    ]

    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode") as mock_tc:
                    mock_tc.side_effect = Exception("Decoder error")
                    # Should handle exception gracefully
                    client.handle_messages(messages)

    # Aircraft should still be created (before exception)
    with test_db.get_session() as session:
        aircraft = session.query(Aircraft).filter_by(icao24="4840d6").first()
        assert aircraft is not None


def test_handle_empty_messages(test_db):
    """Test handling empty message list."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
    )

    # Should handle empty list gracefully
    client.handle_messages([])

    # No aircraft should be created
    with test_db.get_session() as session:
        count = session.query(Aircraft).count()
        assert count == 0


def test_network_client_cleanup_interval(test_db):
    """Test that cleanup doesn't run too frequently."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        stale_timeout=60,
        cleanup_interval=100,  # Long interval
    )

    # Create old aircraft
    with test_db.get_session() as session:
        old_aircraft = Aircraft(
            icao24="old123",
            firstseen=int(time.time()) - 200,
            lastseen=int(time.time()) - 200,
            count=1,
        )
        session.add(old_aircraft)

    # Process a message (should NOT trigger cleanup due to interval)
    messages = [
        ("8D4840D6202CC371C32CE0576098", time.time()),
    ]

    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode", return_value=1):
                    client.handle_messages(messages)

    # Old aircraft should still exist (cleanup didn't run)
    with test_db.get_session() as session:
        old = session.query(Aircraft).filter_by(icao24="old123").first()
        assert old is not None
