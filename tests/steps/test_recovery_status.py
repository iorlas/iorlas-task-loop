"""Shared process observations fence status consumers and successive scheduling rounds."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain.testing import FakeWorktree
from round_bench import Factory, Tracker
from test_recovery import Processes, recovery
from test_recovery_registration import WORKER, intended
from test_recovery_snapshot import capture
from test_recovery_store import OWNER, database, facts, observed

from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_status import Listed, Next, Shown, StatusPorts, current_view, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, SlotFiles, Unsettled
from taskloop.drain.models import Seen
from taskloop.operations import Round
from taskloop.recovery.models import Observations, Outcome, Result
from taskloop.round import NextRequest, run_round


def no_leftovers(_key: AttemptKey) -> Unsettled | None:
    raise AssertionError("Blocked status must not probe leftovers")


def ports(con: sqlite3.Connection, processes: Processes, now: float = 10) -> StatusPorts:
    app = recovery(con, processes)
    app.clock = lambda: now
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "gone", lambda: now, no_leftovers,
                       lambda: "boot", recovery=app.status)


@pytest.mark.parametrize(("states", "word"), [
    ({7: Seen.ALIVE}, "wait"), ({8: Seen.ALIVE}, "wait"), ({30: Seen.ALIVE}, "wait"),
    ({7: Seen.UNKNOWN}, "unknown"), ({8: Seen.UNKNOWN}, "unknown"), ({30: Seen.UNKNOWN}, "unknown"),
    ({7: Seen.ALIVE, 8: Seen.UNKNOWN}, "unknown"), ({8: Seen.ALIVE, 30: Seen.UNKNOWN}, "unknown"),
    ({}, "release"),
])
@pytest.mark.parametrize("expired", [False, True])
def test_shared_gate_covers_all_status_consumers_without_writes(
    tmp_path: Path, states: dict[int, Seen], word: Next, expired: bool,
) -> None:
    con = database(tmp_path / "factory.db")
    intended(recovery(con).store)
    processes = Processes()
    processes.states = states
    reads = ports(con, processes, 100 if expired else 10)
    expected = "stuck:hung" if word == "wait" and expired else word
    before = list(con.iterdump())
    for _ in range(2):
        shown = show_attempt(reads, tmp_path / "artifacts", "tasks", "tl-1")
        listed = list_attempts(reads)
        current = current_view(reads, "tasks", "tl-1")
        assert isinstance(shown, Shown) and isinstance(listed, Listed) and current is not None
        assert shown.view.next == listed.attempts[0].next == current.next == expected
        assert list(con.iterdump()) == before and not (tmp_path / "artifacts").exists()
    assert processes.calls == [7, 8, 30] * 6
    con.close()


@pytest.mark.parametrize("change", [
    "UPDATE attempt SET worker_start=NULL", "UPDATE attempt SET session_ref=NULL",
    "UPDATE attempt SET session_conflict=1", "UPDATE attempt SET entry_start=NULL",
])
def test_incomplete_registration_and_missing_reader_fail_closed(tmp_path: Path, change: str) -> None:
    con = database(tmp_path / "factory.db")
    reads = ports(con, Processes())
    # Exercise the old constructor shape without relying on a supplied recovery reader.
    missing = StatusPorts(reads.store, reads.observe, reads.clock, reads.leftovers, reads.boot)
    view = current_view(missing, "tasks", "tl-1")
    assert view is not None and view.next == "unknown"
    con.execute(change)
    view = current_view(reads, "tasks", "tl-1")
    assert view is not None and view.next == "unknown"
    con.close()


@pytest.mark.parametrize("outcome", [Outcome.CHANGED, Outcome.UNAVAILABLE])
@pytest.mark.parametrize("raises", [False, True])
def test_unavailable_or_changed_observation_cannot_make_status_actionable(tmp_path: Path, outcome: Outcome, raises: bool) -> None:
    con = database(tmp_path / "factory.db")

    def read(_key: AttemptKey) -> Observations | Result:
        if raises:
            raise StoreUnavailable("The observation is unavailable")
        return Result(outcome=outcome, explanation="Facts unavailable.")

    reads = replace(ports(con, Processes()), recovery=read)
    view = current_view(reads, "tasks", "tl-1")
    assert view is not None and view.next == "unknown"
    con.close()


def test_captured_completion_and_explicit_holds_keep_their_own_paths(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    intent = intended(app.store)
    assert app.store.register(intent, WORKER, lambda: 10).intent is not None
    capture(con, observed(app.store).snapshot)

    def forbidden(_key: AttemptKey) -> Observations | Result:
        raise AssertionError("Captured execution must not observe recovery processes")

    reads = replace(ports(con, Processes()), recovery=forbidden, leftovers=lambda _key: None)
    view = current_view(reads, "tasks", "tl-1")
    assert view is not None and view.next == "verify"
    con.execute("DELETE FROM execution")
    con.execute("UPDATE attempt SET phase='registered', label='auto'")
    con.execute("INSERT INTO task_hold(attempt_id,cause_id,reason,held_at) VALUES('attempt','attempt','stuck:entry_lost',10)")
    before = list(con.iterdump())
    shown = show_attempt(ports(con, Processes()), tmp_path / "artifacts", "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.view.next == "hold"
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.UNKNOWN])
def test_successive_rounds_do_not_execute_while_recovery_processes_are_live_or_unknown(
    tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles, seen: Seen,
) -> None:
    con = database(tmp_path / "factory.db")
    intended(recovery(con).store)
    processes = Processes()
    processes.states = {OWNER.pid: seen}
    bench = Factory(con, tmp_path, slot, checkouts, slot_files, Tracker(), adopted=True)
    round_ports = replace(bench.ports(), reads=ports(con, processes))
    request = NextRequest("tasks", "/tracker", slot.repo.path, "auto", StepSettings(), Overrides(), 30)
    before = facts(con), observed(recovery(con).store).snapshot
    for _ in range(2):
        result = run_round(round_ports, request)
        assert isinstance(result, Round)
        assert all(move.action == "report" for move in result.moves)
        assert (facts(con), observed(recovery(con).store).snapshot) == before
    assert not bench.ran and not bench.tracker.claims and not bench.tracker.holds
    con.close()
