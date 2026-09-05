"""Tests for CLI behavior (click group, environment loading)."""

import os
import signal
import sys
import threading
import time
from types import SimpleNamespace

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


def test_download_help_names_source_and_license():
    """`adsb download --help` says where the data comes from and under what terms."""
    result = CliRunner().invoke(main, ["download", "--help"])

    assert result.exit_code == 0, result.output
    assert "Mictronics" in result.output
    assert "tar1090-db" in result.output
    assert "ODC-By" in result.output


def test_download_prints_attribution_notice(tmp_path, monkeypatch):
    """A fresh download ends with the ODC-By notice so the credit is seen at least once."""
    import gzip
    import io

    payload = gzip.compress(b"a00001;N1;C172;;CESSNA 172;\n")

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse(payload))
    dest = tmp_path / "aircraft.csv"

    result = CliRunner().invoke(main, ["download", "--aircraft-db", str(dest)])

    assert result.exit_code == 0, result.output
    assert dest.read_bytes() == b"a00001;N1;C172;;CESSNA 172;\n"
    assert "Mictronics aircraft database" in result.output
    assert "Open Data Commons Attribution License" in result.output


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


@pytest.fixture(autouse=True)
def _no_bundled_frontend(tmp_path, monkeypatch):
    """Never let a test depend on whether this checkout has run `just build`."""
    import adsb.ui

    monkeypatch.setattr(adsb.ui, "STATIC_DIR", tmp_path / "unbuilt")


@pytest.fixture
def built_frontend(tmp_path, monkeypatch):
    """Point adsb.ui at a minimal built frontend."""
    import adsb.ui

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(adsb.ui, "STATIC_DIR", static_dir)
    return static_dir


def test_ui_requires_built_frontend(no_uvicorn):
    """Without `just build`, `adsb start frontend` fails with guidance instead of starting."""
    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "http://receiver:8000"])

    assert result.exit_code != 0
    assert "Frontend not bundled" in result.output


def test_ui_rejects_url_without_scheme(built_frontend, no_uvicorn):
    result = CliRunner().invoke(main, ["start", "frontend", "--api-url", "receiver:8000"])

    assert result.exit_code != 0
    assert "http://host:port" in result.output


def test_ui_launches_proxy_app(tmp_path, monkeypatch, built_frontend, no_uvicorn):
    monkeypatch.chdir(tmp_path)  # keep the repo's own .env out of the picture
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    result = CliRunner().invoke(
        main, ["start", "frontend", "--api-url", "http://receiver.local:8000/", "--port", "3456"]
    )

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.api_url == "http://receiver.local:8000"
    assert no_uvicorn["port"] == 3456
    assert "[!!] MAPBOX_TOKEN unset" in result.output


@pytest.fixture
def fake_servers(monkeypatch):
    """Replace uvicorn.Server so `start all` drives stubs instead of binding ports.

    A stub blocks until `should_exit` is set, like a real server, so tests see the
    same shutdown handshake the command relies on. Tests override that per port
    via `behaviors` to stand in for a crash or an immediate return.
    """
    import adsb.cli

    servers = []
    behaviors = {}

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            self.ran = False
            servers.append(self)

        def run(self):
            self.ran = True
            behavior = behaviors.get(self.config.port)
            if behavior is not None:
                behavior(self)
                return
            while not self.should_exit:
                time.sleep(0.005)

    monkeypatch.setattr(adsb.cli.uvicorn, "Server", FakeServer)
    return SimpleNamespace(servers=servers, behaviors=behaviors)


def run_start_all(tmp_path, *args):
    """Invoke `adsb start all` with the status reporter off to keep output quiet."""
    return CliRunner().invoke(
        main,
        ["start", "all", "--db-path", str(tmp_path / "t.db"), "--stats-interval", "0", *args],
    )


def test_start_all_serves_backend_and_frontend(tmp_path, monkeypatch, built_frontend, fake_servers):
    """Both services run on the requested ports, with the UI proxying to the backend."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    fake_servers.behaviors[8800] = lambda server: None
    fake_servers.behaviors[3456] = lambda server: None

    result = run_start_all(
        tmp_path,
        "--host",
        "127.0.0.1",
        "--backend-port",
        "8800",
        "--frontend-port",
        "3456",
        "--source",
        "net",
        "--connect",
        "localhost",
        "30005",
        "beast",
    )

    by_port = {server.config.port: server for server in fake_servers.servers}
    assert set(by_port) == {8800, 3456}
    # Both threads are joined before the command returns, so both must have run.
    assert all(server.ran for server in fake_servers.servers)
    assert by_port[8800].config.host == "127.0.0.1"
    assert by_port[3456].config.host == "127.0.0.1"
    assert by_port[3456].config.app.state.api_url == "http://127.0.0.1:8800"

    # A service returning on its own is a failure, not a clean run.
    assert result.exit_code != 0
    assert "stopped unexpectedly" in result.output


def test_start_all_proxies_to_the_address_the_backend_binds(
    tmp_path, monkeypatch, built_frontend, fake_servers
):
    """A specific --host may not answer on loopback, so the UI must proxy to it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    fake_servers.behaviors[8800] = lambda server: None
    fake_servers.behaviors[3456] = lambda server: None

    run_start_all(
        tmp_path, "--host", "192.0.2.10", "--backend-port", "8800", "--frontend-port", "3456"
    )

    ui = next(server for server in fake_servers.servers if server.config.port == 3456)
    assert ui.config.app.state.api_url == "http://192.0.2.10:8800"


def test_start_all_reports_a_service_that_cannot_bind(
    tmp_path, monkeypatch, built_frontend, fake_servers
):
    """uvicorn sys.exit()s when a port is taken; that must not look like success."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    fake_servers.behaviors[8800] = lambda server: sys.exit(1)

    result = run_start_all(tmp_path, "--backend-port", "8800", "--frontend-port", "3456")

    assert result.exit_code != 0
    assert "backend stopped" in result.output
    assert "8800" in result.output
    # The surviving service is asked to stop rather than killed mid-request.
    ui = next(server for server in fake_servers.servers if server.config.port == 3456)
    assert ui.should_exit is True


def test_start_all_shuts_both_down_on_interrupt(
    tmp_path, monkeypatch, built_frontend, fake_servers
):
    """Ctrl-C reaches the main thread only, so `all` must relay it to both servers."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")

    import adsb.cli

    class InterruptingEvent(threading.Event):
        """Stand in for the user pressing Ctrl-C while the command waits."""

        def wait(self, timeout=None):
            raise KeyboardInterrupt

    # Swap only the name `adsb.cli` looks up: patching threading.Event globally
    # would also break Thread.start(), which waits on one internally.
    monkeypatch.setattr(
        adsb.cli, "threading", SimpleNamespace(Thread=threading.Thread, Event=InterruptingEvent)
    )

    result = run_start_all(tmp_path, "--backend-port", "8800", "--frontend-port", "3456")

    assert result.exit_code == 0, result.output
    assert "Shutting down" in result.output
    assert all(server.should_exit for server in fake_servers.servers)
    assert all(server.ran for server in fake_servers.servers)


def test_start_all_shuts_both_down_on_sigterm(tmp_path, monkeypatch, built_frontend, fake_servers):
    """systemd, Docker and `kill` stop with SIGTERM, which no worker thread sees."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")

    def signal_then_serve(server):
        """Stand in for `kill <pid>` arriving once both services are up."""
        os.kill(os.getpid(), signal.SIGTERM)
        while not server.should_exit:
            time.sleep(0.005)

    fake_servers.behaviors[8800] = signal_then_serve
    before = signal.getsignal(signal.SIGTERM)

    result = run_start_all(tmp_path, "--backend-port", "8800", "--frontend-port", "3456")

    assert result.exit_code == 0, result.output
    assert "Shutting down" in result.output
    assert all(server.should_exit for server in fake_servers.servers)
    assert all(server.ran for server in fake_servers.servers)
    # The command must not leave its handler behind for whatever runs next.
    assert signal.getsignal(signal.SIGTERM) is before


def test_frontend_defaults_to_local_backend(tmp_path, monkeypatch, built_frontend, no_uvicorn):
    """Single-machine use is just `adsb start backend` + `adsb start frontend`."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    monkeypatch.delenv("ADSB_API_URL", raising=False)

    result = CliRunner().invoke(main, ["start", "frontend"])

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.api_url == "http://127.0.0.1:8000"
    assert "[ok] Mapbox token set" in result.output


def test_frontend_demo_mode(tmp_path, monkeypatch, built_frontend, no_uvicorn):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")

    result = CliRunner().invoke(main, ["start", "frontend", "--demo"])

    assert result.exit_code == 0, result.output
    assert no_uvicorn["app"].state.demo is True
    assert "Demo mode" in result.output
    assert "Backend API" not in result.output


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


def test_backend_log_config_drops_invalid_http_noise(tmp_path, monkeypatch, no_uvicorn):
    """Non-HTTP bytes on the port (HTTPS probes, scanners) must not spam the console."""
    import logging.config

    from adsb.cli import DropNoiseFilter

    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(main, ["start", "backend", "--db-path", str(tmp_path / "t.db")])
    config = no_uvicorn["log_config"]
    assert "drop_noise" in config["handlers"]["default"]["filters"]

    logging.config.dictConfig(config)  # must be a valid dictConfig, filter resolvable
    handler = logging.getLogger("uvicorn.error").handlers[0]
    noise = logging.LogRecord(
        "uvicorn.error", logging.WARNING, "", 0, "Invalid HTTP request received.", None, None
    )
    real = logging.LogRecord(
        "uvicorn.error", logging.WARNING, "", 0, "Unsupported upgrade request.", None, None
    )
    assert not handler.filter(noise)
    assert handler.filter(real)
    assert isinstance(handler.filters[0], DropNoiseFilter)


def test_backend_passes_metadata_retention_to_network_client(tmp_path, monkeypatch, no_uvicorn):
    """--metadata-retention reaches the decoder thread that does the purging."""
    import adsb.cli

    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(
        adsb.cli,
        "start_network_client",
        lambda **kw: calls.append(kw) or SimpleNamespace(stop=lambda: None),
    )

    result = CliRunner().invoke(
        main,
        [
            "start",
            "backend",
            "--db-path",
            str(tmp_path / "t.db"),
            "--source",
            "net",
            "--connect",
            "localhost",
            "30005",
            "beast",
            "--metadata-retention",
            "120",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["metadata_retention"] == 120
    assert "120" in result.output


@pytest.mark.parametrize("command", ["backend", "all"])
def test_feed_options_help_lists_metadata_retention(command):
    result = CliRunner().invoke(main, ["start", command, "--help"])
    assert "--metadata-retention" in result.output
    assert "3600" in result.output


def test_backend_and_frontend_stop_despite_open_streams(
    tmp_path, monkeypatch, built_frontend, no_uvicorn
):
    """A map tab keeps its event streams open forever; shutdown must not wait for them."""
    from adsb.cli import GRACEFUL_SHUTDOWN_TIMEOUT, SHUTDOWN_TIMEOUT

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    assert GRACEFUL_SHUTDOWN_TIMEOUT < SHUTDOWN_TIMEOUT

    CliRunner().invoke(main, ["start", "backend", "--db-path", str(tmp_path / "t.db")])
    assert no_uvicorn["timeout_graceful_shutdown"] == GRACEFUL_SHUTDOWN_TIMEOUT

    CliRunner().invoke(main, ["start", "frontend"])
    assert no_uvicorn["timeout_graceful_shutdown"] == GRACEFUL_SHUTDOWN_TIMEOUT


def test_start_all_servers_stop_despite_open_streams(
    tmp_path, monkeypatch, built_frontend, fake_servers
):
    from adsb.cli import GRACEFUL_SHUTDOWN_TIMEOUT

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.local")
    fake_servers.behaviors[8800] = lambda server: None
    fake_servers.behaviors[3456] = lambda server: None

    # Stubs that return at once read as a crash to the command; the configs are what matter.
    run_start_all(tmp_path, "--backend-port", "8800", "--frontend-port", "3456")

    assert len(fake_servers.servers) == 2
    assert all(
        server.config.timeout_graceful_shutdown == GRACEFUL_SHUTDOWN_TIMEOUT
        for server in fake_servers.servers
    )
