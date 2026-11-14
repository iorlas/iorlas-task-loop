"""One durable answer repair shares the original conversation and attempt fences."""

import json
import sqlite3
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from typing import Literal

import pytest
from any_agent.procs import Worker
from sqlite_store import Store
from test_attempt import ENTRY, KEY, PLAN, WORKER, AttemptSurroundings, app, fake, seed
from test_attempt import surroundings as attempt_surroundings
from test_recovery import Processes, recovery
from test_recovery_store import OWNER

from taskloop.admit import AdmitRefused, Admitted
from taskloop.admit_chain import ChainAdmission, RepeatRequest
from taskloop.answer_failures import AnswerRule
from taskloop.answer_repair import AnswerRepair
from taskloop.answer_repair_models import RepairContext, RepairOutcome
from taskloop.answer_repair_store import AnswerRepairStore, RepairResult
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission, AttemptKey, AttemptRecord, Evidence, ExecutionFacts, FileRef, Replaced, StoredExecution
from taskloop.drain.models import Seen
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.models import Outcome, Result
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import hold
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore

surroundings = attempt_surroundings


@pytest.fixture
def failed(surroundings: AttemptSurroundings) -> Generator[sqlite3.Connection]:
    con = Store(SCHEMA).open_rw(surroundings.tmp / "factory.db")
    assert con is not None
    seed(con, surroundings)
    con.execute("UPDATE attempt SET compaction_token_limit=12345")
    TaskContentStore.insert(con, KEY.attempt_id, TaskContentDigest(value="f" * 64))
    result = app(con, surroundings, fake("not json", refs=("saved",))).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.answer.failure is not None
    yield con
    con.close()


def operation(con: sqlite3.Connection, surroundings: AttemptSurroundings, processes: Processes | None = None) -> AnswerRepair:
    return AnswerRepair(AnswerRepairStore(lambda: con), EvidenceFiles(surroundings.tmp), processes or Processes(),
                        hold, lambda: 10, ids=NativeIds())


def successor(con: sqlite3.Connection, surroundings: AttemptSurroundings) -> AttemptKey:
    found = operation(con, surroundings).admit(KEY)
    assert found.outcome is RepairOutcome.ADMITTED and found.key is not None and found.explanation
    return found.key


def test_repair_retains_settings_claim_slot_deadline_work_and_evidence(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings,
) -> None:
    store = AttemptStore(lambda: failed)
    before = store.load(KEY)
    evidence = store.collect(KEY)
    assert before is not None and evidence is not None
    surroundings.slot.write_file("work.txt", "retained work")
    surroundings.slot.stage(("work.txt",))
    key = successor(failed, surroundings)
    assert store.register_entry(key, ENTRY, 25) == "accepted"
    after = store.load(key)
    assert after is not None and after.admission.repair is not None
    expected = replace(before.admission, key=key, input_ref=after.admission.input_ref, repair=after.admission.repair)
    assert after.admission == expected
    assert after.session_ref == "saved" and after.admission.deadline == 100
    assert after.admission.number == 1 and key.reservation_generation == 2
    assert TaskContentStore(lambda: failed).read(key.attempt_id) == TaskContentDigest(value="f" * 64)
    prompt = EvidenceFiles(surroundings.tmp).read(after.admission.input_ref)
    assert "json:" in prompt and evidence.answer.failure is not None and evidence.answer.failure.describe() in prompt
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store.load(KEY)
    run = fake(refs=("saved",))
    result = surroundings.attempts(store, run, clock=lambda: 25).execute(key, ENTRY)
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert len(run.calls) == 1
    _, spec, timeout, _ = run.calls[0]
    assert spec.argv[1:3] == ["exec", "resume"] and "saved" in spec.argv and "chosen" in spec.argv
    assert spec.cwd == str(surroundings.slot.path) and timeout == 75
    assert "json:" in (spec.stdin or "")
    assert surroundings.slot.read_file("work.txt") == "retained work"
    assert store.collect(KEY) == evidence
    assert len(store.chain(key)) == 1 and store.chain(key)[0].base_commit == before.base_commit
    assert operation(failed, surroundings).admit(key).outcome is RepairOutcome.REFUSED


def test_restart_and_lost_admission_acknowledgement_find_one_saved_successor(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repair = operation(failed, surroundings)
    admit = repair.store.admit

    def lost(expected: AttemptRecord, execution: StoredExecution, context: RepairContext,
             key: AttemptKey, ref: FileRef, now: float) -> RepairResult:
        admit(expected, execution, context, key, ref, now)
        raise StoreUnavailable("admission acknowledgement lost")

    monkeypatch.setattr(repair.store, "admit", lost)
    assert repair.admit(KEY).outcome is RepairOutcome.UNAVAILABLE
    reopened = Store(SCHEMA).open_rw(surroundings.tmp / "factory.db")
    assert reopened is not None
    try:
        saved = operation(reopened, surroundings).admit(KEY)
        assert saved.outcome is RepairOutcome.EXISTING and saved.key is not None
        assert operation(reopened, surroundings).admit(KEY) == saved
        assert reopened.execute("SELECT count(*) FROM attempt").fetchone() == (2,)
        assert reopened.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (saved.key.attempt_id, 2)
        run = fake(refs=("saved",))
        attempts = app(reopened, surroundings, run)
        assert attempts.store.register_entry(saved.key, ENTRY, 10) == "accepted"
        assert attempts.execute(saved.key, ENTRY).execution is not None
        assert attempts.execute(saved.key, ENTRY).execution is not None and len(run.calls) == 1
    finally:
        reopened.close()


def test_two_admitters_converge_on_one_successor(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    barrier = threading.Barrier(2)

    def contend() -> RepairResult:
        con = Store(SCHEMA).open_rw(surroundings.tmp / "factory.db")
        assert con is not None
        repair = operation(con, surroundings)

        @contextmanager
        def raced(admission: Admission) -> Generator[None]:
            barrier.wait(timeout=5)
            with hold(admission):
                yield

        repair.hold = raced
        try:
            return repair.admit(KEY)
        finally:
            con.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: contend(), range(2)))
    keys = {result.key for result in results if result.key is not None}
    assert len(keys) == 1
    assert {result.outcome for result in results} <= {RepairOutcome.ADMITTED, RepairOutcome.EXISTING, RepairOutcome.UNAVAILABLE}
    assert failed.execute("SELECT count(*) FROM attempt").fetchone() == (2,)
    assert operation(failed, surroundings).admit(KEY).key == next(iter(keys))


@pytest.mark.parametrize("change", [
    "UPDATE attempt SET deadline=10",
    "UPDATE attempt SET session_conflict=1",
    "UPDATE execution SET session_state='pending'",
    "UPDATE execution SET session='different'",
    "UPDATE reservation SET generation=2",
    "INSERT INTO task_hold(attempt_id,cause_id,reason,held_at) VALUES('attempt','cause','held',10)",
    "INSERT INTO drain_state VALUES(1,1,'draining')",
])
def test_ineligible_work_is_not_repaired(failed: sqlite3.Connection, surroundings: AttemptSurroundings, change: str) -> None:
    failed.execute(change)
    result = operation(failed, surroundings).admit(KEY)
    assert result.outcome is RepairOutcome.REFUSED and result.explanation
    assert failed.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


@pytest.mark.parametrize("pid", [ENTRY[0], WORKER.pid])
@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.UNKNOWN])
def test_process_absence_is_required(failed: sqlite3.Connection, surroundings: AttemptSurroundings, pid: int, seen: Seen) -> None:
    processes = Processes()
    processes.states[pid] = seen
    assert operation(failed, surroundings, processes).admit(KEY).outcome is RepairOutcome.REFUSED
    assert failed.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


def test_expiration_and_changes_after_process_observation_are_rechecked(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repair = operation(failed, surroundings)
    put = repair.files.put_input

    def changed(key: AttemptKey, text: str) -> FileRef:
        ref = put(key, text)
        failed.execute("UPDATE attempt SET rev=rev+1")
        return ref

    monkeypatch.setattr(repair.files, "put_input", changed)
    assert repair.admit(KEY).outcome is RepairOutcome.REFUSED
    monkeypatch.setattr(repair.files, "put_input", put)
    repair.clock = lambda: 100
    assert repair.admit(KEY).outcome is RepairOutcome.REFUSED
    assert failed.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


def test_registration_lost_acknowledgement_requires_reconciliation(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = successor(failed, surroundings)
    run = fake(refs=("saved",))
    attempts = app(failed, surroundings, run)
    assert attempts.store.register_entry(key, ENTRY, 10) == "accepted"
    register = attempts.store.register

    def lost(admission: Admission, worker: Worker) -> None:
        register(admission, worker)
        raise StoreUnavailable("registration acknowledgement lost")

    monkeypatch.setattr(attempts.store, "register", lost)
    assert attempts.execute(key, ENTRY).status == "unavailable"
    assert attempts.execute(key, ENTRY).reason == "registered" and len(run.calls) == 1
    processes = Processes()
    processes.states[WORKER.pid] = Seen.ALIVE
    continuation = Continuation(recovery(failed, processes), attempts, NativeContinuation(attempts, RecoveryStore(lambda: failed)))
    assert continuation(key, OWNER).explanation
    assert len(run.calls) == 1


def test_returned_execution_capture_retry_never_invokes_another_agent(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = successor(failed, surroundings)
    run = fake(refs=("saved",))
    attempts = app(failed, surroundings, run)
    assert attempts.store.register_entry(key, ENTRY, 10) == "accepted"

    def broken(_raw: object) -> None:
        raise RuntimeError("projection interrupted")

    with monkeypatch.context() as patch:
        patch.setattr("taskloop.attempt.execution_facts", broken)
        result = attempts.execute(key, ENTRY)
    assert result.pending is not None
    assert attempts.capture(result.pending).status == "accepted"
    saved = attempts.execute(key, ENTRY)
    assert saved.execution is not None and saved.execution.facts.session == "saved"
    assert saved.execution.facts.tokens == (8, None, 3) and len(run.calls) == 1


@pytest.mark.parametrize("context", ['{}', '{"session":"-unsafe","base_commit":"b","failure":{}}'])
def test_malformed_saved_context_cannot_launch(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, context: str,
) -> None:
    key = successor(failed, surroundings)
    store = AttemptStore(lambda: failed)
    assert store.register_entry(key, ENTRY, 10) == "accepted"
    failed.execute("UPDATE attempt SET repair_context=? WHERE attempt_id=?", (context, key.attempt_id))
    run = fake()
    assert app(failed, surroundings, run).execute(key, ENTRY).status == "unavailable" and not run.calls


def test_capture_lost_acknowledgement_reopens_and_collects_saved_facts(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = successor(failed, surroundings)
    run = fake(refs=("saved",))
    attempts = app(failed, surroundings, run)
    assert attempts.store.register_entry(key, ENTRY, 10) == "accepted"
    capture = attempts.store.capture

    def lost(admission: Admission, worker: Worker | None, facts: ExecutionFacts, evidence: Evidence,
             session_state: Literal["complete", "pending", "conflict", "fault"], callback: Callback | None = None) -> None:
        capture(admission, worker, facts, evidence, session_state, callback)
        raise StoreUnavailable("capture acknowledgement lost")

    with monkeypatch.context() as patch:
        patch.setattr(attempts.store, "capture", lost)
        result = attempts.execute(key, ENTRY)
    assert result.pending is not None and result.pending.facts is not None
    assert attempts.capture(result.pending).status == "already_same"
    reopened = Store(SCHEMA).open_rw(surroundings.tmp / "factory.db")
    assert reopened is not None
    try:
        result = app(reopened, surroundings, run).execute(key, ENTRY)
        collected = attempts.collect(key)
        assert result.execution is not None and collected.execution is not None
        assert result.execution.facts == collected.execution.facts
        assert len(run.calls) == 1
    finally:
        reopened.close()


def test_repair_restart_never_renews_the_original_deadline(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    key = successor(failed, surroundings)
    store = AttemptStore(lambda: failed)
    assert store.register_entry(key, ENTRY, 10) == "accepted"
    rebooted = (17, "new-entry", "new-boot")
    assert store.register_entry(key, rebooted, 25, Replaced(ENTRY, "gone"), renewed=1000) == "accepted"
    record = store.load(key)
    assert record is not None and record.admission.deadline == 100
    assert store.renew(failed, record, 2000) == record
    assert store.register_entry(key, (18, "later", "later-boot"), 100,
                                Replaced(rebooted, "gone"), renewed=2000) == "refused"
    run = fake(refs=("saved",))
    assert app(failed, surroundings, run).execute(key, rebooted).execution is not None
    failed.execute("DELETE FROM execution WHERE attempt_id=?", (key.attempt_id,))
    failed.execute("UPDATE attempt SET phase='registered' WHERE attempt_id=?", (key.attempt_id,))
    snapshot = RecoveryStore(lambda: failed).snapshot(key, 100, allow_expired=True)
    assert isinstance(snapshot, Result) and snapshot.outcome is Outcome.EXPIRED


def test_implement_repair_preserves_work_without_running_setup(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    store = AttemptStore(lambda: failed)
    record = store.load(KEY)
    assert record is not None
    failed.execute("UPDATE attempt SET step='implement',after_commit=?", (record.base_commit,))
    surroundings.slot.write_file("changed.py", "kept")
    key = successor(failed, surroundings)
    assert store.register_entry(key, ENTRY, 10) == "accepted"
    run = fake(json.dumps({"disposition": "unchanged", "paths": [], "message": None, "explanation": "done"}), refs=("saved",))
    result = app(failed, surroundings, run).execute(key, ENTRY)
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert surroundings.slot.read_file("changed.py") == "kept" and len(run.calls) == 1
    assert failed.execute("SELECT count(*) FROM setup_run").fetchone() == (0,)


def test_repairs_preserve_verification_repeat_numbers_and_cap(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    repair = operation(failed, surroundings)
    chain = ChainAdmission(repair.store.connect, repair.store.begin, repair.files, lambda: 10,
                           surroundings.checkouts, surroundings.files, ids=NativeIds())
    store, current = repair.store, KEY
    unchanged = json.dumps(PLAN | {"disposition": "unchanged", "paths": [], "message": None})
    for number in range(1, 4):
        admitted = repair.admit(current)
        assert admitted.outcome is RepairOutcome.ADMITTED and admitted.key is not None
        key = admitted.key
        assert store.register_entry(key, ENTRY, 10) == "accepted"
        assert app(failed, surroundings, fake(unchanged, refs=("saved",))).execute(key, ENTRY).execution is not None
        assert store.chain(key)[-1].number == number
        assert [link.number for link in store.chain(key)] == list(range(1, number + 1))
        request = RepeatRequest(key, "Repeat verification feedback", 100, "uncommitted",
                                content_digest=TaskContentDigest(value="f" * 64))
        repeated = chain.admit_repeat(request)
        if number == 3:
            assert isinstance(repeated, AdmitRefused) and repeated.reason == "repeat_cap"
        else:
            assert isinstance(repeated, Admitted)
            current = repeated.key
            assert store.register_entry(current, ENTRY, 10) == "accepted"
            assert app(failed, surroundings, fake("not json", refs=("saved",))).execute(current, ENTRY).execution is not None


def test_invalid_repair_cannot_admit_a_third_invocation(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    key = successor(failed, surroundings)
    run = fake('{"bad":true}', refs=("saved",))
    attempts = app(failed, surroundings, run)
    assert attempts.store.register_entry(key, ENTRY, 10) == "accepted"
    result = attempts.execute(key, ENTRY)
    assert result.execution is not None and result.execution.answer.failure is not None
    assert result.execution.answer.failure.rule is AnswerRule.SHAPE
    repair = operation(failed, surroundings)
    refused = repair.admit(key)
    assert refused.outcome is RepairOutcome.REFUSED and "cannot itself" in refused.explanation
    assert repair.admit(KEY).key == key
    assert failed.execute("SELECT count(*) FROM attempt").fetchone() == (2,) and len(run.calls) == 1
