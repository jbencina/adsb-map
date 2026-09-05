"""FastAPI application for the ADS-B REST API.

API only: the map UI is a separate service (`adsb start frontend`, see `adsb.ui`)
that proxies to this one, so nothing here serves HTML, static files or CORS.
"""

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from adsb import __version__
from adsb.aircraft_db import AIRCRAFT_DB_ATTRIBUTION
from adsb.database import Database
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition
from adsb.schemas import (
    AircraftStateSchema,
    SensorSchema,
    StatsSchema,
    TopAircraftSchema,
    TrackPointSchema,
)
from adsb.stream import MEDIA_TYPE, SSE_HEADERS, updates
from adsb.traffic import (
    aircraft_seen_stmt,
    buckets_stmt,
    fill_buckets,
    grid_bounds,
    hour_of,
    top_lifetime_stmt,
    top_window_stmt,
)

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
            "/api/stats?window={seconds}&interval={seconds}&limit={n}": (
                "traffic history: messages and peak aircraft per interval, top aircraft"
            ),
            "/api/stream/aircraft?max_age={seconds}&interval={seconds}": (
                "server-sent events: the /api/all window, resent every interval"
            ),
            "/api/stream/tracks?scope=all|{icao24}&max_age={seconds}&interval={seconds}": (
                "server-sent events: the /api/tracks window, then only new positions"
            ),
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


def positions_after_stmt(last_id: int, aircraft_id: int | None = None) -> Select:
    """
    Positions stored after row ``last_id``, oldest first, with the icao24.

    The row id is the stream's cursor: one writer commits in id order, so
    "everything after the last id sent" is exact where a timestamp cutoff would
    have to overlap and still miss a late commit. A primary-key range scan over
    the last tick's rows, optionally narrowed to one aircraft.
    """
    stmt = (
        select(Aircraft.icao24, AircraftPosition)
        .join(Aircraft, Aircraft.id == AircraftPosition.aircraft_id)
        .where(AircraftPosition.id > last_id)
    )
    if aircraft_id is not None:
        stmt = stmt.where(AircraftPosition.aircraft_id == aircraft_id)
    return stmt.order_by(AircraftPosition.timestamp, AircraftPosition.id)


def aircraft_states(session: Session, cutoff: int) -> list[AircraftStateSchema]:
    """
    State vectors for every aircraft last seen at or after ``cutoff``.

    One statement for the aircraft and one for everyone's newest metadata,
    rather than one per aircraft. Shared by ``/api/all`` and its stream.
    """
    aircraft_list = session.execute(aircraft_since_stmt(cutoff)).scalars().all()

    by_aircraft: dict[int, list[AircraftMetadata]] = {}
    for m in session.execute(latest_metadata_stmt(cutoff)).scalars():
        by_aircraft.setdefault(m.aircraft_id, []).append(m)

    return [
        AircraftStateSchema(
            icao24=aircraft.icao24,
            firstseen=aircraft.firstseen,
            lastseen=aircraft.lastseen,
            callsign=aircraft.callsign,
            registration=aircraft.registration,
            typecode=aircraft.typecode,
            type_description=aircraft.type_description,
            squawk=aircraft.squawk,
            latitude=aircraft.latitude,
            longitude=aircraft.longitude,
            altitude=aircraft.altitude,
            selected_altitude=aircraft.selected_altitude,
            groundspeed=aircraft.groundspeed,
            vertical_rate=aircraft.vertical_rate,
            track=aircraft.track,
            ias=aircraft.ias,
            tas=aircraft.tas,
            mach=aircraft.mach,
            roll=aircraft.roll,
            heading=aircraft.heading,
            nacp=aircraft.nacp,
            count=aircraft.count,
            metadata=[
                {
                    "system_timestamp": m.system_timestamp,
                    "nanoseconds": m.nanoseconds,
                    "rssi": m.rssi,
                    "serial": m.serial,
                }
                for m in by_aircraft.get(aircraft.id, [])
            ],
        )
        for aircraft in aircraft_list
    ]


def _group_points(rows) -> dict[str, list[TrackPointSchema]]:
    """Group ``(icao24, AircraftPosition)`` rows, already in time order, by icao24."""
    tracks: dict[str, list[TrackPointSchema]] = {}
    for key, pos in rows:
        tracks.setdefault(key, []).append(
            TrackPointSchema(
                timestamp=pos.timestamp,
                latitude=pos.latitude,
                longitude=pos.longitude,
                altitude=pos.altitude,
            )
        )
    return tracks


def _aircraft_id(session: Session, icao24: str) -> int | None:
    return session.execute(
        select(Aircraft.id).where(Aircraft.icao24 == icao24.lower())
    ).scalar_one_or_none()


def track_points(
    session: Session, since: int | None, icao24: str | None = None
) -> dict[str, list[TrackPointSchema]]:
    """
    Positions at or after ``since``, oldest first, keyed by icao24.

    With ``icao24`` only that aircraft's points come back (``since`` may then be
    None for its whole retained track); an aircraft never heard is simply
    absent. Shared by ``/api/track``, ``/api/tracks`` and the tracks stream.
    """
    if icao24 is None:
        assert since is not None, "every aircraft's full history is never wanted"
        return _group_points(session.execute(tracks_stmt(since)))
    aircraft_id = _aircraft_id(session, icao24)
    if aircraft_id is None:
        return {}
    positions = session.execute(track_stmt(aircraft_id, since)).scalars()
    return _group_points((icao24.lower(), pos) for pos in positions)


#: The tracks stream's cursor: the id and timestamp of the newest position sent.
TrackCursor = tuple[int, int]


def encode_track_cursor(cursor: TrackCursor) -> str:
    """``id:timestamp`` as sent in the SSE ``id`` field."""
    return f"{cursor[0]}:{cursor[1]}"


def parse_track_cursor(value: str | None) -> TrackCursor | None:
    """A ``Last-Event-ID`` back into a cursor, or None when absent or not one of ours."""
    if not value:
        return None
    try:
        row_id, stamp = value.split(":")
        return int(row_id), int(stamp)
    except ValueError:
        return None


def newest_position(session: Session) -> TrackCursor:
    """Id and timestamp of the last stored position, or ``(0, 0)`` with none."""
    row = session.execute(
        select(AircraftPosition.id, AircraftPosition.timestamp)
        .order_by(AircraftPosition.id.desc())
        .limit(1)
    ).first()
    return (row.id, row.timestamp) if row else (0, 0)


def cursor_is_current(session: Session, cursor: TrackCursor) -> bool:
    """
    Whether the cursor's row is still there with the timestamp it had.

    Positions have no AUTOINCREMENT, so once ``adsb cleanup`` deletes the
    newest rows SQLite hands their ids out again, and "everything after id N"
    would silently skip the reused ones. A cursor row that is gone or carries a
    different timestamp means the table changed underneath the stream. ``(0, 0)``
    was an empty table and has nothing to have been reused.
    """
    row_id, stamp = cursor
    if row_id == 0:
        return True
    found = session.execute(
        select(AircraftPosition.timestamp).where(AircraftPosition.id == row_id)
    ).scalar()
    return found == stamp


def track_points_after(
    session: Session, cursor: TrackCursor, icao24: str | None = None
) -> tuple[dict[str, list[TrackPointSchema]], TrackCursor]:
    """
    Positions stored after the cursor's row and the new cursor, for the tracks stream.

    Returns
    -------
    tuple
        Points keyed by icao24, and the newest row among them (``cursor`` if none)
    """
    aircraft_id = None
    if icao24 is not None:
        aircraft_id = _aircraft_id(session, icao24)
        if aircraft_id is None:
            return {}, cursor
    rows = session.execute(positions_after_stmt(cursor[0], aircraft_id)).all()
    newest = max(((pos.id, pos.timestamp) for _, pos in rows), default=cursor)
    return _group_points(rows), newest


def tracks_update(
    session: Session, cursor: str | None, cutoff: int, icao24: str | None = None
) -> tuple[dict[str, list[TrackPointSchema]], str]:
    """
    One event's worth of the tracks stream: positions to send and the cursor to send them with.

    With no usable cursor the event is the window snapshot. The cursor is read
    before the snapshot rather than after: the driver runs each SELECT in its
    own implicit transaction, so a position committed between the two reads
    then shows up in the snapshot *and* again next tick, instead of falling
    past the cursor and never being sent. The client drops the repeat.

    A cursor whose row has changed (see ``cursor_is_current``) starts the
    stream over from the window rather than skipping reused ids.
    """
    parsed = parse_track_cursor(cursor)
    if parsed is not None and not cursor_is_current(session, parsed):
        parsed = None
    if parsed is None:
        parsed = newest_position(session)
        return track_points(session, cutoff, icao24), encode_track_cursor(parsed)
    points, newest = track_points_after(session, parsed, icao24)
    return points, encode_track_cursor(newest)


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
        return aircraft_states(session, seen_since(max_age))

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
        return track_points(session, since, icao24).get(icao24.lower(), [])

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
        return track_points(session, since if since is not None else seen_since(max_age))

    interval_query = Query(1, ge=1, le=60, description="Seconds between events.")

    def event_stream(load, cursor: int | None, interval: int) -> StreamingResponse:
        return StreamingResponse(
            updates(load, cursor=cursor, interval=interval),
            media_type=MEDIA_TYPE,
            headers=SSE_HEADERS,
        )

    @app.get("/api/stream/aircraft", response_class=StreamingResponse)
    async def stream_aircraft(max_age: int | None = max_age_query, interval: int = interval_query):
        """
        Server-sent events: what ``/api/all`` returns for the window, every interval.

        Each ``update`` event carries the whole list, so a client replaces what it
        holds rather than merging. Most aircraft are heard every second, so a
        delta would be nearly the whole list anyway, and a full list also
        reflects metadata trimmed by retention. The event id is the tick's unix
        time and is not a resume cursor: a reconnect just gets the window again.
        """

        def load(_cursor: str | None) -> tuple[list[dict], str]:
            with get_db().get_session() as session:
                states = aircraft_states(session, seen_since(max_age))
            return [a.model_dump() for a in states], str(int(time.time()))

        return event_stream(load, None, interval)

    @app.get("/api/stream/tracks", response_class=StreamingResponse)
    async def stream_tracks(
        request: Request,
        scope: str = Query(
            ...,
            pattern=r"^(all|[0-9a-fA-F]{6})$",
            description="`all` for every aircraft, or one ICAO 24-bit address.",
        ),
        max_age: int | None = max_age_query,
        interval: int = interval_query,
    ):
        """
        Server-sent events: ``/api/tracks`` for the window, then only new positions.

        Each ``update`` event is a JSON object shaped like ``/api/tracks``; append
        its points to the lines held. The event id names the newest position row
        sent, so a reconnect with ``Last-Event-ID`` resumes exactly after it.
        An aircraft not heard yet is simply absent until it appears, so
        selecting one before its first position is not an error.
        """
        icao24 = None if scope == "all" else scope.lower()

        def load(cursor: str | None) -> tuple[dict[str, list[dict]], str]:
            with get_db().get_session() as session:
                points, cursor = tracks_update(session, cursor, seen_since(max_age), icao24)
            return {k: [p.model_dump() for p in v] for k, v in points.items()}, cursor

        return event_stream(load, request.headers.get("last-event-id"), interval)

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

    @app.get("/api/stats", response_model=StatsSchema)
    async def get_stats(
        window: int = Query(86400, ge=60, le=604800, description="History window in seconds"),
        interval: int = Query(900, ge=60, le=86400, description="Bucket size in seconds"),
        limit: int = Query(10, ge=1, le=100, description="Rows per top-aircraft list"),
        session: Session = Depends(get_session),
    ):
        """
        Traffic history for the map's history view.

        Buckets are aligned to ``interval`` and end at the current interval, so
        the last bucket is partial. ``aircraft`` per bucket is the peak number
        of distinct aircraft heard in any single minute of that bucket. The top
        lists rank aircraft by messages within the window (rounded down to the
        hour the window starts in) and by lifetime message count. Read from the
        per-minute and per-aircraft-hour aggregates, never the per-message rows.

        Parameters
        ----------
        window : int
            Seconds of history, default one day
        interval : int
            Bucket size in seconds; must divide ``window`` evenly
        limit : int
            Rows in each top list
        session : Session
            Database session

        Returns
        -------
        StatsSchema
            Zero-filled bucket grid plus both top lists
        """
        if window % interval:
            raise HTTPException(status_code=422, detail="interval must divide window evenly")
        now = int(time.time())
        since, end = grid_bounds(now, window, interval)
        since_hour = hour_of(since)

        rows = session.execute(buckets_stmt(since, interval)).all()
        buckets = fill_buckets(rows, since, end, interval)
        aircraft_seen = session.execute(aircraft_seen_stmt(since_hour)).scalar() or 0

        def row(aircraft: Aircraft, messages: int) -> TopAircraftSchema:
            return TopAircraftSchema(
                icao24=aircraft.icao24,
                callsign=aircraft.callsign,
                registration=aircraft.registration,
                typecode=aircraft.typecode,
                messages=messages,
                lastseen=aircraft.lastseen,
            )

        top_window = [row(a, m) for a, m in session.execute(top_window_stmt(since_hour, limit))]
        top_lifetime = [
            row(a, a.count) for a in session.execute(top_lifetime_stmt(limit)).scalars()
        ]
        return StatsSchema(
            now=now,
            window=window,
            interval=interval,
            aircraft_seen=aircraft_seen,
            buckets=buckets,
            top_window=top_window,
            top_lifetime=top_lifetime,
        )

    return app
