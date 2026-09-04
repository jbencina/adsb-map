"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, Field


class MetadataSchema(BaseModel):
    """
    Reception metadata schema.

    Attributes
    ----------
    system_timestamp : float
        System timestamp when message was received
    nanoseconds : int
        Nanosecond precision timestamp
    rssi : float, optional
        Received Signal Strength Indicator
    serial : int, optional
        Receiver serial number
    """

    system_timestamp: float
    nanoseconds: int
    rssi: float | None = None
    serial: int | None = None

    model_config = {"from_attributes": True}


class AircraftStateSchema(BaseModel):
    """
    Aircraft state vector schema matching jet1090 API format.

    Attributes
    ----------
    icao24 : str
        ICAO 24-bit address
    firstseen : int
        Unix timestamp of first observation
    lastseen : int
        Unix timestamp of last observation
    callsign : str, optional
        Aircraft callsign
    registration : str, optional
        Aircraft registration
    typecode : str, optional
        Aircraft type code
    type_description : str, optional
        Aircraft type description
    squawk : str, optional
        Transponder squawk code
    latitude : float, optional
        Latitude in degrees
    longitude : float, optional
        Longitude in degrees
    altitude : int, optional
        Altitude in feet
    selected_altitude : int, optional
        Selected/target altitude in feet
    groundspeed : float, optional
        Ground speed in knots
    vertical_rate : int, optional
        Vertical rate in feet per minute
    track : float, optional
        Track angle in degrees
    ias : float, optional
        Indicated airspeed in knots
    tas : float, optional
        True airspeed in knots
    mach : float, optional
        Mach number
    roll : float, optional
        Roll angle in degrees
    heading : float, optional
        Heading in degrees
    nacp : int, optional
        Navigation Accuracy Category for Position
    count : int
        Number of messages received
    metadata : list[MetadataSchema]
        Reception metadata list
    """

    icao24: str
    firstseen: int
    lastseen: int
    callsign: str | None = None
    registration: str | None = None
    typecode: str | None = None
    type_description: str | None = None
    squawk: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: int | None = None
    selected_altitude: int | None = None
    groundspeed: float | None = None
    vertical_rate: int | None = None
    track: float | None = None
    ias: float | None = None
    tas: float | None = None
    mach: float | None = None
    roll: float | None = None
    heading: float | None = None
    nacp: int | None = None
    count: int = 0
    metadata: list[MetadataSchema] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TrackPointSchema(BaseModel):
    """
    Track point schema for trajectory data.

    Attributes
    ----------
    timestamp : int
        Unix timestamp
    latitude : float
        Latitude in degrees
    longitude : float
        Longitude in degrees
    altitude : int, optional
        Altitude in feet
    """

    timestamp: int
    latitude: float
    longitude: float
    altitude: int | None = None

    model_config = {"from_attributes": True}


class SensorSchema(BaseModel):
    """
    Sensor information schema.

    Attributes
    ----------
    serial : int
        Receiver serial number
    """

    serial: int

    model_config = {"from_attributes": True}


class StatsBucketSchema(BaseModel):
    """
    One interval of the traffic history.

    Attributes
    ----------
    start : int
        Unix timestamp the interval begins at
    messages : int
        Messages attributed to an aircraft in the interval
    aircraft : int
        Peak number of distinct aircraft heard in any one minute of the interval
    """

    start: int
    messages: int
    aircraft: int


class TopAircraftSchema(BaseModel):
    """One row of a top-aircraft table."""

    icao24: str
    callsign: str | None = None
    registration: str | None = None
    typecode: str | None = None
    messages: int
    lastseen: int


class StatsSchema(BaseModel):
    """
    Response of ``/api/stats``.

    Attributes
    ----------
    now : int
        Server time the response was built at
    window, interval : int
        Echo of the request, in seconds
    aircraft_seen : int
        Distinct aircraft heard in the window
    buckets : list[StatsBucketSchema]
        Full grid, oldest first, ending in the current (partial) interval
    top_window, top_lifetime : list[TopAircraftSchema]
        Aircraft ranked by messages in the window and by lifetime message count
    """

    now: int
    window: int
    interval: int
    aircraft_seen: int
    buckets: list[StatsBucketSchema]
    top_window: list[TopAircraftSchema]
    top_lifetime: list[TopAircraftSchema]
