default:
    @just --list

# Run backend + Vite dev server (hot reload) on this machine.
# Pass extra args straight through to `adsb start backend`.
# Example: just dev --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
dev *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    uv run adsb start backend {{ARGS}} &
    (cd frontend && bun run dev) &
    wait

# Run only the Vite dev server, proxying /api/* to a backend (local or remote).
# Example: just dev-frontend http://receiver.local:8000
dev-frontend API_URL="http://localhost:8000":
    cd frontend && ADSB_API_URL={{API_URL}} bun run dev

# Run the decoder + API.
# Example: just backend --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
backend *ARGS:
    uv run adsb start backend {{ARGS}}

# Run the bundled map UI against a backend (run `just build` first).
# Example: just frontend http://receiver.local:8000 --host 0.0.0.0
frontend API_URL="http://127.0.0.1:8000" *ARGS:
    uv run adsb start frontend --api-url {{API_URL}} {{ARGS}}

# Install the frontend toolchain. Run once on a fresh checkout.
bootstrap:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v bun >/dev/null 2>&1; then
        echo "bun $(bun --version) already installed"
    else
        curl -fsSL https://bun.sh/install | bash
        echo 'bun installed - add to PATH: export PATH="$HOME/.bun/bin:$PATH"'
    fi

# Build frontend and stage into adsb/static so `adsb start frontend` and the wheel can serve it.
# Preserves the tracked .gitkeep so `git status` stays clean after building.
build:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v bun >/dev/null 2>&1 || {
        echo "error: bun not found. Run \`just bootstrap\` (or see https://bun.sh)." >&2
        exit 1
    }
    (cd frontend && bun install && bun run build)
    mkdir -p adsb/static
    find adsb/static -mindepth 1 ! -name .gitkeep -delete
    cp -r frontend/dist/. adsb/static/

# Remove the bundled frontend (preserves adsb/static/.gitkeep).
clean:
    find adsb/static -mindepth 1 ! -name .gitkeep -delete 2>/dev/null || true
    rm -rf frontend/dist
