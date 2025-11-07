"""Database models for aircraft data storage."""

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class Aircraft(Base):
    """
    Aircraft state information.

    Stores the current and historical state of tracked aircraft including
    position, velocity, identification, and other telemetry data.
    """

    __tablename__ = "aircraft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    icao24: Mapped[str] = mapped_column(String(6), unique=True, index=True, nullable=False)
    firstseen: Mapped[int] = mapped_column(Integer, nullable=False)
    lastseen: Mapped[int] = mapped_column(Integer, nullable=False)
    callsign: Mapped[str | None] = mapped_column(String(8), nullable=True)
    registration: Mapped[str | None] = mapped_column(String(10), nullable=True)
    typecode: Mapped[str | None] = mapped_column(String(4), nullable=True)
    type_description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    squawk: Mapped[str | None] = mapped_column(String(4), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_altitude: Mapped[int | None] = mapped_column(Integer, nullable=True)
    groundspeed: Mapped[float | None] = mapped_column(Float, nullable=True)
    vertical_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track: Mapped[float | None] = mapped_column(Float, nullable=True)
    ias: Mapped[float | None] = mapped_column(Float, nullable=True)
    tas: Mapped[float | None] = mapped_column(Float, nullable=True)
    mach: Mapped[float | None] = mapped_column(Float, nullable=True)
    roll: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    nacp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    positions: Mapped[list["AircraftPosition"]] = relationship(
        "AircraftPosition", back_populates="aircraft", cascade="all, delete-orphan"
    )
    reception_metadata: Mapped[list["AircraftMetadata"]] = relationship(
        "AircraftMetadata", back_populates="aircraft", cascade="all, delete-orphan"
    )


class AircraftPosition(Base):
    """
    Historical position data for aircraft trajectory tracking.

    Stores timestamped position data to enable track visualization.
    """

    __tablename__ = "aircraft_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_id: Mapped[int] = mapped_column(Integer, ForeignKey("aircraft.id"), nullable=False)
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    aircraft: Mapped["Aircraft"] = relationship("Aircraft", back_populates="positions")


class AircraftMetadata(Base):
    """
    Reception metadata for aircraft messages.

    Stores information about message reception including timing,
    signal strength, and receiver identification.
    """

    __tablename__ = "aircraft_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_id: Mapped[int] = mapped_column(Integer, ForeignKey("aircraft.id"), nullable=False)
    system_timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    nanoseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    rssi: Mapped[float | None] = mapped_column(Float, nullable=True)
    serial: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    aircraft: Mapped["Aircraft"] = relationship("Aircraft", back_populates="reception_metadata")
