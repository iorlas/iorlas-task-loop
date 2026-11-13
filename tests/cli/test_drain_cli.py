"""The installed command's parsing, config precedence, structured results and noncreating failure paths."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from sqlite_store import Store
from test_round import seed

from taskloop import cli_drain
from taskloop.cli import main
from taskloop.drain import composition
from taskloop.drain.drain import Ports, drain
from taskloop.drain.models import Conclusion, Seen, State
from taskloop.drain.store import DrainStore
from taskloop.factory_schema import SCHEMA


def initialized(path: Path) -> None:
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    con.close()


@pytest.mark.parametrize("structured", [False, True])
def test_drain_needs_only_an_existing_db_and_reports_verified_idle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "factory.db"
    initialized(path)
    assert main(["drain", "--db", str(path), *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert not output.err
    if structured:
        lines = [json.loads(line) for line in output.out.splitlines()]
        assert [line["conclusion"] for line in lines] == [Conclusion.WAITING.value, Conclusion.COMPLETE.value]
        assert lines[-1]["active_count"] == lines[-1]["uncertain_count"] == lines[-1]["pending_actions"] == 0
    else:
        assert "New work is blocked" in output.out and "Idle was verified" in output.out
        assert "owner" in output.out and "discard" in output.out and "restart" in output.out
    with sqlite3.connect(path) as con:
        assert DrainStore(lambda: con).boundary().state is State.COMPLETE


@pytest.mark.parametrize("structured", [False, True])
def test_missing_db_is_refused_without_creating_a_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "missing" / "factory.db"
    assert main(["drain", "--db", str(path), *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert not output.out and "existing factory database" in output.err
    assert not path.parent.exists()
    if structured:
        assert json.loads(output.err)["conclusion"] == Conclusion.REFUSED.value


@pytest.mark.parametrize("structured", [False, True])
def test_incompatible_db_is_preserved_without_a_drain_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "factory.db"
    initialized(path)
    with sqlite3.connect(path) as con:
        con.execute(f"PRAGMA user_version={SCHEMA.version - 1}")
    before = path.read_bytes()
    assert main(["drain", "--db", str(path), *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert not output.out and "matching runtime" in output.err and "database has been preserved" in output.err
    assert path.read_bytes() == before
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT * FROM drain_state").fetchall() == []


def test_config_db_is_used_and_explicit_db_wins(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured, explicit = tmp_path / "configured.db", tmp_path / "explicit.db"
    initialized(configured)
    initialized(explicit)
    config = tmp_path / "config.toml"
    config.write_text(f'db = "{configured}"\nartifacts = "{tmp_path / "artifacts"}"\n')
    assert main(["--config", str(config), "drain", "--db", str(explicit), "--artifacts", str(tmp_path / "other")]) == 0
    capsys.readouterr()
    with sqlite3.connect(configured) as con:
        assert DrainStore(lambda: con).boundary().state is State.OPEN
    assert main(["--config", str(config), "drain"]) == 0
    with sqlite3.connect(configured) as con:
        assert DrainStore(lambda: con).boundary().state is State.COMPLETE
    assert not (tmp_path / "artifacts").exists() and not (tmp_path / "other").exists()


@pytest.mark.parametrize("structured", [False, True])
def test_unknown_process_observation_exits_three_with_identity_and_keeps_fence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(composition, "observe", lambda _owner: Seen.UNKNOWN)
    path = tmp_path / "factory.db"
    initialized(path)
    with sqlite3.connect(path) as con:
        seed(con, "tl-1", "attempt", entry=(80, "entry", "boot"))
    assert main(["drain", "--db", str(path), *(["--json"] if structured else [])]) == 3
    output = capsys.readouterr()
    if structured:
        result = json.loads(output.err)
        assert result["conclusion"] == Conclusion.UNAVAILABLE.value and result["uncertain_count"] == 1
        assert result["uncertain"][0]["identity"] == {"pid": 80, "pgid": 80, "start": "entry", "boot": "boot"}
    else:
        assert "Idle was not verified" in output.err and "pid=80" in output.err
    with sqlite3.connect(path) as con:
        assert DrainStore(lambda: con).boundary().state is State.DRAINING


def test_ctrl_c_exits_130_and_later_invocation_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "factory.db"
    initialized(path)
    with sqlite3.connect(path) as con:
        seed(con, "tl-1", "attempt", entry=(81, "entry", "boot"))

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    def interrupted(ports: Ports):
        return drain(replace(ports, observe=lambda _owner: Seen.ALIVE, wait=interrupt))

    monkeypatch.setattr(cli_drain, "drain", interrupted)
    assert main(["drain", "--db", str(path)]) == 130
    with sqlite3.connect(path) as con:
        assert DrainStore(lambda: con).boundary().state is State.DRAINING
        assert con.execute("SELECT entry_pid FROM attempt").fetchone() == (81,)
    monkeypatch.setattr(cli_drain, "drain", drain)
    monkeypatch.setattr(composition, "observe", lambda _owner: Seen.GONE)
    assert main(["drain", "--db", str(path)]) == 0


def test_unreadable_database_is_unreliable_and_never_initialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "factory.db"
    path.write_text("not sqlite")
    monkeypatch.setenv("HOME", str(tmp_path))
    before = path.read_bytes()
    assert main(["drain", "--db", str(path)]) == 3
    assert path.read_bytes() == before


def test_help_names_the_drain_surface(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0 and "drain" in capsys.readouterr().out
    with pytest.raises(SystemExit) as ended:
        main(["drain", "--help"])
    assert ended.value.code == 0
    help_text = capsys.readouterr().out
    assert "--db" in help_text and "--artifacts" in help_text and "--json" in help_text
