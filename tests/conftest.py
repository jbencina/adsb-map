"""Pytest configuration and fixtures."""

import os
import tempfile

import pytest

from adsb.database import Database
from adsb.models import Aircraft


@pytest.fixture
def sample_aircraft():
    """Return a sample aircraft for testing."""
    return Aircraft(
        icao24="abc123",
        firstseen=1234567890,
        lastseen=1234567890,
        callsign="TEST123",
        latitude=40.7,
        longitude=-74.0,
        altitude=10000,
        count=5,
    )


@pytest.fixture
def aircraft(test_session, sample_aircraft):
    """Create a sample aircraft in the database."""
    test_session.add(sample_aircraft)
    test_session.commit()
    return sample_aircraft


@pytest.fixture
def mock_pymodes_df4():
    """
    Mock pyModeS for DF4 (altitude reply) message.

    Returns
    -------
    dict
        Dictionary containing mock objects for chaining
    """
    from unittest.mock import patch

    patches = {
        "crc": patch("pyModeS.crc", return_value=0),
        "df": patch("pyModeS.df", return_value=4),
        "icao": patch("pyModeS.icao", return_value="ABC123"),
        "altcode": patch("pyModeS.common.altcode", return_value=35000),
    }

    mocks = {}
    for key, patcher in patches.items():
        mocks[key] = patcher.start()

    yield mocks

    for patcher in patches.values():
        patcher.stop()


@pytest.fixture
def mock_pymodes_df5():
    """
    Mock pyModeS for DF5 (identity reply) message.

    Returns
    -------
    dict
        Dictionary containing mock objects for chaining
    """
    from unittest.mock import patch

    patches = {
        "crc": patch("pyModeS.crc", return_value=0),
        "df": patch("pyModeS.df", return_value=5),
        "icao": patch("pyModeS.icao", return_value="ABC123"),
        "idcode": patch("pyModeS.common.idcode", return_value="7700"),
    }

    mocks = {}
    for key, patcher in patches.items():
        mocks[key] = patcher.start()

    yield mocks

    for patcher in patches.values():
        patcher.stop()


@pytest.fixture(scope="function")
def test_db():
    """
    Create a temporary file-based database for testing.

    Using a file-based database instead of :memory: ensures all connections
    share the same database state.

    Yields
    ------
    Database
        Test database instance
    """
    # Create a temporary file for the database
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database = Database(db_path)
        database.create_tables()
        yield database
    finally:
        # Dispose of the engine to close all connections
        database.dispose()
        # Clean up the temporary database file
        if os.path.exists(db_path):
            os.unlink(db_path)


@pytest.fixture
def test_session(test_db):
    """
    Create a test database session.

    Parameters
    ----------
    test_db : Database
        Test database fixture

    Yields
    ------
    Session
        SQLAlchemy session
    """
    with test_db.get_session() as session:
        yield session
