"""Tests for the standalone map UI server (`adsb ui`)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from adsb.api import create_app
from adsb.models import AircraftPosition
from adsb.ui import create_ui_app, normalize_api_url


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
    """An in-process `adsb serve` backend with one aircraft and two positions."""
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
    return create_app(test_db, serve_ui=False)


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


def test_ui_config_js_proxied_from_backend(ui_client, monkeypatch):
    """Without a local token, the backend's MAPBOX_TOKEN reaches the browser."""
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.on_receiver")
    response = ui_client.get("/config.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "pk.on_receiver" in response.text


def test_ui_config_js_prefers_local_token(static_dir, monkeypatch):
    """A token on the client machine wins, and no backend round-trip is made."""
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
    assert "pk.on_client" in response.text
    assert '"apiUrl": ""' in response.text


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
    assert "http://receiver.test:8000" in response.json()["detail"]


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
