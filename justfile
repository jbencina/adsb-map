default:
    @just --list

# Run backend + Vite dev server concurrently with hot reload.
# Pass extra args straight through to `adsb serve`.
# Example: just dev --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
dev *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    uv run adsb serve {{ARGS}} &
    (cd frontend && bun run dev) &
    wait

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

# Build frontend and stage into adsb/static for a single-process run / wheel build.
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

# Run the bundled single-process server (run `just build` first).
# Example: MAPBOX_TOKEN=pk.… just serve --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
serve *ARGS:
    uv run adsb serve {{ARGS}}

# Remove the bundled frontend (preserves adsb/static/.gitkeep).
clean:
    find adsb/static -mindepth 1 ! -name .gitkeep -delete 2>/dev/null || true
    rm -rf frontend/dist
