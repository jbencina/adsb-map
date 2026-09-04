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
