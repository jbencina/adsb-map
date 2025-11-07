"""Aircraft database loader and query module.

This module loads the aircraft database from CSV and provides lookup functions
to enrich aircraft data with registration, type code, and manufacturer information.
"""

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AircraftDatabase:
    """Aircraft database for looking up aircraft information by ICAO24 address."""

    def __init__(self, db_path: str | None = None):
        """Initialize the aircraft database.

        Args:
            db_path: Path to the aircraft CSV database file. If None, uses default path.
        """
        self.aircraft_data: dict[str, dict[str, str]] = {}
        self._load_database(db_path)

    def _load_database(self, db_path: str | None = None) -> None:
        """Load the aircraft database from CSV file.

        Args:
            db_path: Path to the aircraft CSV database file.
        """
        if db_path is None:
            # Default path relative to this module
            module_dir = Path(__file__).parent.parent
            db_path = module_dir / "data" / "aircraft.csv"
        else:
            db_path = Path(db_path)

        # If CSV doesn't exist but .gz does, extract it
        if not db_path.exists():
            gz_path = Path(str(db_path) + ".gz")
            if gz_path.exists():
                logger.info(f"Extracting aircraft database from {gz_path}")
                import gzip
                import shutil

                with gzip.open(gz_path, "rb") as f_in:
                    with open(db_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                logger.info(f"Extracted to {db_path}")

        if not db_path.exists():
            logger.warning(f"Aircraft database not found at {db_path}")
            return

        logger.info(f"Loading aircraft database from {db_path}")

        try:
            with open(db_path, encoding="utf-8", errors="replace") as f:
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
