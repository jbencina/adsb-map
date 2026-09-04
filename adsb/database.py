"""Database configuration and session management."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex

from adsb.models import Base

logger = logging.getLogger(__name__)


class Database:
    """
    Database connection manager.

    Parameters
    ----------
    database_path : str
        Path to SQLite database file
    echo : bool, optional
        Enable SQL query logging, by default False
    """

    def __init__(self, database_path: str, echo: bool = False):
        """Initialize database connection."""
        self.database_path = database_path
        db_path = Path(database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Note: check_same_thread=False is required for FastAPI with SQLite
        # FastAPI uses multiple threads to handle requests, and SQLite by default
        # only allows connections to be used in the thread that created them.
        # This is safe because we're using connection pooling and sessions properly.
        self.engine = create_engine(
            f"sqlite:///{database_path}",
            echo=echo,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            # WAL lets the API read while the decoder thread commits a batch; in the
            # default rollback-journal mode each of those commits blocked every read.
            # journal_mode persists in the file, synchronous is per connection.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self) -> None:
        """Create all database tables, and any index missing from an existing file."""
        Base.metadata.create_all(bind=self.engine)
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """
        Create model-declared indexes that an existing database lacks.

        ``create_all`` leaves existing tables untouched, so a database created
        before an index was added to the models would never get it. There is no
        migration framework; this is the one schema change we need to apply.
        Building an index on a large table takes a few seconds, once.
        """
        inspector = inspect(self.engine)
        for table in Base.metadata.sorted_tables:
            existing = {ix["name"] for ix in inspector.get_indexes(table.name)}
            for index in table.indexes:
                if index.name not in existing:
                    logger.info("Creating index %s on %s", index.name, table.name)
                    # IF NOT EXISTS: another process may have won the race since we looked.
                    with self.engine.begin() as conn:
                        conn.execute(CreateIndex(index, if_not_exists=True))

    def dispose(self) -> None:
        """Dispose of the connection pool and close all connections."""
        self.engine.dispose()

    @contextmanager
    def get_session(self) -> Generator[Session]:
        """
        Get database session context manager.

        Yields
        ------
        Session
            SQLAlchemy database session
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
