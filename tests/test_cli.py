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
    import adsb.api

    monkeypatch.setattr(adsb.api, "STATIC_DIR", tmp_path / "empty")

    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "http://receiver:8000"])

    assert result.exit_code != 0
    assert "Frontend not bundled" in result.output


def test_ui_rejects_url_without_scheme(tmp_path, monkeypatch, no_uvicorn):
    import adsb.api

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.api, "STATIC_DIR", static_dir)

    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "receiver:8000"])

    assert result.exit_code != 0
    assert "http://host:port" in result.output


def test_ui_launches_proxy_app(tmp_path, monkeypatch, no_uvicorn):
    import adsb.api

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.api, "STATIC_DIR", static_dir)
    monkeypatch.chdir(tmp_path)  # keep the repo's own .env out of the picture
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    result = CliRunner().invoke(
        main, ["start", "frontend", "--api-url", "http://receiver.local:8000/", "--port", "3456"]
    )

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.api_url == "http://receiver.local:8000"
    assert no_uvicorn["port"] == 3456
    assert "Mapbox token: from backend" in result.output


def test_ui_api_url_is_cli_only(tmp_path, monkeypatch, no_uvicorn):
    """No env-var fallback: the backend URL is a CLI argument, not .env content."""
    monkeypatch.setenv("ADSB_API_URL", "http://receiver.local:8000")

    result = CliRunner().invoke(main, ["start", "frontend"])

    assert result.exit_code != 0
    assert "--api-url" in result.output
    assert "app" not in no_uvicorn


def test_serve_no_ui_and_cors_origins(tmp_path, monkeypatch, no_uvicorn):
    """--no-ui / --cors-origins reach create_app and the preflight report."""
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "start",
            "backend",
            "--no-ui",
            "--cors-origins",
            "http://laptop:3000, http://laptop:5173/",
            "--db-path",
            str(tmp_path / "t.db"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Map UI disabled (--no-ui)" in result.output
    assert "CORS origins: http://laptop:3000, http://laptop:5173" in result.output

    client = TestClient(no_uvicorn["app"])
    assert client.get("/").status_code == 404
    allowed = client.get("/api", headers={"Origin": "http://laptop:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://laptop:5173"


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
