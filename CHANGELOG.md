# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **The backend no longer purges stale aircraft.** Previously anything not seen within
  `--stale-timeout` was deleted every 30 seconds, taking its positions and reception
  metadata with it, so the map's "max age" slider could never reach past the last minute
  and the database was useless for offline analysis. Aircraft are now retained forever and
  `/api/all` and `/api/icao24` filter by age instead, via a new `max_age` query parameter
  (seconds) that defaults to `--stale-timeout`. The map passes its slider value through
  and refetches when it changes, so dragging it older brings aircraft back. `adsb cleanup`
  remains as an explicit, manual purge and gained `--stale-timeout`.
- The header's aircraft count now counts what the map draws. Mode-S-only aircraft (no
  position) are tracked but invisible, and with the wider age window they were inflating
  the number well past the markers on screen.
- The "Max age" and "Refresh interval" boxes no longer snap to "0" when cleared (which
  then read back as "020" as you typed), and partially typed or out-of-range values are
  never applied, so the map keeps polling with the last valid setting until you finish.

### Fixed
- **Aircraft enrichment was silently broken on every `pip install`.** `adsb download`
  wrote `./data/aircraft.csv` relative to the working directory, while the loader read
  `<package parent>/data/aircraft.csv` — `site-packages/data/` in a wheel, which nothing
  ever wrote to. Registration, type code, and type description came back `null` forever,
  signalled only by a warning emitted lazily mid-decode. Both sides now resolve the same
  per-user data directory via `aircraft_db.aircraft_db_path()`.
- A source checkout with no frontend build gave no hint that `just build` was the missing
  step. `adsb start frontend` now refuses to start with an explanatory error.

### Added
- **Demo mode.** `adsb start frontend --demo` (or `bun run dev:demo` / `just dev-demo`
  for the Vite dev server) shows a simulated fleet with track history and no backend
  running. The simulation lives in the browser behind the SPA's data layer, so it
  exercises the real map, polling, filtering, and track code paths. The header shows a
  "Demo data" badge.
- **Backend and frontend are separate services** that can run on different machines.
  - `adsb start backend` is the decoder + REST API and nothing else: no HTML, no static
    files, no CORS.
  - `adsb start frontend [--api-url http://receiver:8000]` serves the bundled map and
    reverse-proxies `/api/*` to the backend (same machine by default), so the browser
    stays same-origin and the backend needs no CORS configuration. It serves `/config.js`
    from its own `MAPBOX_TOKEN`, so the token lives with the UI. A backend that is down
    surfaces as a 502/504 JSON error.
  - `ADSB_API_URL=http://receiver:8000 bun run dev` (or `just dev-frontend URL`) points
    the Vite dev/preview proxy at a remote backend; Vite serves its own `/config.js` from
    `VITE_MAPBOX_TOKEN`. New `just backend`, `just frontend`, `just dev-frontend` recipes.
- Startup checks for the conditions that otherwise fail silently: `adsb start backend`
  reports the aircraft database and data source; `adsb start frontend` reports
  `MAPBOX_TOKEN`.
- `adsb start backend` prints a `[STATUS]` line every `--stats-interval` seconds (default
  10, `0` disables): feed address, time since the last message (flagging a stalled feed),
  messages/positions/aircraft in the window with the message rate, aircraft currently
  tracked, and cumulative totals. Replaces the old telemetry lines, which only fired while
  messages were flowing.
- `GET /` on the backend returns the same discovery JSON as `/api` (now also listing
  `/docs`) instead of a 404, so opening port 8000 in a browser explains where the data is.
- `--aircraft-db PATH` on `adsb start backend`, `adsb download` and `adsb decode` overrides the
  aircraft database location.
- `just bootstrap` installs bun; `just build` now fails with an actionable message when
  bun is missing instead of a bare "command not found".
- `adsb download --force`; without it the command is a no-op when the database is
  already present rather than re-fetching ~9MB.

### Changed
- **Breaking:** `adsb serve` is replaced by `adsb start backend` + `adsb start frontend`.
  The backend no longer serves the map at `/` or `/config.js`; visit the frontend's port
  (3000 by default) instead. `just serve` → `just backend`.
- `adsb download` streams the gzip straight to CSV via a `.partial` temp file, so no
  `aircraft.csv.gz` is left on disk and a failed download cannot leave a truncated CSV
  where the loader would read it.
- **Breaking:** `adsb download --data-dir` is removed; use `--aircraft-db PATH` instead
  (same flag on `start backend` and `decode`). Single supported location, single
  override mechanism.
- `.env` is for secrets only (`MAPBOX_TOKEN`); every other setting is a CLI argument.
  Configuration is never read from `ADSB_*` environment variables.
- CORS middleware is removed from the backend: every browser path (bundled UI and Vite
  dev server) reaches the API through a same-origin proxy.
- Everything browser-facing (static files, SPA fallback, `/config.js`) moved from
  `adsb.api` to the new `adsb.ui` module; `adsb.api` is JSON only.
- `httpx` is now a runtime dependency (used by the `adsb start frontend` proxy).
- Per-request HTTP access logging on the backend is off by default (the map polls
  `/api/all` every second, drowning everything else); `--access-log` re-enables it.
- uvicorn's "Invalid HTTP request received." warning is filtered out of the backend
  console. It fires whenever non-HTTP bytes hit the port (a browser trying HTTPS, a LAN
  device probing) and is routine noise on a server bound to `0.0.0.0`.
- `ADSBNetworkClient` exposes `snapshot()` for thread-safe stats; the `telemetry_interval`
  argument and `_log_telemetry` are gone.
- **Breaking:** `AircraftDatabase` no longer auto-extracts a sibling `aircraft.csv.gz`;
  `adsb download` is the one supported way to obtain the database.
- `adsb.api._frontend_is_bundled` is now `adsb.ui.frontend_is_bundled`.

### Removed
- `MANIFEST.in`, which was dead — hatchling ignores it, and its `recursive-include adsb
  *.py` would have *excluded* the bundled frontend had anything honoured it.

## [0.2.0] - 2026-05-01

### Added
- Bundled React frontend in the published wheel: `pip install adsb-map && adsb serve`
  now boots both API and interactive map on a single port. Previously the wheel shipped
  only the backend and required a separate Vite dev server for the UI.
- Runtime config shim served at `/config.js` exposes `MAPBOX_TOKEN` to the SPA from
  server environment, so one wheel works for any user without rebuilding the JS bundle
  per Mapbox token.
- `.env` file support: `adsb serve` loads `.env` from the working directory (and parents)
  via python-dotenv. Process environment still wins over `.env` values. Template at
  `.env.example`.
- `justfile` with `dev`, `build`, `serve`, `clean` recipes for the local development
  loop. `just dev` runs backend and Vite dev server concurrently with hot reload; Vite
  proxies `/api/*` and `/config.js` to the backend so the dev frontend hits the API
  same-origin.
- SPA fallback for client-side routing; unknown `/api/*` paths still return 404 instead
  of leaking the SPA shell.

### Changed
- **REST API paths moved under `/api/*` prefix**: `/all` → `/api/all`, `/icao24` →
  `/api/icao24`, `/track` → `/api/track`, `/sensors` → `/api/sensors`. The `/` route
  is now reserved for the bundled UI. Welcome JSON moved to `/api`.
- Versioning is now derived from git tags via `hatch-vcs`; `pyproject.toml` no longer
  hardcodes a version. Tag `vX.Y.Z` and push to release.
- CORS middleware is now only registered in dev mode (when the frontend is not bundled).
  Bundled-wheel installs serve same-origin and don't need CORS at all.
- README rewritten around the single-process launch model: Quickstart, Configuration
  table, CLI summary, API endpoint table, Develop-from-source section, Release-flow note.
- CI: `actions/checkout` v4 → v5, `astral-sh/setup-uv` v3 → v8.1.0,
  `codecov/codecov-action` v4 → v5 (with `file` → `files` rename). Publish workflow
  gains a `concurrency` block, `contents: read` permission, and PyPI deployment URL.
- Python dependencies refreshed via `uv lock --upgrade`. `pyModeS` pinned to `<3`
  because v3 is a breaking API migration that requires source-level changes in
  `adsb/decoder.py` (deferred to a future release).
- Frontend dependencies refreshed: `mapbox-gl` 3.16 → 3.23, plus minor bumps to
  ESLint, Prettier, and types.
- `adsb --version` and the FastAPI `version=` field now reflect the actual installed
  package version (previously hardcoded `"0.1.0"` had drifted from the published
  `0.1.1`).

### Removed
- `fetchAircraftByIcao` helper from `frontend/src/services/api.js` — dead code that
  pointed at a nonexistent backend route.

### Fixed
- `/config.js` is now registered in both bundled and dev modes; previously it only
  existed when the frontend was bundled, causing the dev-server proxy to 404 and the
  SPA's `<script src="/config.js">` to silently fail (the frontend's
  `import.meta.env` fallback masked the breakage in dev).
- `just build` and the CI staging step preserve the tracked `adsb/static/.gitkeep`
  marker; previously `rm -rf adsb/static` left the working tree dirty after every
  build.

## [0.1.1] - 2024-11-07

### Fixed
- Fixed broken image link on PyPI (now uses absolute GitHub URL)
- Added PyPI version badge to README
- Added CI and Publish workflow status badges
- Corrected GitHub repository URLs in badges (adsb → adsb-map)

## [0.1.0] - 2024-11-07

### Added
- Initial release of adsb-map
- ADS-B decoder using pyModeS library
- FastAPI REST API server with jet1090-compatible endpoints
- React frontend with Mapbox GL for real-time aircraft visualization
- Aircraft database integration with 566,000+ aircraft records from tar1090-db
- SQLite storage for aircraft state, positions, and metadata
- CLI tools for server management:
  - `adsb serve` - Start API server with network data source support
  - `adsb download` - Download aircraft database
  - `adsb init-db` - Initialize database tables
  - `adsb decode` - Decode single ADS-B messages
  - `adsb cleanup` - Remove stale aircraft
  - `adsb db-size` - Display database statistics
- Network client supporting Beast and raw formats (dump1090, readsb)
- Automatic aircraft enrichment with registration and type information
- Position decoding with CPR (Compact Position Reporting)
- Support for multiple ADS-B message types (DF4, DF5, DF17, DF20, DF21)
- Comprehensive test suite with 47 tests
- Pre-commit hooks with Ruff linting and formatting
- GitHub Actions CI workflow testing Python 3.12 and 3.13
- Tox configuration for multi-version testing
- Complete API documentation in README
