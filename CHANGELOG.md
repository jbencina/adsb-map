# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

