"""Standalone map UI server that proxies to a remote ADS-B API.

Lets the bundled frontend run as a client on a different machine from the
decoder. ``adsb start frontend --api-url http://receiver:8000`` serves the SPA locally and
forwards ``/api/*`` (and ``/config.js``) to the backend, so the browser only ever
talks same-origin and the backend needs no CORS configuration.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from adsb import __version__, api
from adsb.api import frontend_is_bundled, mount_spa

logger = logging.getLogger("adsb.ui")

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


def create_ui_app(
    api_url: str,
    *,
    static_dir: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """
    Create the UI-only FastAPI application.

    Parameters
    ----------
    api_url : str
        Base URL of the ``adsb start backend`` backend to proxy to
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
    static_dir = api.STATIC_DIR if static_dir is None else static_dir
    if not frontend_is_bundled(static_dir):
        raise RuntimeError(
            f"Frontend not bundled ({static_dir} has no index.html). "
            "Run `just build`, or install the published wheel with `pip install adsb-map`."
        )
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

    # The Mapbox token normally comes from the backend's environment via its
    # /config.js. A token set on *this* machine takes precedence, so a client
    # can supply its own without touching the receiver.
    @app.get("/config.js", include_in_schema=False)
    async def config_js(request: Request):
        token = os.environ.get("MAPBOX_TOKEN", "")
        if not token:
            return await proxy(request, "/config.js")
        config = {"mapboxToken": token, "apiUrl": ""}
        return Response(
            content=f"window.APP_CONFIG = {json.dumps(config)};",
            media_type="application/javascript",
        )

    mount_spa(app, static_dir)
    return app
