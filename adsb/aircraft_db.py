"""Aircraft database loader and query module.

This module loads the aircraft database from CSV and provides lookup functions
to enrich aircraft data with registration, type code, and manufacturer information.
"""

import csv
import logging
from pathlib import Path

from platformdirs import user_data_dir

logger = logging.getLogger(__name__)

#: Location set by `--aircraft-db` on the CLI; None means the per-user default.
_configured_path: Path | None = None


def set_aircraft_db_path(path: str | Path | None) -> None:
    """Override the aircraft CSV location for this process.

    Called by the CLI when `--aircraft-db` is given, before anything loads the
    database. Configuration is deliberately a CLI argument rather than an
    environment variable: `.env` is reserved for secrets such as `MAPBOX_TOKEN`.

    Args:
        path: New location, or None to restore the per-user default.
    """
    global _configured_path
    _configured_path = Path(path) if path else None


def aircraft_db_path() -> Path:
    """Resolve the aircraft CSV location.

    Single source of truth shared by `adsb download` (which writes the file) and
    `AircraftDatabase` (which reads it), so the two can never disagree. Resolves to
    a per-user data directory rather than a path relative to the CWD or to the
    installed package -- the latter silently broke enrichment for pip installs,
    since nothing ever wrote to `site-packages/data/`.

    Returns:
        Path to `aircraft.csv`, overridable via `set_aircraft_db_path()`
        (the CLI's `--aircraft-db` option).
    """
    return _configured_path or Path(user_data_dir("adsb-map")) / "aircraft.csv"


class AircraftDatabase:
    """Aircraft database for looking up aircraft information by ICAO24 address."""

    def __init__(self, db_path: str | Path | None = None):
        """Initialize the aircraft database.

        Args:
            db_path: Path to the aircraft CSV file. Defaults to `aircraft_db_path()`.
        """
        self.path = Path(db_path) if db_path else aircraft_db_path()
        self.aircraft_data: dict[str, dict[str, str]] = {}
        self._load_database()

    def _load_database(self) -> None:
        """Load the aircraft database from CSV, leaving it empty if absent."""
        if not self.path.is_file():
            logger.warning(
                f"Aircraft database not found at {self.path} - "
                "run `adsb download` to enable registration/type lookup"
            )
            return

        logger.info(f"Loading aircraft database from {self.path}")

        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f, delimiter=";")

                for row in reader:
                    if len(row) < 5:
                        continue

                    icao24 = row[0].strip().lower()  # Store as lowercase for consistency
                    registration = row[1].strip() if len(row) > 1 else ""
                    typecode = row[2].strip() if len(row) > 2 else ""
                    # row[3] is unknown field, skip it
                    type_description = row[4].strip() if len(row) > 4 else ""

                    # Only store if we have at least some information
                    if registration or typecode or type_description:
                        self.aircraft_data[icao24] = {
                            "registration": registration,
                            "typecode": typecode,
                            "type_description": type_description,
                        }

            logger.info(f"Loaded {len(self.aircraft_data)} aircraft records")

        except Exception as e:
            logger.error(f"Error loading aircraft database: {e}")

    def lookup(self, icao24: str) -> dict[str, str] | None:
        """Look up aircraft information by ICAO24 address.

        Args:
            icao24: ICAO24 address (6 hex characters)

        Returns:
            Dictionary with keys: registration, typecode, type_description
            Returns None if not found.
        """
        if not icao24:
            return None

        # Normalize to lowercase for lookup
        icao24_lower = icao24.strip().lower()
        return self.aircraft_data.get(icao24_lower)

    def get_registration(self, icao24: str) -> str | None:
        """Get aircraft registration by ICAO24 address.

        Args:
            icao24: ICAO24 address

        Returns:
            Aircraft registration (tail number) or None if not found
        """
        info = self.lookup(icao24)
        return info["registration"] if info and info.get("registration") else None

    def get_type(self, icao24: str) -> str | None:
        """Get aircraft type code by ICAO24 address.

        Args:
            icao24: ICAO24 address

        Returns:
            Aircraft type code (e.g., B738, A320) or None if not found
        """
        info = self.lookup(icao24)
        return info["typecode"] if info and info.get("typecode") else None

    def get_type_description(self, icao24: str) -> str | None:
        """Get aircraft type description by ICAO24 address.

        Args:
            icao24: ICAO24 address

        Returns:
            Aircraft type description (e.g., BOEING 737-800) or None if not found
        """
        info = self.lookup(icao24)
        return info["type_description"] if info and info.get("type_description") else None


# Global instance for easy access
_global_db: AircraftDatabase | None = None


def get_database() -> AircraftDatabase:
    """Get the global aircraft database instance.

    Returns:
        AircraftDatabase instance
    """
    global _global_db
    if _global_db is None:
        _global_db = AircraftDatabase()
    return _global_db


def lookup_aircraft(icao24: str) -> dict[str, str] | None:
    """Convenience function to lookup aircraft using global database.

    Args:
        icao24: ICAO24 address

    Returns:
        Dictionary with aircraft information or None if not found
    """
    return get_database().lookup(icao24)
