"""FastAPI application for ADS-B REST API."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from adsb.database import Database
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition
from adsb.schemas import AircraftStateSchema, SensorSchema, TrackPointSchema

# Constants
MAX_METADATA_RECORDS = 4  # Match jet1090 API format - last 4 reception metadata

# Global instances
db_instance: Database | None = None
network_client_instance = None


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


def create_app(database: Database, network_client=None) -> FastAPI:
    """
    Create and configure FastAPI application.

    Parameters
    ----------
    database : Database
        Database instance
    network_client : ADSBNetworkClient, optional
        Network client instance for graceful shutdown

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
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS for local development
    # Explicitly specify localhost origins instead of wildcard for security
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",  # Vite default port
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,  # Not needed for this application
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        """
        API root endpoint.

        Returns
        -------
        dict
            Welcome message and available routes
        """
        return {
            "message": "Welcome to the ADS-B REST API!",
            "routes": {
                "/all": "returns all current state vectors",
                "/icao24": "returns all ICAO 24-bit addresses seen",
                "/track?icao24={icao24}&since={timestamp}": "returns the trajectory of a given aircraft",
                "/sensors": "returns information about all sensors",
            },
        }

    @app.get("/all", response_model=list[AircraftStateSchema])
    async def get_all_aircraft(session: Session = Depends(get_session)):
        """
        Get all currently tracked aircraft.

        Parameters
        ----------
        session : Session
            Database session

        Returns
        -------
        list[AircraftStateSchema]
            List of aircraft state vectors
        """
        aircraft_list = session.query(Aircraft).all()

        result = []
        for aircraft in aircraft_list:
            # Get limited metadata (last N messages)
            reception_metadata = (
                session.query(AircraftMetadata)
                .filter_by(aircraft_id=aircraft.id)
                .order_by(AircraftMetadata.system_timestamp.desc())
                .limit(MAX_METADATA_RECORDS)
                .all()
            )

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
                    for m in reception_metadata
                ],
            }
            result.append(AircraftStateSchema(**aircraft_dict))

        return result

    @app.get("/icao24", response_model=list[str])
    async def get_all_icao24(session: Session = Depends(get_session)):
        """
        Get all ICAO 24-bit addresses currently tracked.

        Parameters
        ----------
        session : Session
            Database session

        Returns
        -------
        list[str]
            List of ICAO 24-bit addresses
        """
        aircraft_list = session.query(Aircraft.icao24).all()
        return [aircraft[0] for aircraft in aircraft_list]

    @app.get("/track", response_model=list[TrackPointSchema])
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

    @app.get("/sensors", response_model=list[SensorSchema])
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
