# ADS-B Decoder and REST API

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/adsb-map.svg)](https://pypi.org/project/adsb-map/)
[![CI](https://github.com/jbencina/adsb-map/actions/workflows/ci.yml/badge.svg)](https://github.com/jbencina/adsb-map/actions/workflows/ci.yml)
[![Publish](https://github.com/jbencina/adsb-map/actions/workflows/publish.yml/badge.svg)](https://github.com/jbencina/adsb-map/actions/workflows/publish.yml)

ADS-B decoder and REST API server using [pyModeS](https://github.com/junzis/pyModeS) for
decoding Mode-S and ADS-B messages. Mirrors the [jet1090](https://github.com/xoolive/rs1090/)
REST API interface with a Python-based implementation, plus an interactive map that runs
either on the same port as the API or as a separate client on another machine.

![Map interface demo](https://raw.githubusercontent.com/jbencina/adsb-map/main/docs/map.png)

## Quickstart

The published wheel bundles the React UI; FastAPI serves the API and map on a single port.
You only need Python — no Node, no bun, no Docker.

```bash
pip install adsb-map
adsb download                                # one-time: aircraft database (~30MB)

# Free Mapbox token: https://account.mapbox.com/access-tokens/
# Either export it in your shell, or drop it in a `.env` file in the directory
# you run `adsb start backend` from (template: see .env.example in the repo).
export MAPBOX_TOKEN=pk.your_token_here

adsb start backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

Visit http://localhost:8000/. Aircraft show up as markers; click one for its track.

To run the map on a different machine from the receiver, see
[Split deployment](#split-deployment-backend-and-frontend-on-different-machines).

## Features

- **pyModeS decoding** — DF4/5/17/18/20/21 message types with CPR position decoding
- **Aircraft enrichment** — automatic registration / type / description lookup from
  the [tar1090-db](https://github.com/wiedehopf/tar1090-db) project (566k+ records)
- **REST API** — FastAPI endpoints under `/api/*`, jet1090-compatible
- **SQLite storage** — aircraft state, position history, reception metadata
- **Interactive map** — React + Mapbox GL, served same-origin from the wheel
- **Split deployment** — `adsb start backend --no-ui` on the receiver, `adsb start frontend`
  as the client on any other machine
- **Network data sources** — connects to dump1090 / readsb / modesdeco2 over TCP (Beast or raw)

## Configuration

Everything is a CLI argument except the Mapbox token. `.env` is for secrets only.

| Setting | Default | How to override |
|---|---|---|
| Mapbox token | (required for map UI) | `MAPBOX_TOKEN` env var, or `.env` file in CWD |
| Bind host | `0.0.0.0` | `adsb start backend --host` |
| Bind port | `8000` | `adsb start backend --port` |
| Database path | `./adsb.db` | `adsb start backend --db-path` |
| Stale timeout | `60s` | `adsb start backend --stale-timeout` |
| Receiver lat/lon | (none) | `adsb start backend --lat --lon` (recommended) |
| Aircraft database | per-user data dir | `--aircraft-db PATH` on `serve`, `download`, `decode` |
| Serve the map UI | yes, if bundled | `adsb start backend --no-ui` (API only) |
| Backend for `adsb start frontend` | (required) | `adsb start frontend --api-url` |

`adsb download` writes the aircraft database to a per-user data directory
(`~/.local/share/adsb-map/aircraft.csv` on Linux) rather than the working directory, so
`adsb start backend` finds it no matter where you launch it from. Pass the same `--aircraft-db`
to both if you relocate it. `adsb start backend` prints a startup check confirming whether it was
found.

`--lat` and `--lon` are strongly recommended: ADS-B position messages use Compact Position
Reporting (CPR), which decodes faster and more accurately when given a reference position
within ~180 NM of the receiver.

## CLI

```bash
adsb start backend …    # decoder + API + bundled map UI (--no-ui for API only)
adsb start frontend …   # map UI as a client of a remote backend (--api-url URL)
adsb download           # download tar1090-db aircraft database (--force to refresh)
adsb init-db            # create SQLite tables
adsb decode HEX         # decode a single message and store it
adsb cleanup            # remove aircraft not seen in --stale-timeout
adsb db-size            # show DB file size and row counts
```

Pass `--help` to any command for the full set of options.

## API endpoints

All JSON endpoints live under `/api/`. The map UI is served at `/`.

| Endpoint | Returns |
|---|---|
| `GET /api/all` | All current aircraft state vectors |
| `GET /api/icao24` | List of ICAO24 addresses currently tracked |
| `GET /api/track?icao24={icao24}&since={ts}` | Trajectory for one aircraft |
| `GET /api/sensors` | Receiver/sensor info (serials) |
| `GET /api` | API discovery (welcome JSON) |
| `GET /` | Bundled map UI |
| `GET /config.js` | Runtime config shim (exposes `MAPBOX_TOKEN` to the SPA) |

The REST API is self-contained — you can ignore the bundled UI and build your own
client (mobile, monitoring system, dashboard, etc.) against `/api/*`.

## Split deployment: backend and frontend on different machines

The receiver host (a Raspberry Pi next to the SDR, say) runs only the decoder and API.
The map runs wherever you want to look at it. Two ways to run the client:

### 1. `adsb start frontend` — Python only

```bash
# On the receiver:
adsb start backend --no-ui --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

# On your laptop (pip install adsb-map first):
adsb start frontend --api-url http://receiver.local:8000
```

Visit http://localhost:3000/. `adsb start frontend` serves the bundled map and reverse-proxies `/api/*`
to the backend, so the browser stays same-origin and the backend needs no CORS setup. The
Mapbox token is fetched from the backend's `/config.js`; set `MAPBOX_TOKEN` on the laptop
instead if you would rather keep it off the receiver. Add `--host 0.0.0.0` to share the UI
on your LAN, and `--port` to move it.

`--no-ui` on the receiver is optional — it just skips serving the map there. Without it,
the receiver serves the map at `/` as usual and `adsb start frontend` still works.

### 2. Vite dev server — hot reload against a remote backend

```bash
cd frontend
ADSB_API_URL=http://receiver.local:8000 bun run dev        # or: just dev-frontend http://receiver.local:8000
```

`ADSB_API_URL` (a shell variable on the command line, not a `.env` entry) is the proxy
target for `/api/*` and `/config.js`. Same story for `bun run preview` after a build.

## Network data sources

The decoder connects to existing ADS-B receivers via TCP:

- **dump1090** — port 30005 (Beast), 30002 (raw)
- **readsb** — same ports as dump1090
- **modesdeco2**, or any Beast / raw hex feed

```bash
adsb start backend --source net --connect <host> <port> <beast|raw> --lat <lat> --lon <lon>
```

The network client runs in a background thread, decodes messages, updates the database,
and prunes stale aircraft every 30 seconds.

## Develop from source

The repo uses [`just`](https://github.com/casey/just) to run backend and frontend together
with hot reload. Building the UI from source needs a JS toolchain — end users installing
the wheel do not.

```bash
# Prerequisites (once per machine)
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
uv tool install rust-just                           # just (distro packages are often stale)

git clone https://github.com/jbencina/adsb-map.git
cd adsb-map
just bootstrap                                # installs bun if missing
uv sync --dev
uv run adsb download                          # one-time

cp frontend/.env.example frontend/.env        # then set VITE_MAPBOX_TOKEN

# Args after `dev` are passed straight through to `adsb start backend`.
just dev --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

Visit http://localhost:3000/. Vite proxies `/api/*` and `/config.js` to the backend on
port 8000, so the frontend hits the API as if it were same-origin. To run the two halves
separately, `just dev-backend …` (API only) and `just dev-frontend [URL]` (Vite, proxying
to `URL`, default `http://localhost:8000`).

To exercise the production-style single-process bundle locally:

```bash
just build                                                # frontend → adsb/static/ (needs bun)
MAPBOX_TOKEN=pk.… just backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
# Visit http://localhost:8000/
```

### Tests, linting, formatting

```bash
uv run pytest                                 # full test suite
uv run pytest --cov=adsb --cov-report=term-missing
uv run tox                                    # multi-version (3.12, 3.13)

uv run ruff check .                           # lint
uv run ruff format .                          # format
uv run pre-commit install                     # one-time: enable git hooks
uv run pre-commit run --all-files
```

Frontend: `bun run lint`, `bun run format` from `frontend/`.

Verify the wheel ships the bundled frontend (run before merging changes that
touch packaging, the static mount, or the publish workflow):

```bash
just build && uv build
unzip -l dist/adsb_map-*.whl | grep adsb/static/
# Expected: index.html + assets/*.js + assets/*.css
```

## Architecture

**Backend (`adsb/`)**

| Module | Responsibility |
|---|---|
| `decoder.py` | pyModeS-based message decoding, CPR positions, DB enrichment |
| `network.py` | `ADSBNetworkClient` — daemon thread reading from dump1090/readsb |
| `api.py` | FastAPI app — `/api/*` JSON, bundled SPA at `/` (unless `--no-ui`), runtime `/config.js` |
| `ui.py` | `adsb start frontend` — serves the bundled SPA and reverse-proxies `/api/*` to a remote backend |
| `models.py` | SQLAlchemy ORM: `Aircraft`, `AircraftPosition`, `AircraftMetadata` |
| `database.py` | Session/engine management with context-manager pattern |
| `schemas.py` | Pydantic response models |
| `aircraft_db.py` | Lazy-loaded singleton CSV (566k+ rows) → registration/type lookup; owns `aircraft_db_path()`, the one location both `download` and the loader use |
| `cli.py` | Click CLI: `start backend`, `start frontend`, `download`, `init-db`, `decode`, `cleanup`, `db-size` |
| `static/` | Built frontend assets (populated by `just build` or CI; gitignored) |

**Frontend (`frontend/src/`)** — React 18 + Vite, compiled and bundled into the wheel
during release. End users never need a JS toolchain.

### Release flow

CI (`.github/workflows/publish.yml`) handles all of this on a `v*` tag push:

1. `bun install && bun run build` produces `frontend/dist/`
2. `frontend/dist/` is staged into `adsb/static/`
3. `uv build` packages the wheel — `adsb/static/**` is included via the `artifacts`
   declaration in `pyproject.toml`
4. `uv publish --trusted-publishing always` ships to PyPI via OIDC (no API tokens stored)

The Mapbox token is **not** baked into the wheel. At runtime, the server exposes
`/config.js` which reads `MAPBOX_TOKEN` from its environment (process env, or a
`.env` file in CWD via `python-dotenv`) and writes `window.APP_CONFIG` for the SPA.
One wheel works for any user — no rebuild per token. `adsb start frontend` proxies the same
`/config.js` from the backend, so a token set on the receiver reaches remote clients too.

## Database schema

| Table | Purpose |
|---|---|
| `aircraft` | Current state per aircraft (position, velocity, ID, telemetry, registration/type) |
| `aircraft_positions` | Historical positions for trajectory rendering |
| `aircraft_metadata` | Reception metadata (timing, RSSI, receiver serial) |

See [`data/README.md`](data/README.md) for notes on the aircraft database file.

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE).
