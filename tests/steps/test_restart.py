"""A fresh runtime reopens intact state and reconciles unfinished work without starting over."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import Done
from round_bench import NoRequired
from sqlite_store import Store
from test_attempt import AttemptSurroundings
from test_attempt import surroundings as attempt_surroundings
from test_continuation import captured_work as captured_attempt
from test_launch import NEW, FakeStart, Observe, launcher
from test_native_continuation import NativeRun
from test_recovery_store import KEY
from test_round import ENTRY, REQUEST, Bench, seed

from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Seen, VerifyResult
from taskloop.cli_composition import open_reads
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.hold_store import HoldStore
from taskloop.operations import Failed, Round
from taskloop.recovery.complete_attempt import CapturedCompletion
from taskloop.round import run_round
from taskloop.slot_lock import hold

PROGRESS = ("attempt", "execution", "verification", "slot_release", "published_branch")
surroundings = attempt_surroundings
captured_work = captured_attempt


@pytest.mark.parametrize("pending", ["answer", "pending", "fault"])
def test_reopened_round_finishes_captured_work_before_verifying(
    tmp_path: Path, surroundings: AttemptSurroundings, captured_work: Attempts, pending: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = captured_work.store.connect()
    assert con is not None
    if pending != "answer":
        assert captured_work.execute(KEY, (7, "entry", "boot")).reason == "verification"
        con.execute("UPDATE execution SET session_state=?", (pending,))
        con.execute("UPDATE attempt SET session_ref=NULL")
    reservations = con.execute("SELECT * FROM reservation").fetchall()
    identity = con.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall()
    con.close()
    reopened = sqlite3.connect(tmp_path / "factory.db", isolation_level=None)
    try:
        execution = NativeRun()
        attempts = surroundings.attempts(AttemptStore(lambda: reopened), execution)
        bench = Bench(reopened, free=False)
        verify = bench.recorded.verify

        def checked(key: AttemptKey) -> VerifyResult:
            result = attempts.collect(key)
            assert result.status == "pending" and result.reason == "verification"
            return verify(key)

        monkeypatch.setattr(bench.recorded, "verify", checked)
        completion = CapturedCompletion(attempts, HoldStore(lambda: reopened), hold, lambda _entry: "gone")
        ports = replace(bench.ports(), completion=completion)
        with monkeypatch.context() as patch:
            patch.setattr(attempts.store, "connect", lambda: None)
            failed = run_round(ports, REQUEST)
        assert isinstance(failed, Round)
        assert [(move.action, move.word) for move in failed.moves] == [("verify", "unavailable:store")]
        assert bench.recorded.calls == []
        for _round in range(2):
            result = run_round(ports, REQUEST)
            assert isinstance(result, Round)
            assert [(move.action, move.word) for move in result.moves] == [
                ("verify", "verified release=released branch=published")]
            stored = attempts.store.collect(KEY)
            assert stored is not None and stored.answer.kind == "valid" and stored.session_state == "complete"
        assert execution.calls == [] and execution.permits == 0
        assert bench.launcher.calls == bench.admission.requests == bench.repeats.calls == []
        assert reopened.execute("SELECT * FROM reservation").fetchall() == reservations
        assert reopened.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall() == identity
        assert attempts.store.callback(KEY) is not None
    finally:
        reopened.close()


@pytest.mark.parametrize("phase, seen, action, word, launches", [
    ("dispatching", "matching", "report", "unknown", 0),
    ("admitted", "gone", "relaunch", "relaunched", 1),
    ("dispatching", "unknown", "report", "unknown", 0),
])
def test_compatible_restart_keeps_progress_sessions_and_reservation_and_reconciles_the_same_attempt(
    done: Done, tmp_path: Path, phase: str, seen: Seen, action: str, word: str, launches: int,
) -> None:
    original = Store(SCHEMA)
    con = original.shared_rw(done.path)
    assert con is not None
    con.execute("UPDATE attempt SET session_ref='completed-session' WHERE attempt_id='implement'")
    seed(con, "tl-2", "unfinished", phase=phase, entry=ENTRY)
    con.execute("UPDATE attempt SET repo_id=(SELECT repo_id FROM slot WHERE name='s1'),session_ref='unfinished-session' "
                "WHERE attempt_id='unfinished'")
    con.execute("INSERT INTO reservation SELECT 's1',repo_id,1,'unfinished' FROM slot WHERE name='s1'")
    progress = {table: con.execute(f"SELECT * FROM {table} WHERE attempt_id='implement'").fetchall() for table in PROGRESS}
    reservation = con.execute("SELECT * FROM reservation").fetchall()
    original.close_shared()  # no fixture or runtime connection survives the restart

    with open_reads(done.path, tmp_path, GitViews(30)) as reads:
        assert not isinstance(reads, Failed)
        assert reads.store.attempt_of("tasks", "tl-2") == (AttemptKey("unfinished", "token-unfinished", 1), phase, ENTRY)

    fresh = Store(SCHEMA)
    reopened = fresh.open_rw(done.path)
    assert reopened is not None
    try:
        bench = Bench(reopened, free=False)
        bench.seen = seen
        started = FakeStart()
        ports = bench.ports()
        starting = replace(ports.starting, launcher=launcher(done.path, started, Observe(seen)),
                           checks=replace(ports.starting.checks, admission=NoRequired()))
        ports = replace(ports, starting=starting)
        result = run_round(ports, REQUEST)
        assert isinstance(result, Round)
        assert [(move.action, move.word, move.attempt_id) for move in result.moves if move.task_id == "tl-2"] == [
            (action, word, "unfinished")]
        assert len(started.calls) == launches
        assert bench.admission.requests == bench.repeats.calls == bench.recorded.calls == []
        assert reopened.execute("SELECT * FROM reservation").fetchall() == reservation
        assert reopened.execute("SELECT count(*) FROM attempt").fetchone() == (2,)
        assert reopened.execute("SELECT session_ref FROM attempt WHERE attempt_id='unfinished'").fetchone() == ("unfinished-session",)
        expected_entry = (NEW.pid, NEW.start, NEW.boot) if launches else ENTRY
        assert bench.store.attempt_of("tasks", "tl-2") == (AttemptKey("unfinished", "token-unfinished", 1), phase, expected_entry)
        for table, rows in progress.items():
            assert reopened.execute(f"SELECT * FROM {table} WHERE attempt_id='implement'").fetchall() == rows
    finally:
        reopened.close()
