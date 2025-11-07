"""Command-line interface for ADS-B server."""

import logging

import click
import uvicorn

from adsb.api import create_app
from adsb.database import Database
from adsb.decoder import ADSBDecoder
from adsb.network import start_network_client


@click.group()
@click.version_option(version="0.1.0")
def main():
    """ADS-B decoder and REST API server using pyModeS."""
    pass


@main.command()
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
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(
    host: str,
    port: int,
    db_path: str,
    source: str,
    connect: tuple,
    stale_timeout: int,
    lat: float,
    lon: float,
    reload: bool,
):
    """
    Start the ADS-B API server.

    Examples:

        # Start server with default settings
        adsb serve

        # Start server with custom database path
        adsb serve --db-path /path/to/adsb.db

        # Start server with network data source
        adsb serve --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
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
    app = create_app(database, network_client)

    # Start server
    # Note: Uvicorn handles signals and will trigger FastAPI lifespan shutdown
    click.echo(f"Starting API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload, log_config=log_config)


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
@click.option(
    "--data-dir",
    default="data",
    help="Directory to store the aircraft database",
    show_default=True,
)
def download(data_dir: str):
    """
    Download the aircraft database from tar1090-db.

    Downloads the latest aircraft database (566k+ records) from the
    tar1090-db repository. The database maps ICAO24 addresses to
    aircraft registration, type code, and descriptions.

    Example:

        adsb download
    """
    import gzip
    import os
    import shutil
    from pathlib import Path
    from urllib.request import Request, urlopen

    # Create data directory if it doesn't exist
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    db_url = "https://github.com/wiedehopf/tar1090-db/raw/csv/aircraft.csv.gz"
    db_gz_path = data_path / "aircraft.csv.gz"
    db_csv_path = data_path / "aircraft.csv"

    click.echo("Downloading aircraft database from tar1090-db...")
    click.echo(f"Source: {db_url}")

    try:
        # Download the file
        req = Request(db_url, headers={"User-Agent": "adsb-map/0.1.0"})
        with urlopen(req, timeout=60) as response:
            if response.status != 200:
                click.echo(f"Error: Failed to download database (HTTP {response.status})", err=True)
                return

            # Get content length for progress
            content_length = response.headers.get("Content-Length")
            if content_length:
                total_size = int(content_length)
                click.echo(f"Downloading {total_size / 1024 / 1024:.1f} MB...")
            else:
                click.echo("Downloading...")

            # Download to file
            with open(db_gz_path, "wb") as f:
                shutil.copyfileobj(response, f)

        # Check file size
        gz_size = os.path.getsize(db_gz_path)
        click.echo(f"Downloaded: {gz_size / 1024 / 1024:.1f} MB")

        # Extract the database
        click.echo("Extracting database...")
        with gzip.open(db_gz_path, "rb") as f_in:
            with open(db_csv_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        csv_size = os.path.getsize(db_csv_path)
        click.echo(f"Extracted: {csv_size / 1024 / 1024:.1f} MB")

        # Count records
        with open(db_csv_path, encoding="utf-8", errors="replace") as f:
            record_count = sum(1 for _ in f)

        click.echo("\nAircraft database downloaded successfully!")
        click.echo(f"Location: {db_csv_path}")
        click.echo(f"Records: {record_count:,}")

    except Exception as e:
        click.echo(f"Error downloading database: {e}", err=True)
        # Clean up partial downloads
        if db_gz_path.exists():
            db_gz_path.unlink()
        if db_csv_path.exists():
            db_csv_path.unlink()
        raise click.Abort() from e


if __name__ == "__main__":
    main()
