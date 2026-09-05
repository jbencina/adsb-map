"""Shared helpers for tests that seed metadata rows or inspect the SQL the code emits."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, event, insert, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from adsb.models import AircraftMetadata


def add_metadata(session: Session, aircraft_id: int, timestamps: list[float]) -> None:
    """Bulk-insert one metadata row per timestamp; ``nanoseconds`` records insertion order."""
    session.execute(
        insert(AircraftMetadata),
        [
            {"aircraft_id": aircraft_id, "system_timestamp": ts, "nanoseconds": i, "rssi": -10.0}
            for i, ts in enumerate(timestamps)
        ],
    )


@contextmanager
def statements_containing(engine: Engine, needle: str) -> Iterator[list[str]]:
    """Collect every SQL statement containing ``needle`` that runs inside the block."""
    seen: list[str] = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        if needle in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", spy)


def query_plan(engine: Engine, stmt: Select) -> list[str]:
    """SQLite's EXPLAIN QUERY PLAN steps for a SQLAlchemy statement."""
    sql = str(stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    with engine.connect() as conn:
        return [row[-1] for row in conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"))]


@contextmanager
def serve(app) -> Iterator[str]:
    """
    Run ``app`` under uvicorn on a free loopback port for the block's duration.

    The in-process test transports (``TestClient``, ``httpx.ASGITransport``) run
    an app to completion before handing back a response, so an endless
    ``text/event-stream`` can only be exercised over a real socket.
    """
    import threading
    import time

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
