"""Durable atomic admission and reciprocal exclusion on file-backed SQLite."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import ORIGIN, REQUIRED, SQUASH, D
from git_porcelain import WorktreeInfo
from git_porcelain.testing import FakeRepo
from land_conflict_bench import Bench, bench, copy_row
from sqlite_store import Store, begin_immediate

from taskloop.admit_rows import reserve
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, FileRef
from taskloop.factory_schema import SCHEMA
from taskloop.land_conflict.admit import admit
from taskloop.land_conflict.models import Outcome, Record, Request
from taskloop.land_conflict.store import ConflictStore
from taskloop.land_store import LandAdmitted, Settled, insert
from taskloop.repo import RepoId


def candidate(b: Bench, validation: Settled | None = "same_tree") -> LandAdmitted:
    return LandAdmitted(AttemptKey("candidate", "candidate-token", 1), "checks", 1, ORIGIN, SQUASH, True, REQUIRED,
                        "s2" if validation is None else None, D if validation is None else None,
                        300 if validation is None else None, validation, 10)


def test_repetition_and_reopening_keep_original_admission(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    base = next(info.head for info in repo.worktrees() if not info.is_main)
    first = admit(b.ports, b.request)
    assert first.outcome is Outcome.ADMITTED and first.record is not None and first.explanation
    assert first.record.inputs.key == b.request.source and first.record.request.checks == b.request.checks
    assert first.record.base == base
    b.artifact.unlink()
    b.con.execute("UPDATE attempt SET model='changed'")
    b.con.close()
    con = Store(SCHEMA).open_rw(on_slot)
    assert con is not None
    ports = replace(b.ports, store=ConflictStore(lambda: con), probe=lambda _: pytest.fail("repetition probed a slot"))
    repeated = admit(ports, b.request.model_copy(update={"target": "f" * 40, "deadline": 900}))
    assert repeated.outcome is Outcome.RETAINED and repeated.record == first.record and repeated.explanation
    assert con.execute("SELECT count(*) FROM land_conflict").fetchone() == (1,)
    assert con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        first.record.key.attempt_id, first.record.key.reservation_generation)
    con.close()


def test_competing_connections_adopt_the_winner_after_observation(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    other = Store(SCHEMA).open_rw(on_slot)
    assert other is not None
    competing = replace(b.ports, store=ConflictStore(lambda: other))
    winners = []

    def probe(_: str) -> bool:
        assert not b.con.in_transaction and not other.in_transaction
        winners.append(admit(competing, b.request))
        return True

    # The winner takes the only slot while the first caller is observing it.
    result = admit(replace(b.ports, probe=probe), b.request)
    assert winners[0].outcome is Outcome.ADMITTED
    assert result.outcome is Outcome.RETAINED and result.record == winners[0].record
    adopted = admit(b.ports, b.request)
    assert adopted.record == winners[0].record
    assert b.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    other.close()
    b.con.close()


@pytest.mark.parametrize("change", ["generation", "path", "reserved", "locked", "dirty"])
def test_observation_races_never_overwrite_slot_identity(on_slot: Path, repo: FakeRepo, tmp_path: Path, change: str) -> None:
    b = bench(on_slot, repo, tmp_path)

    def probe(_: str) -> bool:
        assert not b.con.in_transaction
        if change == "generation":
            b.con.execute("UPDATE slot SET generation=20 WHERE name='s1'")
        elif change == "path":
            b.con.execute("UPDATE slot SET path='/different/s1' WHERE name='s1'")
        elif change == "reserved":
            b.con.execute("INSERT INTO reservation VALUES ('s1',?,20,'competitor')", (b.request.repo_id,))
        return change != "locked"

    if change == "dirty":
        repo.worktree(next(info.path for info in repo.worktrees() if not info.is_main)).write_file("dirty", "work")
    result = admit(replace(b.ports, probe=probe), b.request)
    assert result.outcome is Outcome.NO_SLOT and result.explanation
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    if change == "reserved":
        assert b.con.execute("SELECT attempt_id FROM reservation").fetchall() == [("competitor",)]
    b.con.close()


def test_record_failure_rolls_back_reservation_and_generation(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    before = b.con.execute("SELECT * FROM slot").fetchall()
    b.con.execute("CREATE TRIGGER fail_conflict BEFORE INSERT ON land_conflict BEGIN SELECT RAISE(ABORT,'injected'); END")
    result = admit(b.ports, b.request)
    assert result.outcome is Outcome.UNAVAILABLE and result.explanation
    assert b.con.execute("SELECT * FROM reservation").fetchall() == []
    assert b.con.execute("SELECT * FROM slot").fetchall() == before
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    b.con.close()


@pytest.mark.parametrize("change,outcome", [
    ("UPDATE checks_attempt SET released_at=NULL,parked=NULL", Outcome.NOT_CHECKED),
    ("UPDATE checks_attempt SET abandoned=1", Outcome.NOT_CHECKED),
    ("UPDATE checks_attempt SET conclusion='failed',reason='failed'", Outcome.NOT_CHECKED),
    ("UPDATE slot_release SET claim='unclaimed'", Outcome.NOT_DONE),
    ("UPDATE checks_attempt SET dispatch_token='changed'", Outcome.SOURCE),
    ("UPDATE attempt SET end_commit='ffffffffffffffffffffffffffffffffffffffff'", Outcome.SOURCE),
])
def test_ineligible_source_has_no_admission_effect(on_slot: Path, repo: FakeRepo, tmp_path: Path,
                                                 change: str, outcome: Outcome) -> None:
    b = bench(on_slot, repo, tmp_path)
    b.con.execute(change)
    result = admit(b.ports, b.request)
    assert result.outcome is outcome and result.explanation
    assert b.con.execute("SELECT * FROM reservation").fetchall() == []
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    b.con.close()


@pytest.mark.parametrize("validation", ["same_tree", "no_change", None])
def test_candidate_first_excludes_conflict(on_slot: Path, repo: FakeRepo, tmp_path: Path, validation: Settled | None) -> None:
    b = bench(on_slot, repo, tmp_path)
    with begin_immediate(b.con):
        if validation is None:
            b.con.execute("INSERT INTO slot VALUES (?,'s2','/slots/s2',0)", (b.request.repo_id,))
            reserve(b.con, RepoId(b.request.repo_id), "s2", candidate(b, validation).key)
        insert(b.con, candidate(b, validation))
    result = admit(b.ports, b.request)
    assert result.outcome is Outcome.LANDING and result.explanation
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    b.con.close()


@pytest.mark.parametrize("validation", ["same_tree", "no_change", None])
def test_conflict_first_excludes_candidate_and_rolls_back_its_reservation(
    on_slot: Path, repo: FakeRepo, tmp_path: Path, validation: Settled | None,
) -> None:
    b = bench(on_slot, repo, tmp_path)
    assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
    b.con.execute("INSERT INTO slot VALUES (?,'s2','/slots/s2',0)", (b.request.repo_id,))
    before = b.con.execute("SELECT * FROM reservation").fetchall()
    with pytest.raises(StoreRefused, match="landing"), begin_immediate(b.con):
        if validation is None:
            reserve(b.con, RepoId(b.request.repo_id), "s2", candidate(b, validation).key)
        insert(b.con, candidate(b, validation))
    assert b.con.execute("SELECT * FROM reservation").fetchall() == before
    assert b.con.execute("SELECT generation FROM slot WHERE name='s2'").fetchone() == (0,)
    assert b.con.execute("SELECT * FROM land_candidate").fetchall() == []
    b.con.close()


def test_a_released_conflict_reservation_does_not_exclude_candidate(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
    b.con.execute("DELETE FROM reservation")
    with begin_immediate(b.con):
        insert(b.con, candidate(b))
    assert b.con.execute("SELECT count(*) FROM land_candidate").fetchone() == (1,)
    b.con.close()


@pytest.mark.parametrize("earlier_candidate", [False, True])
def test_later_checks_cannot_hide_an_earlier_candidate(on_slot: Path, repo: FakeRepo, tmp_path: Path,
                                                     earlier_candidate: bool) -> None:
    b = bench(on_slot, repo, tmp_path)
    if earlier_candidate:
        with begin_immediate(b.con):
            insert(b.con, candidate(b))
    key = AttemptKey("checks2", "checks2-token", 1)
    copy_row(b.con, "checks_attempt", "checks", {"attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "number": 2})
    request = b.request.model_copy(update={"checks": key}) if earlier_candidate else b.request
    result = admit(b.ports, request)
    assert result.outcome is (Outcome.LANDING if earlier_candidate else Outcome.NOT_CHECKED)
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    b.con.close()


@pytest.mark.parametrize("same_task", [False, True])
def test_other_sources_cannot_take_the_reservation_and_later_attempts_fence_the_source(
    on_slot: Path, repo: FakeRepo, tmp_path: Path, same_task: bool,
) -> None:
    b = bench(on_slot, repo, tmp_path)
    if not same_task:
        assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
    copy_row(b.con, "attempt", "implement", {"attempt_id": "other", "dispatch_token": "other-token", "seq": 3,
                                           "task_id": "tl-1" if same_task else "tl-2"})
    if same_task:
        assert admit(b.ports, b.request).outcome is Outcome.NOT_DONE
    else:
        copy_row(b.con, "slot_release", "implement", {"attempt_id": "other", "dispatch_token": "other-token"})
        copy_row(b.con, "checks_attempt", "checks", {"attempt_id": "other-checks", "dispatch_token": "other-checks-token",
                                                    "after_attempt_id": "other"})
        request = b.request.model_copy(update={"source": AttemptKey("other", "other-token", 1), "task_id": "tl-2",
                                               "checks": AttemptKey("other-checks", "other-checks-token", 1)})
        assert admit(b.ports, request).outcome is Outcome.NO_SLOT
        assert b.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    b.con.close()


@pytest.mark.parametrize("column,value", [("operation_id", "wrong"), ("dispatch_token", "wrong"), ("generation", 100),
                                        ("implement_id", "missing"), ("repo_id", "other"), ("slot", "missing")])
def test_schema_rejects_inconsistent_admission_identity(on_slot: Path, repo: FakeRepo, tmp_path: Path,
                                                      column: str, value: str | int) -> None:
    b = bench(on_slot, repo, tmp_path)
    assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
    with pytest.raises(sqlite3.IntegrityError):
        b.con.execute(f"UPDATE land_conflict SET {column}=?", (value,))
    assert b.con.execute("SELECT count(*) FROM land_conflict").fetchone() == (1,)
    b.con.close()


def test_database_failure_after_slot_observation_is_unavailable(
    on_slot: Path, repo: FakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = bench(on_slot, repo, tmp_path)
    original = b.ports.store.find
    reads = []

    def find(request: Request) -> Record | None:
        if reads:
            raise StoreUnavailable("injected unreadable state")
        reads.append(request)
        return original(request)

    monkeypatch.setattr(b.ports.store, "find", find)
    result = admit(replace(b.ports, probe=lambda _: False), b.request)
    assert result.outcome is Outcome.UNAVAILABLE and result.explanation
    assert b.con.execute("SELECT * FROM reservation").fetchall() == []
    b.con.close()


def test_all_external_observations_precede_the_write_transaction(
    on_slot: Path, repo: FakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = bench(on_slot, repo, tmp_path)
    original_read, original_worktrees = b.ports.files.read, repo.worktrees
    calls = []

    def read(ref: FileRef) -> str:
        assert not b.con.in_transaction
        calls.append("artifact")
        return original_read(ref)

    def worktrees() -> tuple[WorktreeInfo, ...]:
        assert not b.con.in_transaction
        calls.append("git")
        return original_worktrees()

    def clock() -> float:
        assert not b.con.in_transaction
        calls.append("clock")
        return 10

    monkeypatch.setattr(b.ports.files, "read", read)
    monkeypatch.setattr(repo, "worktrees", worktrees)
    assert admit(replace(b.ports, clock=clock), b.request).outcome is Outcome.ADMITTED
    assert {"artifact", "git", "clock"} <= set(calls)
    b.con.close()


@pytest.mark.parametrize("conflict_first", [False, True])
def test_reciprocal_exclusion_uses_actual_reservation_generation(
    on_slot: Path, repo: FakeRepo, tmp_path: Path, conflict_first: bool,
) -> None:
    b = bench(on_slot, repo, tmp_path)
    if conflict_first:
        assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
        b.con.execute("UPDATE reservation SET generation=generation+1")
        with begin_immediate(b.con):
            insert(b.con, candidate(b))
    else:
        b.con.execute("INSERT INTO slot VALUES (?,'s2','/slots/s2',0)", (b.request.repo_id,))
        with begin_immediate(b.con):
            reserve(b.con, RepoId(b.request.repo_id), "s2", candidate(b, None).key)
            insert(b.con, candidate(b, None))
        b.con.execute("UPDATE reservation SET generation=generation+1")
        assert admit(b.ports, b.request).outcome is Outcome.ADMITTED
    b.con.close()
