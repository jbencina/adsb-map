"""FastAPI application for the ADS-B REST API.

API only: the map UI is a separate service (`adsb start frontend`, see `adsb.ui`)
that proxies to this one, so nothing here serves HTML, static files or CORS.
"""

import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from adsb import __version__
from adsb.database import Database
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition
from adsb.schemas import AircraftStateSchema, SensorSchema, TrackPointSchema

# Constants
MAX_METADATA_RECORDS = 4  # Match jet1090 API format - last 4 reception metadata
DEFAULT_STALE_TIMEOUT = 60  # Seconds; aircraft older than this are hidden unless asked for

# Global instances
db_instance: Database | None = None
network_client_instance = None


def api_index() -> dict:
    """Discovery document served at ``/`` and ``/api``."""
    return {
        "message": "Welcome to the ADS-B REST API!",
        "routes": {
            "/api/all": "returns all current state vectors (?max_age=SECONDS widens the window)",
            "/api/icao24": "returns all ICAO 24-bit addresses seen (?max_age=SECONDS as above)",
            "/api/track?icao24={icao24}&since={timestamp}": (
                "returns the trajectory of a given aircraft"
            ),
            "/api/sensors": "returns information about all sensors",
            "/docs": "interactive OpenAPI documentation",
        },
        "map_ui": "run `adsb start frontend --api-url <this server>` and open its port",
    }


def get_db() -> Database:
    """
    Get database instance.

    Returns
    -------
    Database
        Database instance

    Raises
    ------
    RuntimeError
        If database is not initialized
    """
    if db_instance is None:
        raise RuntimeError("Database not initialized")
    return db_instance


def get_session():
    """
    Dependency to get database session.

    Yields
    ------
    Session
        SQLAlchemy database session
    """
    database = get_db()
    with database.get_session() as session:
        yield session


def latest_metadata_stmt(cutoff: int, limit: int = MAX_METADATA_RECORDS) -> Select:
    """
    Newest ``limit`` metadata rows for every aircraft seen since ``cutoff``, in one statement.

    A correlated top-N subquery per aircraft: each one is a seek on the
    ``(aircraft_id, system_timestamp)`` index reading ``limit`` rows, so the cost
    is O(aircraft in window) regardless of how much history the table holds. A
    window function would read every row of every in-window aircraft instead.

    Rows come back grouped by aircraft, newest first within each group.
    """
    t = aliased(AircraftMetadata)
    latest_ids = (
        select(t.id)
        .where(t.aircraft_id == Aircraft.id)
        .order_by(t.system_timestamp.desc())
        .limit(limit)
        .correlate(Aircraft)
        .scalar_subquery()
    )
    return (
        select(AircraftMetadata)
        .join(Aircraft, AircraftMetadata.id.in_(latest_ids))
        .where(Aircraft.lastseen >= cutoff)
        .order_by(AircraftMetadata.aircraft_id, AircraftMetadata.system_timestamp.desc())
    )


def create_app(
    database: Database, network_client=None, stale_timeout: int = DEFAULT_STALE_TIMEOUT
) -> FastAPI:
    """
    Create and configure FastAPI application.

    Parameters
    ----------
    database : Database
        Database instance
    network_client : ADSBNetworkClient, optional
        Network client instance for graceful shutdown
    stale_timeout : int, optional
        Default ``max_age`` window in seconds for ``/api/all`` and ``/api/icao24``.
        Aircraft last seen longer ago than this stay in the database but are only
        returned when a caller asks for a wider ``max_age``.

    Returns
    -------
    FastAPI
        Configured FastAPI application
    """
    global db_instance, network_client_instance
    db_instance = database
    network_client_instance = network_client

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Handle startup and shutdown events."""
        # Startup
        yield
        # Shutdown
        if network_client_instance:
            network_client_instance.stop()

    app = FastAPI(
        title="ADS-B API",
        description="ADS-B decoder REST API using pyModeS",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/api")
    async def api_root():
        """
        API discovery endpoint.

        Returns
        -------
        dict
            Welcome message and available routes
        """
        return api_index()

    # The backend has no UI, so `/` answers with the same discovery document
    # instead of a bare 404 -- someone opening port 8000 in a browser should
    # learn where the data is.
    @app.get("/", include_in_schema=False)
    async def root():
        return api_index()

    max_age_query = Query(
        None,
        ge=1,
        description=(
            "Only aircraft seen within this many seconds. "
            f"Defaults to the backend's stale timeout ({stale_timeout}s)."
        ),
    )

    def seen_since(max_age: int | None) -> int:
        """Unix timestamp before which an aircraft is outside the requested window."""
        return int(time.time()) - (max_age if max_age is not None else stale_timeout)

    @app.get("/api/all", response_model=list[AircraftStateSchema])
    async def get_all_aircraft(
        max_age: int | None = max_age_query, session: Session = Depends(get_session)
    ):
        """
        Get all currently tracked aircraft.

        Aircraft are never purged, so widening ``max_age`` brings back aircraft
        that have aged out of the default window. Reception metadata is only kept
        for the backend's ``--metadata-retention`` window, so aircraft older than
        that come back with an empty ``metadata`` list.

        Parameters
        ----------
        max_age : int, optional
            Only aircraft seen within this many seconds
        session : Session
            Database session

        Returns
        -------
        list[AircraftStateSchema]
            List of aircraft state vectors
        """
        cutoff = seen_since(max_age)
        aircraft_list = (
            session.query(Aircraft).filter(Aircraft.lastseen >= cutoff).order_by(Aircraft.id).all()
        )

        # One statement for everyone's newest metadata, not one per aircraft.
        by_aircraft: dict[int, list[AircraftMetadata]] = defaultdict(list)
        for m in session.execute(latest_metadata_stmt(cutoff)).scalars():
            by_aircraft[m.aircraft_id].append(m)

        result = []
        for aircraft in aircraft_list:
            aircraft_dict = {
                "icao24": aircraft.icao24,
                "firstseen": aircraft.firstseen,
                "lastseen": aircraft.lastseen,
                "callsign": aircraft.callsign,
                "registration": aircraft.registration,
                "typecode": aircraft.typecode,
                "type_description": aircraft.type_description,
                "squawk": aircraft.squawk,
                "latitude": aircraft.latitude,
                "longitude": aircraft.longitude,
                "altitude": aircraft.altitude,
                "selected_altitude": aircraft.selected_altitude,
                "groundspeed": aircraft.groundspeed,
                "vertical_rate": aircraft.vertical_rate,
                "track": aircraft.track,
                "ias": aircraft.ias,
                "tas": aircraft.tas,
                "mach": aircraft.mach,
                "roll": aircraft.roll,
                "heading": aircraft.heading,
                "nacp": aircraft.nacp,
                "count": aircraft.count,
                "metadata": [
                    {
                        "system_timestamp": m.system_timestamp,
                        "nanoseconds": m.nanoseconds,
                        "rssi": m.rssi,
                        "serial": m.serial,
                    }
                    for m in by_aircraft.get(aircraft.id, [])
                ],
            }
            result.append(AircraftStateSchema(**aircraft_dict))

        return result

    @app.get("/api/icao24", response_model=list[str])
    async def get_all_icao24(
        max_age: int | None = max_age_query, session: Session = Depends(get_session)
    ):
        """
        Get all ICAO 24-bit addresses currently tracked.

        Parameters
        ----------
        max_age : int, optional
            Only aircraft seen within this many seconds
        session : Session
            Database session

        Returns
        -------
        list[str]
            List of ICAO 24-bit addresses
        """
        aircraft_list = (
            session.query(Aircraft.icao24).filter(Aircraft.lastseen >= seen_since(max_age)).all()
        )
        return [aircraft[0] for aircraft in aircraft_list]

    @app.get("/api/track", response_model=list[TrackPointSchema])
    async def get_aircraft_track(
        icao24: str = Query(..., description="ICAO 24-bit address"),
        since: int | None = Query(None, description="Unix timestamp to filter positions since"),
        session: Session = Depends(get_session),
    ):
        """
        Get trajectory track for a specific aircraft.

        Parameters
        ----------
        icao24 : str
            ICAO 24-bit address
        since : int, optional
            Unix timestamp to filter positions since
        session : Session
            Database session

        Returns
        -------
        list[TrackPointSchema]
            List of track points
        """
        aircraft = session.query(Aircraft).filter_by(icao24=icao24.lower()).first()

        if aircraft is None:
            return []

        query = session.query(AircraftPosition).filter_by(aircraft_id=aircraft.id)

        if since is not None:
            query = query.filter(AircraftPosition.timestamp >= since)

        positions = query.order_by(AircraftPosition.timestamp).all()

        return [
            TrackPointSchema(
                timestamp=pos.timestamp,
                latitude=pos.latitude,
                longitude=pos.longitude,
                altitude=pos.altitude,
            )
            for pos in positions
        ]

    @app.get("/api/sensors", response_model=list[SensorSchema])
    async def get_sensors(session: Session = Depends(get_session)):
        """
        Get information about all sensors/receivers.

        Parameters
        ----------
        session : Session
            Database session

        Returns
        -------
        list[SensorSchema]
            List of sensor information
        """
        # Get unique sensor serials from metadata
        serials = (
            session.query(AircraftMetadata.serial)
            .distinct()
            .filter(AircraftMetadata.serial.isnot(None))
            .all()
        )

        return [SensorSchema(serial=serial[0]) for serial in serials]

    return app
