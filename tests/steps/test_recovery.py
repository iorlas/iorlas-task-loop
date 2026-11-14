"""Recovery observes proof and atomically authorizes a bounded allowance; it never executes."""

import sqlite3
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from test_recovery_store import KEY, OWNED, OWNER, database, facts, observed, seed

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission, AttemptKey, EntryIdentity, Evidence, ExecutionFacts, FileRef
from taskloop.drain.models import Identity, Seen
from taskloop.ids import NativeIds
from taskloop.recovery.models import Claim, ClaimState, Outcome, ProcessObservation, Result
from taskloop.recovery.recover import Recovery
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


class Processes:
    def __init__(self) -> None:
        self.states: dict[int, Seen] = {}
        self.calls: list[int] = []

    def entry(self, identity: EntryIdentity) -> ProcessObservation:
        self.calls.append(identity[0])
        return ProcessObservation(seen=self.states.get(identity[0], Seen.GONE), explanation="Entry stop observation.")

    def process(self, identity: Identity) -> ProcessObservation:
        self.calls.append(identity.pid)
        return ProcessObservation(seen=self.states.get(identity.pid, Seen.GONE), explanation="Process group stop observation.")


def recovery(con: sqlite3.Connection, processes: Processes | None = None) -> Recovery:
    return Recovery(RecoveryStore(lambda: con), processes or Processes(), lambda _admission: OWNED,
                    lambda _admission: nullcontext(), lambda: 10, NativeIds())


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    seed(factory)
    return factory


def test_standalone_and_already_held_custody_revalidate_without_reacquisition(con: sqlite3.Connection) -> None:
    app = recovery(con)
    before = facts(con)
    first = app.authorize(KEY, OWNER)
    assert first.outcome is Outcome.AUTHORIZED and first.intent is not None

    def forbidden(_admission: Admission) -> AbstractContextManager[None]:
        raise AssertionError("An already-held slot must not be reacquired")

    app.custody = forbidden
    second = app.authorize(KEY, OWNER, custody=nullcontext())
    assert second.outcome is Outcome.AUTHORIZED and second.intent == first.intent
    assert facts(con) == before


@pytest.mark.parametrize("pid", [7, 8, 30])
@pytest.mark.parametrize("state", [Seen.ALIVE, Seen.UNKNOWN])
@pytest.mark.parametrize("renewal", [False, True])
def test_live_or_unknown_entry_worker_and_previous_owner_block_authorization(
    con: sqlite3.Connection, pid: int, state: Seen, renewal: bool,
) -> None:
    processes = Processes()
    app = recovery(con, processes)
    if pid == 30:
        assert app.authorize(KEY, OWNER).outcome is Outcome.AUTHORIZED
    if renewal:
        app.clock = lambda: 100
    processes.states[pid] = state
    before = facts(con)
    saved = con.execute("SELECT * FROM recovery_intent").fetchall()
    other = Identity(pid=40, pgid=40, start="other", boot="boot")
    result = app.authorize(KEY, other, deadline=200 if renewal else None)
    assert result.outcome is (Outcome.OCCUPIED if pid == 30 else Outcome.UNRESOLVED) and result.explanation
    assert facts(con) == before and con.execute("SELECT * FROM recovery_intent").fetchall() == saved


@pytest.mark.parametrize("state", [ClaimState.LOST, ClaimState.UNKNOWN])
@pytest.mark.parametrize("renewal", [False, True])
def test_claim_eligibility_is_read_only_and_explanatory(con: sqlite3.Connection, state: ClaimState, renewal: bool) -> None:
    app = recovery(con)
    calls: list[Admission] = []

    def claim(admission: Admission) -> Claim:
        calls.append(admission)
        return Claim(state=state, explanation="Claim ownership was lost or could not be confirmed.")

    app.claim = claim
    if renewal:
        app.clock = lambda: 100
    before = facts(con)
    result = app.authorize(KEY, OWNER, deadline=200 if renewal else None)
    assert result.outcome is (Outcome.CLAIM_LOST if state is ClaimState.LOST else Outcome.CLAIM_UNKNOWN)
    assert result.explanation and len(calls) == 1 and facts(con) == before
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)


@pytest.mark.parametrize(("exception", "outcome"), [(SlotBusy, Outcome.CUSTODY_BUSY), (SlotLockUnavailable, Outcome.UNAVAILABLE)])
@pytest.mark.parametrize("renewal", [False, True])
def test_unavailable_custody_has_no_authorization_or_claim_read(
    con: sqlite3.Connection, exception: type[Exception], outcome: Outcome, renewal: bool,
) -> None:
    app = recovery(con)

    def unavailable(_admission: Admission) -> AbstractContextManager[None]:
        raise exception()

    def forbidden(_admission: Admission) -> Claim:
        raise AssertionError("Custody must precede claim observation")

    app.custody, app.claim = unavailable, forbidden
    if renewal:
        app.clock = lambda: 100
    before = facts(con)
    result = app.authorize(KEY, OWNER, deadline=200 if renewal else None)
    assert result.outcome is outcome and result.explanation and facts(con) == before


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("UPDATE attempt SET session_ref=NULL", Outcome.INELIGIBLE),
        ("UPDATE attempt SET session_conflict=1", Outcome.INELIGIBLE),
        ("UPDATE attempt SET worker_pid=NULL", Outcome.UNRESOLVED),
        ("UPDATE attempt SET entry_start=NULL", Outcome.UNRESOLVED),
        ("UPDATE attempt SET phase='dispatching'", Outcome.UNRESOLVED),
        ("UPDATE attempt SET deadline=10", Outcome.EXPIRED),
        ("UPDATE attempt SET dispatch_token='replaced'", Outcome.INELIGIBLE),
    ],
)
def test_ineligible_or_incomplete_attempts_do_not_observe_processes(
    con: sqlite3.Connection, change: str, expected: Outcome,
) -> None:
    processes = Processes()
    con.execute(change)
    result = recovery(con, processes).authorize(KEY, OWNER)
    assert result.outcome is expected and result.explanation and processes.calls == []


def test_exclusive_session_ownership_is_rechecked_at_commit(con: sqlite3.Connection) -> None:
    app = recovery(con)

    def claim(_admission: Admission) -> Claim:
        seed(con, attempt="other", task="tl-2")
        return OWNED

    app.claim = claim
    result = app.authorize(KEY, OWNER)
    assert result.outcome is Outcome.INELIGIBLE and "Another current attempt" in result.explanation
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)


def test_captured_execution_between_observation_and_commit_is_collected(con: sqlite3.Connection) -> None:
    app = recovery(con)
    before = observed(app.store)
    admission = before.snapshot.attempt.admission
    files = FileRef("evidence", "digest")
    facts_input = ExecutionFacts(0, False, None, None, True, True, True, None, None, None, None, None, "saved")
    assert AttemptStore(lambda: con).capture(admission, None, facts_input, Evidence(files, files, files, files), "complete") == "accepted"
    result = app.store.authorize(before, OWNER, "intent", lambda: 10)
    assert result.outcome is Outcome.CAPTURED and result.explanation
    processes = Processes()
    saved = facts(con)
    assert recovery(con, processes).authorize(KEY, OWNER).outcome is Outcome.CAPTURED
    assert facts(con) == saved and processes.calls == []


def test_expiration_during_observation_does_not_renew_allowance(con: sqlite3.Connection) -> None:
    app = recovery(con)
    times = iter((10, 100))
    app.clock = lambda: next(times)
    before = facts(con)
    result = app.authorize(KEY, OWNER)
    assert result.outcome is Outcome.EXPIRED and result.explanation and facts(con) == before


@pytest.mark.parametrize("data", ['{}', '{"generation":"bad"}', '[]'])
def test_malformed_durable_intent_is_unavailable_and_preserved(con: sqlite3.Connection, data: str) -> None:
    con.execute("INSERT INTO recovery_intent VALUES('attempt',?)", (data,))
    before = facts(con)
    result = recovery(con).authorize(KEY, OWNER)
    assert result.outcome is Outcome.UNAVAILABLE and result.explanation and facts(con) == before
    assert con.execute("SELECT data FROM recovery_intent").fetchone() == (data,)


def test_missing_database_is_unavailable() -> None:
    app = Recovery(RecoveryStore(lambda: None), Processes(), lambda _admission: OWNED,
                   lambda _admission: nullcontext(), lambda: 10, NativeIds())
    assert app.authorize(KEY, OWNER).outcome is Outcome.UNAVAILABLE


def test_current_owner_cannot_reuse_authorization_after_revision_changes(con: sqlite3.Connection) -> None:
    app = recovery(con)
    first = app.authorize(KEY, OWNER)
    con.execute("UPDATE attempt SET rev=rev+1")
    result = app.authorize(KEY, OWNER)
    assert result.outcome is Outcome.CHANGED and result.intent == first.intent and result.explanation
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (1,)


def test_saved_authorization_with_a_foreign_attempt_key_is_unavailable(con: sqlite3.Connection) -> None:
    app = recovery(con)
    first = app.authorize(KEY, OWNER)
    assert first.intent is not None
    foreign = first.intent.model_copy(update={"key": AttemptKey("other", "dispatch", 1)})
    con.execute("UPDATE recovery_intent SET data=?", (foreign.model_dump_json(),))
    result = app.authorize(KEY, OWNER)
    assert result.outcome is Outcome.UNAVAILABLE and result.explanation
    assert con.execute("SELECT data FROM recovery_intent").fetchone() == (foreign.model_dump_json(),)


def test_reopen_reobserves_old_owner_and_can_replace_only_confirmed_absence(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    original = recovery(con).authorize(KEY, OWNER)
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    processes = Processes()
    processes.states[30] = Seen.UNKNOWN
    app = recovery(con, processes)
    successor = Identity(pid=40, pgid=40, start="successor", boot="boot")
    assert app.authorize(KEY, successor).outcome is Outcome.OCCUPIED
    assert processes.calls == [7, 8, 30]
    processes.states[30] = Seen.GONE
    replacement = app.authorize(KEY, successor)
    assert original.intent is not None and replacement.intent is not None
    assert replacement.intent.generation == 2 and replacement.intent.token != original.intent.token
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    assert recovery(con).authorize(KEY, successor).intent == replacement.intent
    con.close()


def test_expired_allowance_renews_after_custody_stop_and_claim_proof(con: sqlite3.Connection) -> None:
    processes = Processes()
    app = recovery(con, processes)
    app.clock = lambda: 100
    before = facts(con)
    assert app.authorize(KEY, OWNER).outcome is Outcome.EXPIRED
    assert processes.calls == [] and facts(con) == before
    admissions: list[Admission] = []

    def custody(admission: Admission) -> AbstractContextManager[None]:
        admissions.append(admission)
        assert processes.calls == []
        return nullcontext()

    def claim(admission: Admission) -> Claim:
        assert admissions == [admission] and processes.calls == [7, 8]
        assert facts(con) == before
        return OWNED

    app.custody, app.claim = custody, claim
    result = app.authorize(KEY, OWNER, token="renewal", deadline=200)
    assert result.outcome is Outcome.AUTHORIZED and result.intent is not None and result.explanation
    snapshot = observed(app.store, now=100).snapshot
    assert snapshot.attempt.admission.deadline == 200
    assert snapshot.attempt.revision == result.intent.attempt_revision == 5
    assert snapshot.attempt.admission.key == KEY and result.intent.session == "saved"
    app.clock = lambda: 200
    expired = app.reconcile(result.intent)
    assert isinstance(expired, Result) and expired.outcome is Outcome.EXPIRED and expired.explanation


def test_renewal_cannot_revive_old_registered_callbacks(con: sqlite3.Connection) -> None:
    app = recovery(con)
    original = app.authorize(KEY, OWNER)
    assert original.intent is not None
    intended = app.store.execute(original.intent, lambda: 10)
    assert intended.intent is not None
    worker = Identity(pid=40, pgid=40, start="replacement", boot="boot")
    registered = app.store.register(intended.intent, worker, lambda: 10)
    assert registered.intent is not None
    old_callback = callback(registered.intent)
    old_admission = observed(app.store).snapshot.attempt.admission
    app.clock = lambda: 100
    renewed = app.authorize(KEY, OWNER, token="next", deadline=200)
    assert renewed.outcome is Outcome.AUTHORIZED and renewed.intent is not None
    snapshot = observed(app.store, now=100).snapshot
    attempts = AttemptStore(lambda: con)
    before = facts(con)
    for admission in (old_admission, snapshot.attempt.admission):
        with pytest.raises(StoreRefused):
            attempts.session(admission, "saved", old_callback)
        with pytest.raises(StoreRefused):
            attempts.session(admission, "saved")
    assert facts(con) == before
    intended = app.store.execute(renewed.intent, lambda: 100)
    assert intended.intent is not None
    registered = app.store.register(intended.intent, worker, lambda: 100)
    assert registered.intent is not None
    assert attempts.session(snapshot.attempt.admission, "saved", callback(registered.intent)) == "already_same"
