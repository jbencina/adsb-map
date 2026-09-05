"""Tests for the standalone map UI server (`adsb start frontend`)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from adsb.api import create_app
from adsb.models import AircraftPosition
from adsb.ui import config_js_body, create_ui_app, normalize_api_url


@pytest.fixture
def static_dir(tmp_path):
    """A minimal built frontend."""
    d = tmp_path / "static"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>ui-spa</html>")
    (d / "assets" / "app.js").write_text("console.log('hi')")
    return d


@pytest.fixture
def backend(test_db, test_session, aircraft):
    """An in-process backend with one aircraft and two positions."""
    for i in range(2):
        test_session.add(
            AircraftPosition(
                aircraft_id=aircraft.id,
                timestamp=1234567890 + i,
                latitude=40.7,
                longitude=-74.0,
                altitude=10000,
            )
        )
    test_session.commit()
    return create_app(test_db)


@pytest.fixture
def ui_client(static_dir, backend):
    """UI server whose proxy client talks to the in-process backend."""
    app = create_ui_app(
        "http://receiver.test:8000/",
        static_dir=static_dir,
        transport=httpx.ASGITransport(app=backend),
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://receiver.local:8000", "http://receiver.local:8000"),
        ("http://receiver.local:8000/", "http://receiver.local:8000"),
        ("  https://adsb.example.com//  ", "https://adsb.example.com"),
    ],
)
def test_normalize_api_url(raw, expected):
    assert normalize_api_url(raw) == expected


@pytest.mark.parametrize("raw", ["receiver.local:8000", "localhost", "ftp://x", ""])
def test_normalize_api_url_rejects_bare_hosts(raw):
    """A missing scheme is the most common typo; fail fast rather than proxy to nowhere."""
    with pytest.raises(ValueError, match="http://host:port"):
        normalize_api_url(raw)


def test_create_ui_app_requires_built_frontend(tmp_path):
    with pytest.raises(RuntimeError, match="Frontend not bundled"):
        create_ui_app("http://receiver.test:8000", static_dir=tmp_path / "empty")


def test_ui_serves_spa_and_assets(ui_client):
    assert "ui-spa" in ui_client.get("/").text
    assert "ui-spa" in ui_client.get("/some/client/route").text
    assert ui_client.get("/assets/app.js").status_code == 200


def test_ui_proxies_api_to_backend(ui_client):
    root = ui_client.get("/api")
    assert root.status_code == 200
    assert "routes" in root.json()

    aircraft = ui_client.get("/api/all")
    assert aircraft.status_code == 200
    assert aircraft.headers["content-type"].startswith("application/json")
    assert [a["icao24"] for a in aircraft.json()] == ["abc123"]


def test_ui_proxy_forwards_query_string(ui_client):
    """`since` must reach the backend intact or tracks silently return everything."""
    assert len(ui_client.get("/api/track?icao24=abc123").json()) == 2
    assert len(ui_client.get("/api/track?icao24=abc123&since=1234567891").json()) == 1


def test_ui_proxy_passes_backend_errors_through(ui_client):
    """Unknown API paths are the backend's 404, not the SPA shell."""
    response = ui_client.get("/api/nonexistent")
    assert response.status_code == 404
    assert "ui-spa" not in response.text


def test_ui_config_js_from_local_token(static_dir, monkeypatch):
    """The Mapbox token lives with the UI process; the backend is never asked."""
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.on_client")

    def explode(request):
        raise AssertionError("backend should not be contacted")

    app = create_ui_app(
        "http://receiver.test:8000",
        static_dir=static_dir,
        transport=httpx.MockTransport(explode),
    )
    with TestClient(app) as client:
        response = client.get("/config.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "window.APP_CONFIG" in response.text
    assert "pk.on_client" in response.text
    assert '"apiUrl": ""' in response.text


def test_ui_config_js_without_token(ui_client, monkeypatch):
    """No token still yields valid JS so the SPA can render its own hint."""
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    response = ui_client.get("/config.js")
    assert response.status_code == 200
    assert '"mapboxToken": ""' in response.text


def test_ui_config_js_demo_flag(static_dir):
    """`--demo` reaches the SPA only through config.js; the server itself is unchanged."""
    app = create_ui_app("http://receiver.test:8000", static_dir=static_dir, demo=True)
    with TestClient(app) as client:
        assert '"demo": true' in client.get("/config.js").text
    assert '"demo": false' in config_js_body("")


def test_ui_reports_unreachable_backend_as_502(static_dir):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    app = create_ui_app(
        "http://receiver.test:8000",
        static_dir=static_dir,
        transport=httpx.MockTransport(refuse),
    )
    with TestClient(app) as client:
        response = client.get("/api/all")
    assert response.status_code == 502
    assert response.json()["detail"] == "Cannot reach backend at http://receiver.test:8000"


def test_ui_reports_backend_timeout_as_504(static_dir):
    def hang(request):
        raise httpx.ReadTimeout("slow")

    app = create_ui_app(
        "http://receiver.test:8000",
        static_dir=static_dir,
        transport=httpx.MockTransport(hang),
    )
    with TestClient(app) as client:
        response = client.get("/api/all")
    assert response.status_code == 504


def test_ui_strips_hop_by_hop_headers(static_dir):
    """Upstream framing headers must not leak into the re-framed response."""

    def respond(request):
        return httpx.Response(
            200,
            content=b"[]",
            headers={
                "content-type": "application/json",
                "transfer-encoding": "chunked",
                "connection": "keep-alive",
                "x-custom": "kept",
            },
        )

    app = create_ui_app(
        "http://receiver.test:8000",
        static_dir=static_dir,
        transport=httpx.MockTransport(respond),
    )
    with TestClient(app) as client:
        response = client.get("/api/all")
    assert response.status_code == 200
    assert response.headers["x-custom"] == "kept"
    assert response.headers.get("transfer-encoding") != "chunked"


def test_ui_streams_events_without_buffering_or_timing_out(static_dir, backend, monkeypatch):
    """The proxy must relay each event as it arrives and never apply the read timeout."""
    import json

    import adsb.ui
    from tests.helpers import serve

    monkeypatch.setattr(adsb.ui, "PROXY_TIMEOUT", 0.3)
    with serve(backend) as backend_url:
        ui = create_ui_app(backend_url, static_dir=static_dir)
        with serve(ui) as ui_url, httpx.Client(base_url=ui_url, timeout=5) as client:
            with client.stream("GET", "/api/stream/tracks?scope=all&max_age=2000000000") as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                assert "content-length" not in r.headers
                lines = r.iter_lines()
                events = []
                for line in lines:
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:]))
                    if len(events) == 2:
                        break
    assert [p["timestamp"] for p in events[0]["abc123"]] == [1234567890, 1234567891]
    assert events[1] == {}


def test_ui_forwards_last_event_id_to_the_backend(static_dir):
    """Resume only works if the browser's Last-Event-ID reaches the backend."""
    seen = {}

    def respond(request):
        seen.update(request.headers)
        return httpx.Response(200, content=b"id: 1\nevent: update\ndata: []\n\n")

    app = create_ui_app(
        "http://receiver.test:8000",
        static_dir=static_dir,
        transport=httpx.MockTransport(respond),
    )
    with TestClient(app) as client:
        response = client.get("/api/stream/aircraft", headers={"Last-Event-ID": "1700000000"})
    assert response.status_code == 200
    assert seen["last-event-id"] == "1700000000"
    assert response.content == b"id: 1\nevent: update\ndata: []\n\n"
