"""Phase entry is durable before effects; resumes and observations preserve truthful bounds."""

import sqlite3
from pathlib import Path

import pytest
from doubles import CHECKS, Command
from git_porcelain import Sha, Transient
from land_bench import REQUIRED, LandBench, bench

from taskloop.attempt_types import AttemptKey
from taskloop.check_release import ChecksRelease
from taskloop.land import Landed
from taskloop.land_check import inserted
from taskloop.land_close import closed
from taskloop.land_push import Origin, reconcile_delivery
from taskloop.land_store import LandStore, Validation
from taskloop.land_timing import Phase, RetryCause
from taskloop.operations import Failed
from taskloop.slot_lock import landing
from taskloop.slot_release import Released
from taskloop.tracker_client import CloseAnswer


def reopen(b: LandBench) -> LandStore:
    b.con.close()
    b.con = sqlite3.connect(b.root / "factory.db", isolation_level=None)
    b.environment.con = b.con
    b.lands = LandStore(lambda: b.con, b.begin)
    return b.lands


def test_distinct_phase_times_are_stored_before_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = bench(tmp_path)
    b.advance({"OTHER": "another task\n"})
    start = b.lands.start_phase

    def advancing(key: AttemptKey, phase: Phase, now: float,
                  read: tuple[int, Validation | None] | None = None, *, abandon: bool = False) -> None:
        start(key, phase, now, read, abandon=abandon)
        assert not b.con.in_transaction
        b.now += 10

    monkeypatch.setattr(b.lands, "start_phase", advancing)
    found = b.land()
    assert isinstance(found, Landed)
    row = reopen(b).row(found.row.key)
    assert row is not None and row.retry_cause is None and row.admitted_at == 10
    assert (row.validation_started_at, row.validated_at) == (10, 20)
    assert (row.release_started_at, row.released_at) == (20, 30)
    assert (row.delivery_started_at, row.delivered_at) == (30, 40)
    assert (row.close_started_at, row.closed_at) == (40, 50)


def test_interrupted_validation_keeps_first_start_across_reopen(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.advance({"OTHER": "another task\n"})

    def interrupt() -> None:
        row = b.rows()[0]
        assert row.validation_started_at == 10 and row.validated_at is None
        assert row.release_started_at is None and row.delivery_started_at is None
        raise KeyboardInterrupt

    b.environment.process.script = [Command(effect=interrupt)]
    with pytest.raises(KeyboardInterrupt):
        b.land()
    reopen(b)
    b.now = 100
    b.environment.process.script = []
    found = b.land()
    assert isinstance(found, Landed) and found.row.number == 1 and found.row.retry_cause is None
    assert (found.row.validation_started_at, found.row.validated_at) == (10, 100)


@pytest.mark.parametrize("cause", [RetryCause.FAILED, RetryCause.MOVED, RetryCause.GONE, RetryCause.WITHDRAWN])
def test_replacement_cause_survives_reopen(tmp_path: Path, cause: RetryCause) -> None:
    b = bench(tmp_path)
    if cause is RetryCause.FAILED:
        b.advance({"OTHER": "another task\n"})
        b.environment.process.script = [Command(), Command(rc=1)]
    else:
        b.repo.answer = Transient("offline")
    assert isinstance(b.land(), Failed)
    previous = b.rows()[0]
    if cause is not RetryCause.FAILED:
        why = "moved" if cause is RetryCause.MOVED else "gone" if cause is RetryCause.GONE else "withdrawn"
        assert b.lands.supersede(previous.key, why, 11)
    before = b.rows()[0]
    reopen(b)
    b.now = 100
    found = b.land()
    assert isinstance(found, Landed) and found.row.number == 2 and found.row.retry_cause is cause
    assert b.rows()[0] == before
    assert reopen(b).row(found.row.key) == found.row


def test_delivery_and_close_retries_keep_first_starts(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.repo.answer = Transient("offline")
    assert isinstance(b.land(), Failed)
    row = b.rows()[0]
    assert row.delivery_started_at == 10 and row.delivered_at is None and row.close_started_at is None
    assert row.release_started_at is None and row.released_at is None
    b.now = 20
    b.closing = [CloseAnswer("unavailable", detail="offline")]
    assert isinstance(b.land(), Failed)
    row = b.rows()[0]
    assert (row.delivery_started_at, row.delivered_at, row.close_started_at, row.closed_at) == (10, 20, 20, None)
    reopen(b)
    b.now = 30
    found = b.land()
    assert isinstance(found, Landed)
    assert (found.row.close_started_at, found.row.closed_at) == (20, 30)


def test_abandon_records_release_and_replacement_cause(tmp_path: Path) -> None:
    b = bench(tmp_path)
    work = b.checking()
    checks = work.store.row(CHECKS)
    assert checks is not None
    pending = inserted(b.ports(), b.repo, checks, (1, b.base, b.x, False, REQUIRED), None, 100)
    assert not isinstance(pending, Failed)
    b.now = 20
    release = ChecksRelease(work.store, work.checkouts, work.slot_files, work.entry_seen, landing, work.clock,
                            work.seen, work.scratch, ids=b.ports().ids)
    assert isinstance(release.release_candidate(pending.key, True, b.me), Released)
    row = b.rows()[0]
    assert row.validation_started_at is None and row.validated_at is None
    assert row.release_started_at == row.released_at == 20
    reopen(b)
    b.now = 30
    replacement = inserted(b.ports(), b.repo, checks, (2, b.base, b.x, True, REQUIRED), "same_tree", 0)
    assert not isinstance(replacement, Failed) and replacement.retry_cause is RetryCause.ABANDONED
    assert reopen(b).row(replacement.key) == replacement


def test_release_retry_preserves_first_start_after_delivery(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.advance({"OTHER": "another task\n"})
    pointer = b.slot.path / ".git"
    b.environment.process.script = [Command(), Command(), Command(effect=lambda: b.files.contents.update({pointer: b"gitdir: /x\n"}))]
    found = b.land()
    assert isinstance(found, Landed) and found.row.holds_slot
    assert found.row.release_started_at == 10 and found.row.released_at is None
    del b.files.contents[pointer]
    reopen(b)
    b.now = 20
    found = b.land()
    assert isinstance(found, Landed)
    assert found.row.release_started_at == 10 and found.row.released_at == 20


def test_no_change_has_instantaneous_bounds_and_no_release(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.advance({"src/x.py": "X = 1\n"})
    found = b.land(no_change=True)
    assert isinstance(found, Landed)
    row = found.row
    assert row.admitted_at == row.validation_started_at == row.validated_at == row.delivery_started_at == row.delivered_at == 10
    assert row.release_started_at is None and row.released_at is None


def test_observation_records_completion_without_inventing_starts(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.repo.answer = Transient("offline")
    assert isinstance(b.land(), Failed)
    row = b.rows()[0]
    b.con.execute("UPDATE land_candidate SET delivery_started_at=NULL")
    b.repo.worktree(b.repo.path).push("main", remote="origin", head=Sha(row.commit))
    assert reconcile_delivery(b.lands, Origin(b.repo, b.repo.path), b.rows()[0], 20)
    row = b.rows()[0]
    assert row.delivery_started_at is None and row.delivered_at == 20 and row.close_started_at is None
    b.lands.record_close(row.key, "already_closed", 30)
    assert b.rows()[0].close_started_at is None and b.rows()[0].closed_at == 30


def test_concurrent_close_completion_does_not_repeat_tracker_effect(tmp_path: Path) -> None:
    b = bench(tmp_path)
    found = b.land()
    assert isinstance(found, Landed)
    row = found.row
    before = tuple(b.tracker)
    assert closed(b.lands, b.close, lambda: 100, row) == row
    assert tuple(b.tracker) == before
