# History Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-screen history overlay over the map showing 24 h of message volume, 24 h of aircraft counts, and two top-10 aircraft tables, fed by two small aggregate tables the decoder maintains.

**Architecture:** The network client accumulates per-minute message/aircraft counts and per-aircraft-per-hour message counts for each batch and upserts them into `traffic_minutes` and `aircraft_hourly` (new module `adsb/traffic.py`). A new `GET /api/stats` bucketizes those tables. The React app gains a `HistoryOverlay` rendered above the map, a `useStats` hook, a CSS bar chart and a table component, with demo-mode support.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (SQLite upsert), FastAPI, pytest; React 18, Vite, `bun test`, hand-rolled CSS.

**Spec:** `docs/superpowers/specs/2026-09-04-history-overlay-design.md`

## Global Constraints

- Metadata retention default stays `3600`; no new CLI flags.
- Traffic retention constant: `TRAFFIC_RETENTION = 7 * 86400`.
- Timestamps: integer epoch seconds, UTC, everywhere in SQL and the API.
- No new frontend dependencies. Icons are inline SVG, `stroke="currentColor"`, `strokeWidth="1.75"`.
- Every commit message ends with the two attribution trailers used on this branch.
- Existing map behaviour and CSS class names used by the map must keep working.

---

### Task 1: Aggregate tables and the traffic writer

**Files:**
- Modify: `adsb/models.py` (append two models, add `index=True` on `Aircraft.count`)
- Create: `adsb/traffic.py`
- Create: `tests/test_traffic.py`
- Modify: `tests/test_database.py:8-12` (`NEW_INDEXES`)

**Interfaces:**
- Produces: `TrafficMinute(minute:int PK, messages:int, aircraft:int)`, `AircraftHourly(aircraft_id:int, hour:int, messages:int)` with PK `(aircraft_id, hour)` and index `ix_aircraft_hourly_hour`; `ix_aircraft_count` on `aircraft.count`.
- Produces: `traffic.minute_of(ts: float) -> int`, `traffic.hour_of(ts: float) -> int`, `traffic.record_batch(session, minutes: dict[int, tuple[int, int]], hourly: dict[tuple[int, int], int]) -> None`, `traffic.purge_traffic(session, now: float, retention: int = TRAFFIC_RETENTION) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_traffic.py
"""Tests for the per-minute / per-aircraft-hour traffic aggregates."""

import time

from sqlalchemy import select

from adsb.models import Aircraft, AircraftHourly, TrafficMinute
from adsb.traffic import (
    TRAFFIC_RETENTION,
    hour_of,
    minute_of,
    purge_traffic,
    record_batch,
)


def test_minute_and_hour_floor_to_integer_seconds():
    assert minute_of(1788556190.73) == 1788556140
    assert hour_of(1788556190.73) == 1788555600


def test_record_batch_accumulates_messages_and_keeps_max_aircraft(test_db, aircraft):
    minute = minute_of(time.time())
    hour = hour_of(time.time())
    with test_db.get_session() as session:
        record_batch(session, {minute: (5, 3)}, {(aircraft.id, hour): 5})
    with test_db.get_session() as session:
        record_batch(session, {minute: (2, 2)}, {(aircraft.id, hour): 2})
    with test_db.get_session() as session:
        row = session.get(TrafficMinute, minute)
        assert (row.messages, row.aircraft) == (7, 3)
        hourly = session.get(AircraftHourly, (aircraft.id, hour))
        assert hourly.messages == 7


def test_record_batch_with_nothing_is_a_no_op(test_db):
    with test_db.get_session() as session:
        record_batch(session, {}, {})
        assert session.execute(select(TrafficMinute)).all() == []


def test_purge_traffic_drops_rows_older_than_retention(test_db, aircraft):
    now = time.time()
    old = minute_of(now - TRAFFIC_RETENTION - 120)
    fresh = minute_of(now)
    with test_db.get_session() as session:
        record_batch(
            session,
            {old: (1, 1), fresh: (1, 1)},
            {(aircraft.id, hour_of(old)): 1, (aircraft.id, hour_of(now)): 1},
        )
    with test_db.get_session() as session:
        removed = purge_traffic(session, now=now)
        assert removed == 2
        assert [r.minute for r in session.execute(select(TrafficMinute)).scalars()] == [fresh]
        assert [r.hour for r in session.execute(select(AircraftHourly)).scalars()] == [hour_of(now)]


def test_aircraft_count_is_indexed(test_db):
    from sqlalchemy import inspect

    names = {ix["name"] for ix in inspect(test_db.engine).get_indexes("aircraft")}
    assert "ix_aircraft_count" in names
    assert Aircraft.count.property.columns[0].index is True
```

Also extend `tests/test_database.py`:

```python
NEW_INDEXES = {
    "aircraft": "ix_aircraft_lastseen",
    "aircraft_metadata": "ix_aircraft_metadata_aircraft_id_system_timestamp",
    "aircraft_positions": "ix_aircraft_positions_aircraft_id_timestamp",
    "aircraft_hourly": "ix_aircraft_hourly_hour",
}
```

and add a second entry for `aircraft` by turning the dict into a list of `(table, name)` pairs if the existing test iterates `.items()`: change to

```python
NEW_INDEXES = [
    ("aircraft", "ix_aircraft_lastseen"),
    ("aircraft", "ix_aircraft_count"),
    ("aircraft_metadata", "ix_aircraft_metadata_aircraft_id_system_timestamp"),
    ("aircraft_positions", "ix_aircraft_positions_aircraft_id_timestamp"),
    ("aircraft_hourly", "ix_aircraft_hourly_hour"),
]
```

and update the two loops in that file from `NEW_INDEXES.values()` / `NEW_INDEXES.items()` to iterate the pairs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_traffic.py tests/test_database.py -q`
Expected: ImportError on `adsb.traffic` / `AircraftHourly`.

- [ ] **Step 3: Add the models**

In `adsb/models.py`, change `Aircraft.count` to `mapped_column(Integer, default=0, nullable=False, index=True)` and append:

```python
class TrafficMinute(Base):
    """
    Messages and distinct aircraft heard per wall-clock minute.

    Maintained by the network client from each decoded batch, so the history
    view can chart a day of traffic without keeping a day of per-message rows
    (``aircraft_metadata`` is trimmed to an hour). ``aircraft`` is the number
    of distinct icao24 heard in that minute.
    """

    __tablename__ = "traffic_minutes"

    minute: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    messages: Mapped[int] = mapped_column(Integer, nullable=False)
    aircraft: Mapped[int] = mapped_column(Integer, nullable=False)


class AircraftHourly(Base):
    """Messages per aircraft per wall-clock hour, for the 24-hour top list."""

    __tablename__ = "aircraft_hourly"
    # The stats endpoint sums a window of hours across all aircraft.
    __table_args__ = (Index("ix_aircraft_hourly_hour", "hour"),)

    aircraft_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("aircraft.id"), primary_key=True, autoincrement=False
    )
    hour: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    messages: Mapped[int] = mapped_column(Integer, nullable=False)
```

- [ ] **Step 4: Write `adsb/traffic.py` (writer half)**

```python
"""
Traffic aggregates behind the history view.

Per-message rows (``aircraft_metadata``) are trimmed to an hour and arrive at
over a million an hour, so a day of history is kept as two small tables
instead: messages and distinct aircraft per minute, and messages per aircraft
per hour. The network client upserts deltas for every batch it decodes.
"""

import time

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from adsb.models import AircraftHourly, TrafficMinute

TRAFFIC_RETENTION = 7 * 86400  # seconds of aggregate history kept


def minute_of(ts: float) -> int:
    """Epoch seconds floored to the minute."""
    return int(ts) // 60 * 60


def hour_of(ts: float) -> int:
    """Epoch seconds floored to the hour."""
    return int(ts) // 3600 * 3600


def record_batch(
    session: Session,
    minutes: dict[int, tuple[int, int]],
    hourly: dict[tuple[int, int], int],
) -> None:
    """
    Add one batch's traffic to the aggregates.

    Parameters
    ----------
    minutes : dict
        ``{minute: (messages, aircraft)}``. ``messages`` is a delta and is
        added to the stored row; ``aircraft`` is the caller's count of
        distinct aircraft heard so far in that minute and replaces the stored
        value when larger. Within one process the caller keeps an exact set;
        across a restart the larger partial count wins.
    hourly : dict
        ``{(aircraft_id, hour): messages}`` deltas.
    """
    if minutes:
        stmt = sqlite_insert(TrafficMinute).values(
            [{"minute": m, "messages": c, "aircraft": a} for m, (c, a) in minutes.items()]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TrafficMinute.minute],
            set_={
                "messages": TrafficMinute.messages + stmt.excluded.messages,
                "aircraft": func_max(TrafficMinute.aircraft, stmt.excluded.aircraft),
            },
        )
        session.execute(stmt)
    if hourly:
        stmt = sqlite_insert(AircraftHourly).values(
            [{"aircraft_id": a, "hour": h, "messages": c} for (a, h), c in hourly.items()]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AircraftHourly.aircraft_id, AircraftHourly.hour],
            set_={"messages": AircraftHourly.messages + stmt.excluded.messages},
        )
        session.execute(stmt)


def purge_traffic(session: Session, now: float | None = None, retention: int = TRAFFIC_RETENTION) -> int:
    """Delete aggregate rows older than ``retention`` seconds; returns rows removed."""
    cutoff = (time.time() if now is None else now) - retention
    removed = 0
    for model, column in ((TrafficMinute, TrafficMinute.minute), (AircraftHourly, AircraftHourly.hour)):
        result = session.execute(
            delete(model).where(column < cutoff).execution_options(synchronize_session=False)
        )
        removed += result.rowcount
    return removed
```

`func_max` is SQLite's scalar two-argument `max`: add `from sqlalchemy import func` and define `func_max = func.max` at module top (SQLAlchemy emits `max(a, b)` for two arguments).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_traffic.py tests/test_database.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add adsb/models.py adsb/traffic.py tests/test_traffic.py tests/test_database.py
git commit -m "Add traffic aggregate tables and writer"
```

---

### Task 2: Feed the aggregates from the network client

**Files:**
- Modify: `adsb/network.py:138-167` (`__init__`), `adsb/network.py:224-289` (`handle_messages`)
- Test: `tests/test_network.py`

**Interfaces:**
- Consumes: `traffic.record_batch`, `traffic.purge_traffic`, `traffic.minute_of`, `traffic.hour_of`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_network.py` (reuse the `handle_messages` patch stack already used by `test_handle_messages`):

```python
def _patched_client_handle(client, messages):
    with patch("pyModeS.crc", return_value=0):
        with patch("pyModeS.df", return_value=17):
            with patch("pyModeS.icao", return_value="4840D6"):
                with patch("pyModeS.adsb.typecode", return_value=1):
                    with patch("pyModeS.adsb.callsign", return_value="TEST123"):
                        client.handle_messages(messages)


def test_handle_messages_records_traffic_aggregates(test_db):
    from adsb.models import AircraftHourly, TrafficMinute
    from adsb.traffic import hour_of, minute_of

    client = ADSBNetworkClient(host="localhost", port=30005, rawtype="beast", database=test_db)
    ts = 1_788_556_190.4
    _patched_client_handle(client, [("8D4840D6202CC371C32CE0576098", ts)] * 3)
    _patched_client_handle(client, [("8D4840D6202CC371C32CE0576098", ts + 1)])

    with test_db.get_session() as session:
        minute = session.get(TrafficMinute, minute_of(ts))
        assert (minute.messages, minute.aircraft) == (4, 1)
        aircraft = session.query(Aircraft).filter_by(icao24="4840d6").one()
        hourly = session.get(AircraftHourly, (aircraft.id, hour_of(ts)))
        assert hourly.messages == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_network.py::test_handle_messages_records_traffic_aggregates -q`
Expected: FAIL, `minute` is None.

- [ ] **Step 3: Implement**

In `adsb/network.py` add `from adsb.traffic import hour_of, minute_of, purge_traffic, record_batch`. In `__init__` after `self.total_aircraft`:

```python
        # Distinct aircraft heard in the current minute, kept across batches so the
        # per-minute aggregate is exact within this process (see traffic.record_batch).
        self._minute_start = 0
        self._minute_aircraft: set[str] = set()
```

In `handle_messages`, before the `for msg, ts, *extra in messages:` loop:

```python
        minutes: dict[int, list] = {}  # minute -> [messages, set(icao24)]
        hourly: dict[tuple[int, int], int] = {}
```

Inside the loop, right after `if result is not None:` alongside the existing `batch` bookkeeping:

```python
                    bucket = minutes.setdefault(minute_of(ts), [0, set()])
                    bucket[0] += 1
                    bucket[1].add(result.icao24)
                    key = (result.id, hour_of(ts))
                    hourly[key] = hourly.get(key, 0) + 1
```

After the loop, before the metadata purge block:

```python
            # Fold this batch into the traffic aggregates.
            minute_rows: dict[int, tuple[int, int]] = {}
            for minute in sorted(minutes):
                count, seen = minutes[minute]
                if minute != self._minute_start:
                    self._minute_start, self._minute_aircraft = minute, set()
                self._minute_aircraft |= seen
                minute_rows[minute] = (count, len(self._minute_aircraft))
            record_batch(session, minute_rows, hourly)
```

Inside the existing housekeeping `try:` after the metadata purge:

```python
                    removed_traffic = purge_traffic(session, now=now)
                    adsb_logger.debug(f"Purged {removed_traffic} old traffic rows")
```

- [ ] **Step 4: Run the whole network test file**

Run: `uv run pytest tests/test_network.py -q`
Expected: PASS (the existing query-count tests must still pass; if `test_handle_messages` asserts an exact statement count, update it to include the two upserts).

- [ ] **Step 5: Commit**

```bash
git add adsb/network.py tests/test_network.py
git commit -m "Record per-minute and per-aircraft-hour traffic from each batch"
```

---

### Task 3: One-off backfill from retained metadata

**Files:**
- Modify: `adsb/traffic.py` (add `backfill_traffic`)
- Modify: `adsb/cli.py` (`_build_backend`, after `database.create_tables()`)
- Test: `tests/test_traffic.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `traffic.backfill_traffic(session) -> bool` (True if rows were inserted).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_traffic.py`:

```python
from adsb.traffic import backfill_traffic
from tests.helpers import add_metadata


def test_backfill_seeds_minutes_and_hours_from_metadata(test_db, aircraft):
    base = 1_788_556_200.0  # on a minute boundary
    with test_db.get_session() as session:
        add_metadata(session, aircraft.id, [base, base + 10.5, base + 61])
    with test_db.get_session() as session:
        assert backfill_traffic(session) is True
    with test_db.get_session() as session:
        rows = {r.minute: (r.messages, r.aircraft) for r in session.query(TrafficMinute)}
        assert rows == {int(base): (2, 1), int(base) + 60: (1, 1)}
        hourly = session.get(AircraftHourly, (aircraft.id, hour_of(base)))
        assert hourly.messages == 3


def test_backfill_is_a_no_op_when_aggregates_exist(test_db, aircraft):
    with test_db.get_session() as session:
        add_metadata(session, aircraft.id, [1_788_556_200.0])
        record_batch(session, {1_700_000_000: (9, 9)}, {})
    with test_db.get_session() as session:
        assert backfill_traffic(session) is False
        assert session.query(TrafficMinute).count() == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_traffic.py -q -k backfill`
Expected: ImportError `backfill_traffic`.

- [ ] **Step 3: Implement**

Append to `adsb/traffic.py`:

```python
from sqlalchemy import func, select, text

from adsb.models import AircraftMetadata


def backfill_traffic(session: Session) -> bool:
    """
    Seed empty aggregates from whatever reception metadata is still retained.

    Runs once at backend start so an upgraded install shows its last hour of
    history straight away instead of an empty chart. Returns True if it wrote.
    """
    has_rows = session.execute(select(TrafficMinute.minute).limit(1)).first() is not None
    if has_rows or session.execute(select(func.count()).select_from(AircraftMetadata)).scalar() == 0:
        return False
    session.execute(
        text(
            "INSERT INTO traffic_minutes (minute, messages, aircraft) "
            "SELECT (CAST(system_timestamp AS INTEGER) / 60) * 60, COUNT(*), COUNT(DISTINCT aircraft_id) "
            "FROM aircraft_metadata GROUP BY 1"
        )
    )
    session.execute(
        text(
            "INSERT INTO aircraft_hourly (aircraft_id, hour, messages) "
            "SELECT aircraft_id, (CAST(system_timestamp AS INTEGER) / 3600) * 3600, COUNT(*) "
            "FROM aircraft_metadata GROUP BY 1, 2"
        )
    )
    return True
```

(Consolidate the imports at the top of the module.)

In `adsb/cli.py::_build_backend`, directly after `database.create_tables()`:

```python
    with database.get_session() as session:
        if backfill_traffic(session):
            logger.info("Seeded traffic history from retained reception metadata")
```

with `from adsb.traffic import backfill_traffic` at the top. Use whatever logger variable `_build_backend` already uses for its startup messages (check the function; if it prints via `click.echo`, follow that instead).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_traffic.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add adsb/traffic.py adsb/cli.py tests/test_traffic.py
git commit -m "Backfill traffic aggregates from retained metadata at startup"
```

---

### Task 4: `GET /api/stats`

**Files:**
- Modify: `adsb/traffic.py` (reader statements + `fill_buckets`)
- Modify: `adsb/schemas.py` (append schemas)
- Modify: `adsb/api.py` (route, `api_index`)
- Modify: `README.md` API table, `CHANGELOG.md` Unreleased/Added
- Test: `tests/test_api.py`, `tests/test_traffic.py`

**Interfaces:**
- Produces: `traffic.buckets_stmt(since: int, interval: int)`, `traffic.top_window_stmt(since_hour: int, limit: int)`, `traffic.top_lifetime_stmt(limit: int)`, `traffic.aircraft_seen_stmt(since_hour: int)`, `traffic.fill_buckets(rows, since: int, end: int, interval: int) -> list[dict]`.
- Produces HTTP: `GET /api/stats?window=86400&interval=900&limit=10` → `StatsSchema`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_traffic.py`:

```python
from adsb.traffic import fill_buckets


def test_fill_buckets_zero_fills_and_aligns():
    rows = [(1200, 5, 2)]  # (bucket start, messages, aircraft)
    out = fill_buckets(rows, since=600, end=1800, interval=600)
    assert out == [
        {"start": 600, "messages": 0, "aircraft": 0},
        {"start": 1200, "messages": 5, "aircraft": 2},
    ]
```

Append to `tests/test_api.py`:

```python
from adsb.traffic import (
    aircraft_seen_stmt,
    buckets_stmt,
    hour_of,
    minute_of,
    record_batch,
    top_lifetime_stmt,
    top_window_stmt,
)


def test_stats_buckets_are_aligned_and_zero_filled(test_db, test_session):
    now = int(time.time())
    a = Aircraft(icao24="aaa111", firstseen=now - 7200, lastseen=now, callsign="ONE", count=50)
    b = Aircraft(icao24="bbb222", firstseen=now - 7200, lastseen=now - 60, callsign="TWO", count=900)
    test_session.add_all([a, b])
    test_session.commit()
    record_batch(
        test_session,
        {minute_of(now): (10, 2), minute_of(now - 120): (4, 5)},
        {(a.id, hour_of(now)): 12, (b.id, hour_of(now)): 2},
    )
    test_session.commit()
    client = TestClient(create_app(test_db))

    r = client.get("/api/stats?window=3600&interval=600&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert data["window"] == 3600 and data["interval"] == 600
    assert len(data["buckets"]) == 6
    assert all(b["start"] % 600 == 0 for b in data["buckets"])
    assert data["buckets"][-1]["start"] + 600 >= data["now"]
    assert sum(b["messages"] for b in data["buckets"]) == 14
    assert max(b["aircraft"] for b in data["buckets"]) == 5
    assert data["aircraft_seen"] == 2
    assert [t["icao24"] for t in data["top_window"]] == ["aaa111", "bbb222"]
    assert data["top_window"][0]["messages"] == 12
    assert [t["icao24"] for t in data["top_lifetime"]] == ["bbb222", "aaa111"]
    assert data["top_lifetime"][0]["messages"] == 900
    assert data["top_lifetime"][0]["callsign"] == "TWO"


def test_stats_rejects_interval_that_does_not_divide_window(client):
    assert client.get("/api/stats?window=3600&interval=700").status_code == 422


def test_stats_empty_database_returns_full_zero_grid(client):
    data = client.get("/api/stats").json()
    assert len(data["buckets"]) == 96
    assert data["top_window"] == [] and data["top_lifetime"] == []
    assert data["aircraft_seen"] == 0
```

Add `("/api/stats", 200)` to the `test_api_endpoints_exist` parametrization, and extend `test_hot_statements_seek_their_index` with:

```python
        (buckets_stmt(0, 900), "traffic_minutes"),          # PK range: plan mentions the table's autoindex or "USING INTEGER PRIMARY KEY"
        (top_window_stmt(0, 10), "ix_aircraft_hourly_hour"),
        (aircraft_seen_stmt(0), "ix_aircraft_hourly_hour"),
        (top_lifetime_stmt(10), "ix_aircraft_count"),
```

Check that test's assertion shape: if it asserts `index in plan` and "no step starts with SCAN", `buckets_stmt` on an INTEGER PRIMARY KEY reads as `SEARCH traffic_minutes USING INTEGER PRIMARY KEY (rowid>?)`; use the needle `"USING INTEGER PRIMARY KEY"` for that row.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py tests/test_traffic.py -q`
Expected: ImportError.

- [ ] **Step 3: Reader statements in `adsb/traffic.py`**

```python
from sqlalchemy import Select, desc

from adsb.models import Aircraft


def buckets_stmt(since: int, interval: int) -> Select:
    """Per-bucket totals: sum of messages, max of per-minute distinct aircraft."""
    bucket = (TrafficMinute.minute / interval) * interval  # integer division in SQLite
    return (
        select(
            bucket.label("start"),
            func.sum(TrafficMinute.messages),
            func.max(TrafficMinute.aircraft),
        )
        .where(TrafficMinute.minute >= since)
        .group_by(bucket)
        .order_by(bucket)
    )


def aircraft_seen_stmt(since_hour: int) -> Select:
    """Distinct aircraft with any traffic in hours at or after ``since_hour``."""
    return select(func.count(func.distinct(AircraftHourly.aircraft_id))).where(
        AircraftHourly.hour >= since_hour
    )


def top_window_stmt(since_hour: int, limit: int) -> Select:
    """Aircraft ranked by messages in hours at or after ``since_hour``."""
    total = func.sum(AircraftHourly.messages).label("messages")
    return (
        select(Aircraft, total)
        .join(AircraftHourly, AircraftHourly.aircraft_id == Aircraft.id)
        .where(AircraftHourly.hour >= since_hour)
        .group_by(Aircraft.id)
        .order_by(desc(total))
        .limit(limit)
    )


def top_lifetime_stmt(limit: int) -> Select:
    """Aircraft ranked by lifetime message count."""
    return select(Aircraft).order_by(Aircraft.count.desc()).limit(limit)


def fill_buckets(rows, since: int, end: int, interval: int) -> list[dict]:
    """Expand sparse ``(start, messages, aircraft)`` rows into a full zero-filled grid."""
    by_start = {int(start): (int(m), int(a)) for start, m, a in rows}
    out = []
    for start in range(since, end, interval):
        messages, aircraft = by_start.get(start, (0, 0))
        out.append({"start": start, "messages": messages, "aircraft": aircraft})
    return out
```

Note on `bucket`: SQLAlchemy renders `traffic_minutes.minute / :interval * :interval`; SQLite integer division on two INTEGER operands truncates, which is the floor we want. Add a comment saying so.

- [ ] **Step 4: Schemas in `adsb/schemas.py`**

```python
class StatsBucketSchema(BaseModel):
    """One interval of the traffic history."""

    start: int
    messages: int
    aircraft: int  # peak distinct aircraft in any one minute of the interval


class TopAircraftSchema(BaseModel):
    """One row of a top-aircraft table."""

    icao24: str
    callsign: str | None = None
    registration: str | None = None
    typecode: str | None = None
    messages: int
    lastseen: int


class StatsSchema(BaseModel):
    """Response of ``/api/stats``."""

    now: int
    window: int
    interval: int
    aircraft_seen: int
    buckets: list[StatsBucketSchema]
    top_window: list[TopAircraftSchema]
    top_lifetime: list[TopAircraftSchema]
```

- [ ] **Step 5: Route in `adsb/api.py`**

Add imports: `from fastapi import HTTPException`, `from adsb.schemas import StatsSchema, TopAircraftSchema`, and `from adsb.traffic import aircraft_seen_stmt, buckets_stmt, fill_buckets, hour_of, top_lifetime_stmt, top_window_stmt`. Add to `api_index()["routes"]`:

```python
            "/api/stats?window={seconds}&interval={seconds}&limit={n}": (
                "traffic history: message volume and aircraft counts per interval, top aircraft"
            ),
```

Add the route after `/api/sensors`:

```python
    @app.get("/api/stats", response_model=StatsSchema)
    async def get_stats(
        window: int = Query(86400, ge=60, le=604800, description="History window in seconds"),
        interval: int = Query(900, ge=60, le=86400, description="Bucket size in seconds"),
        limit: int = Query(10, ge=1, le=100, description="Rows per top-aircraft list"),
        session: Session = Depends(get_session),
    ):
        """
        Traffic history for the map's history view.

        Buckets are aligned to ``interval`` and end at the current interval, so
        the last bucket is partial. ``aircraft`` per bucket is the peak number
        of distinct aircraft heard in any single minute of that bucket. The top
        lists rank aircraft by messages within the window (rounded down to the
        hour the window starts in) and by lifetime message count.
        """
        if window % interval:
            raise HTTPException(status_code=422, detail="interval must divide window evenly")
        now = int(time.time())
        end = (now // interval + 1) * interval
        since = end - window
        since_hour = hour_of(since)

        buckets = fill_buckets(session.execute(buckets_stmt(since, interval)).all(), since, end, interval)
        aircraft_seen = session.execute(aircraft_seen_stmt(since_hour)).scalar() or 0

        def row(aircraft: Aircraft, messages: int) -> TopAircraftSchema:
            return TopAircraftSchema(
                icao24=aircraft.icao24,
                callsign=aircraft.callsign,
                registration=aircraft.registration,
                typecode=aircraft.typecode,
                messages=messages,
                lastseen=aircraft.lastseen,
            )

        top_window = [row(a, m) for a, m in session.execute(top_window_stmt(since_hour, limit))]
        top_lifetime = [row(a, a.count) for a in session.execute(top_lifetime_stmt(limit)).scalars()]
        return StatsSchema(
            now=now,
            window=window,
            interval=interval,
            aircraft_seen=aircraft_seen,
            buckets=buckets,
            top_window=top_window,
            top_lifetime=top_lifetime,
        )
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all PASS. If the index-plan test fails for `buckets_stmt`, inspect `query_plan(engine, stmt)` output and adjust the needle to the exact phrase SQLite prints.

- [ ] **Step 7: Docs**

README API table, new row after `/api/sensors`:

```
| `GET /api/stats?window={seconds}&interval={seconds}&limit={n}` | Traffic history: messages and peak aircraft per interval (default 24 h in 15-min buckets), plus top aircraft by messages in the window and over their lifetime |
```

README "Database schema" table: add `traffic_minutes` ("Messages and distinct aircraft per minute, 7-day rolling") and `aircraft_hourly` ("Messages per aircraft per hour, 7-day rolling"). Architecture table: add `traffic.py` ("Per-minute / per-aircraft-hour aggregates: writer, purge, backfill, `/api/stats` statements").

CHANGELOG `## [Unreleased]` → `### Added`, first bullet:

```
- **History view.** A clock icon next to the gear opens a full-screen overlay over
  the map with the last 24 hours of traffic: message volume and peak aircraft per
  interval (5 min / 15 min / 1 h), and top-10 aircraft by messages in the window
  and over their lifetime. Backed by a new `GET /api/stats` and two small aggregate
  tables (`traffic_minutes`, `aircraft_hourly`) the decoder maintains per batch and
  trims to seven days, so the charts never touch the per-message rows. Existing
  databases are seeded from their retained hour of metadata on the next start.
```

- [ ] **Step 8: Commit**

```bash
git add adsb/traffic.py adsb/schemas.py adsb/api.py tests/test_api.py tests/test_traffic.py README.md CHANGELOG.md
git commit -m "Add /api/stats: bucketed traffic history and top aircraft"
```

---

### Task 5: Frontend formatting helpers

**Files:**
- Create: `frontend/src/stats.js`
- Create: `frontend/src/stats.test.js`

**Interfaces:**
- Produces: `formatCount(n) -> string`, `niceMax(max) -> number`, `timeTicks(buckets, interval) -> Array<{index:number,label:string}>`, `relativeTime(seconds, nowSeconds) -> string`, `bucketRange(start, interval) -> string`, `INTERVAL_OPTIONS`.

- [ ] **Step 1: Write the failing tests**

```js
// frontend/src/stats.test.js
import { describe, expect, test } from 'bun:test'
import { bucketRange, formatCount, niceMax, relativeTime, timeTicks } from './stats'

describe('formatCount', () => {
  test('groups thousands below 10k and abbreviates above', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(1234)).toBe('1,234')
    expect(formatCount(12345)).toBe('12.3k')
    expect(formatCount(1234567)).toBe('1.23M')
  })
})

describe('niceMax', () => {
  test('rounds up to 1, 2 or 5 times a power of ten', () => {
    expect(niceMax(0)).toBe(1)
    expect(niceMax(7)).toBe(10)
    expect(niceMax(95)).toBe(100)
    expect(niceMax(130)).toBe(200)
    expect(niceMax(430)).toBe(500)
    expect(niceMax(500)).toBe(500)
    expect(niceMax(12000)).toBe(20000)
  })
})

describe('timeTicks', () => {
  test('labels every 3 hours for 15-minute buckets, on the hour', () => {
    const start = Date.UTC(2026, 8, 4, 0, 0) / 1000
    const buckets = Array.from({ length: 96 }, (_, i) => ({ start: start + i * 900 }))
    const ticks = timeTicks(buckets, 900)
    expect(ticks.length).toBe(8)
    expect(ticks[0].index).toBe(0)
    expect(ticks[1].index).toBe(12)
  })
  test('labels every hour for 5-minute buckets and every 4 hours for hourly', () => {
    const start = Date.UTC(2026, 8, 4, 0, 0) / 1000
    const five = Array.from({ length: 288 }, (_, i) => ({ start: start + i * 300 }))
    expect(timeTicks(five, 300).length).toBe(24)
    const hourly = Array.from({ length: 24 }, (_, i) => ({ start: start + i * 3600 }))
    expect(timeTicks(hourly, 3600).length).toBe(6)
  })
})

describe('relativeTime', () => {
  test('describes seconds, minutes, hours and days', () => {
    const now = 1_000_000
    expect(relativeTime(now - 20, now)).toBe('just now')
    expect(relativeTime(now - 240, now)).toBe('4 min ago')
    expect(relativeTime(now - 3 * 3600 - 10, now)).toBe('3 h ago')
    expect(relativeTime(now - 2 * 86400, now)).toBe('2 d ago')
  })
})

describe('bucketRange', () => {
  test('formats a start and end time', () => {
    const s = bucketRange(Date.UTC(2026, 8, 4, 9, 0) / 1000, 900)
    expect(s).toMatch(/\d{1,2}:\d{2}.*–.*\d{1,2}:\d{2}/)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && bun test src/stats.test.js`
Expected: cannot resolve `./stats`.

- [ ] **Step 3: Implement**

```js
// frontend/src/stats.js
/**
 * Pure helpers for the history view: number and time formatting, axis ticks.
 */

export const INTERVAL_OPTIONS = [
  { value: 300, label: '5 min' },
  { value: 900, label: '15 min' },
  { value: 3600, label: '1 h' },
]

export const HISTORY_WINDOW = 86400 // seconds shown in the history view

export function formatCount(n) {
  if (n < 10000) return n.toLocaleString('en-US')
  if (n < 1e6) return `${(n / 1e3).toFixed(1).replace(/\.0$/, '')}k`
  return `${(n / 1e6).toFixed(2).replace(/\.?0+$/, '')}M`
}

/** Smallest of 1, 2, 5 × 10^k that is at least `max`; 1 for empty data. */
export function niceMax(max) {
  if (!(max > 0)) return 1
  const pow = 10 ** Math.floor(Math.log10(max))
  for (const m of [1, 2, 5, 10]) if (m * pow >= max) return m * pow
  return 10 * pow
}

const TICK_EVERY = { 300: 3600, 900: 3 * 3600, 3600: 4 * 3600 }

const hourLabel = seconds =>
  new Date(seconds * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

/** Bucket indexes that get an x-axis label, on round hours. */
export function timeTicks(buckets, interval) {
  const every = TICK_EVERY[interval] || 4 * 3600
  return buckets
    .map((b, index) => ({ index, start: b.start }))
    .filter(({ start }) => start % every === 0)
    .map(({ index, start }) => ({ index, label: hourLabel(start) }))
}

export function relativeTime(seconds, now = Date.now() / 1000) {
  const age = Math.max(0, now - seconds)
  if (age < 60) return 'just now'
  if (age < 3600) return `${Math.floor(age / 60)} min ago`
  if (age < 86400) return `${Math.floor(age / 3600)} h ago`
  return `${Math.floor(age / 86400)} d ago`
}

export function bucketRange(start, interval) {
  return `${hourLabel(start)} – ${hourLabel(start + interval)}`
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && bun test src/stats.test.js`
Expected: PASS. (`timeTicks` uses UTC-aligned starts in tests; `start % every === 0` is timezone-independent because `every` divides 86400 evenly. `hourLabel` output is locale-dependent, which is why tests only check counts and indexes.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stats.js frontend/src/stats.test.js
git commit -m "Add history formatting helpers"
```

---

### Task 6: Data layer: `fetchStats`, demo stats, `useStats`

**Files:**
- Modify: `frontend/src/services/api.js`
- Modify: `frontend/src/services/demo.js`
- Create: `frontend/src/hooks/useStats.js`
- Test: `frontend/src/services/api.test.js`

**Interfaces:**
- Produces: `fetchStats({ window, interval, limit })`, `DemoFleet.stats({ window, interval, limit })`, `useStats(open, interval) -> { stats, loading, error }`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/services/api.test.js`, matching the file's existing fetch-stub style:

```js
test('fetchStats requests /api/stats with window, interval and limit', async () => {
  const calls = []
  globalThis.fetch = async url => {
    calls.push(url)
    return { ok: true, json: async () => ({ buckets: [] }) }
  }
  const { fetchStats } = await import('./api')
  await fetchStats({ window: 86400, interval: 900, limit: 10 })
  expect(calls[0]).toBe('/api/stats?window=86400&interval=900&limit=10')
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && bun test src/services/api.test.js`
Expected: `fetchStats` is not a function.

- [ ] **Step 3: Implement `fetchStats`**

Append to `frontend/src/services/api.js`:

```js
/**
 * Fetches the traffic history behind the history view.
 *
 * @param {{window: number, interval: number, limit: number}} params - Seconds of history,
 *   bucket size in seconds (must divide the window), rows per top list
 * @returns {Promise<Object>} Buckets and top-aircraft lists, shaped like /api/stats
 */
export async function fetchStats({ window, interval, limit }) {
  if (fleet) return fleet.stats({ window, interval, limit })
  const q = new URLSearchParams({ window, interval, limit })
  return getJson(`/api/stats?${q}`)
}
```

- [ ] **Step 4: Demo stats**

Append to `DemoFleet` in `frontend/src/services/demo.js`:

```js
  /**
   * A day of plausible traffic, shaped like /api/stats. Quiet overnight, busy
   * in the afternoon, with per-bucket noise from a PRNG seeded by the bucket
   * so the picture is stable across refreshes.
   */
  stats({ window = 86400, interval = 900, limit = 10 } = {}) {
    const now = Math.floor(this.lastTick / 1000)
    const end = (Math.floor(now / interval) + 1) * interval
    const size = this.entries.length
    const buckets = []
    for (let start = end - window; start < end; start += interval) {
      const rand = mulberry32(start)
      const hour = new Date(start * 1000).getHours() + new Date(start * 1000).getMinutes() / 60
      const diurnal = 0.35 + 0.65 * (0.5 - 0.5 * Math.cos((2 * Math.PI * (hour - 4)) / 24))
      const aircraft = Math.min(size, Math.round(size * diurnal + between(rand, -2, 2)))
      const perMinute = aircraft * between(rand, 55, 75)
      const minutes = Math.min(interval, Math.max(0, now - start)) / 60
      buckets.push({ start, messages: Math.round(perMinute * minutes), aircraft })
    }
    const ranked = [...this.entries].sort((a, b) => b.ac.count - a.ac.count).slice(0, limit)
    const row = (e, messages) => ({
      icao24: e.ac.icao24,
      callsign: e.ac.callsign,
      registration: e.ac.registration,
      typecode: e.ac.typecode,
      messages,
      lastseen: e.ac.lastseen,
    })
    return {
      now,
      window,
      interval,
      aircraft_seen: size,
      buckets,
      top_window: ranked.map(e => row(e, e.ac.count * 40)),
      top_lifetime: ranked.map((e, i) => row(e, e.ac.count * (400 - i * 25))),
    }
  }
```

- [ ] **Step 5: The hook**

```js
// frontend/src/hooks/useStats.js
/**
 * Loads /api/stats for the history view while it is open.
 */

import { useEffect, useState } from 'react'
import { fetchStats } from '../services/api'
import { HISTORY_WINDOW } from '../stats'

const REFRESH_MS = 60_000
const TOP_LIMIT = 10

/**
 * @param {boolean} open - Fetch only while the view is showing
 * @param {number} interval - Bucket size in seconds; a change refetches at once
 * @returns {{stats: Object|null, loading: boolean, error: string|null}}
 */
export function useStats(open, interval) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return undefined
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const data = await fetchStats({ window: HISTORY_WINDOW, interval, limit: TOP_LIMIT })
        if (!cancelled) {
          setStats(data)
          setError(null)
        }
      } catch (err) {
        console.error('Error fetching traffic history:', err)
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [open, interval])

  return { stats, loading, error }
}
```

- [ ] **Step 6: Run tests and lint**

Run: `cd frontend && bun test && bun run lint`
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/services/api.js frontend/src/services/api.test.js frontend/src/services/demo.js frontend/src/hooks/useStats.js
git commit -m "Add fetchStats, demo traffic history and useStats hook"
```

---

### Task 7: Overlay components

**Files:**
- Create: `frontend/src/components/BarChart.jsx`
- Create: `frontend/src/components/TopAircraftTable.jsx`
- Create: `frontend/src/components/HistoryOverlay.jsx`
- Create: `frontend/src/components/HistoryOverlay.css`

**Interfaces:**
- Consumes: `useStats`, `stats.js` helpers, `.segmented`/`.segment`/`.close-button`/`.stat` classes.
- Produces: `<HistoryOverlay open onClose returnFocusTo />`, `<BarChart buckets interval valueKey unit />`, `<TopAircraftTable rows now />`.

No component test runner exists (no jsdom); these are verified visually in Task 9. Keep logic in `stats.js`.

- [ ] **Step 1: `BarChart.jsx`**

```jsx
import PropTypes from 'prop-types'
import { bucketRange, formatCount, niceMax, timeTicks } from '../stats'

const GRID_STEPS = 4

/**
 * A bar per bucket, heights as percentages of a rounded axis maximum. Plain
 * HTML so it needs no measuring; the row of bars is a flex container.
 */
function BarChart({ buckets, interval, valueKey, unit }) {
  const max = niceMax(Math.max(0, ...buckets.map(b => b[valueKey])))
  const total = buckets.reduce((sum, b) => sum + b[valueKey], 0)
  const ticks = timeTicks(buckets, interval)
  const grid = Array.from({ length: GRID_STEPS + 1 }, (_, i) => (max / GRID_STEPS) * i)

  return (
    <div className="chart" role="img" aria-label={`${unit} per ${interval / 60} minutes over the last day`}>
      <div className="chart-plot">
        {grid.map(v => (
          <div key={v} className="chart-grid" style={{ bottom: `${(v / max) * 100}%` }}>
            <span>{formatCount(v)}</span>
          </div>
        ))}
        <div className="chart-bars">
          {buckets.map((b, i) => (
            <div
              key={b.start}
              className={`chart-bar ${i === buckets.length - 1 ? 'current' : ''}`}
              style={{ height: `${(b[valueKey] / max) * 100}%` }}
              title={`${bucketRange(b.start, interval)}\n${b[valueKey].toLocaleString()} ${unit}`}
            />
          ))}
        </div>
        {total === 0 && <div className="chart-empty">No traffic recorded yet</div>}
      </div>
      <div className="chart-axis">
        {ticks.map(t => (
          <span key={t.index} style={{ left: `${((t.index + 0.5) / buckets.length) * 100}%` }}>
            {t.label}
          </span>
        ))}
      </div>
    </div>
  )
}

BarChart.propTypes = {
  buckets: PropTypes.arrayOf(PropTypes.object).isRequired,
  interval: PropTypes.number.isRequired,
  valueKey: PropTypes.oneOf(['messages', 'aircraft']).isRequired,
  unit: PropTypes.string.isRequired,
}

export default BarChart
```

- [ ] **Step 2: `TopAircraftTable.jsx`**

```jsx
import PropTypes from 'prop-types'
import { formatCount, relativeTime } from '../stats'

const cleanCallsign = s => (s || '').trim()

/** Three columns: aircraft, messages, last seen. */
function TopAircraftTable({ rows, now }) {
  if (rows.length === 0) return <p className="table-empty">Nothing heard yet</p>
  return (
    <table className="top-table">
      <thead>
        <tr>
          <th scope="col">Aircraft</th>
          <th scope="col" className="num">Messages</th>
          <th scope="col" className="num">Last seen</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const name = cleanCallsign(r.callsign) || r.registration || r.icao24.toUpperCase()
          const detail = [r.registration, r.typecode].filter(d => d && d !== name).join(' · ')
          return (
            <tr key={r.icao24}>
              <td>
                <span className="rank">{i + 1}</span>
                <span className="ident">
                  <span className="name">{name}</span>
                  <span className="detail">{detail || r.icao24}</span>
                </span>
              </td>
              <td className="num">{formatCount(r.messages)}</td>
              <td className="num" title={new Date(r.lastseen * 1000).toLocaleString()}>
                {relativeTime(r.lastseen, now)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

TopAircraftTable.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  now: PropTypes.number.isRequired,
}

export default TopAircraftTable
```

- [ ] **Step 3: `HistoryOverlay.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'
import PropTypes from 'prop-types'
import BarChart from './BarChart'
import TopAircraftTable from './TopAircraftTable'
import { useStats } from '../hooks/useStats'
import { INTERVAL_OPTIONS, formatCount } from '../stats'
import './HistoryOverlay.css'

/**
 * Full-screen history view over the map. The map keeps running underneath;
 * Escape or the X closes it.
 */
function HistoryOverlay({ onClose }) {
  const [interval, setInterval_] = useState(900)
  const { stats, loading, error } = useStats(true, interval)
  const closeRef = useRef(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const buckets = stats?.buckets ?? []
  const messages = buckets.reduce((s, b) => s + b.messages, 0)
  const peak = buckets.reduce((m, b) => Math.max(m, b.aircraft), 0)
  const now = stats?.now ?? Math.floor(Date.now() / 1000)

  return (
    <div className="history" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <div className="history-scroll">
        <div className="history-inner">
          <header className="history-header">
            <div>
              <h2 id="history-title">History</h2>
              <p className="history-subtitle">
                Last 24 hours
                {stats && <> · updated {new Date(now * 1000).toLocaleTimeString()}</>}
                {loading && <span className="loading-indicator"> Refreshing…</span>}
                {error && <span className="history-error"> {error}</span>}
              </p>
            </div>
            <div className="history-actions">
              <div className="segmented" role="radiogroup" aria-label="Chart interval">
                {INTERVAL_OPTIONS.map(opt => (
                  <label key={opt.value} className={`segment ${interval === opt.value ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="history-interval"
                      value={opt.value}
                      checked={interval === opt.value}
                      onChange={() => setInterval_(opt.value)}
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
              <button ref={closeRef} className="close-button" onClick={onClose} aria-label="Close history">
                <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
                  <path d="M2 2l8 8M10 2l-8 8" />
                </svg>
              </button>
            </div>
          </header>

          <div className="history-strip">
            <div className="stat">
              <div className="stat-value">{formatCount(messages)}</div>
              <div className="stat-label">Messages</div>
            </div>
            <div className="stat">
              <div className="stat-value">{peak}</div>
              <div className="stat-label">Peak aircraft / min</div>
            </div>
            <div className="stat">
              <div className="stat-value">{stats?.aircraft_seen ?? 0}</div>
              <div className="stat-label">Aircraft heard</div>
            </div>
          </div>

          <section className="history-card">
            <h3 className="info-section-title">Message volume</h3>
            <BarChart buckets={buckets} interval={interval} valueKey="messages" unit="messages" />
          </section>
          <section className="history-card">
            <h3 className="info-section-title">Aircraft tracked</h3>
            <p className="card-note">Peak distinct aircraft heard in any one minute of each interval</p>
            <BarChart buckets={buckets} interval={interval} valueKey="aircraft" unit="aircraft" />
          </section>

          <div className="history-tables">
            <section className="history-card">
              <h3 className="info-section-title">Top aircraft · last 24 hours</h3>
              <TopAircraftTable rows={stats?.top_window ?? []} now={now} />
            </section>
            <section className="history-card">
              <h3 className="info-section-title">Top aircraft · all time</h3>
              <TopAircraftTable rows={stats?.top_lifetime ?? []} now={now} />
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

HistoryOverlay.propTypes = { onClose: PropTypes.func.isRequired }

export default HistoryOverlay
```

- [ ] **Step 4: `HistoryOverlay.css`**

```css
/* History view --------------------------------------------------------------- */

.history {
  position: absolute;
  inset: 0;
  z-index: 50;
  background: var(--surface);
  -webkit-backdrop-filter: saturate(140%) blur(24px);
  backdrop-filter: saturate(140%) blur(24px);
  color: var(--ink);
  animation: historyIn 0.2s var(--ease);
}

@keyframes historyIn {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.history-scroll {
  position: absolute;
  inset: 0;
  overflow-y: auto;
}

.history-inner {
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px var(--gutter) 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 4px;
}

.history-header h2 {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.035em;
  line-height: 1.05;
}

.history-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}

.history-error {
  color: var(--danger);
  font-weight: 500;
}

.history-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.history-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.history-strip .stat-value {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.history-strip .stat-label {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ink-2);
}

.history-card {
  background: var(--surface-solid);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 18px 20px 16px;
  min-width: 0;
}

.history-card .info-section-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-3);
  margin-bottom: 12px;
}

.card-note {
  margin: -8px 0 12px;
  font-size: 12px;
  color: var(--ink-2);
}

.history-tables {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

/* Chart */
.chart {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chart-plot {
  position: relative;
  height: 180px;
  margin-left: 44px;
}

.chart-grid {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px solid var(--line);
  transform: translateY(-0.5px);
}

.chart-grid span {
  position: absolute;
  right: calc(100% + 8px);
  top: -0.6em;
  font-size: 11px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.chart-bars {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  gap: 1px;
}

.chart-bar {
  flex: 1;
  min-width: 0;
  min-height: 1px;
  background: var(--accent);
  border-radius: 2px 2px 0 0;
  opacity: 0.85;
  transition: opacity 0.15s var(--ease);
}

.chart-bar:hover {
  opacity: 1;
}

.chart-bar.current {
  background: var(--accent-soft);
  border: 1px solid var(--accent);
  border-bottom: 0;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--ink-3);
}

.chart-axis {
  position: relative;
  height: 16px;
  margin-left: 44px;
  font-size: 11px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.chart-axis span {
  position: absolute;
  transform: translateX(-50%);
  white-space: nowrap;
}

/* Tables */
.top-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.top-table th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-3);
  padding: 0 0 8px;
  border-bottom: 1px solid var(--line);
}

.top-table td {
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}

.top-table tr:last-child td {
  border-bottom: 0;
}

.top-table tbody tr:hover td {
  background: var(--surface-2);
}

.top-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.top-table td.num {
  font-weight: 500;
}

.top-table .rank {
  display: inline-block;
  width: 22px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.top-table .ident {
  display: inline-flex;
  flex-direction: column;
  gap: 1px;
  vertical-align: middle;
}

.top-table .name {
  font-weight: 500;
}

.top-table .detail {
  font-size: 12px;
  color: var(--ink-2);
}

.table-empty {
  font-size: 13px;
  color: var(--ink-3);
  padding: 12px 0;
}

@media (max-width: 900px) {
  .history-tables {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .history-inner {
    padding-top: 20px;
  }
  .history-header {
    flex-direction: column;
  }
  .history-actions {
    width: 100%;
    justify-content: space-between;
  }
  .history-strip {
    grid-template-columns: 1fr;
  }
  .chart-plot {
    height: 140px;
  }
}
```

- [ ] **Step 5: Lint and format**

Run: `cd frontend && bun run lint && bun run format`
Expected: clean (format rewrites files; re-run lint after).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BarChart.jsx frontend/src/components/TopAircraftTable.jsx frontend/src/components/HistoryOverlay.jsx frontend/src/components/HistoryOverlay.css
git commit -m "Add history overlay, bar chart and top-aircraft table components"
```

---

### Task 8: Toolbar button and app wiring

**Files:**
- Modify: `frontend/src/App.jsx` (state, button, overlay render)
- Modify: `frontend/src/App.css:193-249` (generalize button rules)

- [ ] **Step 1: CSS**

In `App.css`, rename the `.settings-button` block to a shared `.toolbar-button` selector (keep `.settings-button` working by listing both): change `.settings-button {`, `.settings-button svg {`, `.settings-button:hover {`, `.settings-button.open {`, `.settings-button:active {` and the `:focus-visible` rule to `.toolbar-button` (search/replace `.settings-button` → `.toolbar-button` throughout `App.css`). Keep `.toolbar-button.open svg { transform: rotate(60deg); }` scoped to the gear by changing it to `.settings-gear.open svg { transform: rotate(60deg); }`. Add `.settings { gap: 2px; }`.

- [ ] **Step 2: App.jsx**

Add `import HistoryOverlay from './components/HistoryOverlay'`. Add state and ref next to `showSettings`:

```jsx
  const [showHistory, setShowHistory] = useState(false)
  const historyButtonRef = useRef(null)
```

Add a close handler (stable for the overlay's Escape effect):

```jsx
  const closeHistory = useCallback(() => {
    setShowHistory(false)
    historyButtonRef.current?.focus()
  }, [])
```

(import `useCallback` from react.) Inside `<div className="settings" ref={settingsRef}>`, **before** the gear button:

```jsx
            <button
              ref={historyButtonRef}
              className={`toolbar-button ${showHistory ? 'open' : ''}`}
              onClick={() => {
                setShowSettings(false)
                setShowHistory(true)
              }}
              aria-label="Show history"
              aria-expanded={showHistory}
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.75"
                  d="M3 12a9 9 0 1 0 3-6.7M3 4v4.5h4.5M12 7v5l3.5 2"
                />
              </svg>
            </button>
```

Change the gear's className to `` `toolbar-button settings-gear ${showSettings ? 'open' : ''}` ``. After `</main>` inside `.app`:

```jsx
      {showHistory && <HistoryOverlay onClose={closeHistory} />}
```

- [ ] **Step 3: Lint, format, tests, build**

Run: `cd frontend && bun run lint && bun run format:check && bun test && bun run build`
Expected: all clean; build emits `dist/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/App.css
git commit -m "Add history button to the toolbar and mount the overlay"
```

---

### Task 9: Verification, Codex review, PR

- [ ] **Step 1: Full suites**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && (cd frontend && bun test && bun run lint && bun run format:check)`
Expected: all pass.

- [ ] **Step 2: Playwright against demo mode**

Start `cd frontend && bun run dev:demo` in the background. With the Playwright MCP tools: navigate to `http://localhost:3000/`, resize to 1440×900, click the "Show history" button, take a screenshot; switch the theme (settings → Dark) before opening, screenshot again; click each interval segment and screenshot; hover a bar and confirm the tooltip (`title`) text; press Escape and confirm the overlay is gone and the header's "Updated" time keeps changing; resize to 390×844 and screenshot the overlay. Save screenshots to the scratchpad and review them for alignment, contrast, overflow, and horizontal scroll (there must be none).

- [ ] **Step 3: Playwright against the live backend**

Run `just dev` (with the user's receiver args from their shell history, or `uv run adsb start backend` alone) so the backfill seeds an hour of buckets. `curl -s localhost:8000/api/stats | head -c 600`, confirm non-zero recent buckets and populated top lists. Open the overlay in the browser and screenshot.

- [ ] **Step 4: Codex review of the diff**

Run: `codex exec --sandbox read-only -C . "Review the diff of this branch against main (git diff main...HEAD) for bugs, regressions to existing map behaviour, and over-engineering. Read the spec at docs/superpowers/specs/2026-09-04-history-overlay-design.md first. Be terse; cite file:line."` Fix anything real; re-run step 1.

- [ ] **Step 5: Draft PR**

```bash
git push -u origin feature/history-overlay
gh pr create --draft --title "Add history view: 24-hour traffic charts and top aircraft" --body-file <body>
```

Body: summary, screenshots (attach via the PR after upload or describe), test plan, the two attribution trailers.
