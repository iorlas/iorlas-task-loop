"""An incompatible restart refuses before scheduling and preserves the existing database."""

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Never

import pytest
from beads_client import BdError
from sqlite_store import SchemaError, Store
from test_admit import tasks

from taskloop import cli_composition
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.cli import main
from taskloop.drain import composition as drain_composition
from taskloop.drain.models import ActionKind, ActionState, Identity, Reason, Seen, State
from taskloop.drain.store import DrainStore
from taskloop.factory_schema import SCHEMA, refusal
from taskloop.git_views import GitViews
from taskloop.ids import NativeIds
from taskloop.interrupts import Interrupts
from taskloop.operations import Ended, Failed
from taskloop.round import NextRequest
from taskloop.task import TaskInspection
from taskloop.tracker import ACTOR

REQUEST = NextRequest("tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), Overrides(model="m", effort="high"), 30)
VERSIONS = [SCHEMA.version - 1, SCHEMA.version + 1, 0]


def incompatible(tmp_path: Path, version: int) -> Path:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    con.execute("INSERT INTO slot VALUES ('repo','s1','/slots/s1',1)")
    con.execute("INSERT INTO reservation VALUES ('s1','repo',1,'unfinished')")
    con.execute(f"PRAGMA user_version={version}")
    if version == SCHEMA.version:
        con.execute("DROP TABLE merge_operation")
    con.close()
    return path


def recovery_words(detail: str, path: Path, version: int) -> None:
    assert str(path.resolve()) in detail
    assert f"records schema version {version}" in detail
    assert f"expects schema version {SCHEMA.version}" in detail
    assert "database has been preserved" in detail
    assert "Resume with matching code to keep unfinished work" in detail
    assert "first stop admitting work" in detail
    assert "attempts and their entry processes finish under the matching runtime" in detail
    assert "this incompatible runtime cannot safely perform it" in detail
    assert "Stopping rounds alone does not confirm that entries or agents have stopped" in detail
    assert "After confirming they have stopped, the owner deliberately discards" in detail
    assert "before initializing the new runtime" in detail
    assert "Discard loses local execution progress and session references" in detail
    assert "tl " not in detail
    if version == SCHEMA.version:
        assert "incompatible: missing required tables: merge_operation" in detail
        assert len(detail.strip().splitlines()) == 1


@pytest.mark.parametrize("version", [*VERSIONS, SCHEMA.version])
@pytest.mark.parametrize("as_json", [False, True])
def test_rounds_restart_reports_the_same_recovery_in_human_and_json_and_preserves_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], version: int, as_json: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    path = incompatible(tmp_path, version)
    before = path.read_bytes()
    argv = ["step", "rounds", "--db", str(path), "--artifacts", str(tmp_path / "art"), "--backlog", "tasks",
            "--tracker-root", "/tracker", "--checkout", "/checkout", "--label", "auto", "--model", "m", "--effort", "high",
            "--minutes", "30"]
    for _ in range(2):
        assert main([*argv, *(["--json"] if as_json else [])]) == 1
        output = capsys.readouterr()
        assert output.out == ""
        if as_json:
            error = json.loads(output.err)["error"]
            assert (error["kind"], error["reason"]) == ("refused", "schema")
            detail = error["message"]
        else:
            detail = output.err.removeprefix("tl step rounds: refused:schema\n")
        recovery_words(detail.splitlines()[0], path, version)
        assert path.read_bytes() == before
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone() == (version,)
        assert con.execute("SELECT * FROM slot").fetchall() == [("repo", "s1", "/slots/s1", 1)]
        assert con.execute("SELECT * FROM reservation").fetchall() == [("s1", "repo", 1, "unfinished")]
    assert not (tmp_path / "art").exists()


@pytest.mark.parametrize("version", [*VERSIONS, SCHEMA.version])
def test_incompatible_rounds_reaches_no_lock_handler_or_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int,
) -> None:
    path = incompatible(tmp_path, version)

    def unexpected(*args: object, **kwargs: object) -> Never:
        pytest.fail("incompatible startup reached a scheduling port")

    monkeypatch.setattr(cli_composition, "hold", unexpected)
    monkeypatch.setattr(cli_composition, "one_round", unexpected)
    with cli_composition.open_rounds(path, tmp_path / "art", GitViews(30), REQUEST, unexpected) as ports:
        assert isinstance(ports, Failed) and (ports.kind, ports.reason) == ("refused", "schema")
        recovery_words(ports.detail, path, version)


@pytest.mark.parametrize("contents", [None, b"not a SQLite database"])
def test_missing_or_unreadable_database_is_never_initialized(tmp_path: Path, contents: bytes | None) -> None:
    path = tmp_path / "factory.db"
    if contents is not None:
        path.write_bytes(contents)
    with cli_composition.open_reads(path, tmp_path / "art", GitViews(30)) as ports:
        assert isinstance(ports, Failed) and ports.reason == "database"
    assert path.read_bytes() == contents if contents is not None else not path.exists()
    assert not (tmp_path / "art").exists()


class Claims:
    """Tracker observations and fenced release at the production drain adapter's external boundary."""

    def __init__(self) -> None:
        self.assignee, self.status = ACTOR, "in_progress"
        self.failing = False
        self.releases: list[str] = []

    def inspect(self, task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
        assert (backlog, tracker_root) == ("tasks", "/tracker")
        return replace(tasks(task_id, backlog, tracker_root), assignee=self.assignee, status=self.status)

    def unclaim(self, tracker_root: str, task_id: str) -> bool:
        assert tracker_root == "/tracker"
        if self.failing:
            raise BdError("timeout", "tracker temporarily unavailable")
        self.releases.append(task_id)
        self.assignee, self.status = "", "open"
        return True


class Handler:
    def __init__(self) -> None:
        self.installed = 0

    @contextmanager
    def install(self, _say: object) -> Generator[Interrupts]:
        self.installed += 1
        yield Interrupts(print, lambda: None)


@pytest.mark.parametrize("retry", [False, True])
def test_normal_rounds_restart_reconciles_claims_before_scheduling_without_retake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retry: bool,
) -> None:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    gate = DrainStore(lambda: con, ids=NativeIds())
    old = Identity(pid=101, pgid=101, start="lost-admission", boot="old-boot")
    assert gate.authorize(ActionKind.CLAIM, old, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    con.close()
    tracker, handler = Claims(), Handler()
    monkeypatch.setattr(drain_composition, "observe", lambda _owner: Seen.GONE)
    monkeypatch.setattr(drain_composition, "inspect_tracker_task", tracker.inspect)
    monkeypatch.setattr(drain_composition, "tracker_claims", lambda: tracker)
    assert not REQUEST.retake
    if retry:
        tracker.failing = True
        with cli_composition.open_rounds(path, tmp_path / "art", GitViews(30), REQUEST, handler.install) as failed:
            assert isinstance(failed, Failed) and (failed.kind, failed.reason) == ("unavailable", Reason.DRAINING)
            assert "claims" in failed.detail and "tl " not in failed.detail
        assert handler.installed == 0 and tracker.releases == []
        con = Store(SCHEMA).open_rw(path)
        assert con is not None
        assert DrainStore(lambda: con, ids=NativeIds()).pending()[0].state is ActionState.UNCERTAIN
        con.close()
        tracker.failing = False
    with cli_composition.open_rounds(path, tmp_path / "art", GitViews(30), REQUEST, handler.install) as opened:
        assert not isinstance(opened, (Failed, Ended)) and not opened.draining()
        assert handler.installed == 1 and tracker.releases == ["tl-1"]
        con = Store(SCHEMA).open_rw(path)
        assert con is not None
        try:
            gate = DrainStore(lambda: con, ids=NativeIds())
            assert not gate.pending() and gate.boundary().state is State.OPEN
        finally:
            con.close()


def test_unreadable_version_diagnosis_never_invents_a_recorded_version(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    path.write_bytes(b"unreadable metadata")
    detail = refusal(SchemaError("schema metadata unavailable"), path)
    assert str(path.resolve()) in detail and "recorded schema version could not be read" in detail
    assert "schema metadata unavailable" in detail and f"expects schema version {SCHEMA.version}" in detail
    assert "owner deliberately discards" in detail and path.read_bytes() == b"unreadable metadata"


@pytest.mark.parametrize("version", [SCHEMA.version - 1, SCHEMA.version])
def test_refusal_preserves_uncheckpointed_rows_sidecars_and_evidence(tmp_path: Path, version: int) -> None:
    path = incompatible(tmp_path, version)
    evidence = tmp_path / "entry.log"
    evidence.write_text("retained execution evidence")
    writer = sqlite3.connect(path, isolation_level=None)
    try:
        writer.execute("INSERT INTO slot VALUES ('repo','s2','/slots/s2',0)")
        wal, shm = path.with_name("factory.db-wal"), path.with_name("factory.db-shm")
        before, journal = path.read_bytes(), wal.read_bytes()
        assert journal
        identities = (wal.stat().st_ino, shm.stat().st_ino)
        for _ in range(2):
            with cli_composition.open_rounds(path, tmp_path / "art", GitViews(30), REQUEST) as ports:
                assert isinstance(ports, Failed) and ports.reason == "schema"
            assert path.read_bytes() == before and wal.read_bytes() == journal
            assert (wal.stat().st_ino, shm.stat().st_ino) == identities
        assert writer.execute("SELECT name FROM slot ORDER BY name").fetchall() == [("s1",), ("s2",)]
        assert evidence.read_text() == "retained execution evidence"
    finally:
        writer.close()


def test_temporary_open_failure_keeps_existing_database_handling_and_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = incompatible(tmp_path, SCHEMA.version)
    before = path.read_bytes()
    monkeypatch.setattr(Store, "open_ro", lambda self, database: None)
    with cli_composition.open_rounds(path, tmp_path / "art", GitViews(30), REQUEST) as ports:
        assert isinstance(ports, Failed) and ports.reason == "database"
    assert path.read_bytes() == before and not (tmp_path / "art").exists()


def test_incomplete_database_is_not_a_transient_round_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = incompatible(tmp_path, SCHEMA.version)

    def unexpected(*args: object, **kwargs: object) -> Never:
        pytest.fail("incomplete database reached a round")

    monkeypatch.setattr(cli_composition, "run_round", unexpected)
    found = cli_composition.one_round(path, tmp_path / "art", GitViews(30), REQUEST, lambda: False)(frozenset())
    assert isinstance(found, Failed) and found.word == "refused:schema"
    recovery_words(found.detail, path, SCHEMA.version)
    assert not (tmp_path / "art").exists()
