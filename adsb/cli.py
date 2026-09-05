"""Command-line interface for ADS-B server."""

import logging
import os
import signal
import threading
import warnings

import click
import uvicorn
from dotenv import find_dotenv, load_dotenv

from adsb import __version__
from adsb.aircraft_db import (
    AIRCRAFT_DB_NOTICE,
    AIRCRAFT_DB_URL,
    aircraft_db_path,
    set_aircraft_db_path,
)
from adsb.api import create_app
from adsb.database import Database
from adsb.decoder import DEFAULT_METADATA_RETENTION, ADSBDecoder
from adsb.network import start_network_client
from adsb.status import StatusReporter
from adsb.traffic import backfill_traffic
from adsb.ui import DEFAULT_API_URL, create_ui_app

DATEFMT = "%Y-%m-%d %H:%M:%S"

#: Seconds uvicorn waits for open connections on shutdown before closing them.
#: The map holds event streams open indefinitely, so without a bound Ctrl-C
#: would hang until every browser tab closed. Kept under SHUTDOWN_TIMEOUT so
#: `start all` sees its servers finish before it stops waiting for them.
GRACEFUL_SHUTDOWN_TIMEOUT = 2
SHUTDOWN_TIMEOUT = 10  # seconds to let a service finish its own shutdown


class DropNoiseFilter(logging.Filter):
    """Drop uvicorn's warning for non-HTTP bytes on the port (HTTPS attempts, LAN probes)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid HTTP request received" not in record.getMessage()


def _console_handler(fmt: str) -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt=DATEFMT))
    return handler


def _isolated_logger(name: str, fmt: str, level: int = logging.INFO) -> None:
    """Give a logger its own console format and stop it propagating to root."""
    log = logging.getLogger(name)
    log.setLevel(level)
    log.addHandler(_console_handler(fmt))
    log.propagate = False


def _echo_checks(checks: list[tuple[bool, str, str]]) -> None:
    """Print (ok, message-if-ok, message-if-not) checks for things that fail silently."""
    click.echo("Startup checks:")
    for ok, good, bad in checks:
        click.echo(f"  [{'ok' if ok else '!!'}] {good if ok else bad}")


def aircraft_db_option(f):
    """`--aircraft-db PATH`, applied eagerly so it is set before the command body runs."""

    def _apply(ctx, param, value):
        if value:
            set_aircraft_db_path(value)

    return click.option(
        "--aircraft-db",
        type=click.Path(dir_okay=False),
        metavar="PATH",
        is_eager=True,
        expose_value=False,
        callback=_apply,
        help="Aircraft database CSV location (default: per-user data dir)",
    )(f)


def feed_options(f):
    """Feed, database and decoding options shared by `start backend` and `start all`."""
    options = [
        click.option(
            "--db-path",
            default="adsb.db",
            help="Path to SQLite database file",
            show_default=True,
        ),
        click.option(
            "--source",
            type=click.Choice(["net"], case_sensitive=False),
            help="Data source (currently only 'net' is supported)",
        ),
        click.option(
            "--connect",
            nargs=3,
            metavar="HOST PORT TYPE",
            help="Connect to network source: HOST PORT TYPE (raw/beast)",
        ),
        click.option(
            "--stale-timeout",
            default=60,
            help=(
                "Seconds of silence after which an aircraft is hidden from /api/all (unless the "
                "caller asks for a wider max_age) and, if heard again, treated as a new contact. "
                "Aircraft are never deleted; use `adsb cleanup` to purge."
            ),
            show_default=True,
        ),
        click.option(
            "--metadata-retention",
            default=DEFAULT_METADATA_RETENTION,
            show_default=True,
            metavar="SECONDS",
            help=(
                "Delete reception metadata (RSSI, receiver serial) older than this while "
                "running; 0 keeps everything. Aircraft and positions are never deleted."
            ),
        ),
        click.option(
            "--lat",
            type=float,
            help="Receiver latitude (required for accurate position decoding)",
        ),
        click.option(
            "--lon",
            type=float,
            help="Receiver longitude (required for accurate position decoding)",
        ),
        click.option(
            "--stats-interval",
            default=10,
            show_default=True,
            metavar="SECONDS",
            help="Print a feed/decoding status line this often (0 to disable)",
        ),
        click.option(
            "--access-log",
            is_flag=True,
            help="Log every HTTP request (noisy: the map polls /api/all every second)",
        ),
    ]
    # Applied bottom-up, so `--help` lists them in the order written above.
    for option in reversed(options):
        f = option(f)
    return f


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
    warnings.filterwarnings("ignore", category=DeprecationWarning)


@main.group()
def start():
    """Start a service: `backend` (decoder + API), `frontend` (map UI),
    or `all` (backend + frontend in one command)."""


def _build_backend(
    db_path: str,
    source: str,
    connect: tuple,
    stale_timeout: int,
    lat: float,
    lon: float,
    stats_interval: int,
    access_log: bool,
    metadata_retention: int,
):
    """Configure logging, open the database, start the decoder, build the API app.

    Everything `start backend` does except bind a socket, so `start all` can
    reuse it and drive the server itself. Returns (app, log_config, reporter).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(_console_handler("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    _isolated_logger("adsb.data", "%(asctime)s - [ADSB] %(levelname)s - %(message)s")
    _isolated_logger("adsb.status", "%(asctime)s - [STATUS] %(message)s")
    logging.getLogger("adsb.decoder").setLevel(logging.WARNING)  # per-aircraft chatter

    # uvicorn configures its own loggers; give access logs an [API] prefix.
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "api": {
                "format": "%(asctime)s - [API] %(levelname)s - %(message)s",
                "datefmt": DATEFMT,
            },
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": DATEFMT,
            },
        },
        "filters": {
            "drop_noise": {"()": "adsb.cli.DropNoiseFilter"},
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
                "filters": ["drop_noise"],
            },
        },
        "loggers": {
            "uvicorn.access": {
                "handlers": ["api"],
                "level": "INFO" if access_log else "WARNING",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["default"],
                "level": "WARNING",  # hide uvicorn's own startup banner
                "propagate": False,
            },
        },
    }

    # Initialize database
    database = Database(db_path)
    database.create_tables()
    click.echo(f"Database initialized: {db_path}")
    with database.get_session() as session:
        if backfill_traffic(session):
            click.echo("Traffic history seeded from retained reception metadata")

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

        retained = f"{metadata_retention}s" if metadata_retention > 0 else "forever"
        click.echo(f"Reception metadata retained: {retained}")
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
            metadata_retention=metadata_retention,
        )
        click.echo("Network decoder started successfully")

    # Create FastAPI app with network client for graceful shutdown
    app = create_app(database, network_client, stale_timeout=stale_timeout)

    db = aircraft_db_path()
    _echo_checks(
        [
            (
                db.is_file(),
                f"Aircraft database: {db}",
                f"No aircraft database at {db} - run `adsb download` (or pass --aircraft-db)",
            ),
            (
                bool(source and connect),
                "Data source configured",
                "No data source - map stays empty; use --source net --connect HOST PORT TYPE",
            ),
        ]
    )

    reporter = None
    if stats_interval > 0:
        reporter = StatusReporter(
            database, network_client, interval=stats_interval, stale_timeout=stale_timeout
        ).start()

    return app, log_config, reporter


@start.command()
@click.option("--host", default="0.0.0.0", help="Host to bind the server to", show_default=True)
@click.option("--port", default=8000, help="Port to bind the server to", show_default=True)
@feed_options
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
    stats_interval: int,
    access_log: bool,
    metadata_retention: int,
    reload: bool,
):
    """
    Start the decoder and REST API.

    The map UI is a separate service: run `adsb start frontend` (on this or
    any other machine) and point it here with --api-url.

    Examples:

        # Start with default settings
        adsb start backend

        # Custom database path
        adsb start backend --db-path /path/to/adsb.db

        # With a network data source
        adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
    """
    app, log_config, reporter = _build_backend(
        db_path=db_path,
        source=source,
        connect=connect,
        stale_timeout=stale_timeout,
        lat=lat,
        lon=lon,
        stats_interval=stats_interval,
        access_log=access_log,
        metadata_retention=metadata_retention,
    )

    # uvicorn handles signals and triggers the FastAPI lifespan shutdown.
    click.echo(f"Starting API server on http://{host}:{port}/")
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
            log_config=log_config,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
        )
    finally:
        if reporter:
            reporter.stop()


def _build_frontend(api_url: str, demo: bool):
    """Everything `start frontend` does except bind a socket. Returns the app."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - [UI] %(levelname)s - %(message)s",
        datefmt=DATEFMT,
    )

    try:
        app = create_ui_app(api_url, demo=demo)
    except (RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e

    if demo:
        click.echo("Demo mode: simulated aircraft, no backend needed")
    else:
        click.echo(f"Backend API: {app.state.api_url}")
    _echo_checks(
        [
            (
                bool(os.environ.get("MAPBOX_TOKEN")),
                "Mapbox token set",
                "MAPBOX_TOKEN unset - map tiles will not render",
            ),
        ]
    )

    return app


@start.command()
@click.option(
    "--api-url",
    default=DEFAULT_API_URL,
    show_default=True,
    metavar="URL",
    help="Base URL of the `adsb start backend` to display, e.g. http://receiver.local:8000",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (use 0.0.0.0 to share on the LAN)",
    show_default=True,
)
@click.option("--port", default=3000, help="Port to bind to", show_default=True)
@click.option(
    "--demo",
    is_flag=True,
    help="Show simulated aircraft instead of a backend's data (nothing else needs to run)",
)
def frontend(api_url: str, host: str, port: int, demo: bool):
    """
    Start the map UI.

    Serves the bundled map and proxies /api/* to the backend given by
    --api-url (same machine by default), so the browser stays same-origin and
    the backend needs no CORS configuration. Needs MAPBOX_TOKEN in this
    process's environment or a .env file in the working directory.

    Examples:

        # Backend on this machine
        adsb start frontend

        # Backend on the receiver
        adsb start frontend --api-url http://receiver.local:8000

        # No backend at all: simulated traffic for trying out or testing the UI
        adsb start frontend --demo
    """
    app = _build_frontend(api_url, demo=demo)
    click.echo(f"Starting map UI on http://{host}:{port}/")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
    )


def _proxy_url(host: str, port: int) -> str:
    """Where the bundled UI should reach the backend it was started alongside.

    A wildcard bind is reachable on the loopback; a specific --host may not be,
    so proxy to the address the backend actually listens on.
    """
    target = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    return f"http://[{target}]:{port}" if ":" in target else f"http://{target}:{port}"


@start.command(name="all")
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind both services to (use 0.0.0.0 to share on the LAN)",
    show_default=True,
)
@click.option("--backend-port", default=8000, help="Backend bind port", show_default=True)
@click.option("--frontend-port", default=3000, help="Frontend bind port", show_default=True)
@feed_options
@aircraft_db_option
def all_(
    host: str,
    backend_port: int,
    frontend_port: int,
    db_path: str,
    source: str,
    connect: tuple,
    stale_timeout: int,
    lat: float,
    lon: float,
    stats_interval: int,
    access_log: bool,
    metadata_retention: int,
):
    """
    Start the backend and the map UI together.

    The same as running `adsb start backend` and `adsb start frontend` side by
    side, in one process: the UI proxies to the backend on --host, so only
    --host and --frontend-port decide who can reach the map.

    Examples:

        # Everything on this machine
        adsb start all --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

        # Share the map with the rest of the LAN
        adsb start all --host 0.0.0.0 --source net --connect localhost 30005 beast
    """
    # Built here, in order, so the backend's logging configuration wins over the
    # frontend's basicConfig() and a startup failure is reported before anything binds.
    backend_app, log_config, reporter = _build_backend(
        db_path=db_path,
        source=source,
        connect=connect,
        stale_timeout=stale_timeout,
        lat=lat,
        lon=lon,
        stats_interval=stats_interval,
        access_log=access_log,
        metadata_retention=metadata_retention,
    )
    frontend_app = _build_frontend(_proxy_url(host, backend_port), demo=False)

    servers = {
        "backend": uvicorn.Server(
            uvicorn.Config(
                backend_app,
                host=host,
                port=backend_port,
                log_config=log_config,
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
            )
        ),
        # log_config=None: the backend already configured uvicorn's loggers for
        # this process, and a second dictConfig would undo it.
        "frontend": uvicorn.Server(
            uvicorn.Config(
                frontend_app,
                host=host,
                port=frontend_port,
                log_config=None,
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
            )
        ),
    }
    ports = {"backend": backend_port, "frontend": frontend_port}

    failures: list[tuple[str, BaseException]] = []
    finished: list[str] = []
    first_exit = threading.Event()

    def _run(name: str, server: uvicorn.Server) -> None:
        try:
            server.run()
        except BaseException as err:  # uvicorn sys.exit()s when it cannot bind
            failures.append((name, err))
        finally:
            finished.append(name)
            first_exit.set()

    threads = [
        threading.Thread(target=_run, args=(name, server), name=f"adsb-{name}", daemon=True)
        for name, server in servers.items()
    ]

    # uvicorn installs its signal handlers only on the main thread, so neither
    # threaded server sees a shutdown signal. Relay them ourselves by setting
    # should_exit, which is what runs the FastAPI lifespan shutdown (and so closes
    # the Beast socket and the UI's HTTP client). Ctrl-C arrives as
    # KeyboardInterrupt below; SIGTERM -- how systemd, Docker and plain `kill` stop
    # the process -- has to be caught here or it terminates us outright. Installed
    # before the threads start, so there is no window where a signal is missed.
    stopping = False

    def _handle_sigterm(signum, frame) -> None:
        nonlocal stopping
        stopping = True
        click.echo("\nShutting down...")
        for server in servers.values():
            server.should_exit = True

    previous_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)

    for thread in threads:
        thread.start()

    click.echo(
        f"Starting ADS-B stack: backend=http://{host}:{backend_port}, "
        f"frontend=http://{host}:{frontend_port}"
    )

    try:
        first_exit.wait()
    except KeyboardInterrupt:
        stopping = True
        click.echo("\nShutting down...")
    finally:
        for server in servers.values():
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=SHUTDOWN_TIMEOUT)
        signal.signal(signal.SIGTERM, previous_sigterm)
        if reporter:
            reporter.stop()

    if failures:
        name, err = failures[0]
        detail = (
            f"exit status {err.code} - is port {ports[name]} already in use?"
            if isinstance(err, SystemExit)
            else f"{err.__class__.__name__}: {err}"
        )
        raise click.ClickException(f"{name} stopped: {detail}")
    if not stopping:
        raise click.ClickException(f"{finished[0]} stopped unexpectedly")


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
    with database.get_session() as session:
        if backfill_traffic(session):
            click.echo("Traffic history seeded from retained reception metadata")


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
@click.option(
    "--stale-timeout",
    default=60,
    help="Delete aircraft (and their history) not seen in this many seconds",
    show_default=True,
)
def cleanup(db_path: str, stale_timeout: int):
    """
    Purge stale aircraft from the database.

    The running backend never deletes aircraft or positions, so the database can
    be analysed offline. Run this only when you want to reclaim space.
    """
    database = Database(db_path)

    with database.get_session() as session:
        decoder = ADSBDecoder(session, stale_timeout=stale_timeout)
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
    Download the aircraft database (Mictronics, via tar1090-db).

    Downloads the latest aircraft database (566k+ records) as published by
    the tar1090-db repository, which mirrors the Mictronics aircraft
    database. The database maps ICAO24 addresses to aircraft registration,
    type code, and descriptions.

    The data is licensed under the Open Data Commons Attribution License
    (ODC-By) v1.0: keep the Mictronics credit with anything you build or
    publish from it. `adsb` shows it in the map's detail card and at /api.

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

    click.echo("Downloading aircraft database (Mictronics, via tar1090-db)...")
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
    click.echo(f"\n{AIRCRAFT_DB_NOTICE}")


if __name__ == "__main__":
    main()
