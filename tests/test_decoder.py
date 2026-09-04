"""Tests for ADS-B decoder."""

import time
from unittest.mock import patch

from adsb.decoder import ADSBDecoder
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition


def test_decoder_initialization(test_session):
    """Test decoder initialization."""
    decoder = ADSBDecoder(test_session)
    assert decoder.session == test_session
    assert decoder.stale_timeout == 60


def test_process_valid_adsb_message(test_session):
    """Test processing a valid ADS-B message."""
    decoder = ADSBDecoder(test_session)

    # Valid ADS-B message: 8D4840D6202CC371C32CE0576098
    # This is a callsign message for ICAO 4840D6
    msg = "8D4840D6202CC371C32CE0576098"
    decoder.process_message(msg, timestamp=1234567890.0)

    # Check aircraft was created
    aircraft = test_session.query(Aircraft).filter_by(icao24="4840d6").first()
    assert aircraft is not None
    assert aircraft.icao24 == "4840d6"
    assert aircraft.count == 1
    assert len(aircraft.reception_metadata) == 1


def test_process_invalid_message(test_session):
    """Test processing an invalid message."""
    decoder = ADSBDecoder(test_session)

    # Invalid message (too short)
    msg = "8D4840"
    decoder.process_message(msg)

    # No aircraft should be created
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_cleanup_stale_aircraft(test_session):
    """Test cleaning up stale aircraft."""
    import time

    decoder = ADSBDecoder(test_session, stale_timeout=1)

    # Create old aircraft
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=int(time.time()) - 100,
        lastseen=int(time.time()) - 100,
        count=1,
    )
    test_session.add(aircraft)
    test_session.commit()

    # Create recent aircraft
    aircraft2 = Aircraft(
        icao24="def456", firstseen=int(time.time()), lastseen=int(time.time()), count=1
    )
    test_session.add(aircraft2)
    test_session.commit()

    # Cleanup should remove old aircraft
    count = decoder.cleanup_stale_aircraft()
    assert count == 1

    # Only recent aircraft should remain
    remaining = test_session.query(Aircraft).all()
    assert len(remaining) == 1
    assert remaining[0].icao24 == "def456"


def test_decoder_with_reference_position(test_session):
    """Test decoder initialization with reference position."""
    decoder = ADSBDecoder(test_session, lat_ref=40.7, lon_ref=-74.0)
    assert decoder.lat_ref == 40.7
    assert decoder.lon_ref == -74.0


def test_process_message_with_invalid_type(test_session):
    """Test processing a message with invalid type (not string)."""
    decoder = ADSBDecoder(test_session)

    # Should handle None gracefully
    decoder.process_message(None)

    # Should handle non-string types
    decoder.process_message(12345)
    decoder.process_message([])

    # No aircraft should be created
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_process_message_with_invalid_hex(test_session):
    """Test processing a message with invalid hex characters."""
    decoder = ADSBDecoder(test_session)

    # Invalid hex characters
    decoder.process_message("GHIJKLMNOP")
    decoder.process_message("8D4840D6-INVALID")

    # No aircraft should be created
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_process_message_with_bad_crc(test_session):
    """Test processing a message with bad CRC."""
    decoder = ADSBDecoder(test_session)

    # Valid hex but bad CRC (modified message)
    decoder.process_message("8D4840D6202CC371C32CE0576099")  # Last digit changed

    # No aircraft should be created
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_process_message_crc_exception(test_session):
    """Test handling of CRC check exceptions."""
    decoder = ADSBDecoder(test_session)

    with patch("pyModeS.crc") as mock_crc:
        mock_crc.side_effect = Exception("CRC error")
        decoder.process_message("8D4840D6202CC371C32CE0576098")

    # Should handle exception gracefully
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_process_message_df_extraction_exception(test_session):
    """Test handling of DF/ICAO extraction exceptions."""
    decoder = ADSBDecoder(test_session)

    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df") as mock_df:
            mock_df.side_effect = Exception("DF extraction error")
            decoder.process_message("8D4840D6202CC371C32CE0576098")

    # Should handle exception gracefully
    count = test_session.query(Aircraft).count()
    assert count == 0


def test_process_altitude_reply_df4(test_session, mock_pymodes_df4):
    """Test processing altitude reply (DF4)."""
    decoder = ADSBDecoder(test_session)

    # Create an aircraft first
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=int(time.time()),
        lastseen=int(time.time()),
        count=0,
    )
    test_session.add(aircraft)
    test_session.flush()

    # Process DF4 message
    decoder.process_message("20000000000000")

    # Check altitude was updated
    updated_aircraft = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert updated_aircraft.altitude == 35000


def test_process_altitude_reply_exception(test_session):
    """Test handling of altitude reply exceptions."""
    decoder = ADSBDecoder(test_session)

    # Create an aircraft first (without altitude set)
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=int(time.time()),
        lastseen=int(time.time()),
        count=0,
    )
    test_session.add(aircraft)
    test_session.flush()

    # Mock DF4 message with exception
    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=4):
            with patch("pyModeS.icao", return_value="ABC123"):
                with patch("pyModeS.common.altcode") as mock_altcode:
                    mock_altcode.side_effect = Exception("Altitude decode error")
                    decoder.process_message("20000000000000")

    # Should handle exception gracefully - altitude should remain None
    updated_aircraft = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert updated_aircraft.altitude is None


def test_process_identity_reply_df5(test_session, mock_pymodes_df5):
    """Test processing identity reply (DF5)."""
    decoder = ADSBDecoder(test_session)

    # Create an aircraft first
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=int(time.time()),
        lastseen=int(time.time()),
        count=0,
    )
    test_session.add(aircraft)
    test_session.flush()

    # Process DF5 message
    decoder.process_message("28000000000000")

    # Check squawk was updated
    updated_aircraft = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert updated_aircraft.squawk == "7700"


def test_process_identity_reply_exception(test_session):
    """Test handling of identity reply exceptions."""
    decoder = ADSBDecoder(test_session)

    # Create an aircraft first (without squawk set)
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=int(time.time()),
        lastseen=int(time.time()),
        count=0,
    )
    test_session.add(aircraft)
    test_session.flush()

    # Mock DF5 message with exception
    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=5):
            with patch("pyModeS.icao", return_value="ABC123"):
                with patch("pyModeS.common.idcode") as mock_idcode:
                    mock_idcode.side_effect = Exception("Squawk decode error")
                    decoder.process_message("28000000000000")

    # Should handle exception gracefully - squawk should remain None
    updated_aircraft = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert updated_aircraft.squawk is None


# Removed overly complex mocking tests that don't add real value
# The existing integration tests in test_decoder.py adequately cover
# the main functionality


def test_extract_nacp(test_session):
    """Test NACP extraction from typecode."""
    decoder = ADSBDecoder(test_session)

    # Test known typecode -> NACP mappings
    assert decoder._extract_nacp(9) == 9
    assert decoder._extract_nacp(10) == 9
    assert decoder._extract_nacp(11) == 8
    assert decoder._extract_nacp(15) == 6
    assert decoder._extract_nacp(18) == 4
    assert decoder._extract_nacp(20) == 9
    assert decoder._extract_nacp(21) == 8
    assert decoder._extract_nacp(22) == 0

    # Test unknown typecode
    assert decoder._extract_nacp(99) is None
    assert decoder._extract_nacp(1) is None


def test_process_message_stores_rssi(test_session):
    """The rssi argument is stored on the reception metadata row."""
    decoder = ADSBDecoder(test_session)

    aircraft = decoder.process_message(
        "8D4840D6202CC371C32CE0576098", timestamp=1234567890.0, rssi=-12.5
    )

    assert aircraft.reception_metadata[0].rssi == -12.5


def _returning_aircraft(test_session, seconds_ago: int) -> Aircraft:
    """An aircraft with a full previous-flight state, last heard ``seconds_ago``."""
    now = int(time.time())
    aircraft = Aircraft(
        icao24="abc123",
        firstseen=now - seconds_ago - 3600,
        lastseen=now - seconds_ago,
        count=7,
        callsign="OLD123",
        squawk="1200",
        latitude=40.7,
        longitude=-74.0,
        altitude=10000,
        groundspeed=250.0,
        track=90.0,
        registration="N12345",
        typecode="B738",
    )
    test_session.add(aircraft)
    test_session.flush()
    return aircraft


def test_returning_aircraft_drops_previous_flight_state(test_session, mock_pymodes_df4):
    """A row retained past stale_timeout must not republish its old position on reactivation."""
    decoder = ADSBDecoder(test_session, stale_timeout=60)
    _returning_aircraft(test_session, seconds_ago=600)

    decoder.process_message("20000000000000")  # DF4: altitude only, no position

    ac = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert ac.latitude is None and ac.longitude is None
    assert ac.callsign is None and ac.squawk is None
    assert ac.groundspeed is None and ac.track is None
    assert ac.altitude == 35000  # from the new frame
    assert ac.lastseen >= int(time.time()) - 5
    # Identity and history survive: enrichment is static and count is cumulative
    assert ac.registration == "N12345" and ac.typecode == "B738"
    assert ac.count == 8


def test_brief_gap_keeps_current_state(test_session, mock_pymodes_df4):
    """A dropout shorter than stale_timeout is the same contact; keep its state."""
    decoder = ADSBDecoder(test_session, stale_timeout=60)
    _returning_aircraft(test_session, seconds_ago=10)

    decoder.process_message("20000000000000")

    ac = test_session.query(Aircraft).filter_by(icao24="abc123").first()
    assert ac.latitude == 40.7 and ac.callsign == "OLD123"
    assert ac.altitude == 35000


def seed_metadata(session, aircraft, timestamps):
    for ts in timestamps:
        session.add(
            AircraftMetadata(aircraft_id=aircraft.id, system_timestamp=ts, nanoseconds=0, rssi=-9.0)
        )
    session.commit()


def test_purge_old_metadata_deletes_only_rows_older_than_retention(test_session, aircraft):
    """Metadata older than the retention window goes; newer rows, aircraft and positions stay."""
    now = time.time()
    seed_metadata(test_session, aircraft, [now - 7200 + i for i in range(5)])
    seed_metadata(test_session, aircraft, [now - 300 + i for i in range(5)])
    test_session.add(
        AircraftPosition(
            aircraft_id=aircraft.id, timestamp=int(now) - 7200, latitude=1, longitude=2
        )
    )
    test_session.commit()
    decoder = ADSBDecoder(test_session)

    removed = decoder.purge_old_metadata(retention=3600, now=now)

    assert removed == 5
    remaining = [m.system_timestamp for m in test_session.query(AircraftMetadata).all()]
    assert len(remaining) == 5 and all(ts >= now - 3600 for ts in remaining)
    assert test_session.query(Aircraft).count() == 1
    assert test_session.query(AircraftPosition).count() == 1


def test_purge_old_metadata_zero_retention_keeps_everything(test_session, aircraft):
    seed_metadata(test_session, aircraft, [time.time() - 7200])
    decoder = ADSBDecoder(test_session)

    assert decoder.purge_old_metadata(retention=0) == 0
    assert test_session.query(AircraftMetadata).count() == 1
