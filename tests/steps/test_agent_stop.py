"""Stop callbacks with real SQLite: committed intent precedes action, identity fences, proof and read-only recovery."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from any_agent import StopIntent
from any_agent.procs import StopReport, Worker
from any_agent.procs import Survivor as ProcessSurvivor
from pydantic import ValidationError
from sqlite_store import Store

from taskloop.agents.stop import AgentStops, reconcile
from taskloop.agents.stop_models import StopCause, StopPhase, decode, encode
from taskloop.agents.stop_store import StopStore
from taskloop.agents.stop_text import stop_text
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission, AttemptKey
from taskloop.factory_schema import SCHEMA

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="agent-start", boot="boot")


def running(con: sqlite3.Connection) -> Admission:
    attempts = AttemptStore(lambda: con)
    record = attempts.load(KEY)
    assert record is not None
    assert attempts.dispatch(record, "b" * 40) == "accepted"
    assert attempts.register(record.admission, WORKER) == "accepted"
    return record.admission


@pytest.mark.parametrize(("reason", "cause"), [
    ("timeout", StopCause.DEADLINE), ("hung:first_event", StopCause.FIRST_OUTPUT), ("hung:silence", StopCause.INACTIVITY),
    ("hung:stall", StopCause.STALLED),
    ("stall", StopCause.STALLED), ("answer", StopCause.ANSWER), ("secret", StopCause.POLICY),
    ("limit", StopCause.LIMIT), ("credit", StopCause.CREDIT), ("logged_out", StopCause.AUTHENTICATION),
    ("network", StopCause.NETWORK), ("watchdog", StopCause.WATCHDOG), ("entry_signal", StopCause.ENTRY_SIGNAL),
    ("interrupt", StopCause.INTERRUPT), ("parent_gone", StopCause.PARENT_LOST), ("caller", StopCause.CALLER_EXIT),
])
def test_callbacks_commit_before_action_and_preserve_each_initiator(
    registered: sqlite3.Connection, reason: str, cause: StopCause,
) -> None:
    admission = running(registered)
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, admission, lambda: 11)
    intent = StopIntent(worker=WORKER, reason=reason)
    callbacks.before(intent)
    record = store.get(KEY.attempt_id)
    assert record is not None and record.cause == cause and record.phase == StopPhase.REQUESTED
    assert record.agent.pid == WORKER.pid and record.entry.pid == ENTRY[0]
    assert not registered.in_transaction  # the supervisor's action runs only after this callback returns
    callbacks.after(intent, StopReport(term_sent=True, term_delivered=True, kill_sent=True, kill_delivered=True))
    completed = store.get(KEY.attempt_id)
    assert completed is not None and completed.cause == cause and completed.phase == StopPhase.REPORTED
    assert decode(encode(completed)) == completed
    text = stop_text(completed, -9)
    assert text is not None and "because" in text and "SIGTERM" in text and "escalated to SIGKILL" in text
    assert not registered.in_transaction


@pytest.mark.parametrize("trigger", [1, 2, 15])
def test_entry_signal_is_separate_from_the_signal_requested_for_its_agent(registered: sqlite3.Connection, trigger: int) -> None:
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, running(registered), lambda: 12)
    intent = StopIntent(worker=WORKER, reason="interrupt" if trigger == 2 else "entry_signal", trigger_signal=trigger)
    callbacks.before(intent)
    callbacks.after(intent, StopReport(term_sent=True, term_delivered=True))
    record = store.get(KEY.attempt_id)
    assert record is not None and record.requested_signal == 15 and record.trigger_signal == trigger
    text = stop_text(record)
    assert text is not None and "sender of the entry signal is unknown" in text
    assert {1: "SIGHUP", 2: "SIGINT", 15: "SIGTERM"}[trigger] in text and "factory sent SIGTERM" in text


@pytest.mark.parametrize("sent,delivered,error", [(False, False, True), (True, False, False), (True, False, True), (True, True, False)])
def test_actual_signal_flags_are_copied_without_inference_from_grace(
    registered: sqlite3.Connection, sent: bool, delivered: bool, error: bool,
) -> None:
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, running(registered), lambda: 12)
    intent = StopIntent(worker=WORKER, reason="timeout")
    callbacks.before(intent)
    callbacks.after(intent, StopReport(term_sent=sent, term_delivered=delivered, waited_s=1000, error=error,
                                      survivors=[ProcessSurvivor(pid=43, start="child-start")]))
    record = store.get(KEY.attempt_id)
    assert record is not None and record.proof is not None
    assert (record.proof.term_attempted, record.proof.term_delivered, record.proof.error) == (sent, delivered, error)
    assert not record.proof.kill_attempted and not record.proof.kill_delivered
    assert record.proof.survivors[0].pid == 43
    text = stop_text(record)
    assert text is not None and ("factory sent" in text) == delivered
    assert "whole process tree ended" in text


@pytest.mark.parametrize("changed", ["entry_start", "entry_boot", "worker_pid", "worker_pgid", "worker_start", "worker_boot", "generation"])
def test_stale_generation_and_reused_process_identities_refuse_before_action(registered: sqlite3.Connection, changed: str) -> None:
    admission = running(registered)
    callbacks = AgentStops(StopStore(lambda: registered), admission, lambda: 12)
    value: str | int = 99 if changed in ("worker_pid", "worker_pgid", "generation") else "different"
    registered.execute(f"UPDATE attempt SET {changed}=?", (value,))
    with pytest.raises(StoreRefused):
        callbacks.before(StopIntent(worker=WORKER, reason="timeout"))
    assert callbacks.intent is None and callbacks.store.get(KEY.attempt_id) is None


def test_first_cause_survives_duplicate_and_competing_callbacks(registered: sqlite3.Connection) -> None:
    admission = running(registered)
    store = StopStore(lambda: registered)
    first, second = AgentStops(store, admission, lambda: 12), AgentStops(store, admission, lambda: 13)
    deadline = StopIntent(worker=WORKER, reason="timeout")
    first.before(deadline)
    first.before(deadline)  # idempotent persistence, no factory action is replayed
    with pytest.raises(StoreRefused, match="changed"):
        second.before(StopIntent(worker=WORKER, reason="caller"))
    report = StopReport(term_sent=True, term_delivered=True)
    first.after(deadline, report)
    first.after(deadline, report)
    record = store.get(KEY.attempt_id)
    assert record is not None and record.cause == StopCause.DEADLINE and record.requested_at == 12


def test_failed_intent_or_report_surfaces_storage_failure_and_preserves_custody(registered: sqlite3.Connection) -> None:
    admission = running(registered)
    available = True
    callbacks = AgentStops(StopStore(lambda: registered if available else None), admission, lambda: 12)
    intent = StopIntent(worker=WORKER, reason="timeout")
    available = False
    with pytest.raises(StoreUnavailable):
        callbacks.before(intent)
    assert callbacks.intent is None
    available = True
    callbacks.before(intent)
    available = False
    with pytest.raises(StoreUnavailable):
        callbacks.after(intent, StopReport(term_sent=True, term_delivered=True))
    available = True
    record = callbacks.store.get(KEY.attempt_id)
    assert record is not None and record.proof is None
    assert registered.execute("SELECT attempt_id FROM reservation").fetchall() == [(KEY.attempt_id,)]


def test_busy_write_never_acknowledges_an_intent(admitted: Path) -> None:
    store = Store(SCHEMA)
    con = store.open_rw(admitted)
    assert con is not None
    attempts = AttemptStore(lambda: con)
    assert attempts.register_entry(KEY, ENTRY, 10) == "accepted"
    admission = running(con)
    other = store.open_rw(admitted)
    assert other is not None
    con.execute("PRAGMA busy_timeout=1")
    try:
        other.execute("BEGIN IMMEDIATE")
        callbacks = AgentStops(StopStore(lambda: con), admission, lambda: 12)
        with pytest.raises(StoreUnavailable):
            callbacks.before(StopIntent(worker=WORKER, reason="timeout"))
        assert callbacks.intent is None
    finally:
        other.rollback()
        other.close()
        con.close()


@pytest.mark.parametrize("gone", [False, True])
def test_reconciliation_adopts_only_observed_completion_and_never_sends_a_signal(registered: sqlite3.Connection, gone: bool) -> None:
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, running(registered), lambda: 12)
    callbacks.before(StopIntent(worker=WORKER, reason="entry_signal", trigger_signal=15))
    seen: list[Worker] = []

    def observe(worker: Worker) -> bool:
        assert not registered.in_transaction
        seen.append(worker)
        return gone

    reconcile(store, KEY, observe, 13)
    reconcile(store, KEY, observe, 14)
    record = store.get(KEY.attempt_id)
    assert record is not None and record.phase == (StopPhase.OBSERVED_GONE if gone else StopPhase.REQUESTED)
    assert record.proof is None and seen == [WORKER, WORKER]
    assert registered.execute("SELECT attempt_id FROM reservation").fetchall() == [(KEY.attempt_id,)]
    text = stop_text(record)
    assert text is not None and "requested" in text and "No signal delivery was confirmed" in text


def test_report_cannot_change_target_or_claim_delivery_without_an_attempt(registered: sqlite3.Connection) -> None:
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, running(registered), lambda: 12)
    intent = StopIntent(worker=WORKER, reason="timeout")
    callbacks.before(intent)
    with pytest.raises(ValueError, match="matching committed intent"):
        callbacks.after(replace(intent, worker=replace(WORKER, start="reused")), StopReport())
    with pytest.raises(ValidationError):
        callbacks.after(intent, StopReport(term_delivered=True))
    record = store.get(KEY.attempt_id)
    assert record is not None and record.proof is None


def test_unknown_signal_sender_is_never_guessed() -> None:
    assert stop_text(None, -15) == "The agent ended with SIGTERM; the factory has no recorded sender or stop cause."
    assert stop_text(None, 1) is None


def test_concurrent_callbacks_cannot_replace_the_first_cause(admitted: Path) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    attempts = AttemptStore(lambda: con)
    assert attempts.register_entry(KEY, ENTRY, 10) == "accepted"
    admission = running(con)
    barrier = Barrier(2)

    def callback(reason: str) -> StopCause | None:
        writer = Store(SCHEMA).open_rw(admitted)
        assert writer is not None
        try:
            callbacks = AgentStops(StopStore(lambda: writer), admission, lambda: 12)
            barrier.wait(timeout=5)
            try:
                callbacks.before(StopIntent(worker=WORKER, reason=reason))
            except StoreRefused:
                return None
            assert callbacks.intent is not None
            return callbacks.intent.cause
        finally:
            writer.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(callback, ("timeout", "caller")))
        winners = [each for each in results if each is not None]
        record = StopStore(lambda: con).get(KEY.attempt_id)
        assert len(winners) == 1 and record is not None and record.cause == winners[0]
    finally:
        con.close()


@pytest.mark.parametrize("start", ["survivor-start", None])
def test_survivors_outside_the_original_group_prevent_reconciliation_until_proven_gone(
    registered: sqlite3.Connection, start: str | None,
) -> None:
    store = StopStore(lambda: registered)
    callbacks = AgentStops(store, running(registered), lambda: 12)
    intent = StopIntent(worker=WORKER, reason="timeout")
    callbacks.before(intent)
    callbacks.after(intent, StopReport(term_sent=True, term_delivered=True,
                                      survivors=[ProcessSurvivor(pid=43, start=start)]))
    seen: list[Worker] = []
    survivor_gone = False

    def observe(worker: Worker) -> bool:
        assert not registered.in_transaction
        seen.append(worker)
        return worker.pid == WORKER.pid or survivor_gone

    assert not reconcile(store, KEY, observe, 13)
    record = store.get(KEY.attempt_id)
    assert record is not None and record.phase == StopPhase.REPORTED
    survivor_gone = True
    assert reconcile(store, KEY, observe, 14) == (start is not None)
    if start is not None:
        assert seen[-1] == Worker(pid=43, pgid=WORKER.pgid, start=start, boot=WORKER.boot)
    assert registered.execute("SELECT attempt_id FROM reservation").fetchall() == [(KEY.attempt_id,)]
