default:
    @just --list

# Run backend and Vite dev servers together; pass ARGS to `adsb start backend`.
dev *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    uv run adsb start backend {{ARGS}} &
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

# Build the frontend and stage it into the Python package.
build:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v bun >/dev/null 2>&1 || {
        echo "error: bun not found. Run \`just bootstrap\` (or see https://bun.sh)." >&2
        exit 1
    }
    (cd frontend && bun install --frozen-lockfile && bun run build)
    mkdir -p adsb/static
    find adsb/static -mindepth 1 ! -name .gitkeep -delete
    cp -r frontend/dist/. adsb/static/

# Remove the bundled frontend (preserves adsb/static/.gitkeep).
clean:
    find adsb/static -mindepth 1 ! -name .gitkeep -delete 2>/dev/null || true
    rm -rf frontend/dist
