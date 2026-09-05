# Development guide

[Back to the README](../README.md)

The repo uses [`just`](https://github.com/casey/just) for setup, running both development
servers, building the bundled UI, and cleaning generated assets. Run individual services
with `uv run adsb …` or Bun directly. Building the UI from source needs a JS toolchain —
end users installing the wheel do not.

If `just bootstrap` installs Bun, add it to your `PATH` as instructed before running
`bun install`. The bootstrap recipe installs the toolchain; `bun install` installs
the frontend dependencies.

```bash
# Prerequisites (once per machine)
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
uv tool install rust-just                       # just

git clone https://github.com/jbencina/adsb-map.git
cd adsb-map
just bootstrap                                # installs Bun if missing
(cd frontend && bun install --frozen-lockfile)
uv sync --locked --dev
uv run adsb download                          # one-time

# Add MAPBOX_TOKEN=pk.your_token_here to the repo-root .env file.

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
command to use a remote backend, as shown in the [README](../README.md#running-on-separate-machines).

To exercise the production-style bundled frontend locally:

```bash
just build                                                # frontend → adsb/static/ (needs bun)
MAPBOX_TOKEN=pk.… uv run adsb start all --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
# Visit http://localhost:3000/
```

`adsb start all` runs the backend and bundled UI together. Use `just dev` when
editing the frontend: it runs Vite so source changes appear without rebuilding.
For a remote backend, run only `uv run adsb start frontend --api-url http://receiver:8000`.

## Tests, linting, formatting

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
| `models.py` | SQLAlchemy ORM: `Aircraft`, `AircraftPosition`, `AircraftMetadata`, `TrafficMinute`, `AircraftHourly` |
| `database.py` | Session/engine management with context-manager pattern |
| `schemas.py` | Pydantic response models |
| `aircraft_db.py` | Lazy-loaded singleton CSV → registration/type lookup; owns `aircraft_db_path()`, the one location both `download` and the loader use |
| `status.py` | `StatusReporter` — daemon thread printing the periodic `[STATUS]` line |
| `traffic.py` | Per-minute / per-aircraft-hour traffic aggregates: writer, purge, backfill, and the `/api/stats` statements |
| `cli.py` | Click CLI: `start all`, `start backend`, `start frontend`, `download`, `init-db`, `decode`, `cleanup`, `db-size` |
| `static/` | Built frontend assets served by `ui.py` (populated by `just build` or CI; gitignored) |

**Frontend (`frontend/src/`)** — React 18 + Vite, compiled and bundled into the wheel
during release. End users never need a JS toolchain.

## Release flow

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
The same wheel works with any public Mapbox token; changing the token does not require a rebuild.
