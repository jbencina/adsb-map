"""FastAPI application for ADS-B REST API."""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from adsb import __version__
from adsb.database import Database
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition
from adsb.schemas import AircraftStateSchema, SensorSchema, TrackPointSchema

# Constants
MAX_METADATA_RECORDS = 4  # Match jet1090 API format - last 4 reception metadata
STATIC_DIR = Path(__file__).parent / "static"

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


def _frontend_is_bundled() -> bool:
    """Return True when the built frontend has been staged into the package."""
    return STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file()


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
        version=__version__,
        lifespan=lifespan,
    )

    # CORS is only required when the frontend runs as a separate dev server.
    # In a bundled wheel the frontend is served same-origin from this app.
    if not _frontend_is_bundled():
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
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
        return {
            "message": "Welcome to the ADS-B REST API!",
            "routes": {
                "/api/all": "returns all current state vectors",
                "/api/icao24": "returns all ICAO 24-bit addresses seen",
                "/api/track?icao24={icao24}&since={timestamp}": (
                    "returns the trajectory of a given aircraft"
                ),
                "/api/sensors": "returns information about all sensors",
            },
        }

    @app.get("/api/all", response_model=list[AircraftStateSchema])
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

    @app.get("/api/icao24", response_model=list[str])
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

    # Runtime config shim: server env vars become window.APP_CONFIG so a single
    # wheel works across users without rebuilding the JS bundle per Mapbox token.
    # Registered in both modes so the dev server (via Vite proxy) doesn't 404.
    @app.get("/config.js", include_in_schema=False)
    async def config_js():
        config = {
            "mapboxToken": os.environ.get("MAPBOX_TOKEN", ""),
            "apiUrl": "",
        }
        return Response(
            content=f"window.APP_CONFIG = {json.dumps(config)};",
            media_type="application/javascript",
        )

    if _frontend_is_bundled():
        app.mount(
            "/assets",
            StaticFiles(directory=STATIC_DIR / "assets"),
            name="assets",
        )

        # SPA fallback: any non-API path serves index.html so client-side routing works.
        # Unmatched /api/* paths return 404 instead of leaking the SPA shell.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        logging.getLogger("adsb").info(
            "Frontend not bundled (adsb/static/ missing). "
            "Run `just build` to bundle, or `just dev` for hot-reload dev mode."
        )

    return app
