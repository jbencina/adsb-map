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
    ):
        """Initialize network client."""
        super().__init__(host, port, rawtype)
        self.database = database
        self.stale_timeout = stale_timeout
        self.cleanup_interval = cleanup_interval
        self.lat_ref = lat_ref
        self.lon_ref = lon_ref
        self.last_cleanup = time.time()
        self._stop_event = threading.Event()

        # Counters are written by the client thread and read by the status
        # reporter thread; the lock keeps snapshot() atomic.
        self._lock = threading.Lock()
        self.last_message_at: float | None = None
        self._interval = self._empty_interval()
        self.total_messages = 0
        self.total_positions = 0
        self.total_aircraft: set[str] = set()

    @staticmethod
    def _empty_interval() -> dict:
        return {
            "messages_received": 0,
            "messages_processed": 0,
            "messages_invalid": 0,
            "positions_decoded": 0,
            "aircraft_seen": set(),
            "errors": 0,
        }

    def snapshot(self) -> dict:
        """
        Return decoding statistics and reset the per-interval counters.

        Called by the status reporter once per interval. Totals accumulate
        for the life of the process.

        Returns
        -------
        dict
            ``interval`` (counts since the previous snapshot), ``total``
            (cumulative counts), and ``last_message_at`` (epoch seconds of the
            most recent message from the feed, or None if nothing yet)
        """
        with self._lock:
            interval = self._interval
            self._interval = self._empty_interval()
            return {
                "interval": {
                    "messages_received": interval["messages_received"],
                    "messages_processed": interval["messages_processed"],
                    "messages_invalid": interval["messages_invalid"],
                    "positions_decoded": interval["positions_decoded"],
                    "aircraft_seen": len(interval["aircraft_seen"]),
                    "errors": interval["errors"],
                },
                "total": {
                    "messages_processed": self.total_messages,
                    "positions_decoded": self.total_positions,
                    "aircraft_seen": len(self.total_aircraft),
                },
                "last_message_at": self.last_message_at,
            }

    def handle_messages(self, messages):
        """
        Handle incoming messages from the network stream.

        Parameters
        ----------
        messages : list of tuple
            List of (message, timestamp) tuples
        """
        if not messages:
            return

        with self._lock:
            self._interval["messages_received"] += len(messages)
            self.last_message_at = time.time()

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
                    with self._lock:
                        self._interval["messages_invalid"] += 1
                    continue

                try:
                    result = decoder.process_message(msg, timestamp=ts)
                except Exception as e:
                    with self._lock:
                        self._interval["errors"] += 1
                    adsb_logger.debug(f"Error processing message {msg}: {e}")
                    continue

                has_position = (
                    result is not None
                    and result.latitude is not None
                    and result.longitude is not None
                )
                with self._lock:
                    self._interval["messages_processed"] += 1
                    self.total_messages += 1
                    if result is not None:
                        self._interval["aircraft_seen"].add(result.icao24)
                        self.total_aircraft.add(result.icao24)
                    if has_position:
                        self._interval["positions_decoded"] += 1
                        self.total_positions += 1

            # Periodically cleanup stale aircraft
            current_time = time.time()
            if current_time - self.last_cleanup > self.cleanup_interval:
                removed = decoder.cleanup_stale_aircraft()
                if removed > 0:
                    adsb_logger.debug(f"Cleaned up {removed} stale aircraft")
                self.last_cleanup = current_time

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
