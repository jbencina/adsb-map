"""Map UI server (`adsb start frontend`).

Serves the bundled React frontend and reverse-proxies ``/api/*`` to an
``adsb start backend`` instance, which may be on another machine. The browser
only ever talks to this process, so the backend needs no CORS configuration.
The Mapbox token is injected at request time via ``/config.js`` from this
process's ``MAPBOX_TOKEN``, so the token lives with the UI, not the receiver.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from adsb import __version__

logger = logging.getLogger("adsb.ui")

#: Built frontend, staged here by `just build` or CI before the wheel is built.
STATIC_DIR = Path(__file__).parent / "static"

#: Default backend, matching `adsb start backend` defaults on the same machine.
DEFAULT_API_URL = "http://127.0.0.1:8000"

#: Seconds to wait for the backend before answering 504. `/api/all` on a busy
#: receiver is well under a second; anything longer is a connectivity problem.
PROXY_TIMEOUT = 10.0

#: Hop-by-hop headers must not be forwarded by a proxy (RFC 7230 §6.1).
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        # Body is re-framed by Starlette; never copy the upstream length/encoding.
        "content-length",
        "content-encoding",
    }
)

FRONTEND_MISSING_HELP = (
    "Frontend not bundled ({static_dir} has no index.html). "
    "Run `just build`, or install the published wheel with `pip install adsb-map`."
)


def frontend_is_bundled(static_dir: Path | None = None) -> bool:
    """Return True when the built frontend has been staged into the package."""
    static_dir = STATIC_DIR if static_dir is None else static_dir
    return static_dir.is_dir() and (static_dir / "index.html").is_file()


def normalize_api_url(api_url: str) -> str:
    """
    Validate and normalise a backend base URL.

    Parameters
    ----------
    api_url : str
        Backend URL, e.g. ``http://receiver.local:8000`` (a scheme is required)

    Returns
    -------
    str
        URL without a trailing slash

    Raises
    ------
    ValueError
        If the URL has no ``http``/``https`` scheme or no host
    """
    url = httpx.URL(api_url.strip())
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError(f"API URL must look like http://host:port, got {api_url!r}")
    return str(url).rstrip("/")


def config_js_body(mapbox_token: str) -> str:
    """JavaScript that hands runtime config to the SPA as ``window.APP_CONFIG``.

    ``apiUrl`` is always empty: the SPA calls ``/api/*`` same-origin and this
    server forwards it, so one bundle works for any backend without a rebuild.
    """
    return f"window.APP_CONFIG = {json.dumps({'mapboxToken': mapbox_token, 'apiUrl': ''})};"


def create_ui_app(
    api_url: str = DEFAULT_API_URL,
    *,
    static_dir: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """
    Create the frontend FastAPI application.

    Parameters
    ----------
    api_url : str, optional
        Base URL of the ``adsb start backend`` instance to proxy to
    static_dir : Path, optional
        Directory holding the built frontend; defaults to the bundled one
    transport : httpx.AsyncBaseTransport, optional
        Custom transport for the proxy client (tests use ``httpx.ASGITransport``
        to point at an in-process backend)

    Returns
    -------
    FastAPI
        Configured application

    Raises
    ------
    RuntimeError
        If ``static_dir`` does not contain a built frontend
    ValueError
        If ``api_url`` is not an absolute http(s) URL
    """
    static_dir = STATIC_DIR if static_dir is None else static_dir
    if not frontend_is_bundled(static_dir):
        raise RuntimeError(FRONTEND_MISSING_HELP.format(static_dir=static_dir))
    api_url = normalize_api_url(api_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.client = httpx.AsyncClient(
            base_url=api_url,
            transport=transport,
            timeout=PROXY_TIMEOUT,
            headers={"User-Agent": f"adsb-map-ui/{__version__}"},
        )
        try:
            yield
        finally:
            await app.state.client.aclose()

    app = FastAPI(
        title="ADS-B Map UI",
        description=f"Map UI proxying to {api_url}",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.api_url = api_url

    async def proxy(request: Request, path: str) -> Response:
        client: httpx.AsyncClient = request.app.state.client
        try:
            upstream = await client.get(path, params=request.query_params.multi_items())
        except httpx.TimeoutException:
            logger.warning("Timed out waiting for backend %s%s", api_url, path)
            return JSONResponse(
                {"detail": f"Backend at {api_url} did not respond within {PROXY_TIMEOUT:g}s"},
                status_code=504,
            )
        except httpx.HTTPError as e:
            logger.warning("Cannot reach backend %s%s: %s", api_url, path, e)
            return JSONResponse(
                {"detail": f"Cannot reach backend at {api_url}: {e}"},
                status_code=502,
            )
        headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
        )

    @app.get("/api", include_in_schema=False)
    async def proxy_api_root(request: Request):
        return await proxy(request, "/api")

    @app.get("/api/{path:path}", include_in_schema=False)
    async def proxy_api(request: Request, path: str):
        return await proxy(request, f"/api/{path}")

    # Read at request time (not at startup) so a token added to the environment
    # is picked up without a restart, and so tests can vary it per request.
    @app.get("/config.js", include_in_schema=False)
    async def config_js():
        return Response(
            content=config_js_body(os.environ.get("MAPBOX_TOKEN", "")),
            media_type="application/javascript",
        )

    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    # SPA fallback: any path not claimed above serves index.html so client-side
    # routing works. The guard keeps the SPA shell from ever leaking under /api.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        return FileResponse(static_dir / "index.html")

    return app
