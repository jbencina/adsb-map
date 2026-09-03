"""Tests for CLI behavior (click group, environment loading)."""

import os

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from adsb.cli import main


def test_dotenv_loaded_from_cwd(tmp_path, monkeypatch):
    """A .env file in the working directory is loaded into os.environ.

    Uses `init-db` (a harmless subcommand) to trigger the click group body —
    eager options like `--help` short-circuit before the body runs.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("MAPBOX_TOKEN=pk.from_dotenv\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    runner = CliRunner()
    result = runner.invoke(main, ["init-db", "--db-path", str(tmp_path / "test.db")])

    assert result.exit_code == 0, result.output
    assert os.environ.get("MAPBOX_TOKEN") == "pk.from_dotenv"


def test_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    """Process env wins over .env so explicit `MAPBOX_TOKEN=… adsb …` still works."""
    env_file = tmp_path / ".env"
    env_file.write_text("MAPBOX_TOKEN=pk.from_dotenv\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.from_process_env")

    runner = CliRunner()
    result = runner.invoke(main, ["init-db", "--db-path", str(tmp_path / "test.db")])

    assert result.exit_code == 0, result.output
    assert os.environ["MAPBOX_TOKEN"] == "pk.from_process_env"


@pytest.fixture(autouse=True)
def _reset_aircraft_db_path():
    """`--aircraft-db` sets process-wide state; never leak it between tests."""
    import adsb.aircraft_db

    yield
    adsb.aircraft_db.set_aircraft_db_path(None)


def test_aircraft_db_not_configurable_via_env(tmp_path, monkeypatch):
    """`.env` is for tokens only; the old ADSB_AIRCRAFT_DB env var is ignored."""
    from adsb.aircraft_db import aircraft_db_path

    monkeypatch.setenv("ADSB_AIRCRAFT_DB", str(tmp_path / "ignored.csv"))
    assert aircraft_db_path() != tmp_path / "ignored.csv"


def test_aircraft_db_path_is_cwd_independent(tmp_path, monkeypatch):
    """The default location must not depend on where the CLI was launched from."""
    from adsb.aircraft_db import aircraft_db_path

    monkeypatch.chdir(tmp_path)
    from_tmp = aircraft_db_path()
    monkeypatch.chdir(tmp_path.parent)
    assert aircraft_db_path() == from_tmp
    assert from_tmp.name == "aircraft.csv"


def test_download_skips_when_already_present(tmp_path):
    """`adsb download` is a no-op without --force, so it never re-fetches 9MB."""
    existing = tmp_path / "aircraft.csv"
    existing.write_text("abc123;N1;C172;;CESSNA 172\n")

    result = CliRunner().invoke(main, ["download", "--aircraft-db", str(existing)])

    assert result.exit_code == 0, result.output
    assert "already present" in result.output
    assert existing.read_text().startswith("abc123")


def test_loader_reads_the_path_download_writes(tmp_path):
    """Writer and reader resolve to the same file -- the pip-install enrichment bug."""
    from adsb.aircraft_db import AircraftDatabase, aircraft_db_path, set_aircraft_db_path

    set_aircraft_db_path(tmp_path / "aircraft.csv")
    aircraft_db_path().write_text("abc123;N1;C172;;CESSNA 172\n")

    assert AircraftDatabase().lookup("abc123") == {
        "registration": "N1",
        "typecode": "C172",
        "type_description": "CESSNA 172",
    }


@pytest.fixture
def no_uvicorn(monkeypatch):
    """Capture uvicorn.run kwargs instead of binding a port (which would hang the test)."""
    import adsb.cli

    launched = {}
    monkeypatch.setattr(adsb.cli.uvicorn, "run", lambda app, **kw: launched.update(kw, app=app))
    return launched


def test_ui_requires_built_frontend(tmp_path, monkeypatch, no_uvicorn):
    """`adsb start frontend` on a source checkout without `just build` fails with guidance, not a 503."""
    import adsb.ui

    monkeypatch.setattr(adsb.ui, "STATIC_DIR", tmp_path / "empty")

    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "http://receiver:8000"])

    assert result.exit_code != 0
    assert "Frontend not bundled" in result.output


def test_ui_rejects_url_without_scheme(tmp_path, monkeypatch, no_uvicorn):
    import adsb.ui

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.ui, "STATIC_DIR", static_dir)

    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "receiver:8000"])

    assert result.exit_code != 0
    assert "http://host:port" in result.output


def test_ui_launches_proxy_app(tmp_path, monkeypatch, no_uvicorn):
    import adsb.ui

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.ui, "STATIC_DIR", static_dir)
    monkeypatch.chdir(tmp_path)  # keep the repo's own .env out of the picture
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    result = CliRunner().invoke(
        main, ["start", "frontend", "--api-url", "http://receiver.local:8000/", "--port", "3456"]
    )

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.api_url == "http://receiver.local:8000"
    assert no_uvicorn["port"] == 3456
    assert "[!!] MAPBOX_TOKEN unset" in result.output


def test_frontend_defaults_to_local_backend(tmp_path, monkeypatch, no_uvicorn):
    """Single-machine use is just `adsb start backend` + `adsb start frontend`."""
    import adsb.ui

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.ui, "STATIC_DIR", static_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    monkeypatch.delenv("ADSB_API_URL", raising=False)

    result = CliRunner().invoke(main, ["start", "frontend"])

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.api_url == "http://127.0.0.1:8000"
    assert "[ok] Mapbox token set" in result.output


def test_backend_is_api_only(tmp_path, monkeypatch, no_uvicorn):
    """The backend never serves the UI and has no flag about it."""
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["start", "backend", "--db-path", str(tmp_path / "t.db")])

    assert result.exit_code == 0, result.output
    assert "Map UI" not in result.output
    assert "MAPBOX" not in result.output

    client = TestClient(no_uvicorn["app"])
    assert client.get("/").status_code == 200
    assert "routes" in client.get("/").json()
    assert client.get("/api").status_code == 200

    assert CliRunner().invoke(main, ["start", "backend", "--no-ui"]).exit_code != 0


def test_serve_aircraft_db_option_applies_before_preflight(tmp_path, monkeypatch, no_uvicorn):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "planes.csv"
    target.write_text("abc123;N1;C172;;CESSNA 172\n")

    result = CliRunner().invoke(
        main,
        ["start", "backend", "--aircraft-db", str(target), "--db-path", str(tmp_path / "t.db")],
    )

    assert result.exit_code == 0, result.output
    assert f"[ok] Aircraft database: {target}" in result.output


def test_backend_status_reporter_lifecycle(tmp_path, monkeypatch, no_uvicorn):
    """The reporter starts before uvicorn and is stopped when uvicorn returns."""
    import adsb.cli

    monkeypatch.chdir(tmp_path)
    started = []
    orig_start = adsb.cli.StatusReporter.start
    orig_stop = adsb.cli.StatusReporter.stop
    monkeypatch.setattr(
        adsb.cli.StatusReporter, "start", lambda self: started.append(self) or orig_start(self)
    )
    stopped = []
    monkeypatch.setattr(
        adsb.cli.StatusReporter, "stop", lambda self: stopped.append(self) or orig_stop(self)
    )

    result = CliRunner().invoke(
        main, ["start", "backend", "--db-path", str(tmp_path / "t.db"), "--stats-interval", "5"]
    )
    assert result.exit_code == 0, result.output
    assert len(started) == 1 and started[0].interval == 5
    assert stopped == started

    started.clear()
    result = CliRunner().invoke(
        main, ["start", "backend", "--db-path", str(tmp_path / "t.db"), "--stats-interval", "0"]
    )
    assert result.exit_code == 0, result.output
    assert started == []


def test_backend_access_log_off_by_default(tmp_path, monkeypatch, no_uvicorn):
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(main, ["start", "backend", "--db-path", str(tmp_path / "t.db")])
    assert no_uvicorn["log_config"]["loggers"]["uvicorn.access"]["level"] == "WARNING"

    CliRunner().invoke(
        main, ["start", "backend", "--db-path", str(tmp_path / "t.db"), "--access-log"]
    )
    assert no_uvicorn["log_config"]["loggers"]["uvicorn.access"]["level"] == "INFO"
