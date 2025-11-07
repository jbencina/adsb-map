"""Database configuration and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from adsb.models import Base


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
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self) -> None:
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)

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
