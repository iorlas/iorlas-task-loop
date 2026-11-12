"""Rollback and upgrade across factory.db versions stay `refused schema` (tl-8bh9.8.3 section 8, Q13): a newer factory.db
met by this code ("update it") and an older one (an older version wrote it; the owner discards it) are refused by every
command that opens factory.db, before any tracker, Git or slot is touched, and nothing is written."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeWorktree

from taskloop.cli import main
from taskloop.cli_composition import adopt
from taskloop.factory_schema import SCHEMA
from taskloop.operations import Failed
from taskloop.slots import SlotGit

BACKLOG = ["--backlog", "tasks"]
CHOICES = ["--tracker-root", "/tracker", "--checkout", "/checkout", "--model", "m", "--effort", "high", "--minutes", "30"]
COMMANDS = {
    "list": ["step", "list"],
    "show": ["step", "show", "tl-1", *BACKLOG],
    "start": ["step", "start", "tl-1", *BACKLOG, *CHOICES],
    "next": ["step", "next", *BACKLOG, "--label", "auto", *CHOICES],
    "land_summary": ["step", "land", "tl-1", *BACKLOG, "--checkout", "/checkout", "--minutes", "20", "--summary"],
}
VERSIONS = {"newer": SCHEMA.version + 1, "older": SCHEMA.version - 1}


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def database(folder: Path, version: int) -> Path:
    """A factory.db of another schema version, as another version of the code left it."""
    path = folder / "factory.db"
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE other_version (id INTEGER PRIMARY KEY)")
    con.execute(f"PRAGMA user_version={version}")
    con.close()
    return path


def digest(path: Path) -> str:
    """The database file's bytes; SQLite's own `-wal`/`-shm` beside it may appear on open, but the log holds no frame."""
    wal = path.with_name(f"{path.name}-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("direction", list(VERSIONS))
@pytest.mark.parametrize("command", list(COMMANDS))
def test_another_schema_version_is_refused_schema_and_nothing_is_written(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, direction: str) -> None:
    folder = tmp_path / "state"
    folder.mkdir()
    path = database(folder, VERSIONS[direction])
    before = digest(path)
    artifacts = [] if command == "list" else ["--artifacts", str(tmp_path / "art")]  # `step list` reads no artifacts
    assert main([*COMMANDS[command], "--db", str(path), *artifacts, "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "schema")
    words = {"newer": "update it", "older": "an older version wrote it and nothing upgrades it; the owner discards factory.db"}
    assert words[direction] in error["message"] and "not upgraded" not in error["message"]
    assert digest(path) == before and not (tmp_path / "art").exists()


@pytest.mark.parametrize("direction", list(VERSIONS))
def test_slot_adopt_refuses_another_schema_version_and_writes_nothing(
        tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: FakeSlotFiles, direction: str) -> None:
    folder, main_checkout = tmp_path / "state", slot.repo.path
    folder.mkdir()
    main_checkout.mkdir()
    path = database(folder, VERSIONS[direction])
    before = digest(path)
    refused = adopt(path, main_checkout, tmp_path / "slots", 1, SlotGit(checkouts, slot_files))
    assert isinstance(refused, Failed) and (refused.kind, refused.reason) == ("refused", "schema")
    assert digest(path) == before and not (tmp_path / "slots").exists()
