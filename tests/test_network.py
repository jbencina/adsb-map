"""Tests for network client."""

import math
import time
from unittest.mock import patch

import pytest

from adsb.models import Aircraft, AircraftMetadata
from adsb.network import ADSBNetworkClient, beast_signal_to_dbfs, start_network_client


def test_network_client_initialization(test_db):
    """Test network client initialization."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        lat_ref=40.7,
        lon_ref=-74.0,
    )

    assert client.database == test_db
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


def test_handle_messages_keeps_stale_aircraft(test_db):
    """Aircraft that age out are retained for offline analysis, never deleted."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
    )

    with test_db.get_session() as session:
        old_aircraft = Aircraft(
            icao24="old123",
            firstseen=int(time.time()) - 100,
            lastseen=int(time.time()) - 100,
            count=1,
        )
        session.add(old_aircraft)

    messages = [
        ("8D4840D6202CC371C32CE0576098", time.time()),
    ]

    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode", return_value=1):
                    client.handle_messages(messages)

    with test_db.get_session() as session:
        assert {a.icao24 for a in session.query(Aircraft).all()} == {"old123", "4840d6"}


def test_start_network_client(test_db):
    """Test starting network client in background thread."""
    # Mock the TcpClient.run method to prevent actual network connection
    with patch.object(ADSBNetworkClient, "run") as mock_run:
        client = start_network_client(
            host="localhost",
            port="30005",
            rawtype="beast",
            database=test_db,
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


LONG_MSG = "8D4840D6202CC371C32CE0576098"  # DF17, 14 bytes
SHORT_MSG = "5D484BA898F8C6"  # DF11, 7 bytes


def beast_frame(msgtype: int, data_hex: str, signal: int = 0x80) -> bytes:
    """Build an escaped Beast frame: <esc> type, 6 ts bytes, signal, payload."""
    body = bytes([msgtype]) + bytes(6) + bytes([signal]) + bytes.fromhex(data_hex)
    return b"\x1a" + body.replace(b"\x1a", b"\x1a\x1a")


def make_client(test_db):
    return ADSBNetworkClient(host="localhost", port=30005, rawtype="beast", database=test_db)


def test_read_beast_buffer_long_frame_keeps_rssi(test_db):
    """A long frame yields (msg, ts, rssi) with rssi converted to dBFS."""
    client = make_client(test_db)
    client.buffer = list(beast_frame(0x33, LONG_MSG, signal=0x80))

    rows = client.read_beast_buffer()

    assert len(rows) == 1
    msg, ts, rssi = rows[0]
    assert msg == LONG_MSG
    assert isinstance(ts, float)
    assert rssi == pytest.approx(20 * math.log10(0x80 / 255))


def test_read_beast_buffer_short_frame(test_db):
    """A short frame yields a 14-character message."""
    client = make_client(test_db)
    client.buffer = list(beast_frame(0x32, SHORT_MSG))

    rows = client.read_beast_buffer()

    assert [row[0] for row in rows] == [SHORT_MSG]


def test_read_beast_buffer_zero_signal_is_none(test_db):
    """A signal byte of 0x00 (no signal info) yields rssi None, not an error."""
    client = make_client(test_db)
    client.buffer = list(beast_frame(0x33, LONG_MSG, signal=0x00))

    rows = client.read_beast_buffer()

    assert len(rows) == 1
    assert rows[0][2] is None


def test_read_beast_buffer_unescapes_0x1a(test_db):
    """An escaped 0x1A 0x1A inside the payload becomes a literal 0x1A."""
    client = make_client(test_db)
    msg = "8D1A40D6202CC371C32CE0576098"
    client.buffer = list(beast_frame(0x33, msg))

    rows = client.read_beast_buffer()

    assert [row[0] for row in rows] == [msg]


def test_read_beast_buffer_skips_mode_ac_and_truncated(test_db):
    """Mode-AC frames and truncated frames are dropped."""
    client = make_client(test_db)
    truncated = beast_frame(0x33, LONG_MSG[:10])
    client.buffer = list(beast_frame(0x31, "1234") + truncated + beast_frame(0x33, LONG_MSG))

    rows = client.read_beast_buffer()

    assert [row[0] for row in rows] == [LONG_MSG]


def test_read_beast_buffer_retains_partial_frame(test_db):
    """A partial trailing frame is kept and completed on the next read."""
    client = make_client(test_db)
    frame = beast_frame(0x33, LONG_MSG)
    client.buffer = list(frame[:12])

    assert client.read_beast_buffer() == []
    assert client.buffer  # partial frame retained

    client.buffer.extend(frame[12:])
    rows = client.read_beast_buffer()

    assert [row[0] for row in rows] == [LONG_MSG]
    assert client.buffer == []


def test_handle_messages_stores_rssi(test_db):
    """A (msg, ts, rssi) row stores rssi on the reception metadata."""
    client = ADSBNetworkClient(
        host="localhost",
        port=30005,
        rawtype="beast",
        database=test_db,
        lat_ref=40.7,
        lon_ref=-74.0,
    )

    client.handle_messages([(LONG_MSG, time.time(), -12.5)])

    with test_db.get_session() as session:
        metadata = session.query(AircraftMetadata).one()
        assert metadata.rssi == -12.5


ESCAPED_MSG = "8D1A40D6202CC371C32CE057601A"  # 0x1A in payload, including the last byte


@pytest.mark.parametrize("split", range(1, len(beast_frame(0x33, ESCAPED_MSG, signal=0x1A))))
def test_read_beast_buffer_survives_any_split(test_db, split):
    """A frame split at any byte boundary across two reads is decoded intact."""
    client = make_client(test_db)
    frame = beast_frame(0x33, ESCAPED_MSG, signal=0x1A)

    client.buffer = list(frame[:split])
    rows = client.read_beast_buffer()
    client.buffer.extend(frame[split:])
    rows += client.read_beast_buffer()

    assert [(row[0], row[2]) for row in rows] == [(ESCAPED_MSG, beast_signal_to_dbfs(0x1A))]
    assert client.buffer == []
