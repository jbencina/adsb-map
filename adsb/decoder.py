"""ADS-B message decoder using pyModeS."""

import logging
import time

import pyModeS as pms
from sqlalchemy.orm import Session

from adsb.aircraft_db import get_database
from adsb.models import Aircraft, AircraftMetadata, AircraftPosition

logger = logging.getLogger(__name__)


class ADSBDecoder:
    """
    ADS-B message decoder and state manager.

    Decodes ADS-B messages using pyModeS and maintains aircraft state
    in the database.

    Parameters
    ----------
    session : Session
        SQLAlchemy database session
    stale_timeout : int, optional
        Seconds after which aircraft are removed from active tracking, by default 60
    """

    def __init__(
        self,
        session: Session,
        stale_timeout: int = 60,
        lat_ref: float | None = None,
        lon_ref: float | None = None,
    ):
        """Initialize decoder."""
        self.session = session
        self.stale_timeout = stale_timeout
        self.lat_ref = lat_ref
        self.lon_ref = lon_ref
        self.aircraft_db = get_database()

    def process_message(
        self,
        msg: str,
        timestamp: float | None = None,
        rssi: float | None = None,
        serial: int | None = None,
    ) -> Aircraft | None:
        """
        Process a single ADS-B message.

        Parameters
        ----------
        msg : str
            Hexadecimal ADS-B message
        timestamp : float, optional
            Message timestamp, by default current time
        rssi : float, optional
            Received Signal Strength Indicator
        serial : int, optional
            Receiver serial number
        """
        if timestamp is None:
            timestamp = time.time()

        # Validate message
        if not msg or not isinstance(msg, str):
            logger.warning(f"Invalid message type: {type(msg)}")
            return

        if not all(c in "0123456789ABCDEFabcdef" for c in msg):
            logger.warning(f"Invalid hex characters in message: {msg}")
            return

        if len(msg) not in [14, 28]:  # DF 4/5/11 or DF 17/18
            return

        try:
            if pms.crc(msg, encode=False) != 0:
                return
        except Exception as e:
            logger.debug(f"CRC check failed for message {msg}: {e}")
            return

        # Extract downlink format and ICAO address
        try:
            df = pms.df(msg)
            icao24 = pms.icao(msg).lower()
        except Exception as e:
            logger.warning(f"Failed to extract DF/ICAO from message {msg}: {e}")
            return

        # Get or create aircraft record
        aircraft = self.session.query(Aircraft).filter_by(icao24=icao24).first()
        current_time = int(timestamp)

        if aircraft is None:
            # Look up aircraft info from database
            aircraft_info = self.aircraft_db.lookup(icao24)

            # Create aircraft with database info if available
            aircraft = Aircraft(
                icao24=icao24,
                firstseen=current_time,
                lastseen=current_time,
                count=0,
                registration=aircraft_info.get("registration") if aircraft_info else None,
                typecode=aircraft_info.get("typecode") if aircraft_info else None,
                type_description=aircraft_info.get("type_description") if aircraft_info else None,
            )
            self.session.add(aircraft)

            if aircraft_info:
                logger.info(
                    f"New aircraft {icao24}: {aircraft_info.get('registration', 'N/A')} "
                    f"({aircraft_info.get('type_description', 'Unknown type')})"
                )

        # Update last seen time and message count
        aircraft.lastseen = current_time
        aircraft.count += 1

        # Add metadata
        metadata = AircraftMetadata(
            aircraft=aircraft,
            system_timestamp=timestamp,
            nanoseconds=int((timestamp % 1) * 1e9),
            rssi=rssi,
            serial=serial,
        )
        self.session.add(metadata)

        # Process different message types
        if df == 17:  # ADS-B
            self._process_adsb_message(msg, aircraft, current_time)
        elif df in [4, 20]:  # Altitude reply
            self._process_altitude_reply(msg, aircraft)
        elif df in [5, 21]:  # Identity reply
            self._process_identity_reply(msg, aircraft)

        # Flush to make objects queryable, but commit is handled by context manager
        self.session.flush()

        return aircraft

    def _process_adsb_message(self, msg: str, aircraft: Aircraft, timestamp: int) -> None:
        """
        Process ADS-B message (DF17).

        Parameters
        ----------
        msg : str
            Hexadecimal ADS-B message
        aircraft : Aircraft
            Aircraft database record
        timestamp : int
            Message timestamp
        """
        try:
            tc = pms.adsb.typecode(msg)

            # Typecode 1-4: Aircraft identification
            if 1 <= tc <= 4:
                callsign = pms.adsb.callsign(msg)
                if callsign:
                    aircraft.callsign = callsign.strip()

            # Typecode 5-8: Surface position
            elif 5 <= tc <= 8:
                # Note: Surface position decoding requires reference position
                # We'll skip this for now as it's more complex
                pass

            # Typecode 9-18: Airborne position (barometric altitude)
            elif 9 <= tc <= 18:
                try:
                    altitude = pms.adsb.altitude(msg)
                    if altitude is not None:
                        aircraft.altitude = altitude
                except Exception as e:
                    logger.warning(
                        f"Failed to decode altitude for {aircraft.icao24}: {e}",
                        exc_info=True,
                    )

                # Decode position if we have reference coordinates
                if self.lat_ref is not None and self.lon_ref is not None:
                    try:
                        position = pms.adsb.airborne_position_with_ref(
                            msg, self.lat_ref, self.lon_ref
                        )
                        if position:
                            lat, lon = position
                            if lat is not None and lon is not None:
                                aircraft.latitude = lat
                                aircraft.longitude = lon
                                # Save position to track history
                                position_record = AircraftPosition(
                                    aircraft=aircraft,
                                    timestamp=timestamp,
                                    latitude=lat,
                                    longitude=lon,
                                    altitude=aircraft.altitude,
                                )
                                self.session.add(position_record)
                    except Exception as e:
                        logger.warning(
                            f"Failed to decode airborne position for {aircraft.icao24}: {e}",
                            exc_info=True,
                        )

                # Store navigation accuracy
                nacp = self._extract_nacp(tc)
                if nacp is not None:
                    aircraft.nacp = nacp

            # Typecode 19: Airborne velocity
            elif tc == 19:
                try:
                    velocity = pms.adsb.velocity(msg)
                    if velocity:
                        speed, track, vrate, _ = velocity
                        if speed is not None:
                            aircraft.groundspeed = speed
                        if track is not None:
                            aircraft.track = track
                        if vrate is not None:
                            aircraft.vertical_rate = vrate
                except Exception as e:
                    logger.warning(
                        f"Failed to decode velocity for {aircraft.icao24}: {e}",
                        exc_info=True,
                    )

            # Typecode 20-22: Airborne position (GNSS altitude)
            elif 20 <= tc <= 22:
                try:
                    altitude = pms.adsb.altitude(msg)
                    if altitude is not None:
                        aircraft.altitude = altitude
                except Exception as e:
                    logger.warning(
                        f"Failed to decode GNSS altitude for {aircraft.icao24}: {e}",
                        exc_info=True,
                    )

                # Decode position if we have reference coordinates
                if self.lat_ref is not None and self.lon_ref is not None:
                    try:
                        position = pms.adsb.airborne_position_with_ref(
                            msg, self.lat_ref, self.lon_ref
                        )
                        if position:
                            lat, lon = position
                            if lat is not None and lon is not None:
                                aircraft.latitude = lat
                                aircraft.longitude = lon
                                # Save position to track history
                                position_record = AircraftPosition(
                                    aircraft=aircraft,
                                    timestamp=timestamp,
                                    latitude=lat,
                                    longitude=lon,
                                    altitude=aircraft.altitude,
                                )
                                self.session.add(position_record)
                    except Exception as e:
                        logger.warning(
                            f"Failed to decode GNSS position for {aircraft.icao24}: {e}",
                            exc_info=True,
                        )

        except Exception as e:
            logger.warning(
                f"Failed to process ADS-B message for {aircraft.icao24}: {e}",
                exc_info=True,
            )

    def _process_altitude_reply(self, msg: str, aircraft: Aircraft) -> None:
        """
        Process altitude reply (DF4/20).

        Parameters
        ----------
        msg : str
            Hexadecimal message
        aircraft : Aircraft
            Aircraft database record
        """
        try:
            altitude = pms.common.altcode(msg)
            if altitude is not None:
                aircraft.altitude = altitude
        except Exception as e:
            logger.warning(
                f"Failed to decode altitude reply for {aircraft.icao24}: {e}",
                exc_info=True,
            )

    def _process_identity_reply(self, msg: str, aircraft: Aircraft) -> None:
        """
        Process identity reply (DF5/21).

        Parameters
        ----------
        msg : str
            Hexadecimal message
        aircraft : Aircraft
            Aircraft database record
        """
        try:
            squawk = pms.common.idcode(msg)
            if squawk:
                aircraft.squawk = squawk
        except Exception as e:
            logger.warning(
                f"Failed to decode identity reply for {aircraft.icao24}: {e}",
                exc_info=True,
            )

    def _extract_nacp(self, typecode: int) -> int | None:
        """
        Extract Navigation Accuracy Category for Position from typecode.

        Parameters
        ----------
        typecode : int
            ADS-B typecode

        Returns
        -------
        int, optional
            NACP value
        """
        # Simplified NACP extraction based on typecode
        nacp_map = {
            9: 9,
            10: 9,
            11: 8,
            12: 8,
            13: 7,
            14: 7,
            15: 6,
            16: 6,
            17: 5,
            18: 4,
            20: 9,
            21: 8,
            22: 0,
        }
        return nacp_map.get(typecode)

    def cleanup_stale_aircraft(self) -> int:
        """
        Remove aircraft not seen within stale timeout.

        Returns
        -------
        int
            Number of aircraft removed
        """
        cutoff_time = int(time.time()) - self.stale_timeout
        stale = self.session.query(Aircraft).filter(Aircraft.lastseen < cutoff_time).all()

        count = len(stale)
        for aircraft in stale:
            self.session.delete(aircraft)

        # Flush to make deletions effective, but commit is handled by context manager
        self.session.flush()
        return count
