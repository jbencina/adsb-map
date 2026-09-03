"""Command-line interface for ADS-B server."""

import logging
import os

import click
import uvicorn
from dotenv import find_dotenv, load_dotenv

from adsb import __version__
from adsb.aircraft_db import aircraft_db_path, set_aircraft_db_path
from adsb.api import create_app, frontend_is_bundled, parse_cors_origins
from adsb.database import Database
from adsb.decoder import ADSBDecoder
from adsb.network import start_network_client
from adsb.ui import create_ui_app

AIRCRAFT_DB_URL = "https://github.com/wiedehopf/tar1090-db/raw/csv/aircraft.csv.gz"


def _echo_preflight(source: str, connect: tuple, serve_ui: bool, cors_origins: list) -> None:
    """Report the things that otherwise fail silently at runtime.

    Each of these leaves the server looking healthy while the map stays blank or
    unenriched, so surface them once at startup instead of as buried log lines.
    """
    db = aircraft_db_path()
    if serve_ui:
        ui_check = (
            frontend_is_bundled(),
            "Map UI bundled",
            "Map UI not built - API only; see `just build`",
        )
    else:
        ui_check = (True, "Map UI disabled (--no-ui) - API only", "")
    checks = [
        ui_check,
        (
            db.is_file(),
            f"Aircraft database: {db}",
            f"No aircraft database at {db} - run `adsb download` (or pass --aircraft-db)",
        ),
        (
            bool(os.environ.get("MAPBOX_TOKEN")),
            "Mapbox token set",
            "MAPBOX_TOKEN unset - map tiles will not render",
        ),
        (
            bool(source and connect),
            "Data source configured",
            "No data source - map stays empty; use --source net --connect HOST PORT TYPE",
        ),
    ]
    if cors_origins:
        checks.append((True, f"CORS origins: {', '.join(cors_origins)}", ""))
    for ok, good, bad in checks:
        click.echo(f"  [{'ok' if ok else '!!'}] {good if ok else bad}")


def aircraft_db_option(f):
    """`--aircraft-db PATH` for every command that reads or writes the aircraft CSV.

    Applied eagerly (`is_eager`) so the override is installed before the command
    body -- and anything it imports lazily -- resolves the path.
    """

    def _apply(ctx, param, value):
        if value:
            set_aircraft_db_path(value)
        return value

    return click.option(
        "--aircraft-db",
        type=click.Path(dir_okay=False, path_type=str),
        metavar="PATH",
        is_eager=True,
        expose_value=False,
        callback=_apply,
        help="Aircraft database CSV location (default: per-user data dir)",
    )(f)


@click.group()
@click.version_option(version=__version__)
def main():
    """ADS-B decoder and REST API server using pyModeS."""
    # Load .env from the current working directory (or parents) if present. It is
    # for secrets only (MAPBOX_TOKEN); everything else is a CLI argument.
    # `usecwd=True` is required: the default starts searching from the importing
    # module's location, which under pytest/CliRunner doesn't match the user's CWD.
    # `override=False` so explicit `MAPBOX_TOKEN=… adsb start backend` still beats a stale .env.
    load_dotenv(find_dotenv(usecwd=True), override=False)


@main.group()
def start():
    """Start a service: `backend` (decoder + API) or `frontend` (map UI client)."""


@start.command()
@click.option("--host", default="0.0.0.0", help="Host to bind the server to", show_default=True)
@click.option("--port", default=8000, help="Port to bind the server to", show_default=True)
@click.option(
    "--db-path",
    default="adsb.db",
    help="Path to SQLite database file",
    show_default=True,
)
@click.option(
    "--source",
    type=click.Choice(["net"], case_sensitive=False),
    help="Data source (currently only 'net' is supported)",
)
@click.option(
    "--connect",
    nargs=3,
    metavar="HOST PORT TYPE",
    help="Connect to network source: HOST PORT TYPE (raw/beast)",
)
@click.option(
    "--stale-timeout",
    default=60,
    help="Seconds before removing stale aircraft",
    show_default=True,
)
@click.option(
    "--lat",
    type=float,
    help="Receiver latitude (required for accurate position decoding)",
)
@click.option(
    "--lon",
    type=float,
    help="Receiver longitude (required for accurate position decoding)",
)
@click.option(
    "--no-ui",
    is_flag=True,
    help="Serve the REST API only; do not serve the bundled map UI at /",
)
@click.option(
    "--cors-origins",
    metavar="ORIGINS",
    help=(
        "Comma-separated browser origins allowed to call /api/* cross-origin, "
        "e.g. http://laptop:3000 or '*'. Only needed when the UI is hosted elsewhere "
        "and talks to this API directly (not via `adsb start frontend`, which proxies)."
    ),
)
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@aircraft_db_option
def backend(
    host: str,
    port: int,
    db_path: str,
    source: str,
    connect: tuple,
    stale_timeout: int,
    lat: float,
    lon: float,
    no_ui: bool,
    cors_origins: str | None,
    reload: bool,
):
    """
    Start the decoder and REST API (plus the bundled map UI unless --no-ui).

    Examples:

        # Start with default settings
        adsb start backend

        # Custom database path
        adsb start backend --db-path /path/to/adsb.db

        # With a network data source
        adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

        # API only; run the map elsewhere with `adsb start frontend --api-url http://this-host:8000`
        adsb start backend --no-ui --source net --connect localhost 30005 beast
    """
    # Suppress deprecation warnings from dependencies
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)

    # Configure logging with different formats for different loggers
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Default formatter for other loggers
    default_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler.setFormatter(default_formatter)
    root_logger.addHandler(console_handler)

    # Configure ADSB data logger separately
    adsb_formatter = logging.Formatter(
        "%(asctime)s - [ADSB] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    adsb_logger = logging.getLogger("adsb.data")
    adsb_logger.setLevel(logging.INFO)
    adsb_handler = logging.StreamHandler()
    adsb_handler.setFormatter(adsb_formatter)
    adsb_logger.addHandler(adsb_handler)
    adsb_logger.propagate = False  # Don't propagate to root logger

    # Set decoder logger to WARNING to reduce noise (individual aircraft updates)
    logging.getLogger("adsb.decoder").setLevel(logging.WARNING)

    # Custom uvicorn log config to add [API] prefix to access logs
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "api": {
                "format": "%(asctime)s - [API] %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "api": {
                "formatter": "api",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn.access": {
                "handlers": ["api"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["default"],
                "level": "WARNING",  # Only show warnings/errors, not startup messages
                "propagate": False,
            },
        },
    }

    # Initialize database
    database = Database(db_path)
    database.create_tables()
    click.echo(f"Database initialized: {db_path}")

    # If network source is specified, start background decoder
    network_client = None
    if source == "net" and connect:
        net_host, net_port, net_type = connect
        click.echo(f"Network source: {net_host}:{net_port} ({net_type})")

        if lat is not None and lon is not None:
            click.echo(f"Reference position: {lat:.4f}, {lon:.4f}")
        else:
            click.echo(
                "Warning: No reference position provided. Position decoding may be inaccurate."
            )
            click.echo("Use --lat and --lon options to provide receiver location.")

        click.echo("Starting network decoder in background...")

        # Start network client in background thread
        network_client = start_network_client(
            host=net_host,
            port=net_port,
            rawtype=net_type,
            database=database,
            stale_timeout=stale_timeout,
            lat_ref=lat,
            lon_ref=lon,
        )
        click.echo("Network decoder started successfully")

    # Create FastAPI app with network client for graceful shutdown
    origins = parse_cors_origins(cors_origins)
    app = create_app(database, network_client, serve_ui=not no_ui, cors_origins=origins)

    click.echo("Startup checks:")
    _echo_preflight(source, connect, serve_ui=not no_ui, cors_origins=origins)

    # Start server
    # Note: Uvicorn handles signals and will trigger FastAPI lifespan shutdown
    click.echo(f"Starting API server on http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, reload=reload, log_config=log_config)


@start.command()
@click.option(
    "--api-url",
    required=True,
    metavar="URL",
    help="Base URL of the `adsb start backend` host, e.g. http://receiver.local:8000",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (use 0.0.0.0 to share on the LAN)",
    show_default=True,
)
@click.option("--port", default=3000, help="Port to bind to", show_default=True)
def frontend(api_url: str, host: str, port: int):
    """
    Start the map UI as a client of a remote backend.

    Runs the bundled map on this machine and proxies /api/* to the backend
    given by --api-url, so the receiver host only needs `adsb start backend`
    and no CORS configuration. The Mapbox token comes from the backend unless
    MAPBOX_TOKEN is set here.

    Example:

        adsb start frontend --api-url http://receiver.local:8000
    """
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - [UI] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        app = create_ui_app(api_url)
    except (RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Backend API: {app.state.api_url}")
    token_source = "local MAPBOX_TOKEN" if os.environ.get("MAPBOX_TOKEN") else "backend"
    click.echo(f"Mapbox token: from {token_source}")
    click.echo(f"Starting map UI on http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@main.command()
@click.option(
    "--db-path",
    default="adsb.db",
    help="Path to SQLite database file",
    show_default=True,
)
def init_db(db_path: str):
    """
    Initialize the database.

    Creates all necessary tables in the SQLite database.
    """
    database = Database(db_path)
    database.create_tables()
    click.echo(f"Database initialized: {db_path}")


@main.command()
@click.argument("message")
@click.option(
    "--db-path",
    default="adsb.db",
    help="Path to SQLite database file",
    show_default=True,
)
@aircraft_db_option
def decode(message: str, db_path: str):
    """
    Decode a single ADS-B message and store it in the database.

    MESSAGE: Hexadecimal ADS-B message to decode

    Example:

        adsb decode 8D4840D6202CC371C32CE0576098
    """
    # Initialize database
    database = Database(db_path)
    database.create_tables()

    # Decode message
    with database.get_session() as session:
        decoder = ADSBDecoder(session)
        decoder.process_message(message)

    click.echo(f"Message decoded and stored: {message}")


@main.command()
@click.option(
    "--db-path",
    default="adsb.db",
    help="Path to SQLite database file",
    show_default=True,
)
def cleanup(db_path: str):
    """
    Clean up stale aircraft from the database.

    Removes aircraft that haven't been seen in the last 60 seconds.
    """
    database = Database(db_path)

    with database.get_session() as session:
        decoder = ADSBDecoder(session)
        count = decoder.cleanup_stale_aircraft()

    click.echo(f"Removed {count} stale aircraft")


@main.command()
@click.option(
    "--db-path",
    default="adsb.db",
    help="Path to SQLite database file",
    show_default=True,
)
def db_size(db_path: str):
    """
    Display database size and statistics.

    Shows the total database file size and table row counts.
    """
    import os

    from sqlalchemy import text

    database = Database(db_path)

    # Get file size
    if os.path.exists(db_path):
        file_size_bytes = os.path.getsize(db_path)
        file_size_mb = file_size_bytes / (1024 * 1024)
        click.echo(f"Database file: {db_path}")
        click.echo(f"File size: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)")
    else:
        click.echo(f"Database file not found: {db_path}")
        return

    # Get table statistics
    with database.get_session() as session:
        # Count aircraft
        aircraft_count = session.execute(text("SELECT COUNT(*) FROM aircraft")).scalar()

        # Count positions
        position_count = session.execute(text("SELECT COUNT(*) FROM aircraft_positions")).scalar()

        # Count metadata
        metadata_count = session.execute(text("SELECT COUNT(*) FROM aircraft_metadata")).scalar()

        # Get SQLite database page info
        page_count = session.execute(text("PRAGMA page_count")).scalar()
        page_size = session.execute(text("PRAGMA page_size")).scalar()

        click.echo("\nTable Statistics:")
        click.echo(f"  Aircraft: {aircraft_count:,}")
        click.echo(f"  Positions: {position_count:,}")
        click.echo(f"  Metadata: {metadata_count:,}")

        click.echo("\nSQLite Info:")
        click.echo(f"  Page count: {page_count:,}")
        click.echo(f"  Page size: {page_size:,} bytes")

        # Calculate and show database efficiency
        if aircraft_count > 0:
            avg_positions_per_aircraft = position_count / aircraft_count
            avg_messages_per_aircraft = metadata_count / aircraft_count
            click.echo("\nAverages:")
            click.echo(f"  Positions per aircraft: {avg_positions_per_aircraft:.1f}")
            click.echo(f"  Messages per aircraft: {avg_messages_per_aircraft:.1f}")


@main.command()
@click.option("--force", is_flag=True, help="Re-download even if the database is already present")
@aircraft_db_option
def download(force: bool):
    """
    Download the aircraft database from tar1090-db.

    Downloads the latest aircraft database (566k+ records) from the
    tar1090-db repository. The database maps ICAO24 addresses to
    aircraft registration, type code, and descriptions.

    Stored in a per-user data directory so it is found no matter which
    directory `adsb start backend` runs from. Override with --aircraft-db (pass the
    same path to `adsb start backend`).

    Example:

        adsb download
    """
    import gzip
    import shutil
    from urllib.request import Request, urlopen

    dest = aircraft_db_path()
    if dest.is_file() and not force:
        click.echo(f"Aircraft database already present: {dest}")
        click.echo("Use --force to re-download.")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Decompress as it streams: no .gz copy is left behind, and a failed download
    # never leaves a truncated CSV where the loader would find it.
    tmp = dest.with_name(dest.name + ".partial")

    click.echo("Downloading aircraft database from tar1090-db...")
    click.echo(f"Source: {AIRCRAFT_DB_URL}")

    try:
        req = Request(AIRCRAFT_DB_URL, headers={"User-Agent": f"adsb-map/{__version__}"})
        with urlopen(req, timeout=60) as response:
            with gzip.GzipFile(fileobj=response) as gz, open(tmp, "wb") as f:
                shutil.copyfileobj(gz, f)
        tmp.replace(dest)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        click.echo(f"Error downloading database: {e}", err=True)
        raise click.Abort() from e

    with open(dest, encoding="utf-8", errors="replace") as f:
        record_count = sum(1 for _ in f)

    click.echo("\nAircraft database downloaded successfully!")
    click.echo(f"Location: {dest}")
    click.echo(f"Size: {dest.stat().st_size / 1024 / 1024:.1f} MB")
    click.echo(f"Records: {record_count:,}")


if __name__ == "__main__":
    main()
