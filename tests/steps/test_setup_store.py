"""`setup_run`'s one writer on real SQLite: every write fenced by the attempt's key (an agent attempt's or a checks
attempt's) against its held reservation while `admitted`, a concluded run never rewritten, "latest" the highest run, and
the failure count."""

import sqlite3

import pytest
from doubles import CHECKS, X
from stream_proc import OwnedProcess

from taskloop.attempt_reads import AttemptReads, StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.setup_store import Conclusion, SetupRow, SetupStore, running

KEY = AttemptKey("attempt", "dispatch", 1)
B = "b" * 40
DIGEST = "d" * 64
ME = OwnedProcess(501, 501, "start-501", "boot")


def store(con: sqlite3.Connection) -> SetupStore:
    return SetupStore(lambda: con)


@pytest.mark.parametrize(
    "key", [AttemptKey("attempt", "other", 1), AttemptKey("attempt", "dispatch", 2), AttemptKey("other", "dispatch", 1)],
    ids=["token", "generation", "attempt"],
)
def test_a_write_under_another_key_is_refused(registered: sqlite3.Connection, key: AttemptKey) -> None:
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store(registered).start(key, 1, B, DIGEST, 10)
    assert registered.execute("SELECT count(*) FROM setup_run").fetchone() == (0,)


@pytest.mark.parametrize(
    "change", ["DELETE FROM reservation", "UPDATE attempt SET phase='dispatching',base_commit=slot_head"], ids=["released", "dispatched"]
)
def test_every_write_needs_the_held_reservation_of_an_admitted_attempt(registered: sqlite3.Connection, change: str) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    registered.execute(change)
    for write in (lambda: setup.registered(KEY, 1, 0, ME), lambda: setup.conclude(KEY, 1, "passed", 0, 11),
                  lambda: setup.start(KEY, 2, B, DIGEST, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert registered.execute("SELECT run,pid,conclusion FROM setup_run").fetchall() == [(1, None, None)]


def test_a_concluded_run_is_never_rewritten_and_a_run_number_starts_once(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    setup.registered(KEY, 1, 0, ME)
    setup.conclude(KEY, 1, "failed", 3, 11)
    for write in (lambda: setup.registered(KEY, 1, 1, ME), lambda: setup.conclude(KEY, 1, "passed", 0, 12),
                  lambda: setup.start(KEY, 1, B, DIGEST, 13), lambda: setup.conclude(KEY, 2, "passed", 0, 12)):
        with pytest.raises(StoreRefused, match="setup_changed"):
            write()
    assert setup.latest(KEY) == SetupRow(1, B, DIGEST, 0, ME, "failed")


def test_latest_is_the_highest_run_whatever_the_clock_and_failures_count_only_the_setups_own(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    runs: tuple[tuple[int, Conclusion, float], ...] = ((1, "failed", 50.0), (2, "interrupted", 40.0), (3, "passed", 30.0),
                                                       (4, "lingering", 20.0))
    for run, conclusion, started in runs:
        setup.start(KEY, run, B, DIGEST, started)
        setup.conclude(KEY, run, conclusion, None, started + 1)
    setup.start(KEY, 5, B, DIGEST, 10.0)
    found = setup.latest(KEY)
    assert found is not None and (found.run, found.conclusion, found.process) == (5, None, None)
    assert setup.failures(KEY) == 2


def test_the_release_sees_only_an_unfinished_runs_registered_command(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    assert running(registered, "attempt") is None
    setup.start(KEY, 1, B, DIGEST, 10)
    assert running(registered, "attempt") is None  # nothing registered: nothing executed
    setup.registered(KEY, 1, 0, ME)
    assert running(registered, "attempt") == ME
    setup.conclude(KEY, 1, "passed", 0, 11)
    assert running(registered, "attempt") is None


@pytest.mark.parametrize(
    ("values", "column"),
    [(("e" * 39, DIGEST, None, None), "commit"), ((B, "d" * 63, None, None), "digest"), ((B, DIGEST, 2.0, None), "ended"),
     ((B, DIGEST, None, "passed"), "conclusion"), ((B, DIGEST, 2.0, "done"), "word")],
)
def test_the_v11_checks_hold(registered: sqlite3.Connection, values: tuple[object, ...], column: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        registered.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,
                           conclusion) VALUES ('attempt',1,'dispatch',1,?,?,1,?,?)""", values)


def test_only_the_identity_write_uses_the_registration_connection(registered: sqlite3.Connection) -> None:
    """The bounded registration connection serves the write inside the registered start's window, nothing else."""
    opened: list[str] = []

    def main() -> sqlite3.Connection:
        opened.append("main")
        return registered

    def registering() -> sqlite3.Connection:
        opened.append("registration")
        return registered

    setup = SetupStore(main, registering=AttemptReads(registering))
    setup.start(KEY, 1, B, DIGEST, 10)
    assert opened == ["main"]
    setup.registered(KEY, 1, 0, ME)
    assert opened == ["main", "registration"]
    setup.conclude(KEY, 1, "passed", 0, 11)
    assert setup.latest(KEY) == SetupRow(1, B, DIGEST, 0, ME, "passed") and opened.count("registration") == 1


@pytest.mark.parametrize(("conclusion", "held"), [(None, True), ("lingering", True), ("timed_out", True), ("failed", False),
                                                  ("passed", False), ("dirty", False), ("interrupted", False)])
def test_a_run_holds_the_slot_while_unfinished_or_concluded_with_a_group_maybe_left(conclusion: Conclusion | None, held: bool) -> None:
    assert SetupRow(1, B, DIGEST, 0, ME, conclusion).unsettled == (ME if held else None)


def test_a_checks_attempts_setup_runs_are_fenced_by_its_own_held_reservation(checking: sqlite3.Connection) -> None:
    """`setup_run` names an agent attempt or a checks attempt: `HELD` is the union of the two fences."""
    setup = store(checking)
    setup.start(CHECKS, 1, X, DIGEST, 10)
    setup.registered(CHECKS, 1, 0, ME)
    setup.conclude(CHECKS, 1, "failed", 2, 11)
    setup.start(CHECKS, 2, X, DIGEST, 12)
    assert setup.latest(CHECKS) == SetupRow(2, X, DIGEST, 0, None, None) and setup.failures(CHECKS) == 1
    for key in (AttemptKey("checks", "other", 1), AttemptKey("checks", "checks-token", 2), AttemptKey("implement", "implement-token", 1)):
        with pytest.raises(StoreRefused, match="stale_reservation"):  # the implement attempt released its slot
            setup.start(key, 3, X, DIGEST, 13)


@pytest.mark.parametrize("change", [
    "DELETE FROM reservation", "UPDATE reservation SET generation=2", "UPDATE reservation SET slot='s1'",
    "UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5",
], ids=["released", "generation", "slot", "concluded"])
def test_a_checks_attempts_setup_needs_its_held_reservation_while_admitted(checking: sqlite3.Connection, change: str) -> None:
    setup = store(checking)
    setup.start(CHECKS, 1, X, DIGEST, 10)
    checking.execute(change)
    for write in (lambda: setup.registered(CHECKS, 1, 0, ME), lambda: setup.conclude(CHECKS, 1, "passed", 0, 11),
                  lambda: setup.start(CHECKS, 2, X, DIGEST, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert checking.execute("SELECT run,pid,conclusion FROM setup_run").fetchall() == [(1, None, None)]
