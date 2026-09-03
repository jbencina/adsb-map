"""Tests for the periodic backend status line."""

import time
from unittest.mock import patch

from adsb.models import Aircraft
from adsb.network import ADSBNetworkClient
from adsb.status import StatusReporter, format_status, tracked_counts


def _client(test_db):
    return ADSBNetworkClient(host="rx.local", port=30005, rawtype="beast", database=test_db)


def _feed_one_message(client):
    with (
        patch("pyModeS.crc", return_value=0),
        patch("pyModeS.df", return_value=17),
        patch("pyModeS.icao", return_value="4840D6"),
        patch("pyModeS.adsb.typecode", return_value=1),
    ):
        client.handle_messages([("8D4840D6202CC371C32CE0576098", time.time())])


def test_snapshot_reports_and_resets_interval_counters(test_db):
    client = _client(test_db)
    assert client.snapshot()["last_message_at"] is None

    _feed_one_message(client)
    client.handle_messages([("8D4840", time.time())])  # invalid length

    first = client.snapshot()
    assert first["interval"]["messages_received"] == 2
    assert first["interval"]["messages_processed"] == 1
    assert first["interval"]["messages_invalid"] == 1
    assert first["interval"]["aircraft_seen"] == 1
    assert first["total"]["messages_processed"] == 1
    assert first["total"]["aircraft_seen"] == 1
    assert first["last_message_at"] is not None

    second = client.snapshot()
    assert second["interval"]["messages_received"] == 0
    assert second["total"]["messages_processed"] == 1  # totals persist


def test_tracked_counts(test_db):
    with test_db.get_session() as session:
        now = int(time.time())
        session.add(Aircraft(icao24="a", firstseen=now, lastseen=now, count=1))
        session.add(
            Aircraft(icao24="b", firstseen=now, lastseen=now, count=1, latitude=1.0, longitude=2.0)
        )
    assert tracked_counts(test_db) == (2, 1)


def test_format_status_without_feed():
    line = format_status(feed=None, stats=None, tracked=3, tracked_with_position=2, interval=10)
    assert line == "no data source | tracking 3 ac (2 w/ pos)"


def test_format_status_with_feed():
    stats = {
        "interval": {
            "messages_received": 1200,
            "messages_processed": 1100,
            "messages_invalid": 5,
            "positions_decoded": 80,
            "aircraft_seen": 12,
            "errors": 0,
        },
        "total": {"messages_processed": 50000, "positions_decoded": 4000, "aircraft_seen": 90},
        "last_message_at": 1000.0,
    }
    line = format_status(
        feed="rx.local:30005 (beast)",
        stats=stats,
        tracked=14,
        tracked_with_position=11,
        interval=10,
        now=1002.5,
    )
    assert line == (
        "feed rx.local:30005 (beast) | last msg 2s ago | "
        "10s: 1,200 msgs (120/s), 80 pos, 12 ac [5 invalid] | "
        "tracking 14 ac (11 w/ pos) | total 50,000 msgs, 4,000 pos, 90 ac"
    )


def test_format_status_flags_stalled_feed():
    stats = {
        "interval": dict.fromkeys(
            [
                "messages_received",
                "messages_processed",
                "messages_invalid",
                "positions_decoded",
                "aircraft_seen",
                "errors",
            ],
            0,
        ),
        "total": {"messages_processed": 1, "positions_decoded": 0, "aircraft_seen": 1},
        "last_message_at": 1000.0,
    }
    line = format_status(
        feed="rx:30005 (raw)",
        stats=stats,
        tracked=0,
        tracked_with_position=0,
        interval=10,
        now=1061.0,
    )
    assert "last msg 61s ago (feed stalled?)" in line

    stats["last_message_at"] = None
    line = format_status(
        feed="rx:30005 (raw)", stats=stats, tracked=0, tracked_with_position=0, interval=10
    )
    assert "no data yet" in line


def test_reporter_tick_emits_line(test_db):
    client = _client(test_db)
    _feed_one_message(client)
    lines = []
    reporter = StatusReporter(test_db, client, interval=10, emit=lines.append)

    line = reporter.tick()

    assert lines == [line]
    assert line.startswith("feed rx.local:30005 (beast) | last msg <1s ago | 10s: 1 msgs")
    assert "tracking 1 ac (0 w/ pos)" in line


def test_reporter_thread_runs_and_stops(test_db):
    lines = []
    reporter = StatusReporter(test_db, None, interval=0.05, emit=lines.append).start()
    deadline = time.time() + 2
    while not lines and time.time() < deadline:
        time.sleep(0.01)
    reporter.stop()
    reporter._thread.join(timeout=1)
    assert lines and lines[0].startswith("no data source")
    assert not reporter._thread.is_alive()
