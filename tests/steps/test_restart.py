"""A fresh runtime reopens intact state and reconciles unfinished work without starting over."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import Done
from round_bench import NoRequired
from sqlite_store import Store
from stream_proc import OwnedProcess
from test_attempt import AttemptSurroundings, codex
from test_attempt import surroundings as attempt_surroundings
from test_continuation import captured_work as captured_attempt
from test_launch import NEW, FakeStart, Observe, launcher
from test_native_continuation import NativeRun, prepared
from test_operations import REQUEST as START_REQUEST
from test_recovery import Processes, recovery
from test_recovery_store import KEY, OWNED, OWNER, database
from test_round import ENTRY, REQUEST, Bench, seed

from taskloop import composition
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, Seen, VerifyResult
from taskloop.cli_composition import open_reads
from taskloop.drain.models import Seen as ProcessSeen
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.hold_store import HoldStore
from taskloop.operations import Failed, Round, Started, start
from taskloop.recovery.complete_attempt import CapturedCompletion
from taskloop.recovery.continuation_models import State
from taskloop.recovery.entry import RecoveryEntry
from taskloop.recovery.models import Intent
from taskloop.round import run_round
from taskloop.slot_lock import hold

PROGRESS = ("attempt", "execution", "verification", "slot_release", "published_branch")
surroundings = attempt_surroundings
captured_work = captured_attempt


def continue_saved(path: Path, artifacts: Path, views: GitViews) -> None:
    app = composition.open_continuation(path, artifacts, views, credentials=codex)
    con = app.attempts.store.connect()
    assert con is not None
    try:
        entry = RecoveryEntry(app)
        intent = entry.registered(KEY, (OWNER.pid, OWNER.start, OWNER.boot))
        assert isinstance(intent, Intent) and intent.session == "saved"
        record = app.attempts.store.load(KEY)
        assert record is not None
        with hold(record.admission):
            result = entry.run(intent, OWNER, lambda: 10, lambda _seconds: None, 2)
        assert result.state is State.COMPLETED
    finally:
        con.close()
        recovery_con = app.recovery.store.connect()
        assert recovery_con is not None
        recovery_con.close()


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_reopened_start_and_rounds_resume_one_saved_attempt(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, direct: bool, expired: bool,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    con.execute("PRAGMA journal_mode=WAL")
    execution, processes = NativeRun(), Processes()
    prepared(con, surroundings, execution)
    reservations = con.execute("SELECT * FROM reservation").fetchall()
    identity = con.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall()
    con.close()
    child = FakeStart(identity=OwnedProcess(OWNER.pid, OWNER.pgid, OWNER.start, OWNER.boot))
    monkeypatch.setattr(composition, "NativeProcesses", lambda: processes)
    monkeypatch.setattr(composition, "tracker_recovery_claim", lambda _root: lambda _admission: OWNED)
    monkeypatch.setattr(composition, "popen_registered", child)
    monkeypatch.setattr(composition.time, "time", lambda: 200 if expired else 10)
    monkeypatch.setattr(composition, "run", lambda harness, spec, timeout, hooks, **_kwargs: execution(harness, spec, timeout, hooks))
    views = GitViews(30)
    authorized: list[tuple[object, ...]] = []
    for index in range(4):
        processes.states = {OWNER.pid: ProcessSeen.ALIVE} if index == 1 else (
            {OWNER.pid: ProcessSeen.UNKNOWN} if index == 2 else {})
        if index == 3:
            continue_saved(path, tmp_path, views)
        reopened = sqlite3.connect(path, isolation_level=None)
        try:
            bench = Bench(reopened, free=False)
            bench.now = 200 if expired else 10
            ports = bench.ports()
            observed = recovery(reopened, processes)
            observed.clock = ports.reads.clock
            ports = replace(ports, reads=replace(ports.reads, recovery=observed.status),
                            starting=replace(ports.starting, launcher=composition.open_launcher(path, tmp_path, views)))
            if direct and index == 0:
                result = start(ports.starting, START_REQUEST)
                assert isinstance(result, Started) and result.existing and result.attempt_id == KEY.attempt_id
            else:
                result = run_round(ports, REQUEST)
                assert isinstance(result, Round)
                expected = [("relaunch", "relaunched"), ("report", "running"), ("report", "unknown"),
                            ("verify", "verified release=released branch=published")][index]
                assert [(move.action, move.word) for move in result.moves] == [expected]
                assert all(move.attempt_id == KEY.attempt_id for move in result.moves)
            assert bench.launcher.calls == bench.admission.requests == bench.repeats.calls == []
            assert reopened.execute("SELECT * FROM reservation").fetchall() == reservations
            assert reopened.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall() == identity
            assert reopened.execute("SELECT session_ref FROM attempt").fetchone() == ("saved",)
            intents = reopened.execute("SELECT * FROM recovery_intent").fetchall()
            if index == 0:
                authorized = intents
            elif index < 3:
                assert intents == authorized
        finally:
            reopened.close()
    assert len(child.calls) == 1 and child.permitted
    assert len(execution.calls) == execution.permits == 1 and "saved" in execution.calls[0][1].argv


def complete_round(
    reopened: sqlite3.Connection, surroundings: AttemptSurroundings, execution: NativeRun, index: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = surroundings.attempts(AttemptStore(lambda: reopened), execution)
    bench = Bench(reopened, free=False)
    verify = bench.recorded.verify
    events: list[str] = []

    def checked(key: AttemptKey) -> VerifyResult:
        result = attempts.collect(key)
        assert result.status == "pending" and result.reason == "verification"
        if index == 1:
            assert events == ["complete"]
        events.append("verify")
        return verify(key)

    completion = CapturedCompletion(attempts, HoldStore(lambda: reopened), hold, lambda _entry: "gone")

    def completed(backlog: str, task_id: str, attempt_id: str) -> AttemptResult:
        events.append("complete")
        return completion(backlog, task_id, attempt_id)

    monkeypatch.setattr(bench.recorded, "verify", checked)
    ports = replace(bench.ports(), completion=completed)
    with monkeypatch.context() as patch:
        if index == 0:
            patch.setattr(attempts.store, "connect", lambda: None)
        result = run_round(ports, REQUEST)
    assert isinstance(result, Round)
    assert bench.launcher.calls == bench.admission.requests == bench.repeats.calls == []
    if index == 0:
        assert [(move.action, move.word) for move in result.moves] == [("verify", "unavailable:store")]
        assert events == ["complete"] and bench.recorded.calls == []
    else:
        assert [(move.action, move.word) for move in result.moves] == [
            ("verify", "verified release=released branch=published")]
        assert events == (["complete", "verify"] if index == 1 else ["verify"])
        stored = attempts.store.collect(KEY)
        assert stored is not None and stored.answer.kind == "valid" and stored.session_state == "complete"
        assert attempts.store.callback(KEY) is not None


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
    execution = NativeRun()
    for index in range(3):
        reopened = sqlite3.connect(tmp_path / "factory.db", isolation_level=None)
        try:
            complete_round(reopened, surroundings, execution, index, monkeypatch)
            assert reopened.execute("SELECT * FROM reservation").fetchall() == reservations
            assert reopened.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall() == identity
        finally:
            reopened.close()
    assert execution.calls == [] and execution.permits == 0


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
