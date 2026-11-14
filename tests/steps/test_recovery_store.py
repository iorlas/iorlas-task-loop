"""Real file databases fence authorization, preserve ownership and survive reopen."""

import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest
from sqlite_store import begin_immediate

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Identity, Seen
from taskloop.factory_schema import SCHEMA
from taskloop.recovery.models import Claim, ClaimState, Observations, Outcome, ProcessObservation, Result, Snapshot
from taskloop.recovery.store import RecoveryStore

KEY = AttemptKey("attempt", "dispatch", 1)
OWNER = Identity(pid=30, pgid=30, start="owner", boot="boot")
GONE = ProcessObservation(seen=Seen.GONE, explanation="The exact process and group are absent.")
OWNED = Claim(state=ClaimState.OWNED, explanation="The task claim still belongs to this factory.")


def seed(con: sqlite3.Connection, *, attempt: str = "attempt", task: str = "tl-1", session: str = "saved") -> None:
    con.execute("INSERT INTO slot(repo_id,name,path) VALUES('repo',?,?)", (attempt, f"/slots/{attempt}"))
    con.execute("INSERT INTO reservation VALUES(?,'repo',1,?)", (attempt, attempt))
    con.execute(
        """INSERT INTO attempt(attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,
        repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,
        entry_pid,entry_start,entry_boot,phase,rev,worker_pid,worker_pgid,worker_start,worker_boot,session_ref,base_commit)
        VALUES(?,?,1,'plan','beads','tasks',?,'/tracker','repo',?,'input','digest',1,'chosen','high',
        '{"harness":"codex","sandbox":"workspace-write"}',100,1,1,?,7,'entry','boot','registered',4,8,8,'worker','boot',?,?)""",
        (attempt, "dispatch" if attempt == "attempt" else attempt, task, attempt, "d" * 40, session, "b" * 40),
    )


def database(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version={SCHEMA.version}")
    seed(con)
    return con


def observed(store: RecoveryStore) -> Observations:
    snapshot = store.snapshot(KEY, 10)
    assert isinstance(snapshot, Snapshot), snapshot
    return Observations(snapshot=snapshot, entry=GONE, worker=GONE, owner=GONE, claim=OWNED)


def facts(con: sqlite3.Connection) -> list[list[tuple[object, ...]]]:
    return [con.execute(f"SELECT * FROM {table}").fetchall() for table in ("attempt", "reservation", "execution")]


def test_reopen_revalidates_exact_intent_and_preserves_attempt_facts(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    before = facts(con)
    con.close()  # unfinished compatible work has no recovery record yet
    con = sqlite3.connect(path, isolation_level=None)
    store = RecoveryStore(lambda: con)
    result = store.authorize(observed(store), OWNER, "first", lambda: 10)
    assert result.outcome is Outcome.AUTHORIZED and result.intent is not None
    assert result.intent.attempt_revision == 4 and result.intent.generation == 1
    assert result.intent.session == "saved" and result.intent.entry == (7, "entry", "boot")
    assert result.intent.worker == Identity(pid=8, pgid=8, start="worker", boot="boot")
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    reopened = RecoveryStore(lambda: con)
    snapshot = observed(reopened)
    assert snapshot.snapshot.intent == result.intent
    again = reopened.authorize(snapshot, OWNER, "first", lambda: 10)
    assert again.outcome is Outcome.AUTHORIZED and again.intent == result.intent and again.explanation
    assert facts(con) == before
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (1,)
    con.close()


def race(path: Path, *, replacement: bool) -> list[Result]:
    barrier = Barrier(2)

    def contender(number: int) -> Result:
        con = sqlite3.connect(path, isolation_level=None)
        try:
            store = RecoveryStore(lambda: con)
            snapshot = observed(store)
            assert (snapshot.snapshot.intent is not None) is replacement
            barrier.wait(timeout=5)
            owner = Identity(pid=number, pgid=number, start=str(number), boot="boot")
            return store.authorize(snapshot, owner, str(number), lambda: 10)
        finally:
            con.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(contender, (40, 50)))


@pytest.mark.parametrize("replacement", [False, True])
def test_independent_connections_elect_one_owner_and_fence_loser(tmp_path: Path, replacement: bool) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    store = RecoveryStore(lambda: con)
    before = facts(con)
    if replacement:
        assert store.authorize(observed(store), OWNER, "old", lambda: 10).outcome is Outcome.AUTHORIZED
    stale = observed(store)
    con.close()
    results = race(path, replacement=replacement)
    assert sorted(result.outcome for result in results) == sorted((Outcome.AUTHORIZED, Outcome.CHANGED))
    assert all(result.explanation for result in results)
    con = sqlite3.connect(path, isolation_level=None)
    store = RecoveryStore(lambda: con)
    current = observed(store).snapshot.intent
    assert current is not None and current.generation == (2 if replacement else 1)
    refused = store.authorize(stale, OWNER, "old", lambda: 10)
    assert refused.outcome is Outcome.CHANGED and refused.intent == current
    assert facts(con) == before and con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (1,)
    con.close()


def test_failed_commit_leaves_no_authorization_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    original = observed(RecoveryStore(lambda: con))

    @contextmanager
    def fail_commit(connection: sqlite3.Connection) -> Generator[None]:
        with begin_immediate(connection):
            yield
            raise sqlite3.OperationalError("commit failed")

    with pytest.raises(StoreUnavailable):
        RecoveryStore(lambda: con, fail_commit).authorize(original, OWNER, "rolled-back", lambda: 10)
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    assert observed(RecoveryStore(lambda: con)).snapshot.intent is None
    con.close()


def test_deadline_is_checked_after_obtaining_the_writer_transaction(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    snapshot = observed(RecoveryStore(lambda: con))
    now = 10

    @contextmanager
    def delayed(connection: sqlite3.Connection) -> Generator[None]:
        nonlocal now
        with begin_immediate(connection):
            now = 100  # allowance expires while authorization is obtaining the write transaction
            yield

    before = facts(con)
    result = RecoveryStore(lambda: con, delayed).authorize(snapshot, OWNER, "late", lambda: now)
    assert result.outcome is Outcome.EXPIRED and result.explanation and facts(con) == before
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)
    con.close()


CHANGES = [
    ("UPDATE attempt SET rev=rev+1", Outcome.CHANGED),
    ("UPDATE attempt SET session_ref='other',rev=rev+1", Outcome.CHANGED),
    ("UPDATE attempt SET session_conflict=1,rev=rev+1", Outcome.INELIGIBLE),
    ("UPDATE attempt SET deadline=10", Outcome.EXPIRED),
    ("UPDATE attempt SET phase='captured'", Outcome.UNRESOLVED),
    ("UPDATE reservation SET generation=2", Outcome.INELIGIBLE),
    ("DELETE FROM reservation", Outcome.INELIGIBLE),
    ("INSERT INTO slot_release VALUES('attempt','dispatch',1,'" + "b" * 40 + "',10,'kept')", Outcome.INELIGIBLE),
    ("INSERT INTO slot_release VALUES('attempt','dispatch',1,'" + "b" * 40 + "',10,'unclaimed')", Outcome.INELIGIBLE),
    ("INSERT INTO task_hold(attempt_id,cause_id,reason,held_at) VALUES('attempt','cause','held',10)", Outcome.INELIGIBLE),
    ("INSERT INTO drain_state VALUES(1,1,'draining')", Outcome.DRAINING),
    ("INSERT INTO drain_state VALUES(1,2,'open')", Outcome.CHANGED),
    ("UPDATE attempt SET entry_start='replacement',rev=rev+1", Outcome.CHANGED),
    ("UPDATE attempt SET worker_start='replacement',rev=rev+1", Outcome.CHANGED),
]


@pytest.mark.parametrize(("change", "expected"), CHANGES)
def test_local_changes_between_observation_and_commit_cannot_authorize(
    tmp_path: Path, change: str, expected: Outcome,
) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    snapshot = observed(store)
    con.execute(change)
    before = facts(con)
    result = store.authorize(snapshot, OWNER, "intent", lambda: 10)
    assert result.outcome is expected and result.explanation
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)
    assert facts(con) == before
    con.close()


@pytest.mark.parametrize("checks", [False, True])
def test_successor_created_after_observation_prevents_authorization(tmp_path: Path, checks: bool) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    snapshot = observed(store)
    if checks:
        con.execute("""INSERT INTO checks_attempt(attempt_id,dispatch_token,generation,after_attempt_id,number,slot,
                    slot_head,target_commit,required,deadline) VALUES('checks','checks',1,'attempt',1,'attempt',?,?, '[]',100)""",
                    ("b" * 40, "b" * 40))
    else:
        seed(con, attempt="successor", task="tl-other", session="another")
        con.execute("UPDATE attempt SET task_id='tl-1',seq=2 WHERE attempt_id='successor'")
    result = store.authorize(snapshot, OWNER, "intent", lambda: 10)
    assert result.outcome is Outcome.INELIGIBLE and result.explanation
    assert con.execute("SELECT count(*) FROM recovery_intent").fetchone() == (0,)
    con.close()
