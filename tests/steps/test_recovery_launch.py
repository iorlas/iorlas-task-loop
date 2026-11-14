"""Registered recovery starts commit the child's authority before sending permission."""

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from stream_proc import OwnedProcess
from test_launch import FakeStart, Observe
from test_recovery import Processes
from test_recovery_store import KEY, OWNED, database

from taskloop import slot_lock
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.drain.models import Identity, Seen
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.launch import Launched, Launcher, LaunchRefused, LaunchUncertain
from taskloop.operations import Failed, launched
from taskloop.recovery.launch import RecoveryLaunch
from taskloop.recovery.models import Claim, ClaimState, Outcome, Snapshot
from taskloop.recovery.recover import Recovery
from taskloop.recovery.store import RecoveryStore


def launcher(path: Path, start: FakeStart, recovery: Recovery) -> Launcher:
    return Launcher(path, EvidenceFiles(path.parent), lambda: 10, start, Observe(), "/venv/bin/python",
                    read_seconds=DEFAULT_GIT_READ_SECONDS, ids=NativeIds(), recovery=RecoveryLaunch(recovery))


@pytest.fixture
def con(tmp_path: Path) -> Generator[sqlite3.Connection]:
    connection = database(tmp_path / "factory.db")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("UPDATE slot SET path=?", (str(tmp_path / "slot"),))
    yield connection
    connection.close()


def recovery(con: sqlite3.Connection, processes: Processes | None = None, claim: Claim = OWNED) -> Recovery:
    return Recovery(RecoveryStore(lambda: con), processes or Processes(), lambda _admission: claim,
                    slot_lock.hold, lambda: 10, NativeIds())


def test_child_authority_is_durable_before_permit(con: sqlite3.Connection, tmp_path: Path) -> None:
    start = FakeStart()
    app = recovery(con)
    columns = "attempt_id,dispatch_token,generation,entry_pid,entry_start,entry_boot,session_ref"
    original = con.execute(f"SELECT {columns} FROM attempt").fetchone()
    reservation = con.execute("SELECT * FROM reservation").fetchall()

    def authorized_before_permit() -> None:
        assert not start.permitted
        snapshot = app.store.snapshot(KEY, 10)
        assert isinstance(snapshot, Snapshot) and snapshot.intent is not None
        assert snapshot.intent.owner == Identity(pid=9, pgid=9, start="new-start", boot="boot")
        assert snapshot.intent.session == "saved" and snapshot.attempt.admission.deadline == 1810

    start.after = authorized_before_permit
    assert launcher(tmp_path / "factory.db", start, app).launch("tasks", "tl-1", 30) == Launched(KEY, (9, "new-start", "boot"))
    assert start.permitted and start.child.stdin.closed and start.child.stdout.closed
    assert con.execute(f"SELECT {columns} FROM attempt").fetchone() == original
    assert con.execute("SELECT * FROM reservation").fetchall() == reservation


@pytest.mark.parametrize(("pid", "seen"), [(7, Seen.ALIVE), (7, Seen.UNKNOWN), (8, Seen.ALIVE), (8, Seen.UNKNOWN)])
def test_live_or_unknown_original_processes_receive_no_permit(
    con: sqlite3.Connection, tmp_path: Path, pid: int, seen: Seen,
) -> None:
    processes = Processes()
    processes.states[pid] = seen
    start = FakeStart()
    result = launcher(tmp_path / "factory.db", start, recovery(con, processes)).launch("tasks", "tl-1", 30)
    assert isinstance(result, LaunchRefused) and result.reason is Outcome.UNRESOLVED and result.explanation
    assert not start.permitted and con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)


@pytest.mark.parametrize("state", [ClaimState.LOST, ClaimState.UNKNOWN])
def test_unowned_claim_has_an_explained_refusal(con: sqlite3.Connection, tmp_path: Path, state: ClaimState) -> None:
    start = FakeStart()
    app = recovery(con, claim=Claim(state=state, explanation="The bound task claim is unavailable."))
    result = launcher(tmp_path / "factory.db", start, app).launch("tasks", "tl-1", 30)
    assert isinstance(result, LaunchRefused) and result.explanation and not start.permitted
    mapped = launched(result, "tasks", "tl-1", KEY, existing=True)
    assert isinstance(mapped, Failed) and mapped.detail == result.explanation


def test_uncertain_start_retains_authority_until_its_owner_is_gone(con: sqlite3.Connection, tmp_path: Path) -> None:
    processes = Processes()
    app = recovery(con, processes)
    first = FakeStart("uncertain")
    assert isinstance(launcher(tmp_path / "factory.db", first, app).launch("tasks", "tl-1", 30), LaunchUncertain)
    processes.states[9] = Seen.ALIVE
    second = FakeStart(identity=OwnedProcess(10, 10, "second", "boot"))
    result = launcher(tmp_path / "factory.db", second, app).launch("tasks", "tl-1", 30)
    assert isinstance(result, LaunchRefused) and result.reason is Outcome.OCCUPIED and not second.permitted
    processes.states[9] = Seen.GONE
    assert isinstance(launcher(tmp_path / "factory.db", second, app).launch("tasks", "tl-1", 30), Launched)
    snapshot = app.store.snapshot(KEY, 10)
    assert isinstance(snapshot, Snapshot) and snapshot.intent is not None and snapshot.intent.generation == 2


@pytest.mark.parametrize(("change", "outcome"), [
    ("INSERT INTO task_hold(attempt_id,cause_id,reason,held_at) VALUES('attempt','cause','held',10)", Outcome.INELIGIBLE),
    ("INSERT INTO drain_state VALUES(1,1,'draining')", Outcome.DRAINING),
    ("UPDATE attempt SET rev=rev+1", Outcome.CHANGED),
])
def test_changed_or_fenced_work_runs_no_child(
    con: sqlite3.Connection, tmp_path: Path, change: str, outcome: Outcome,
) -> None:
    app = recovery(con)
    if outcome is Outcome.CHANGED:
        def changed_claim(_admission: object) -> Claim:
            con.execute(change)
            return OWNED

        app.claim = changed_claim
    else:
        con.execute(change)
    start = FakeStart()
    result = launcher(tmp_path / "factory.db", start, app).launch("tasks", "tl-1", 30)
    assert isinstance(result, LaunchRefused) and result.reason == outcome and result.explanation
    assert not start.permitted and con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)
