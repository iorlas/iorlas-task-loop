"""The registered entry: one winner per admitted attempt, replacement only of an observed-dead identity, on real SQLite."""

import sqlite3
import threading
from pathlib import Path

import pytest
from sqlite_store import Store

from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore, StoreUnavailable
from taskloop.plan_types import AttemptKey, Replaced

KEY = AttemptKey("attempt", "dispatch", 1)
FIRST = (7, "entry-start", "boot")
SECOND = (8, "later-start", "boot")


def seed(con: sqlite3.Connection) -> sqlite3.Connection:
    """An admitted, unregistered attempt (entry_* NULL) and its held reservation, as admission writes them."""
    con.execute("INSERT INTO reservation VALUES ('slot','repo','/slots/repo/slot',1,'attempt')")
    con.execute(
        """INSERT INTO plan_attempt
        (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
         schema_version,model,effort,sandbox,deadline)
        VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','repo','slot','input.txt','0',1,'chosen','high','workspace-write',100)"""
    )
    return con


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    return seed(factory)


def entry(con: sqlite3.Connection) -> tuple[object, ...]:
    return con.execute("SELECT entry_pid,entry_start,entry_boot,rev FROM plan_attempt").fetchone()


def test_first_registration_wins_and_a_second_is_a_conflict(con: sqlite3.Connection) -> None:
    store = PlanStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, SECOND, 10) == "conflict"
    assert store.register_entry(KEY, FIRST, 10) == "conflict"  # no already_same: one callback never commits twice
    assert entry(con) == (*FIRST, 1)
    loaded = store.load(KEY)
    assert loaded is not None and loaded.admission.entry == FIRST and loaded.phase == "admitted"


def test_replacement_needs_the_exact_stored_identity(con: sqlite3.Connection) -> None:
    store = PlanStore(lambda: con)
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "gone")) == "conflict"  # nothing stored yet to replace
    assert entry(con) == (None, None, None, 0)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, SECOND, 10, Replaced((7, "other-start", "boot"), "different_process")) == "conflict"
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "different_process")) == "accepted"
    assert entry(con) == (*SECOND, 2)
    assert store.register_entry(KEY, FIRST, 10, Replaced(FIRST, "gone")) == "conflict"  # the replaced identity is no longer stored


@pytest.mark.parametrize("phase", ["dispatching", "registered", "captured"])
def test_no_registration_or_replacement_after_admitted(con: sqlite3.Connection, phase: str) -> None:
    store = PlanStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    con.execute("UPDATE plan_attempt SET phase=?", (phase,))
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "gone")) == "conflict"
    con.execute("UPDATE plan_attempt SET entry_pid=NULL,entry_start=NULL,entry_boot=NULL")
    assert store.register_entry(KEY, SECOND, 10) == "conflict"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE reservation SET generation=2",
        "UPDATE reservation SET attempt_id='other'",
        "UPDATE reservation SET repo_id='other-repo'",
        "DELETE FROM reservation",
        "UPDATE plan_attempt SET deadline=10",
        "DELETE FROM plan_attempt",
    ],
)
def test_stale_reservation_expired_or_missing_attempt_is_refused(con: sqlite3.Connection, change: str) -> None:
    con.execute(change)
    assert PlanStore(lambda: con).register_entry(KEY, FIRST, 10) == "refused"
    assert con.execute("SELECT count(*) FROM plan_attempt WHERE entry_pid IS NOT NULL").fetchone() == (0,)


@pytest.mark.parametrize(
    "key",
    [AttemptKey("attempt", "other-token", 1), AttemptKey("attempt", "dispatch", 2), AttemptKey("other", "dispatch", 1)],
)
def test_a_wrong_key_is_refused(con: sqlite3.Connection, key: AttemptKey) -> None:
    assert PlanStore(lambda: con).register_entry(key, FIRST, 10) == "refused"
    assert entry(con) == (None, None, None, 0)


def test_replacing_an_identity_with_itself_is_a_conflict_and_changes_nothing(con: sqlite3.Connection) -> None:
    store = PlanStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, FIRST, 10, Replaced(FIRST, "gone")) == "conflict"
    assert entry(con) == (*FIRST, 1)


def test_two_connections_contend_for_one_registration(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    first = Store(SCHEMA).open_rw(path)
    assert first is not None
    seed(first)
    barrier, outcomes = threading.Barrier(2), []

    def contender(identity: tuple[int, str, str]) -> None:
        store = Store(SCHEMA)
        mine = store.open_rw(path)
        barrier.wait()
        outcomes.append(PlanStore(lambda: mine, store.begin_immediate).register_entry(KEY, identity, 10))

    threads = [threading.Thread(target=contender, args=(identity,)) for identity in (FIRST, SECOND)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "conflict"]
    assert entry(first)[3] == 1 and entry(first)[:3] in (FIRST, SECOND)


def test_unavailable_store_registers_nothing(con: sqlite3.Connection) -> None:
    with pytest.raises(StoreUnavailable):
        PlanStore(lambda: None).register_entry(KEY, FIRST, 10)
    con.execute("PRAGMA user_version=1")
    with pytest.raises(StoreUnavailable):
        PlanStore(lambda: con).register_entry(KEY, FIRST, 10)


def test_attempt_of_is_the_recovery_read_by_task(con: sqlite3.Connection) -> None:
    store = PlanStore(lambda: con)
    assert store.attempt_of("tasks", "tl-1") == (KEY, "admitted", None)
    assert store.attempt_of("tasks", "tl-2") is None
    assert store.attempt_of("other", "tl-1") is None
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    con.execute("UPDATE plan_attempt SET phase='dispatching'")
    con.execute("DELETE FROM reservation")  # a recovery read needs no live reservation
    assert store.attempt_of("tasks", "tl-1") == (KEY, "dispatching", FIRST)
    with pytest.raises(StoreUnavailable):
        PlanStore(lambda: None).attempt_of("tasks", "tl-1")
