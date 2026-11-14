"""Intact-database restart settles lost entries without weakening custody or registration gates."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from beads_client import BdError
from git_porcelain.testing import FakeWorktree
from test_round import Bench
from test_slot_release import ENTRY, KEY, WORKER, WORKING, Ports, executed, head, stored

from taskloop.attempt_status import current_view
from taskloop.attempt_types import Checkouts, Seen, SlotFiles
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.release_proof import Stopping, stop_proof, worker_stopped
from taskloop.slot_release import AlreadyReleased, NotReleased, Released


def dispatched(con: sqlite3.Connection, worker: bool) -> None:
    identity = (WORKER.pid, WORKER.pgid, WORKER.start, WORKER.boot) if worker else (None,) * 4
    con.execute(WORKING, ("registered" if worker else "dispatching", *identity))


@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("claim_failure", [False, True])
def test_reopened_status_requires_explicit_release_then_round_finishes_claim_return(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts,
    slot_files: SlotFiles, worker: bool, claim_failure: bool,
) -> None:
    dispatched(registered, worker)
    path = tmp_path / "restart.db"
    con = sqlite3.connect(path, isolation_level=None)
    registered.backup(con)
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    try:
        ports = Ports(con, checkouts, slot_files)
        if claim_failure:
            ports.answers = [BdError("other", "down"), True]
        bench = Bench(con, free=False)
        bench.releaser = ports.releaser()
        view = current_view(bench.ports().reads, "tasks", "tl-1")
        assert view is not None and view.next == "unknown"
        before = list(con.iterdump())
        assert current_view(bench.ports().reads, "tasks", "tl-1") == view
        assert list(con.iterdump()) == before
        first = bench.round()
        assert (first.moves[0].action, first.moves[0].word) == ("report", "unknown")
        assert stored(con)[0] != [] and ports.unclaimed == []
        released = ports.releaser().reconcile(KEY)
        assert isinstance(released, NotReleased if claim_failure else Released)
        if isinstance(released, NotReleased):
            assert released.reason == "tracker"
        assert stored(con)[0] == []
        con.close()
        con = sqlite3.connect(path, isolation_level=None)
        ports.con = con
        bench = Bench(con, free=False)
        bench.releaser = ports.releaser()
        bench.round()
        assert stored(con)[1] == [(head(slot), 30.0, "unclaimed")]
        assert ports.unclaimed == [("/tracker", "tl-1")] * (2 if claim_failure else 1)
        assert ports.releaser().reconcile(KEY) == AlreadyReleased("s1", "unclaimed", True)
    finally:
        con.close()


@pytest.mark.parametrize(("seen", "worker", "alive", "reason"), [
    ("matching", False, False, "entry_running"), ("unknown", False, False, "observe"),
    ("gone", True, True, "worker_alive"), ("different_process", True, True, "worker_alive"),
])
def test_uncertain_or_running_processes_preserve_reservation_without_git(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles,
    seen: Seen, worker: bool, alive: bool, reason: str,
) -> None:
    dispatched(registered, worker)
    ports = Ports(registered, checkouts, slot_files, seen, alive)
    before = stored(registered), registered.execute("SELECT * FROM attempt").fetchall()
    result = ports.releaser().reconcile(KEY)
    assert isinstance(result, NotReleased) and result.reason == reason and result.detail
    assert (stored(registered), registered.execute("SELECT * FROM attempt").fetchall()) == before
    assert (ports.opens, ports.holds, ports.unclaimed) == (0, 0, [])


@pytest.mark.parametrize("race", [False, True])
@pytest.mark.parametrize("capture", [False, True])
def test_capture_and_explicit_hold_prevent_reconciliation_even_after_stop_proof(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts,
    slot_files: SlotFiles, race: bool, capture: bool,
) -> None:
    if capture:
        assert executed(registered, tmp_path, slot, checkouts, slot_files, {}) == "verification"
    captured = registered.execute("SELECT * FROM execution").fetchone()
    if race and capture:
        registered.execute("DELETE FROM execution")
    if not capture or race:
        dispatched(registered, False)
    if not capture:
        registered.execute("UPDATE attempt SET label='auto'")
    ports = Ports(registered, checkouts, slot_files)

    def protect() -> None:
        if capture:
            assert captured is not None
            if race:
                registered.execute(f"INSERT INTO execution VALUES ({','.join('?' for _ in captured)})", captured)
            registered.execute("UPDATE attempt SET phase='dispatching'")  # capture remains authoritative
        else:
            HoldStore(lambda: registered).insert(HoldInsert(KEY.attempt_id, KEY.attempt_id, "stuck:entry_lost", 20))

    if race:
        ports.inside = protect
    else:
        protect()
    before = stored(registered)
    result = ports.releaser().reconcile(KEY)
    assert isinstance(result, NotReleased) and result.reason in ("captured", "held", "changed")
    assert stored(registered) == before and ports.unclaimed == []
    assert ports.opens == 0


def test_absence_and_self_release_are_not_external_entry_death_proof() -> None:
    row = Stopping("dispatching", ENTRY, None)
    for candidate, me in [(replace(row, entry=None), None), (row, ENTRY)]:
        assert stop_proof(lambda _entry: "gone", lambda _worker: True, me, candidate) is not None
    assert worker_stopped(lambda _worker: True, "dispatching", None) is not None
    assert stop_proof(lambda _entry: "gone", lambda _worker: True, None, row) is None


@pytest.mark.parametrize("change", [
    "rev=rev+1", "entry_start='replacement'", "worker_pid=42,worker_pgid=42,worker_start='new',worker_boot='boot'",
    "phase='admitted'", "generation=generation+1",
])
def test_attempt_changed_between_observation_and_custody_is_preserved_before_git(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles, change: str,
) -> None:
    dispatched(registered, False)
    ports = Ports(registered, checkouts, slot_files)
    ports.inside = lambda: registered.execute(f"UPDATE attempt SET {change}")
    before = stored(registered)
    result = ports.releaser().reconcile(KEY)
    assert isinstance(result, NotReleased) and result.reason == "changed"
    assert stored(registered) == before and ports.unclaimed == [] and ports.opens == 0


def test_missing_entry_registration_cannot_authorize_automatic_release(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles,
) -> None:
    dispatched(registered, False)
    registered.execute("UPDATE attempt SET entry_pid=NULL,entry_start=NULL,entry_boot=NULL")
    ports = Ports(registered, checkouts, slot_files)
    before = stored(registered)
    result = ports.releaser().reconcile(KEY)
    assert isinstance(result, NotReleased) and result.reason == "ineligible"
    assert stored(registered) == before and (ports.opens, ports.holds, ports.unclaimed) == (0, 0, [])


@pytest.mark.parametrize("unsafe", ["dirty", "diverted", "generation"])
def test_unsafe_slot_or_changed_ownership_keeps_reservation(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, unsafe: str,
) -> None:
    dispatched(registered, False)
    if unsafe == "dirty":
        slot.write_file("user-data.txt", "keep me")
    elif unsafe == "diverted":
        slot.checkout_new("user-branch")
    else:
        registered.execute("UPDATE reservation SET generation=generation+1")
    ports = Ports(registered, checkouts, slot_files)
    before = stored(registered)
    result = ports.releaser().reconcile(KEY)
    assert isinstance(result, NotReleased) and result.reason in ("slot_dirty", "slot_branch", "changed")
    assert stored(registered) == before and ports.unclaimed == []
