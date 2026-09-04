"""Tests for database setup: SQLite pragmas and index backfill on existing files."""

from sqlalchemy import inspect, text

from adsb.database import Database

# Indexes added after the first release, which existing database files lack.
NEW_INDEXES = {
    "aircraft": "ix_aircraft_lastseen",
    "aircraft_metadata": "ix_aircraft_metadata_aircraft_id_system_timestamp",
    "aircraft_positions": "ix_aircraft_positions_aircraft_id_timestamp",
}


def index_names(database: Database, table: str) -> set[str]:
    return {ix["name"] for ix in inspect(database.engine).get_indexes(table)}


def test_wal_mode_and_synchronous_normal(test_db):
    """The decoder commits every batch; WAL keeps those commits from blocking API reads."""
    with test_db.get_session() as session:
        assert session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert session.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL


def test_create_tables_adds_missing_indexes_to_existing_db(tmp_path):
    """A database created before the indexes existed gets them on the next start.

    create_all() skips tables that already exist, so without a backfill an old
    adsb.db would keep its full-scan query plans forever.
    """
    path = str(tmp_path / "old.db")
    database = Database(path)
    database.create_tables()
    with database.engine.begin() as conn:
        for name in NEW_INDEXES.values():
            conn.execute(text(f"DROP INDEX {name}"))
    for table, name in NEW_INDEXES.items():
        assert name not in index_names(database, table)
    database.dispose()

    reopened = Database(path)
    reopened.create_tables()
    try:
        for table, name in NEW_INDEXES.items():
            assert name in index_names(reopened, table)
    finally:
        reopened.dispose()


def test_create_tables_is_idempotent(test_db):
    before = {t: index_names(test_db, t) for t in NEW_INDEXES}
    test_db.create_tables()
    assert {t: index_names(test_db, t) for t in NEW_INDEXES} == before
