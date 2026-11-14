"""Old hooks and pending results cannot acquire a replacement execution's authority."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from test_attempt import PLAN, AttemptSurroundings
from test_attempt import WORKER as UNUSED_WORKER
from test_attempt import surroundings as attempt_surroundings
from test_recovery_registration import WORKER, intended
from test_recovery_store import KEY, database, facts

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AnswerState, PendingResult, SessionInput, execution_facts
from taskloop.recovery.callbacks import Callbacks
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.models import Intent, Outcome
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore
from taskloop.session import SessionLatch

surroundings = attempt_surroundings


def registered(store: RecoveryStore, intent: Intent, worker: Worker) -> Callback:
    identity = WORKER.model_copy(update={"pid": worker.pid, "pgid": worker.pgid, "start": worker.start, "boot": worker.boot})
    result = store.register(intent, identity, lambda: 10)
    assert result.intent is not None
    return callback(result.intent)


def raw(worker: Worker) -> RunOutcome:
    return RunOutcome(rc=0, worker=worker, summary=Summary(text=json.dumps(PLAN), res={"ref": "saved"}))


def test_stale_hooks_results_answers_and_pending_retries_preserve_current_rows(
    tmp_path: Path, surroundings: AttemptSurroundings,
) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    attempts = AttemptStore(lambda: con)
    app = surroundings.attempts(attempts, FakeRun(RunOutcome(worker=UNUSED_WORKER)))
    record = attempts.load(KEY)
    assert record is not None and record.worker is not None
    admission = record.admission
    ordinary = SessionLatch(attempts, admission)
    ordinary_pending = PendingResult(admission, raw(record.worker), None, SessionInput("other"))
    first = intended(store, "first")
    first_worker = Worker(pid=80, pgid=81, start="first", boot="boot")
    old = Callbacks(app, admission, registered(store, first, first_worker))
    pending = old.returned(raw(first_worker))
    second = intended(store, "second")
    second_worker = Worker(pid=90, pgid=91, start="second", boot="boot")
    current = Callbacks(app, admission, registered(store, second, second_worker))

    for captured in (False, True):
        if captured:
            assert current.capture(current.returned(raw(second_worker))).status == "accepted"
        before = facts(con)
        ordinary.observe("other")
        old.sessions.observe("other")
        assert old.capture(pending).status == "conflict"
        assert app.capture(ordinary_pending).status == "conflict"
        evidence = app.files.capture(KEY, raw(first_worker), old.identity)
        with pytest.raises(StoreRefused):
            attempts.answer(admission, evidence, AnswerState("missing"), old.identity)
        assert facts(con) == before
    assert con.execute("SELECT session_ref,session_conflict FROM attempt").fetchone() == ("saved", 0)
    con.close()


def test_current_retries_session_conflict_and_full_worker_fence(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    attempts = AttemptStore(lambda: con)
    app = surroundings.attempts(attempts, FakeRun(RunOutcome(worker=UNUSED_WORKER)))
    record = attempts.load(KEY)
    assert record is not None
    worker = Worker(pid=80, pgid=81, start="first", boot="boot")
    current = Callbacks(app, record.admission, registered(store, intended(store), worker))
    assert current.observe("saved").outcome is Outcome.ACCEPTED
    pending = current.returned(raw(worker))
    before = facts(con)
    wrong_worker = Worker(pid=80, pgid=999, start="first", boot="boot")
    assert current.capture(current.returned(raw(wrong_worker))).status == "conflict"
    assert facts(con) == before
    assert current.capture(pending).status == "accepted"
    assert current.capture(pending).status == "already_same"
    stored = attempts.collect(KEY)
    assert stored is not None and stored.answer.kind == "valid"
    assert attempts.answer(record.admission, stored.evidence, stored.answer, current.identity) == "already_same"
    foreign = app.files.capture(KEY, raw(worker))
    mismatched = replace(pending, result=replace(pending.result, evidence=foreign))
    assert current.capture(mismatched).reason == "evidence"
    wrong = current.identity.model_copy(update={"worker": WORKER.model_copy(update={"pgid": 999})})
    before = facts(con)
    with pytest.raises(StoreRefused):
        attempts.session(record.admission, "other", wrong)
    assert facts(con) == before
    reported = current.observe("different")
    assert reported.outcome is Outcome.CONFLICT and reported.explanation
    assert con.execute("SELECT session_ref,session_conflict FROM attempt").fetchone() == ("saved", 1)
    conflicted = attempts.collect(KEY)
    assert conflicted is not None and conflicted.session_state == "conflict"
    con.close()


def test_unavailable_capture_retries_and_reopen_finishes_without_agent(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    down = False
    attempts = AttemptStore(lambda: None if down else con)
    app = surroundings.attempts(attempts, FakeRun(RunOutcome(worker=UNUSED_WORKER)))
    record = attempts.load(KEY)
    assert record is not None
    store = RecoveryStore(lambda: con)
    worker = Worker(pid=80, pgid=81, start="first", boot="boot")
    identity = registered(store, intended(store), worker)
    current = Callbacks(app, record.admission, identity)
    current.sessions.observe("saved")
    pending = current.returned(raw(worker))
    down = True
    assert current.capture(pending).status == "unavailable"
    down = False
    # Persist the returned execution but leave decoding to trusted completion after restart.
    evidence = app.files.capture(KEY, pending.result.raw, identity)
    assert attempts.capture(record.admission, worker, execution_facts(pending.result.raw), evidence, "pending", identity) == "accepted"
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    execution = FakeRun(RunOutcome(worker=UNUSED_WORKER))
    reopened = surroundings.attempts(AttemptStore(lambda: con), execution)
    completed = reopened.execute(KEY, record.admission.entry)
    assert completed.execution is not None and completed.execution.answer.kind == "valid"
    assert execution.calls == [] and reopened.store.callback(KEY) == identity
    con.close()
