"""Network client for receiving ADS-B messages."""

import logging
import math
import threading
import time

import pyModeS as pms
from pyModeS.extra.tcpclient import TcpClient

from adsb.database import Database
from adsb.decoder import DEFAULT_METADATA_RETENTION, METADATA_PURGE_INTERVAL, ADSBDecoder

# Separate logger for ADSB data processing (different from API requests)
adsb_logger = logging.getLogger("adsb.data")
logger = logging.getLogger(__name__)

BEAST_ESC = 0x1A
# Beast frame layout: type byte, 6-byte MLAT timestamp, 1-byte signal level, payload.
BEAST_HEADER_LEN = 8
BEAST_PAYLOAD_LEN = {0x31: 2, 0x32: 7, 0x33: 14}  # Mode-AC, Mode-S short, Mode-S long
BEAST_MODE_S_TYPES = (0x32, 0x33)


def beast_signal_to_dbfs(level: int) -> float | None:
    """
    Convert a Beast signal-level byte (0-255) to dBFS.

    Matches the dump1090/readsb ``rssi`` convention (0 dBFS is full scale).
    A level of 0 means the source had no signal information, so returns None.
    """
    if level <= 0:
        return None
    return 20 * math.log10(level / 255)


def _split_beast_frames(buffer: list[int]) -> tuple[list[bytearray], list[int]]:
    """
    Split a raw Beast byte stream into unescaped frames.

    Returns the complete frames and the unconsumed tail of the buffer (an
    unterminated frame or a dangling escape byte) to carry into the next read.
    A frame is complete when it reaches the fixed length for its type, or when
    the next frame's escape byte arrives.
    """
    frames: list[bytearray] = []
    current: bytearray | None = None
    remainder_start = len(buffer)
    i = 0
    n = len(buffer)

    def push(b: int, end: int) -> None:
        """Append a decoded byte to the current frame, emitting it if complete."""
        nonlocal current, remainder_start
        if current is None:
            return
        current.append(b)
        expected = BEAST_PAYLOAD_LEN.get(current[0])
        if expected is not None and len(current) == BEAST_HEADER_LEN + expected:
            frames.append(current)
            current = None
            remainder_start = end

    while i < n:
        b = buffer[i]
        if b == BEAST_ESC:
            if i + 1 >= n:
                # Dangling escape: keep the in-progress frame (if any) and the
                # escape byte for the next read.
                if current is None:
                    remainder_start = i
                break
            if buffer[i + 1] == BEAST_ESC:
                push(BEAST_ESC, i + 2)
                i += 2
                continue
            if current is not None:
                frames.append(current)
            current = bytearray()
            remainder_start = i
            i += 1
            continue
        push(b, i + 1)
        i += 1
    return frames, buffer[remainder_start:]


def _decode_beast_frame(frame: bytearray) -> tuple[str, float | None] | None:
    """Return (hex message, rssi dBFS) for a Mode-S frame, or None to skip it."""
    msgtype = frame[0]
    if msgtype not in BEAST_MODE_S_TYPES:
        return None
    payload_len = BEAST_PAYLOAD_LEN[msgtype]
    if len(frame) < BEAST_HEADER_LEN + payload_len:
        return None
    msg = frame[BEAST_HEADER_LEN : BEAST_HEADER_LEN + payload_len].hex().upper()
    # Same DF/length sanity check pyModeS applies
    df = pms.df(msg)
    if df in [0, 4, 5, 11] and len(msg) != 14:
        return None
    if df in [16, 17, 18, 19, 20, 21, 24] and len(msg) != 28:
        return None
    return msg, beast_signal_to_dbfs(frame[7])


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
        Seconds of silence after which an aircraft heard again is a new contact
        (see :class:`ADSBDecoder`), by default 60
    lat_ref, lon_ref : float, optional
        Receiver position for CPR decoding
    metadata_retention : int, optional
        Delete reception metadata older than this many seconds; 0 keeps it all.
        By default ``DEFAULT_METADATA_RETENTION``
    cleanup_interval : int, optional
        Seconds between metadata purges, by default ``METADATA_PURGE_INTERVAL``

    Aircraft and their positions are only ever added: aircraft that stop
    transmitting stay in the database for offline analysis, and the API hides
    them by age instead. Reception metadata is trimmed to ``metadata_retention``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        rawtype: str,
        database: Database,
        stale_timeout: int = 60,
        lat_ref: float | None = None,
        lon_ref: float | None = None,
        metadata_retention: int = DEFAULT_METADATA_RETENTION,
        cleanup_interval: int = METADATA_PURGE_INTERVAL,
    ):
        """Initialize network client."""
        super().__init__(host, port, rawtype)
        self.database = database
        self.stale_timeout = stale_timeout
        self.lat_ref = lat_ref
        self.lon_ref = lon_ref
        self.metadata_retention = metadata_retention
        self.cleanup_interval = cleanup_interval
        self.last_cleanup = 0.0
        self._stop_event = threading.Event()

        # Written by the client thread, read by the status reporter thread.
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

        Returns
        -------
        dict
            ``interval`` (counts since the previous snapshot), ``total``
            (cumulative counts) and ``last_message_at`` (epoch seconds of the
            most recent feed message, or None if nothing has arrived)
        """
        with self._lock:
            interval, self._interval = self._interval, self._empty_interval()
            return {
                "interval": {**interval, "aircraft_seen": len(interval["aircraft_seen"])},
                "total": {
                    "messages_processed": self.total_messages,
                    "positions_decoded": self.total_positions,
                    "aircraft_seen": len(self.total_aircraft),
                },
                "last_message_at": self.last_message_at,
            }

    def read_beast_buffer(self):
        """
        Parse Beast frames from ``self.buffer``, keeping the signal level.

        Overrides the pyModeS parser (which discards the signal byte) and is
        called by the inherited ``run`` loop when ``rawtype`` is ``beast``.

        Returns
        -------
        list of tuple
            (message, timestamp, rssi) tuples; rssi is dBFS or None
        """
        frames, self.buffer = _split_beast_frames(self.buffer)
        ts = time.time()
        messages = []
        for frame in frames:
            decoded = _decode_beast_frame(frame)
            if decoded is not None:
                messages.append((decoded[0], ts, decoded[1]))
        return messages

    def handle_messages(self, messages):
        """
        Handle incoming messages from the network stream.

        Parameters
        ----------
        messages : list of tuple
            List of (message, timestamp) or (message, timestamp, rssi) tuples
        """
        if not messages:
            return

        batch = self._empty_interval()
        batch["messages_received"] = len(messages)

        with self.database.get_session() as session:
            decoder = ADSBDecoder(
                session,
                stale_timeout=self.stale_timeout,
                lat_ref=self.lat_ref,
                lon_ref=self.lon_ref,
            )

            for msg, ts, *extra in messages:
                rssi = extra[0] if extra else None
                if len(msg) not in [14, 28]:
                    batch["messages_invalid"] += 1
                    continue
                try:
                    result = decoder.process_message(msg, timestamp=ts, rssi=rssi)
                except Exception as e:
                    batch["errors"] += 1
                    adsb_logger.debug(f"Error processing message {msg}: {e}")
                    continue
                batch["messages_processed"] += 1
                if result is not None:
                    batch["aircraft_seen"].add(result.icao24)
                    if result.latitude is not None and result.longitude is not None:
                        batch["positions_decoded"] += 1

            # Trim reception metadata now and then; the decoder is a no-op at retention 0.
            now = time.time()
            if now - self.last_cleanup >= self.cleanup_interval:
                self.last_cleanup = now
                try:
                    removed = decoder.purge_old_metadata(self.metadata_retention, now=now)
                    adsb_logger.debug(f"Purged {removed} old metadata rows")
                except Exception as e:  # housekeeping must never take the feed down
                    adsb_logger.warning(f"Metadata purge failed, will retry: {e}")

            # One lock per batch rather than per message; the reporter only
            # needs a consistent view, not real-time updates.
            with self._lock:
                self.last_message_at = now
                for key in (
                    "messages_received",
                    "messages_processed",
                    "messages_invalid",
                    "positions_decoded",
                    "errors",
                ):
                    self._interval[key] += batch[key]
                self._interval["aircraft_seen"] |= batch["aircraft_seen"]
                self.total_messages += batch["messages_processed"]
                self.total_positions += batch["positions_decoded"]
                self.total_aircraft |= batch["aircraft_seen"]

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
    metadata_retention: int = DEFAULT_METADATA_RETENTION,
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
        Seconds of silence after which an aircraft heard again is a new contact
    lat_ref, lon_ref : float, optional
        Receiver position for CPR decoding
    metadata_retention : int, optional
        Delete reception metadata older than this many seconds; 0 keeps it all

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
        metadata_retention=metadata_retention,
    )

    # Run client in background thread as daemon
    # Daemon threads are killed immediately when main process exits
    # We handle graceful shutdown via signal handlers in CLI
    thread = threading.Thread(target=client.run, daemon=True)
    thread.start()

    return client
