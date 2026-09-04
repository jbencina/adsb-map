# History overlay: 24-hour traffic charts and top aircraft

**Date:** 2026-09-04
**Status:** approved (user), pending implementation

## Goal

A second screen showing what the receiver has heard over the past 24 hours,
reached from a history icon next to the gear in the toolbar. It is a full-screen
overlay over the map with an X to close, not a route: the map keeps polling and
rendering underneath, and closing returns to it untouched. Contents:

1. Message volume over the past 24 hours, bucketed by a selectable interval
   (5 min / 15 min / 1 h, default 15 min).
2. Aircraft tracked over the past 24 hours, same buckets. Each bar is the
   **maximum number of distinct aircraft heard in any one minute** inside the
   bucket ("between 09:00 and 09:15 we saw at most 95").
3. Top aircraft, two tables of 10 rows, three columns each (aircraft, messages,
   last seen): one ranked by messages in the past 24 hours, one by lifetime
   messages.

Current map functionality must not change. Visual quality must match the map
page (same tokens, glass, radii, motion, tabular numerals, light and dark).

## Why aggregate tables

Per-message rows (`aircraft_metadata`) are trimmed to one hour and arrive at
~1.2 M rows/hour on the user's feed. Keeping 24 h would cost ~29 M rows (~2 GB)
and a bucketing query of ~12 s per open. Measured on the live database:
0.48 s per hour of rows. So the decoder maintains two small aggregate tables
instead, and metadata retention stays at its default.

## Backend

### Schema (`adsb/models.py`)

```
traffic_minutes            one row per wall-clock minute with traffic
  minute     INTEGER PK    epoch seconds floored to 60
  messages   INTEGER NN    messages attributed to an aircraft in that minute
  aircraft   INTEGER NN    distinct icao24 heard in that minute

aircraft_hourly            one row per (aircraft, hour) with traffic
  aircraft_id INTEGER FK aircraft.id
  hour        INTEGER      epoch seconds floored to 3600
  messages    INTEGER NN
  PK (aircraft_id, hour); INDEX ix_aircraft_hourly_hour (hour)
```

Plus `ix_aircraft_count` on `aircraft(count)` for the lifetime top list.
`create_all` creates the tables and `_ensure_indexes` backfills the indexes on
existing files, the project's existing migration path. No new CLI flags.
Retention for both tables is a constant, 7 days (`TRAFFIC_RETENTION`).

### Writer (`adsb/traffic.py`, called from `ADSBNetworkClient.handle_messages`)

`handle_messages` already walks a batch and knows, per processed message, the
`Aircraft` row and the timestamp, and whether a position was decoded. It
accumulates for the batch:

- `per_minute[minute] -> (messages, set(icao24))`
- `per_aircraft_hour[(aircraft_id, hour)] -> messages`

and hands them to `traffic.record_batch(session, ...)`, which issues one SQLite
upsert per row inside the batch's existing session/transaction:

```
INSERT INTO traffic_minutes VALUES (:minute, :m, :a)
ON CONFLICT(minute) DO UPDATE SET
  messages = messages + excluded.messages,
  aircraft = max(aircraft, excluded.aircraft)
```

For `aircraft`, the client keeps the current minute's `set[str]` of icao24 in
memory across batches (`self._minute_aircraft`, reset when the minute changes)
and passes its size, so within one process the value is exact. Across a restart
`max()` keeps the larger of the two partial counts, an acceptable approximation.
Messages are exact deltas either way. `aircraft_hourly` uses the
same upsert shape with `messages = messages + excluded.messages`.

`traffic.purge(session, now)` deletes rows older than 7 days from both tables and
runs in the existing once-a-minute housekeeping block alongside the metadata
purge.

**Backfill:** at backend start (`cli._build_backend`, after `create_tables()`),
if `traffic_minutes` is empty and `aircraft_metadata` is not, seed
`traffic_minutes` and `aircraft_hourly` from the retained hour of metadata with
two `INSERT ... SELECT ... GROUP BY`. One-off, ~0.5 s, so an upgraded install
shows its last hour immediately instead of an empty chart.

### Reader (`GET /api/stats`, `adsb/api.py` + statements in `adsb/traffic.py`)

Query parameters: `window` seconds (default 86400, 60..604800), `interval`
seconds (default 900, 60..86400, must divide evenly into the window), `limit`
(default 10, 1..100).

Response (`adsb/schemas.py: StatsSchema`):

```json
{
  "now": 1788556190, "window": 86400, "interval": 900, "aircraft_seen": 412,
  "buckets": [{"start": 1788469800, "messages": 12345, "aircraft": 95}],
  "top_window":   [{"icao24": "a1b2c3", "callsign": "UAL123", "registration": "N12345",
                    "typecode": "B738", "messages": 4321, "lastseen": 1788556100}],
  "top_lifetime": [ ...same shape... ]
}
```

- `buckets` is the full grid, oldest first, aligned so the last bucket ends at
  `now` rounded up to the interval, with zero rows filled in server-side.
  Query: `SELECT (minute/:iv)*:iv AS b, SUM(messages), MAX(aircraft) FROM
  traffic_minutes WHERE minute >= :since GROUP BY b` (PK range scan).
- `top_window`: `SELECT aircraft_id, SUM(messages) FROM aircraft_hourly WHERE hour
  >= :since_hour GROUP BY aircraft_id ORDER BY 2 DESC LIMIT :n`, joined to
  `aircraft` for identity fields. `since_hour` is the window start floored to
  the hour, so "24 h" can include up to 59 extra minutes; documented.
- `top_lifetime`: `SELECT ... FROM aircraft ORDER BY count DESC LIMIT :n`.

Four statements total (buckets, aircraft_seen, top_window, top_lifetime). Added to `api_index()` routes, the README endpoint table
and the CHANGELOG.

### Tests (pytest)

- `tests/test_traffic.py`: upsert accumulates across batches; `aircraft` takes
  the max; purge respects the cutoff; backfill from metadata produces the
  expected minute rows and is a no-op when the table is non-empty.
- `tests/test_network.py`: `handle_messages` writes `traffic_minutes` and
  `aircraft_hourly` rows for a processed message.
- `tests/test_api.py`: `/api/stats` shape, zero-filled and aligned buckets,
  both top lists ordered and limited, validation (interval not dividing window
  is 422). Statements added to the `test_hot_statements_seek_their_index`
  parametrization. Smoke entry in `test_api_endpoints_exist`.
- `tests/test_database.py`: new indexes added to `NEW_INDEXES`.

## Frontend

### Data (`frontend/src/services/api.js`, `services/demo.js`, `hooks/useStats.js`)

- `fetchStats({ window, interval, limit })` calls `/api/stats`; in demo mode
  returns `fleet.stats(...)`.
- `DemoFleet.stats()` synthesises 24 h of buckets from the seeded PRNG with a
  diurnal curve (quiet overnight, busy afternoon) so the demo charts look
  realistic, and builds both top lists from the fleet's `count` values.
- `useStats(open, interval)` fetches when the overlay opens or the interval
  changes, refreshes every 60 s while open, and returns
  `{ stats, loading, error }`. It does nothing while closed.

### Pure helpers (`frontend/src/stats.js`, tested with `bun test`)

- `formatCount(n)`: `1,234` below 10 k, `12.3k` / `1.2M` above.
- `niceMax(max)`: rounds an axis maximum up to 1/2/5 × 10^k for gridlines.
- `timeTicks(buckets)`: picks x-axis label positions (every 3 h at 15-min
  buckets, every hour at 5 min, every 4 h at 1 h).
- `relativeTime(seconds, now)`: `just now`, `4 min ago`, `3 h ago`, `2 d ago`.
- `bucketRange(start, interval)`: `09:00 – 09:15` for tooltips.

### Components

- `components/HistoryOverlay.jsx` + `HistoryOverlay.css`: the screen.
  Rendered by `App` as a sibling of `header` and `main`, `position: absolute;
  inset: 0; z-index: 50`, glass background (`var(--surface)` + the existing
  blur recipe) so the live map shows faintly beneath. Content column
  `max-width: 1080px`, centred, scrolls internally (`overflow-y: auto`, the
  body never scrolls). `role="dialog" aria-modal="true" aria-labelledby`.
  Entrance: fade + 0.98→1 scale, 0.2 s `var(--ease)`; reduced-motion is
  already handled globally.
  Layout, top to bottom:
  1. Header row: title "History", subtitle "Last 24 hours · updated 12:04",
     interval segmented control (reuses `.segmented`/`.segment`), X button
     (reuses `.close-button`).
  2. Summary strip of three `.stat` tiles: messages (sum of buckets), peak
     aircraft in one minute (max over buckets), and aircraft heard in the
     window (`aircraft_seen`, from `COUNT(DISTINCT aircraft_id)` over
     `aircraft_hourly` in the window).
  3. Two chart cards, "Message volume" and "Aircraft tracked", each a
     `BarChart`.
  4. Two table cards side by side, "Top aircraft · last 24 hours" and
     "Top aircraft · all time"; they stack under 900 px.
- `components/BarChart.jsx`: plain HTML/CSS, no chart dependency (none is
  in the repo) and no measuring. A flex row of bar `div`s whose heights are
  percentages of `niceMax`, over absolutely positioned gridlines with
  right-aligned tabular labels; x labels from `timeTicks`. Each bar has a
  `title` (bucket range and value) and an `aria-label`; hovering brightens
  it. Empty data renders the frame with a muted "No traffic recorded yet".
- `components/TopAircraftTable.jsx`: a real `<table>` with three columns.
  Aircraft cell: callsign (or registration, or icao24) in 500 weight with a
  muted second line of registration · type. Messages right-aligned tabular.
  Last seen as relative time with the absolute time in `title`. Row hover
  uses `var(--surface-2)`. Rank number in `var(--ink-3)`.

### App wiring (`App.jsx`, `App.css`)

- `showHistory` state next to `showSettings`. A history button (clock with a
  counter-clockwise arrow, inline SVG, 1.75 stroke like the gear) goes inside
  the `.settings` group before the gear; both share `.toolbar-button` rules
  (the current `.settings-button` rules, renamed; the gear keeps its
  `rotate(60deg)` open state under a gear-specific selector).
- Opening the overlay closes the settings popover. Escape closes the overlay.
  Focus moves to the X on open and back to the history button on close.
- The map, polling hooks and selection state are untouched; nothing unmounts.

### Tests

- `bun test`: `stats.test.js` for the helpers; `api.test.js` gains a
  `fetchStats` URL test in the existing fetch-stub style.
- `bun run lint` and `bun run format:check` clean.

## Verification

1. `uv run pytest` and `uv run ruff check .` pass.
2. `cd frontend && bun test && bun run lint && bun run format:check` pass.
3. Playwright (MCP, not added to the repo) against `bun run dev:demo`: open
   the overlay from the toolbar, screenshot light and dark at 1440×900 and
   390×844, switch intervals, hover a bar, press Escape, confirm the map's
   header count is still updating underneath.
4. Playwright against `just dev` with the live receiver: `/api/stats` returns
   backfilled buckets for the last hour and real top lists; overlay renders
   them.
5. Codex CLI reviews the spec before implementation and the diff after.
