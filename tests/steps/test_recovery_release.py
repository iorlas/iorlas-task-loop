"""Release retains recovery custody, branch work and evidence across interruption and reopen."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest
from beads_client import BdError
from git_porcelain.testing import FakeWorktree
from stream_proc import OwnedProcess
from test_recovery_registration import WORKER
from test_recovery_store import OWNER
from test_slot_release import ENTRY, KEY, Ports, head, stored, tip, verified

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.drain.models import Boundary, Identity, State
from taskloop.recovery.execution_models import Execution, Phase
from taskloop.recovery.models import Intent
from taskloop.recovery.state_store import callback, save
from taskloop.recovery.store import RecoveryStore
from taskloop.release_proof import RecoveryReason, recovery_stopped
from taskloop.setup_store import ProcessSeen
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, SlotRelease, _Row


def saved_recovery(con: sqlite3.Connection, owner: Identity = OWNER) -> Intent:
    value = Intent(key=KEY, generation=1, token="recovery", owner=owner, attempt_revision=4,
                   session="saved", entry=ENTRY, worker=Identity(pid=42, pgid=43, start="old", boot="boot"),
                   execution=Execution(drain=Boundary(generation=0, state=State.OPEN), phase=Phase.REGISTERED,
                                       worker=WORKER, revision=5))
    save(con, value, None)
    con.execute("UPDATE execution SET recovery_callback=?", (callback(value).model_dump_json(),))
    return value


@pytest.mark.parametrize("mode", ["settled", "abandon", "reconcile"])
@pytest.mark.parametrize("pid", [OWNER.pid, 42, WORKER.pid])
@pytest.mark.parametrize("seen", ["alive", "unknown"])
def test_recovery_process_or_group_blocks_every_initial_release(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    mode: str, pid: int, seen: ProcessSeen,
) -> None:
    if mode == "reconcile":
        registered.execute("UPDATE attempt SET phase='dispatching',base_commit=slot_head")
    else:
        verified(registered, tmp_path, slot, checkouts, slot_files)
    saved_recovery(registered)
    before, branch, commit = stored(registered), slot.branch(), head(slot)
    ports = Ports(registered, checkouts, slot_files)
    ports.setups[pid] = seen
    app = ports.releaser()
    result = app.reconcile(KEY) if mode == "reconcile" else app.release(KEY, mode == "abandon", ENTRY)
    reason = RecoveryReason.RUNNING if seen == "alive" else RecoveryReason.UNKNOWN
    assert isinstance(result, NotReleased) and result.reason is reason and result.detail
    assert stored(registered) == before and (slot.branch(), head(slot)) == (branch, commit)
    assert ports.holds == ports.opens == 0 and ports.emptied == ports.unclaimed == []
    ports.setups[pid] = "gone"
    result = app.reconcile(KEY) if mode == "reconcile" else app.release(KEY, mode == "abandon", ENTRY)
    assert isinstance(result, Released) and not stored(registered)[0]


def test_recovery_proof_deduplicates_identities(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles,
) -> None:
    value = saved_recovery(registered)
    assert value.execution is not None
    value = value.model_copy(update={"owner": value.worker,
                                     "execution": value.execution.model_copy(update={"worker": value.worker})})
    ports = Ports(registered, checkouts, slot_files)
    assert recovery_stopped(ports.setup_seen, value) is None
    assert ports.setup_asked == [value.worker.pid]


@pytest.mark.parametrize("during_custody", [False, True])
@pytest.mark.parametrize("seen", ["alive", "unknown"])
def test_callers_recovery_group_blocks_release_even_when_liveness_changes_under_custody(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    during_custody: bool, seen: ProcessSeen,
) -> None:
    verified(registered, tmp_path, slot, checkouts, slot_files)
    owner = Identity(pid=ENTRY[0], pgid=17, start=ENTRY[1], boot=ENTRY[2])
    saved_recovery(registered, owner)
    ports = Ports(registered, checkouts, slot_files, seen="matching")
    before = stored(registered)
    if during_custody:
        ports.inside = lambda: ports.setups.update({owner.pid: seen})
    else:
        ports.setups[owner.pid] = seen
    result = ports.releaser().release(KEY, False, ENTRY)
    assert isinstance(result, NotReleased) and result.reason in (RecoveryReason.RUNNING, RecoveryReason.UNKNOWN)
    assert stored(registered) == before and ports.opens == 0 and ports.holds == int(during_custody)
    assert ports.emptied == ports.unclaimed == []


@pytest.mark.parametrize("corruption", ["json", "key", "execution"])
def test_invalid_recovery_records_refuse_release_without_effects(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles, corruption: str,
) -> None:
    value = saved_recovery(registered)
    data = ("{}" if corruption == "json" else value.model_copy(update={"key": replace(KEY, dispatch_token="other")}).model_dump_json()
            if corruption == "key" else value.model_dump_json().replace('"revision":5', '"revision":9'))
    registered.execute("UPDATE recovery_intent SET data=?", (data,))
    with pytest.raises(StoreUnavailable):
        RecoveryStore(lambda: registered).release_intent(KEY)
    ports = Ports(registered, checkouts, slot_files)
    before = stored(registered)
    result = ports.releaser().release(KEY, True)
    assert isinstance(result, NotReleased) and result.reason == "store"
    assert stored(registered) == before and ports.emptied == ports.unclaimed == [] and ports.opens == 0


@pytest.mark.parametrize("moment", ["custody", "observation", "record"])
def test_recovery_drift_retains_reservation_and_reports_completed_park(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch, moment: str,
) -> None:
    x = verified(registered, tmp_path, slot, checkouts, slot_files)
    value = saved_recovery(registered)
    ports = Ports(registered, checkouts, slot_files)

    def change() -> None:
        save(registered, value.model_copy(update={"token": "changed"}), value)

    if moment == "custody":
        ports.inside = change
    elif moment == "observation":
        observed = ports.setup_seen

        def drift(process: OwnedProcess) -> ProcessSeen:
            if len(ports.setup_asked) == 3:
                change()
            return observed(process)

        monkeypatch.setattr(ports, "setup_seen", drift)
    else:
        record = SlotRelease._record

        def drift_record(app: SlotRelease, row: _Row, commit: str, abandon: bool) -> bool:
            change()
            return record(app, row, commit, abandon)

        monkeypatch.setattr(SlotRelease, "_record", drift_record)
    result = ports.releaser().release(KEY, False)
    assert isinstance(result, NotReleased) and result.reason == "changed"
    assert stored(registered)[0] and stored(registered)[1] == []
    assert ports.emptied == ports.unclaimed == [] and tip(slot) == x
    assert ("was parked" in result.detail) == (moment == "record")


@pytest.mark.parametrize("interruption", ["park", "claim", "none"])
def test_completed_recovery_release_reopens_and_preserves_work_evidence_and_reused_slot(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch, interruption: str,
) -> None:
    x = verified(registered, tmp_path, slot, checkouts, slot_files)
    value = saved_recovery(registered)
    registered.execute("UPDATE attempt SET session_ref='saved'")
    path = tmp_path / "reopened.db"
    con = sqlite3.connect(path, isolation_level=None)
    registered.backup(con)
    evidence = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and p != path}
    durable = {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in ("execution", "recovery_intent")}
    ports = Ports(con, checkouts, slot_files)
    if interruption == "park":
        def interrupted(*_args: object, **_kwargs: object) -> NoReturn:
            raise KeyboardInterrupt

        with monkeypatch.context() as patch:
            patch.setattr(SlotRelease, "_record", interrupted)
            with pytest.raises(KeyboardInterrupt):
                ports.releaser().release(KEY, False)
        assert stored(con)[0] and stored(con)[1] == []
    elif interruption == "claim":
        ports.answers = [BdError("other", "offline"), True]
        assert isinstance(ports.releaser().release(KEY, True), NotReleased)
        assert stored(con)[1][0][2] == "unclaiming"
    else:
        assert isinstance(ports.releaser().release(KEY, False), Released)
    if interruption == "claim":
        slot.write_file("new-work", "next attempt's uncommitted work")
        ports.setups[OWNER.pid] = "unknown"
    pending = (ports.opens, ports.holds, len(ports.emptied))
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    ports.con = con
    assert RecoveryStore(lambda: con).release_intent(KEY) == value
    assert isinstance(ports.releaser().release(KEY, False), (Released, AlreadyReleased))
    if interruption == "claim":
        assert (ports.opens, ports.holds, len(ports.emptied)) == pending
    assert not stored(con)[0] and len(stored(con)[1]) == 1 and tip(slot) == x
    # A new use of the free slot must survive repeated settled release and abandon.
    slot.write_file("new-work", "next attempt's uncommitted work")
    before = (ports.opens, ports.holds, len(ports.emptied))
    ports.setups[OWNER.pid] = "alive"
    assert isinstance(ports.releaser().release(KEY, True), (Released, AlreadyReleased))
    assert isinstance(ports.releaser().release(KEY, True), AlreadyReleased)
    assert isinstance(ports.releaser().release(KEY, False), AlreadyReleased)
    assert (ports.opens, ports.holds, len(ports.emptied)) == before
    assert slot.read_file("new-work") == "next attempt's uncommitted work" and tip(slot) == x
    assert {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in durable} == durable
    assert con.execute("SELECT session_ref FROM attempt").fetchone() == ("saved",)
    assert all(p.read_bytes() == data for p, data in evidence.items())
    assert len(ports.unclaimed) == (2 if interruption == "claim" else 1)
    assert len(ports.emptied) == 1
    con.close()
