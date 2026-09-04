"""FastAPI application for the ADS-B REST API.

API only: the map UI is a separate service (`adsb start frontend`, see `adsb.ui`)
that proxies to this one, so nothing here serves HTML, static files or CORS.
"""

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from adsb import __version__
from adsb.aircraft_db import AIRCRAFT_DB_ATTRIBUTION
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
            "/api/tracks?max_age={seconds}&since={timestamp}": (
                "returns the trajectories of all aircraft, keyed by icao24"
            ),
            "/api/sensors": "returns information about all sensors",
            "/docs": "interactive OpenAPI documentation",
        },
        "map_ui": "run `adsb start frontend --api-url <this server>` and open its port",
        # Registration / type fields in /api/all come from this database; ODC-By
        # asks that the credit travel with the data, so clients can find it here.
        "aircraft_db": AIRCRAFT_DB_ATTRIBUTION,
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


def aircraft_since_stmt(cutoff: int) -> Select:
    """
    Aircraft last seen at or after ``cutoff``, via the ``lastseen`` index.

    Deliberately unordered: an ``ORDER BY id`` makes SQLite drop the index and
    scan every aircraft ever seen, and callers attach data by id anyway.
    """
    return select(Aircraft).where(Aircraft.lastseen >= cutoff)


def latest_metadata_stmt(cutoff: int) -> Select:
    """
    Newest ``MAX_METADATA_RECORDS`` metadata rows for every aircraft seen since ``cutoff``.

    One statement: a correlated top-N subquery per aircraft, each a seek on the
    ``(aircraft_id, system_timestamp)`` index, so the cost is O(aircraft in
    window) regardless of how much history the table holds. A window function
    would read every row of every in-window aircraft instead.

    Rows come back newest first. Frames parsed from one socket read share a
    timestamp, so ``id`` breaks ties.
    """
    t = aliased(AircraftMetadata)
    latest_ids = (
        select(t.id)
        .where(t.aircraft_id == Aircraft.id)
        .order_by(t.system_timestamp.desc(), t.id.desc())
        .limit(MAX_METADATA_RECORDS)
        .correlate(Aircraft)
        .scalar_subquery()
    )
    return (
        select(AircraftMetadata)
        .join(Aircraft, AircraftMetadata.id.in_(latest_ids))
        .where(Aircraft.lastseen >= cutoff)
        .order_by(AircraftMetadata.system_timestamp.desc(), AircraftMetadata.id.desc())
    )


def track_stmt(aircraft_id: int, since: int | None) -> Select:
    """
    One aircraft's positions since ``since`` (all of them if None), oldest first.

    Seeks the ``(aircraft_id, timestamp)`` index, which also supplies the order.
    Positions are retained forever, so the global timestamp index alone would
    walk every aircraft's points since the cutoff.
    """
    stmt = select(AircraftPosition).where(AircraftPosition.aircraft_id == aircraft_id)
    if since is not None:
        stmt = stmt.where(AircraftPosition.timestamp >= since)
    return stmt.order_by(AircraftPosition.timestamp)


def tracks_stmt(since: int) -> Select:
    """
    Every aircraft's positions since ``since``, oldest first, with the icao24.

    Seeks the ``timestamp`` index and takes its order, which is also each
    aircraft's own order, so the caller can group without sorting. The map
    polls this with ``since`` set to the newest timestamp it has, so after the
    first call the result is just the last second or so of positions.
    """
    return (
        select(Aircraft.icao24, AircraftPosition)
        .join(Aircraft, Aircraft.id == AircraftPosition.aircraft_id)
        .where(AircraftPosition.timestamp >= since)
        .order_by(AircraftPosition.timestamp)
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
        aircraft_list = session.execute(aircraft_since_stmt(cutoff)).scalars().all()

        # One statement for everyone's newest metadata, not one per aircraft.
        by_aircraft: dict[int, list[AircraftMetadata]] = {}
        for m in session.execute(latest_metadata_stmt(cutoff)).scalars():
            by_aircraft.setdefault(m.aircraft_id, []).append(m)

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

        positions = session.execute(track_stmt(aircraft.id, since)).scalars().all()

        return [
            TrackPointSchema(
                timestamp=pos.timestamp,
                latitude=pos.latitude,
                longitude=pos.longitude,
                altitude=pos.altitude,
            )
            for pos in positions
        ]

    @app.get("/api/tracks", response_model=dict[str, list[TrackPointSchema]])
    async def get_all_tracks(
        max_age: int | None = max_age_query,
        since: int | None = Query(
            None,
            description=(
                "Unix timestamp; only positions at or after it. Overrides max_age, "
                "so a client can fetch just the positions it has not seen yet."
            ),
        ),
        session: Session = Depends(get_session),
    ):
        """
        Get the trajectories of every aircraft with positions in the window.

        This is the map's single source for track lines: it seeds from the
        ``max_age`` window and then polls with ``since`` for new points, and the
        selected aircraft's line is the same data highlighted. Aircraft with no
        positions in the window are omitted.

        Parameters
        ----------
        max_age : int, optional
            Window in seconds, defaulting to the backend's stale timeout
        since : int, optional
            Unix timestamp overriding the window
        session : Session
            Database session

        Returns
        -------
        dict[str, list[TrackPointSchema]]
            Track points per icao24, oldest first
        """
        cutoff = since if since is not None else seen_since(max_age)
        tracks: dict[str, list[TrackPointSchema]] = {}
        for icao24, pos in session.execute(tracks_stmt(cutoff)):
            tracks.setdefault(icao24, []).append(
                TrackPointSchema(
                    timestamp=pos.timestamp,
                    latitude=pos.latitude,
                    longitude=pos.longitude,
                    altitude=pos.altitude,
                )
            )
        return tracks

    @app.get("/api/sensors", response_model=list[SensorSchema])
    async def get_sensors(session: Session = Depends(get_session)):
        """
        Get information about recently active sensors/receivers.

        Serials come from reception metadata, which the backend trims to its
        ``--metadata-retention`` window (an hour by default), so a receiver that
        has been silent longer than that drops off this list.

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
