"""The registered entry: one winner per admitted attempt, replacement only of an observed-dead identity, on real SQLite."""

import math
import sqlite3
import threading
from pathlib import Path

import pytest
from doubles import ENGINE, pin_workflow
from sqlite_store import Store
from test_attempt import ENTRY, AttemptSurroundings, Flaky, database, fake, owner
from test_attempt import KEY as BENCH_KEY
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import REGISTRATION_BUSY_MS, AttemptStore, configure_registration
from taskloop.attempt_types import AttemptKey, EntryIdentity, Replaced
from taskloop.factory_schema import SCHEMA

KEY = AttemptKey("attempt", "dispatch", 1)
FIRST = (7, "entry-start", "boot")
SECOND = (8, "later-start", "boot")
surroundings = attempt_surroundings


def seed(con: sqlite3.Connection) -> sqlite3.Connection:
    """An admitted, unregistered attempt (entry_* NULL) and its held reservation, as admission writes them."""
    con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','slot','/slots/repo/slot')")
    con.execute("INSERT INTO reservation VALUES ('slot','repo',1,'attempt')")
    pin_workflow(con)
    con.execute(
        """INSERT INTO attempt
        (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
         schema_version,model,effort,access_policy,deadline,number,seq,slot_head,engine_digest,workflow_digest,workflow_sha,admitted_at)
        VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker','repo','slot','input.txt','0',1,'chosen','high',
        '{"harness":"codex","sandbox":"workspace-write"}',100,1,1,'dddddddddddddddddddddddddddddddddddddddd',
        'abababababababababababababababababababababababababababababababab',
        (SELECT digest FROM workflow_file),
        'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',1.0)"""
    )
    return con


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    return seed(factory)


def entry(con: sqlite3.Connection) -> tuple[object, ...]:
    return con.execute("SELECT entry_pid,entry_start,entry_boot,rev FROM attempt").fetchone()


def test_registration_configuration_is_connection_local_and_preserves_transaction(
    con: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    ordinary = Store(SCHEMA).open_rw(tmp_path / "ordinary.db")
    assert ordinary is not None
    try:
        con.execute("BEGIN IMMEDIATE")
        configure_registration(con)
        assert con.in_transaction
        assert con.execute("PRAGMA busy_timeout").fetchone() == (REGISTRATION_BUSY_MS,)
        assert ordinary.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        con.rollback()
    finally:
        ordinary.close()


def test_registration_configuration_propagates_sqlite_errors(con: sqlite3.Connection) -> None:
    con.close()
    with pytest.raises(sqlite3.Error):
        configure_registration(con)


def test_missing_status_results_and_required_input(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    missing = AttemptKey("missing", "missing", 1)
    assert store.state(missing) is None
    assert store.tracker_root(missing) is None
    assert store.release_of(missing) is None
    assert store.attempt_of("tasks", "missing") is None
    assert store.release_of(KEY) is None
    with pytest.raises(StoreUnavailable, match="Attempt input reference unavailable"):
        store.input_ref(missing)


def test_first_registration_wins_and_a_second_is_a_conflict(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, SECOND, 10) == "conflict"
    assert store.register_entry(KEY, FIRST, 10) == "conflict"  # no already_same: one callback never commits twice
    assert entry(con) == (*FIRST, 1)
    loaded = store.load(KEY)
    assert loaded is not None and loaded.admission.entry == FIRST and loaded.phase == "admitted"


def test_replacement_needs_the_exact_stored_identity(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "gone")) == "conflict"  # nothing stored yet to replace
    assert entry(con) == (None, None, None, 0)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, SECOND, 10, Replaced((7, "other-start", "boot"), "different_process")) == "conflict"
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "different_process")) == "accepted"
    assert entry(con) == (*SECOND, 2)
    assert store.register_entry(KEY, FIRST, 10, Replaced(FIRST, "gone")) == "conflict"  # the replaced identity is no longer stored


@pytest.mark.parametrize("phase", ["dispatching", "registered", "captured"])
def test_no_registration_or_replacement_after_admitted(con: sqlite3.Connection, phase: str) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    con.execute("UPDATE attempt SET phase=?,base_commit=?", (phase, "b" * 40))
    assert store.register_entry(KEY, SECOND, 10, Replaced(FIRST, "gone")) == "conflict"
    con.execute("UPDATE attempt SET entry_pid=NULL,entry_start=NULL,entry_boot=NULL")
    assert store.register_entry(KEY, SECOND, 10) == "conflict"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE reservation SET generation=2",
        "UPDATE reservation SET attempt_id='other'",
        "UPDATE reservation SET repo_id='other-repo'",
        "DELETE FROM reservation",
        "UPDATE attempt SET deadline=10",
        "DELETE FROM attempt",
    ],
)
def test_stale_reservation_expired_or_missing_attempt_is_refused(con: sqlite3.Connection, change: str) -> None:
    con.execute(change)
    assert AttemptStore(lambda: con).register_entry(KEY, FIRST, 10) == "refused"
    assert con.execute("SELECT count(*) FROM attempt WHERE entry_pid IS NOT NULL").fetchone() == (0,)


@pytest.mark.parametrize(
    "key",
    [AttemptKey("attempt", "other-token", 1), AttemptKey("attempt", "dispatch", 2), AttemptKey("other", "dispatch", 1)],
)
def test_a_wrong_key_is_refused(con: sqlite3.Connection, key: AttemptKey) -> None:
    assert AttemptStore(lambda: con).register_entry(key, FIRST, 10) == "refused"
    assert entry(con) == (None, None, None, 0)


def test_replacing_an_identity_with_itself_is_a_conflict_and_changes_nothing(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, FIRST, 10, Replaced(FIRST, "gone")) == "conflict"
    assert entry(con) == (*FIRST, 1)


def test_two_connections_contend_for_one_registration(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    first = Store(SCHEMA).open_rw(path)
    assert first is not None
    seed(first)
    barrier, outcomes = threading.Barrier(2), []

    def contender(identity: EntryIdentity) -> None:
        store = Store(SCHEMA)
        mine = store.open_rw(path)
        barrier.wait()
        outcomes.append(AttemptStore(lambda: mine, store.begin_immediate).register_entry(KEY, identity, 10))

    threads = [threading.Thread(target=contender, args=(identity,)) for identity in (FIRST, SECOND)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "conflict"]
    assert entry(first)[3] == 1 and entry(first)[:3] in (FIRST, SECOND)


def test_unavailable_store_registers_nothing(con: sqlite3.Connection) -> None:
    with pytest.raises(StoreUnavailable):
        AttemptStore(lambda: None).register_entry(KEY, FIRST, 10)
    con.execute("PRAGMA user_version=1")
    with pytest.raises(StoreUnavailable):
        AttemptStore(lambda: con).register_entry(KEY, FIRST, 10)


def test_attempt_of_is_the_recovery_read_by_task(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.attempt_of("tasks", "tl-1") == (KEY, "admitted", None)
    assert store.attempt_of("tasks", "tl-2") is None
    assert store.attempt_of("other", "tl-1") is None
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    con.execute("UPDATE attempt SET phase='dispatching',base_commit=?", ("b" * 40,))
    con.execute("DELETE FROM reservation")  # a recovery read needs no live reservation
    assert store.attempt_of("tasks", "tl-1") == (KEY, "dispatching", FIRST)
    with pytest.raises(StoreUnavailable):
        AttemptStore(lambda: None).attempt_of("tasks", "tl-1")


REBOOTED = (9, "after-reboot", "new-boot")


def deadline(con: sqlite3.Connection) -> object:
    return con.execute("SELECT deadline FROM attempt").fetchone()[0]


def test_a_replacement_from_another_boot_renews_the_deadline_once_per_reboot(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, REBOOTED, 200, Replaced(FIRST, "different_process"), renewed=2000) == "accepted"  # past 100
    assert (entry(con), deadline(con)) == ((*REBOOTED, 2), 2000)
    again = (10, "again", "new-boot")
    assert store.register_entry(KEY, again, 300, Replaced(REBOOTED, "gone"), renewed=5000) == "accepted"  # same boot now
    assert deadline(con) == 2000
    assert store.register_entry(KEY, (11, "late", "new-boot"), 2500, Replaced(again, "gone"), renewed=9000) == "refused"
    assert (entry(con), deadline(con)) == ((*again, 3), 2000)


def test_a_first_registration_or_a_same_boot_replacement_never_renews(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, REBOOTED, 200, renewed=2000) == "refused"  # never registered: nothing to compare
    assert store.register_entry(KEY, FIRST, 10, renewed=2000) == "accepted"
    assert deadline(con) == 100
    assert store.register_entry(KEY, SECOND, 200, Replaced(FIRST, "gone"), renewed=2000) == "refused"
    assert (entry(con), deadline(con)) == ((*FIRST, 1), 100)


def test_the_renewal_is_fenced_by_key_phase_and_the_stored_identity(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    replacing = Replaced(FIRST, "different_process")
    assert store.register_entry(AttemptKey("attempt", "other-token", 1), REBOOTED, 200, replacing, renewed=2000) == "refused"
    assert store.register_entry(KEY, REBOOTED, 200, Replaced(SECOND, "different_process"), renewed=2000) == "conflict"
    con.execute("UPDATE attempt SET phase='dispatching',base_commit=?", ("d" * 40,))
    assert store.register_entry(KEY, REBOOTED, 200, replacing, renewed=2000) == "conflict"
    assert (entry(con), deadline(con)) == ((*FIRST, 1), 100)


@pytest.mark.parametrize("renewed", [200, 150, math.inf, math.nan])
def test_a_renewal_not_after_now_or_not_finite_is_refused_and_not_consumed(con: sqlite3.Connection, renewed: float) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, REBOOTED, 200, Replaced(FIRST, "different_process"), renewed=renewed) == "refused"
    assert (entry(con), deadline(con)) == ((*FIRST, 1), 100)
    assert store.register_entry(KEY, REBOOTED, 200, Replaced(FIRST, "different_process"), renewed=2000) == "accepted"
    assert deadline(con) == 2000


def test_a_renewal_never_shortens_a_live_deadline(con: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: con)
    assert store.register_entry(KEY, FIRST, 10) == "accepted"
    assert store.register_entry(KEY, REBOOTED, 20, Replaced(FIRST, "gone"), renewed=50) == "accepted"  # before the deadline 100
    assert (entry(con), deadline(con)) == ((*REBOOTED, 2), 100)


def test_capture_stores_the_given_end_time_and_keeps_the_admission_facts(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    attempts = owner(Flaky(con), surroundings, fake(), clock=lambda: 42.5)
    assert attempts.execute(BENCH_KEY, ENTRY).execution is not None
    assert con.execute("SELECT phase,ended_at,admitted_at,engine_digest FROM attempt").fetchone() == ("captured", 42.5, 1.0, ENGINE)


def test_an_attempt_that_is_not_captured_cannot_have_an_end_time(con: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="ended_at IS NULL OR phase='captured'"):
        con.execute("UPDATE attempt SET ended_at=5.0")
    assert con.execute("SELECT phase,ended_at FROM attempt").fetchone() == ("admitted", None)


@pytest.mark.parametrize("digest", ["", "ab" * 31, "AB" * 32, "xy" * 32, "ab" * 33])
def test_the_engine_digest_must_be_64_lowercase_hex_characters(con: sqlite3.Connection, digest: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        con.execute("UPDATE attempt SET engine_digest=?", (digest,))
    assert con.execute("SELECT engine_digest FROM attempt").fetchone() == (ENGINE,)
