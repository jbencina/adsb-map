"""Network client for receiving ADS-B messages."""

import logging
import threading
import time

from pyModeS.extra.tcpclient import TcpClient

from adsb.database import Database
from adsb.decoder import ADSBDecoder

# Separate logger for ADSB data processing (different from API requests)
adsb_logger = logging.getLogger("adsb.data")
logger = logging.getLogger(__name__)


class ADSBNetworkClient(TcpClient):
    """
    Network client for receiving and decoding ADS-B messages.

    Extends pyModeS TcpClient to integrate with our database and decoder.

    Parameters
    ----------
    host : str
        Hostname or IP address of the data source
    port : int
        Port number of the data source
    rawtype : str
        Type of data format ('raw' or 'beast')
    database : Database
        Database instance for storing decoded data
    stale_timeout : int, optional
        Seconds before removing stale aircraft, by default 60
    cleanup_interval : int, optional
        Seconds between cleanup runs, by default 30
    """

    def __init__(
        self,
        host: str,
        port: int,
        rawtype: str,
        database: Database,
        stale_timeout: int = 60,
        cleanup_interval: int = 30,
        lat_ref: float | None = None,
        lon_ref: float | None = None,
        telemetry_interval: int = 30,
    ):
        """Initialize network client."""
        super().__init__(host, port, rawtype)
        self.database = database
        self.stale_timeout = stale_timeout
        self.cleanup_interval = cleanup_interval
        self.telemetry_interval = telemetry_interval
        self.lat_ref = lat_ref
        self.lon_ref = lon_ref
        self.last_cleanup = time.time()
        self.last_telemetry = time.time()
        self._stop_event = threading.Event()

        # Telemetry counters (reset every interval)
        self.interval_stats = {
            "messages_received": 0,
            "messages_processed": 0,
            "messages_invalid": 0,
            "positions_decoded": 0,
            "aircraft_seen": set(),
            "errors": 0,
        }

        # Cumulative stats
        self.total_stats = {
            "messages_processed": 0,
            "positions_decoded": 0,
            "aircraft_total": set(),
        }

    def handle_messages(self, messages):
        """
        Handle incoming messages from the network stream.

        Parameters
        ----------
        messages : list of tuple
            List of (message, timestamp) tuples
        """
        self.interval_stats["messages_received"] += len(messages)

        with self.database.get_session() as session:
            decoder = ADSBDecoder(
                session,
                stale_timeout=self.stale_timeout,
                lat_ref=self.lat_ref,
                lon_ref=self.lon_ref,
            )

            for msg, ts in messages:
                # Skip invalid message lengths
                if len(msg) not in [14, 28]:
                    self.interval_stats["messages_invalid"] += 1
                    continue

                try:
                    # Process the message
                    result = decoder.process_message(msg, timestamp=ts)
                    self.interval_stats["messages_processed"] += 1
                    self.total_stats["messages_processed"] += 1

                    # Track aircraft seen
                    if result and hasattr(result, "icao24"):
                        self.interval_stats["aircraft_seen"].add(result.icao24)
                        self.total_stats["aircraft_total"].add(result.icao24)

                        # Check if position was decoded
                        if result.latitude is not None and result.longitude is not None:
                            self.interval_stats["positions_decoded"] += 1
                            self.total_stats["positions_decoded"] += 1

                except Exception as e:
                    self.interval_stats["errors"] += 1
                    adsb_logger.debug(f"Error processing message {msg}: {e}")

            # Periodically cleanup stale aircraft
            current_time = time.time()
            if current_time - self.last_cleanup > self.cleanup_interval:
                removed = decoder.cleanup_stale_aircraft()
                if removed > 0:
                    adsb_logger.debug(f"Cleaned up {removed} stale aircraft")
                self.last_cleanup = current_time

            # Periodic telemetry logging
            if current_time - self.last_telemetry > self.telemetry_interval:
                self._log_telemetry(current_time)
                self.last_telemetry = current_time

    def _log_telemetry(self, current_time: float):
        """Log periodic telemetry statistics."""
        elapsed = current_time - (
            self.last_telemetry
            if hasattr(self, "last_telemetry")
            else current_time - self.telemetry_interval
        )

        # Calculate rates
        msg_rate = self.interval_stats["messages_received"] / elapsed if elapsed > 0 else 0
        pos_rate = self.interval_stats["positions_decoded"] / elapsed if elapsed > 0 else 0

        # Log interval statistics
        adsb_logger.info(
            f"[ADSB TELEMETRY] Interval: {elapsed:.1f}s | "
            f"Messages: {self.interval_stats['messages_received']} received, "
            f"{self.interval_stats['messages_processed']} processed, "
            f"{self.interval_stats['messages_invalid']} invalid | "
            f"Positions: {self.interval_stats['positions_decoded']} | "
            f"Aircraft: {len(self.interval_stats['aircraft_seen'])} | "
            f"Rates: {msg_rate:.1f} msg/s, {pos_rate:.1f} pos/s | "
            f"Errors: {self.interval_stats['errors']}"
        )

        # Log cumulative statistics
        adsb_logger.info(
            f"[ADSB CUMULATIVE] Total messages: {self.total_stats['messages_processed']:,} | "
            f"Total positions: {self.total_stats['positions_decoded']:,} | "
            f"Unique aircraft: {len(self.total_stats['aircraft_total'])}"
        )

        # Reset interval counters
        self.interval_stats = {
            "messages_received": 0,
            "messages_processed": 0,
            "messages_invalid": 0,
            "positions_decoded": 0,
            "aircraft_seen": set(),
            "errors": 0,
        }

    def stop(self):
        """Signal the client to stop gracefully."""
        self._stop_event.set()


def start_network_client(
    host: str,
    port: int,
    rawtype: str,
    database: Database,
    stale_timeout: int = 60,
    lat_ref: float | None = None,
    lon_ref: float | None = None,
) -> ADSBNetworkClient:
    """
    Start network client in a background thread.

    Parameters
    ----------
    host : str
        Hostname or IP address of the data source
    port : int
        Port number of the data source
    rawtype : str
        Type of data format ('raw' or 'beast')
    database : Database
        Database instance for storing decoded data
    stale_timeout : int, optional
        Seconds before removing stale aircraft, by default 60

    Returns
    -------
    ADSBNetworkClient
        Network client instance (thread is already started)
    """
    client = ADSBNetworkClient(
        host=host,
        port=int(port),
        rawtype=rawtype,
        database=database,
        stale_timeout=stale_timeout,
        lat_ref=lat_ref,
        lon_ref=lon_ref,
    )

    # Run client in background thread as daemon
    # Daemon threads are killed immediately when main process exits
    # We handle graceful shutdown via signal handlers in CLI
    thread = threading.Thread(target=client.run, daemon=True)
    thread.start()

    return client
