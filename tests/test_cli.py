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
