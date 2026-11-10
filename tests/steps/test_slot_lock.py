"""Slot custody: the per-slot `flock` beside the slots, taken at once or refused. The other holder is the conftest's
`occupy`: a second open file description holding the lock, as another process would. Real SQLite, the semantic Git fake
and the owning agent fake."""

import json
import os
import sqlite3
from collections.abc import Callable, Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import NoReturn

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain.testing import FakeWorktree

from taskloop import verifier as verifier_module
from taskloop.admit import AdmitRefused, Admitted, AdmitUnavailable, RepeatRequest
from taskloop.attempt import Attempts, Execution
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    Admission,
    AnswerState,
    AttemptKey,
    Checkouts,
    SlotFiles,
    Unsettled,
    Verified,
    VerifyUnavailable,
    WorkerGone,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_commit import Quiet, Settled
from taskloop.operations import Failed
from taskloop.repeat import StepRepeat
from taskloop.slot_lock import LABEL, acquire, hold, lock_path, refused, repeating
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}


type Occupy = Callable[[Path], AbstractContextManager[None]]


def agent(slot: FakeWorktree, files: dict[str, str]) -> Execution:
    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        for path, text in files.items():
            slot.write_file(path, text)
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return call


def captured(
    con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, files: SlotFiles, written: dict[str, str]
) -> None:
    attempts = Attempts(AttemptStore(lambda: con), EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), agent(slot, written), lambda: 10,
                            checkouts, files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"


def verifier(con: sqlite3.Connection, checkouts: Checkouts, files: SlotFiles, gone: WorkerGone = lambda _worker: True) -> Verifier:
    return Verifier(AttemptStore(lambda: con), checkouts, files, gone, lambda: 20, hold)


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every factory Git write on a slot (`stage`, `record`), counted."""
    found: list[str] = []
    stage, record = FakeWorktree.stage, FakeWorktree.record

    def staging(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        found.append("stage")
        stage(self, paths, literal=literal)

    def recording(self: FakeWorktree, message: str, **options: object) -> object:
        found.append("record")
        return record(self, message, paths="staged", hooks=False)

    monkeypatch.setattr(FakeWorktree, "stage", staging)
    monkeypatch.setattr(FakeWorktree, "record", recording)
    return found


def test_a_held_slot_refuses_verify_before_any_git_write_and_then_it_settles(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str],
    occupy: Occupy,
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    with occupy(lock_path(str(slot.path))):
        assert verifier(registered, checkouts, slot_files).verify(KEY) == VerifyUnavailable("slot_busy")
    assert writes == [] and registered.execute("SELECT count(*) FROM plan_verification").fetchone() == (0,)
    found = verifier(registered, checkouts, slot_files).verify(KEY)
    assert isinstance(found, Verified) and writes == ["stage", "record"]
    with occupy(lock_path(str(slot.path))):  # a stored verdict reads no Git and takes no lock
        assert verifier(registered, checkouts, slot_files).verify(KEY) == found


def test_the_lock_is_released_after_a_verify_and_a_live_worker_is_still_alive(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str]
) -> None:
    """A free lock is never a stop proof: the worker gate still refuses the Git write."""
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    assert verifier(registered, checkouts, slot_files, lambda _worker: False).verify(KEY) == Unsettled("worker_alive")
    assert writes == []
    acquire(str(slot.path), "probe", "verify").release()  # free again


def test_the_holder_record_names_the_attempt_and_the_role_only(slot: FakeWorktree) -> None:
    lock = acquire(str(slot.path), "attempt", "entry")
    try:
        assert not lock_path(str(slot.path)).is_relative_to(slot.path)  # outside the agent's writable slot
        record = json.loads(lock_path(str(slot.path)).read_text())
        assert set(record) == {"pid", "created", "label", "meta"}
        assert record["pid"] == os.getpid() and record["label"] == LABEL and record["meta"] == {"attempt": "attempt", "role": "entry"}
    finally:
        lock.release()


def test_an_uncreatable_lock_file_is_unavailable_lock(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str]
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    lock_path(str(slot.path)).parent.parent.mkdir(parents=True, exist_ok=True)
    lock_path(str(slot.path)).parent.write_text("not a folder")
    assert verifier(registered, checkouts, slot_files).verify(KEY) == VerifyUnavailable("lock") and writes == []


class Admits:
    def __init__(self) -> None:
        self.calls: list[RepeatRequest] = []

    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        self.calls.append(request)
        return AdmitRefused("not_repeatable")


class NoLaunch:
    def launch(self, backlog: str, task_id: str, minutes: int) -> NoReturn:
        raise AssertionError(f"nothing launches for {backlog}/{task_id}")


def test_a_repeat_whose_verify_finds_the_slot_held_admits_nothing(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str],
    occupy: Occupy,
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n", "stray.txt": "s"})
    store, admits = AttemptStore(lambda: registered), Admits()
    repeat = StepRepeat(
        store, verifier(registered, checkouts, slot_files), EvidenceFiles(tmp_path), admits, NoLaunch(), lambda _worker: True,
        lambda _entry: "gone", lambda: 10, repeating,
    )
    with occupy(lock_path(str(slot.path))):
        found = repeat.repeat("tasks", "tl-1", KEY, None, 30)
    assert found == Failed("unavailable", "slot_busy") and admits.calls == [] and writes == []


def test_a_read_only_verifier_asked_to_write_is_its_own_unknown(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str]
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    found = Verifier(AttemptStore(lambda: registered), checkouts, slot_files, lambda _worker: True, lambda: 20, refused).verify(KEY)
    assert found == VerifyUnavailable("read_only") and writes == []


def test_a_verify_reads_the_attempt_again_under_the_lock(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, writes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another verifier settles between this one's first read and its lock: this one returns that stored verdict with
    no Git step of its own (one `settle` in all), never acting on what it read before the lock."""
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    other: list[object] = []
    settled: list[str] = []
    real = verifier_module.settle

    def settle(checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str, answer: AnswerState, quiet: Quiet) -> Settled:
        settled.append(admission.key.attempt_id)
        return real(checkouts, files, admission, base, answer, quiet)

    monkeypatch.setattr(verifier_module, "settle", settle)

    @contextmanager
    def late(admission: Admission) -> Generator[None]:
        other.append(verifier(registered, checkouts, slot_files).verify(admission.key))
        with hold(admission):
            yield

    found = Verifier(AttemptStore(lambda: registered), checkouts, slot_files, lambda _worker: True, lambda: 20, late).verify(KEY)
    assert isinstance(found, Verified) and other == [found] and writes == ["stage", "record"] and settled == ["attempt"]
