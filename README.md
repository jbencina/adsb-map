# ADS-B Decoder and REST API

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/adsb-map.svg)](https://pypi.org/project/adsb-map/)
[![CI](https://github.com/jbencina/adsb-map/actions/workflows/ci.yml/badge.svg)](https://github.com/jbencina/adsb-map/actions/workflows/ci.yml)
[![Publish](https://github.com/jbencina/adsb-map/actions/workflows/publish.yml/badge.svg)](https://github.com/jbencina/adsb-map/actions/workflows/publish.yml)

ADS-B decoder and REST API server using [pyModeS](https://github.com/junzis/pyModeS) for
decoding Mode-S and ADS-B messages. Mirrors the [jet1090](https://github.com/xoolive/rs1090/)
REST API interface with a Python-based implementation, plus an interactive map that runs as
a separate service — on the same machine or anywhere that can reach the API.

![Map interface demo](https://raw.githubusercontent.com/jbencina/adsb-map/main/docs/map.png)

## Quickstart

Two services: the **backend** (decoder + REST API) and the **frontend** (map UI). The
published wheel contains both, including the prebuilt React UI, so you only need Python —
no Node, no bun, no Docker.

```bash
pip install adsb-map
adsb download                                # one-time: aircraft database (~30MB)

# Terminal 1 — on the machine attached to the receiver:
adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

# Terminal 2 — wherever you want to look at the map (same machine, or a laptop):
# Free Mapbox token: https://account.mapbox.com/access-tokens/
# Export it, or put it in a `.env` file in the directory you run this from.
export MAPBOX_TOKEN=pk.your_token_here
adsb start frontend                          # add --api-url http://receiver:8000 if remote

# Or run both in one command:
adsb start all --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

Visit http://localhost:3000/. Aircraft show up as markers; click one for its track.

The frontend proxies `/api/*` to the backend, so the browser only ever talks to the
frontend process: no CORS, no per-machine build, and the Mapbox token stays with the UI.
See [Running on separate machines](#running-on-separate-machines).

## Features

- **pyModeS decoding** — DF4/5/17/18/20/21 message types with CPR position decoding
- **Aircraft enrichment** — automatic registration / type / description lookup from
  the [Mictronics aircraft database](https://www.mictronics.de/aircraft-database/)
  (566k+ records, ODC-By), fetched via [tar1090-db](https://github.com/wiedehopf/tar1090-db);
  see [Aircraft database attribution](#aircraft-database-attribution)
- **REST API** — FastAPI endpoints under `/api/*`, jet1090-compatible
- **SQLite storage** — aircraft state, position history, reception metadata; nothing is
  purged while running, so the file doubles as a log for offline analysis
- **Interactive map** — React + Mapbox GL, prebuilt and shipped in the wheel; signal-strength
  indicator per aircraft and an optional shade-by-signal view of the markers
- **Separate services** — backend on the receiver, frontend on any machine that can reach it
- **Network data sources** — connects to dump1090 / readsb / modesdeco2 over TCP (Beast or raw)

## Configuration

Everything is a CLI argument except the Mapbox token. `.env` is for secrets only.

| Setting | Default | How to override |
|---|---|---|
| **Backend** | | |
| Bind host / port | `0.0.0.0` / `8000` | `adsb start backend --host --port` |
| Database path | `./adsb.db` | `adsb start backend --db-path` |
| Stale timeout (default API window) | `60s` | `adsb start backend --stale-timeout` |
| Receiver lat/lon | (none) | `adsb start backend --lat --lon` (recommended) |
| Aircraft database | per-user data dir | `--aircraft-db PATH` on `start backend`, `download`, `decode` |
| Status line interval | `10s` | `adsb start backend --stats-interval` (`0` disables) |
| Reception metadata retention | `3600s` | `adsb start backend --metadata-retention` (`0` keeps everything) |
| HTTP access log | off | `adsb start backend --access-log` |
| **Frontend** | | |
| Backend URL | `http://127.0.0.1:8000` | `adsb start frontend --api-url` |
| Bind host / port | `127.0.0.1` / `3000` | `adsb start frontend --host --port` (`--host 0.0.0.0` to share on the LAN) |
| Mapbox token | (required) | `MAPBOX_TOKEN` env var, or `.env` file in CWD |
| Demo mode | off | `adsb start frontend --demo` (simulated aircraft, no backend) |

`adsb download` writes the aircraft database to a per-user data directory
(`~/.local/share/adsb-map/aircraft.csv` on Linux) rather than the working directory, so
`adsb start backend` finds it no matter where you launch it from. Pass the same `--aircraft-db`
to both if you relocate it. `adsb start backend` prints a startup check confirming whether it was
found.

`--lat` and `--lon` are strongly recommended: ADS-B position messages use Compact Position
Reporting (CPR), which decodes faster and more accurately when given a reference position
within ~180 NM of the receiver.

While running, the backend prints a status line every `--stats-interval` seconds so you
can tell at a glance whether the feed is alive and what it is decoding:

```
2026-09-02 19:05:10 - [STATUS] feed localhost:30005 (beast) | last msg <1s ago | 10s: 1,842 msgs (184/s), 131 pos, 27 ac | tracking 31 ac (24 w/ pos) | total 96,210 msgs, 7,455 pos, 142 ac
```

`last msg … (feed stalled?)` appears when nothing has arrived for over 30 seconds, and
`no data yet` until the first message. Per-request HTTP logging is off by default because
the map polls `/api/all` every second; `--access-log` turns it back on.

## CLI

```bash
adsb start backend …    # decoder + REST API
adsb start frontend …   # map UI, proxying to a backend (--api-url URL, or --demo for simulated traffic)
adsb download           # download tar1090-db aircraft database (--force to refresh)
adsb init-db            # create SQLite tables
adsb decode HEX         # decode a single message and store it
adsb cleanup            # purge aircraft not seen in --stale-timeout (manual; never automatic)
adsb db-size            # show DB file size and row counts
```

Pass `--help` to any command for the full set of options.

## API endpoints

All JSON endpoints live under `/api/` on the backend. The frontend exposes the same
paths (proxied) plus the map itself.

| Endpoint | Returns |
|---|---|
| `GET /api/all?max_age={seconds}` | Aircraft state vectors seen within `max_age` (default: `--stale-timeout`) |
| `GET /api/icao24?max_age={seconds}` | ICAO24 addresses seen within `max_age` (default: `--stale-timeout`) |
| `GET /api/track?icao24={icao24}&since={ts}` | Trajectory for one aircraft |
| `GET /api/tracks?max_age={seconds}&since={ts}` | Trajectories of every aircraft in the window, keyed by ICAO24; `since` overrides the window for incremental polling |
| `GET /api/sensors` | Receiver/sensor serials heard within `--metadata-retention` |
| `GET /api/stats?window={seconds}&interval={seconds}&limit={n}` | Traffic history: messages and peak aircraft per interval (default 24 h in 15-min buckets), plus top aircraft by messages in the window and over their lifetime |
| `GET /api` | API discovery (welcome JSON) |
| `GET /docs` | Interactive OpenAPI docs (backend) |
| `GET /` | Backend: same discovery JSON as `/api`. Frontend: the map |
| `GET /config.js` | Runtime config shim exposing `MAPBOX_TOKEN` to the SPA (frontend only) |

The backend never deletes aircraft or their positions. `--stale-timeout` only sets the
default `max_age` window, so the map's "max age" slider can reach back through everything
the database holds, and the SQLite file stays complete for offline analysis. Run
`adsb cleanup` yourself if you ever want to reclaim space. Per-message reception metadata
(RSSI, receiver serial) is the exception: it is only shown for live aircraft, so the
backend trims it to a rolling window (`--metadata-retention`, 0 keeps everything).

The database runs in SQLite WAL mode, so `adsb.db-wal` and `adsb.db-shm` alongside
`adsb.db` are normal while the backend is running.

The REST API is self-contained — you can ignore the map and build your own client
(mobile, monitoring system, dashboard, etc.) against the backend's `/api/*`.

## Track lines on the map

Every track line on the map comes from one place: the positions the backend stores,
fetched in bulk from `/api/tracks`. "Show tracks" draws every aircraft's line, and
clicking an aircraft highlights that same line, so the two can never disagree and the
line reaches back through the whole "max age" window, not just since the page opened.
The UI seeds from the window once, then polls with `since` set to the newest timestamp
it holds, so each refresh only carries the last second or so of positions. It polls only
while lines are being drawn.

The marker's rotation is a different measurement: the ground track from the aircraft's
latest velocity report, not something derived from the positions. A marker can point a
few degrees off its own line because the two come from different messages. Rotation is
animated and always turns the short way round, so a track crossing north (359° to 1°)
nudges the marker rather than spinning it.

## Running on separate machines

The receiver host (a Raspberry Pi next to the SDR, say) runs the backend. The frontend
runs wherever you want to look at the map and only needs network access to the backend's
port:

```bash
# On the receiver:
adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

# On your laptop (pip install adsb-map first; MAPBOX_TOKEN in env or .env):
adsb start frontend --api-url http://receiver.local:8000
```

Or run both on one machine against a remote receiver. `adsb start all` binds to
`127.0.0.1` by default; `--host` opens both services up and is also the address the
UI proxies to, so pass it rather than relying on loopback:

```bash
adsb start all --host 0.0.0.0 --backend-port 8000 --frontend-port 3000 \
  --source net --connect receiver.local 30005 beast --lat 40.7 --lon -74.0
```

The frontend reverse-proxies `/api/*` to the backend, so the browser stays same-origin and
the backend needs no CORS configuration. If the backend is unreachable the UI reports a
502 rather than hanging. Add `--host 0.0.0.0` to share the UI on your LAN.

For UI development against a remote backend, the Vite dev server proxies the same way:

```bash
cd frontend
ADSB_API_URL=http://receiver.local:8000 bun run dev
```

`ADSB_API_URL` is a shell variable on the command line, not a `.env` entry. Same story for
`bun run preview` after a build.

## Demo mode

To try the map, or work on the UI, without a receiver or backend at all, add `--demo`:

```bash
adsb start frontend --demo                 # bundled UI
cd frontend && bun run dev:demo            # Vite, hot reload
```

The browser then answers every API call from a built-in simulator: a fixed fleet of
airliners and light aircraft flying around the default map center, complete with track
history, occasional reception gaps, and a couple of contacts without a position. The
header shows a "Demo data" badge so simulated traffic is never mistaken for real. A
Mapbox token is still needed for the base map.

## Network data sources

The decoder connects to existing ADS-B receivers via TCP:

- **dump1090** — port 30005 (Beast), 30002 (raw)
- **readsb** — same ports as dump1090
- **modesdeco2**, or any Beast / raw hex feed

Signal strength (RSSI, in dBFS) is only available from Beast feeds; the raw hex format carries no signal level, so `rssi` stays `null` there and the map shows "No data" for signal.

```bash
adsb start backend --source net --connect <host> <port> <beast|raw> --lat <lat> --lon <lon>
```

The network client runs in a background thread, decodes messages, updates the database,
and prunes stale aircraft every 30 seconds.

## Develop from source

The repo uses [`just`](https://github.com/casey/just) for setup, running both development
servers, building the bundled UI, and cleaning generated assets. Run individual services
with `uv run adsb …` or Bun directly. Building the UI from source needs a JS toolchain —
end users installing the wheel do not.

```bash
# Prerequisites (once per machine)
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
uv tool install rust-just                           # just (distro packages are often stale)

git clone https://github.com/jbencina/adsb-map.git
cd adsb-map
just bootstrap                                # installs bun if missing
uv sync --dev
uv run adsb download                          # one-time

echo 'MAPBOX_TOKEN=pk.your_token_here' > .env    # shared by backend, bundled UI and Vite

# Args after `dev` are passed straight through to `adsb start backend`.
just dev --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

Visit http://localhost:3000/. Vite proxies `/api/*` to the backend on port 8000 and serves
its own `/config.js` from `MAPBOX_TOKEN` in the repo-root `.env`, so the dev UI behaves exactly like
`adsb start frontend`. To run the halves separately, use these in two terminals:

```bash
uv run adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
cd frontend && bun run dev
```

Vite proxies to `http://localhost:8000` by default. Set `ADSB_API_URL` on the Bun
command to use a remote backend, as shown above.

To exercise the production-style bundled frontend locally:

```bash
just build                                                # frontend → adsb/static/ (needs bun)
MAPBOX_TOKEN=pk.… uv run adsb start all --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
# Visit http://localhost:3000/
```

`adsb start all` runs the backend and bundled UI together. Use `just dev` when
editing the frontend: it runs Vite so source changes appear without rebuilding.
For a remote backend, run only `uv run adsb start frontend --api-url http://receiver:8000`.

### Tests, linting, formatting

```bash
uv run pytest                                 # full test suite
uv run pytest --cov=adsb --cov-report=term-missing
uv run tox                                    # multi-version (3.12, 3.13, 3.14)

uv run ruff check .                           # lint
uv run ruff format .                          # format
uv run pre-commit install                     # one-time: enable git hooks
uv run pre-commit run --all-files
```

Frontend: `bun run test`, `bun run lint`, `bun run format` from `frontend/`.

Verify the wheel ships the bundled frontend (run before merging changes that
touch packaging, the static mount, or the publish workflow):

```bash
just build
uv sync --locked --group build
uv build --no-build-isolation
uv run --no-sync twine check --strict dist/*
uv run --no-sync python scripts/check_dist.py dist
```

CI pins Bun using `.bun-version` and uv in the workflows. The build group locks
Hatchling, hatch-vcs, and Twine alongside the other Python dependencies. Ordinary
`uv build` still works with an isolated build environment; the command above uses
the locked build tools. Run `uv lock --upgrade` to refresh Python dependencies,
then test on Python 3.12–3.14. Keep the Ruff version in `pyproject.toml`, `tox.ini`,
and `.pre-commit-config.yaml` aligned. pyModeS remains on 2.x pending a decoder migration.

## Architecture

**Backend (`adsb/`)**

| Module | Responsibility |
|---|---|
| `decoder.py` | pyModeS-based message decoding, CPR positions, DB enrichment |
| `network.py` | `ADSBNetworkClient` — daemon thread reading from dump1090/readsb |
| `api.py` | Backend FastAPI app — `/api/*` JSON only |
| `ui.py` | Frontend FastAPI app — bundled SPA, `/config.js` from `MAPBOX_TOKEN`, reverse proxy for `/api/*` |
| `models.py` | SQLAlchemy ORM: `Aircraft`, `AircraftPosition`, `AircraftMetadata` |
| `database.py` | Session/engine management with context-manager pattern |
| `schemas.py` | Pydantic response models |
| `aircraft_db.py` | Lazy-loaded singleton CSV (566k+ rows) → registration/type lookup; owns `aircraft_db_path()`, the one location both `download` and the loader use |
| `status.py` | `StatusReporter` — daemon thread printing the periodic `[STATUS]` line |
| `traffic.py` | Per-minute / per-aircraft-hour traffic aggregates: writer, purge, backfill, and the `/api/stats` statements |
| `cli.py` | Click CLI: `start backend`, `start frontend`, `download`, `init-db`, `decode`, `cleanup`, `db-size` |
| `static/` | Built frontend assets served by `ui.py` (populated by `just build` or CI; gitignored) |

**Frontend (`frontend/src/`)** — React 18 + Vite, compiled and bundled into the wheel
during release. End users never need a JS toolchain.

### Release flow

CI (`.github/workflows/publish.yml`) handles all of this on a `v*` tag push:

1. The reusable CI workflow runs Python tests on 3.12–3.14 on Linux and macOS,
   Ruff, and frontend tests. Python environments must match `uv.lock`.
2. The pinned Bun toolchain builds the UI from `frontend/bun.lock` and stages it
   into `adsb/static/`.
3. Locked build tools create an sdist, then build the wheel from that sdist.
   Validation checks metadata, frontend assets, rebuild sources, and the tag's
   version. A fresh environment installs the wheel and checks the CLI and UI.
4. Only after every check passes, a separate job downloads those exact artifacts
   and uses `uv publish --trusted-publishing always` to ship them via PyPI OIDC.
   Build jobs have read-only repository permissions and no publishing credentials.
5. A separate job creates the GitHub Release using the same artifacts and a notes
   file extracted from `CHANGELOG.md` (or generated notes if no section exists).

The PyPI trusted publisher continues to use the `publish.yml` workflow and `pypi`
environment. The sdist contains the frontend source, lockfile, and build/test
configuration so the bundled UI can also be rebuilt from source.

The Mapbox token is **not** baked into the wheel. At runtime, `adsb start frontend`
exposes `/config.js` which reads `MAPBOX_TOKEN` from its environment (process env, or a
`.env` file in CWD via `python-dotenv`) and writes `window.APP_CONFIG` for the SPA.
One wheel works for any user — no rebuild per token, and the backend never sees it.

## Database schema

| Table | Purpose |
|---|---|
| `aircraft` | Current state per aircraft (position, velocity, ID, telemetry, registration/type) |
| `aircraft_positions` | Historical positions for trajectory rendering |
| `aircraft_metadata` | Reception metadata (timing, RSSI, receiver serial); rolling `--metadata-retention` window |
| `traffic_minutes` | Messages and distinct aircraft per minute, for the history view; rolling 7 days |
| `aircraft_hourly` | Messages per aircraft per hour, for the history view's 24-hour top list; rolling 7 days |

See [`data/README.md`](data/README.md) for notes on the aircraft database file.

## Aircraft database attribution

The registration, type code and type description fields come from the
[Mictronics aircraft database](https://www.mictronics.de/aircraft-database/), published
under the [Open Data Commons Attribution License (ODC-By) v1.0](https://opendatacommons.org/licenses/by/1-0/).
`adsb download` fetches it from [wiedehopf/tar1090-db](https://github.com/wiedehopf/tar1090-db),
which repackages the Mictronics export (with a few community merges) as one gzipped CSV.
tar1090-db is treated as a distribution mirror only: the data and its licence are
Mictronics', and the credit stays with them.

ODC-By asks that the attribution travel with the data, so it is surfaced wherever the
enriched fields appear: the map's detail card, the `/api` discovery document
(`aircraft_db`), the end of `adsb download`, and `adsb download --help`. If you build
something on top of `/api/all` and show the registration or type fields, carry the notice
through:

> Aircraft registration and type data: Mictronics aircraft database
> (https://www.mictronics.de/aircraft-database/), Open Data Commons Attribution License v1.0,
> distributed via wiedehopf/tar1090-db.

The Python constants live in `adsb/aircraft_db.py` (`AIRCRAFT_DB_ATTRIBUTION`,
`AIRCRAFT_DB_NOTICE`) and the UI copy in `frontend/src/constants.js`
(`AIRCRAFT_DB_CREDIT`). See [`data/README.md`](data/README.md) for the file format.

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE).
The aircraft database is a separate work under ODC-By; see above.
