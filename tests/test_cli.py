"""Tests for CLI behavior (click group, environment loading)."""

import os

from click.testing import CliRunner

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


def test_aircraft_db_path_prefers_env_override(tmp_path, monkeypatch):
    """ADSB_AIRCRAFT_DB is the single supported way to relocate the database."""
    from adsb.aircraft_db import AIRCRAFT_DB_ENV, aircraft_db_path

    target = tmp_path / "custom" / "aircraft.csv"
    monkeypatch.setenv(AIRCRAFT_DB_ENV, str(target))
    assert aircraft_db_path() == target


def test_aircraft_db_path_is_cwd_independent(tmp_path, monkeypatch):
    """The default location must not depend on where the CLI was launched from."""
    from adsb.aircraft_db import AIRCRAFT_DB_ENV, aircraft_db_path

    monkeypatch.delenv(AIRCRAFT_DB_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    from_tmp = aircraft_db_path()
    monkeypatch.chdir(tmp_path.parent)
    assert aircraft_db_path() == from_tmp
    assert from_tmp.name == "aircraft.csv"


def test_download_skips_when_already_present(tmp_path, monkeypatch):
    """`adsb download` is a no-op without --force, so it never re-fetches 9MB."""
    from adsb.aircraft_db import AIRCRAFT_DB_ENV

    existing = tmp_path / "aircraft.csv"
    existing.write_text("abc123;N1;C172;;CESSNA 172\n")
    monkeypatch.setenv(AIRCRAFT_DB_ENV, str(existing))

    result = CliRunner().invoke(main, ["download"])

    assert result.exit_code == 0, result.output
    assert "already present" in result.output
    assert existing.read_text().startswith("abc123")


def test_loader_reads_the_path_download_writes(tmp_path, monkeypatch):
    """Writer and reader resolve to the same file -- the pip-install enrichment bug."""
    from adsb.aircraft_db import AIRCRAFT_DB_ENV, AircraftDatabase, aircraft_db_path

    monkeypatch.setenv(AIRCRAFT_DB_ENV, str(tmp_path / "aircraft.csv"))
    aircraft_db_path().write_text("abc123;N1;C172;;CESSNA 172\n")

    assert AircraftDatabase().lookup("abc123") == {
        "registration": "N1",
        "typecode": "C172",
        "type_description": "CESSNA 172",
    }
