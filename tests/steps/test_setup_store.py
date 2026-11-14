"""`setup_run`'s one writer on real SQLite: every write fenced by the attempt's key (an agent attempt's, a checks
attempt's or a land candidate's) against its held reservation while `admitted` (a candidate: pending), a concluded run
never rewritten, "latest" the highest run, and the failure count."""

import sqlite3

import pytest
from doubles import CANDIDATE, CHECKS, SQUASH, X
from stream_proc import OwnedProcess

from taskloop.attempt_reads import AttemptReads, StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.command_conclusion import CommandConclusion
from taskloop.setup_store import SetupRow, SetupStore, running

KEY = AttemptKey("attempt", "dispatch", 1)
B = "b" * 40
DIGEST = "d" * 64
ME = OwnedProcess(501, 501, "start-501", "boot")


def store(con: sqlite3.Connection) -> SetupStore:
    return SetupStore(lambda: con)


def add_owner(con: sqlite3.Connection, identity: str, started: float, *, backlog: str = "tasks", step: str = "implement") -> None:
    con.execute("""INSERT INTO attempt
        (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit)
        SELECT ?,?,generation,?,adapter,?,?,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,number,seq,slot_head,? FROM attempt WHERE attempt_id='attempt'""",
        (identity, f"token-{identity}", step, backlog, identity, B if step == "implement" else None))
    con.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at)
        VALUES (?,1,?,1,?,?,?)""", (identity, f"token-{identity}", B, DIGEST, started))


def test_samples_select_ten_latest_implement_owners_not_runs_or_inherited_environments(registered: sqlite3.Connection) -> None:
    for index in range(12):
        add_owner(registered, f"owner-{index:02}", float(index))
    add_owner(registered, "other-backlog", 1000, backlog="other")
    add_owner(registered, "plan", 1000, step="plan")
    add_owner(registered, "repeat", 1000)
    registered.execute("""UPDATE attempt SET number=2,previous_attempt_id='owner-11',repeat_reason='uncommitted',
        repair_context='{}',after_commit=NULL WHERE attempt_id='repeat'""")
    # Unjoined checks/land runs, and an older run with a newer clock, cannot inflate the report.
    registered.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at)
        SELECT 'checks-or-land',1,'not-an-agent',1,commit_sha,digest,2000 FROM setup_run LIMIT 1""")
    registered.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at)
        SELECT attempt_id,2,dispatch_token,generation,commit_sha,digest,10 FROM setup_run WHERE attempt_id='owner-11'""")
    before = registered.total_changes
    rows = store(registered).samples("tasks")
    assert [(row.attempt_id, row.run) for row in rows] == [
        ("owner-10", 1), ("owner-11", 2), *((f"owner-{index:02}", 1) for index in range(9, 1, -1))]
    assert rows[1].started_at == 10 and rows[1].ended_at is None and rows[1].conclusion is None
    assert all(row.task_id == row.attempt_id and row.repo_id for row in rows)
    assert registered.total_changes == before


@pytest.mark.parametrize(
    "key", [AttemptKey("attempt", "other", 1), AttemptKey("attempt", "dispatch", 2), AttemptKey("other", "dispatch", 1)],
    ids=["token", "generation", "attempt"],
)
def test_a_write_under_another_key_is_refused(registered: sqlite3.Connection, key: AttemptKey) -> None:
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store(registered).start(key, 1, B, DIGEST, 10)
    assert registered.execute("SELECT count(*) FROM setup_run").fetchone() == (0,)


def test_an_unknown_owner_cannot_register_or_conclude_setup(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    foreign = AttemptKey("unowned-conflict", KEY.dispatch_token, KEY.reservation_generation)
    for write in (lambda: setup.start(foreign, 1, B, DIGEST, 10), lambda: setup.registered(foreign, 1, 0, ME),
                  lambda: setup.conclude(foreign, 1, CommandConclusion.PASSED, 0, 11)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert setup.latest(KEY) == SetupRow(1, B, DIGEST, 0, None, None, 10.0, None)


@pytest.mark.parametrize(
    "change", ["DELETE FROM reservation", "UPDATE attempt SET phase='dispatching',base_commit=slot_head"], ids=["released", "dispatched"]
)
def test_every_write_needs_the_held_reservation_of_an_admitted_attempt(registered: sqlite3.Connection, change: str) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    registered.execute(change)
    for write in (lambda: setup.registered(KEY, 1, 0, ME), lambda: setup.conclude(KEY, 1, CommandConclusion.PASSED, 0, 11),
                  lambda: setup.start(KEY, 2, B, DIGEST, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert registered.execute("SELECT run,pid,conclusion FROM setup_run").fetchall() == [(1, None, None)]


def test_a_concluded_run_is_never_rewritten_and_a_run_number_starts_once(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    setup.registered(KEY, 1, 0, ME)
    setup.conclude(KEY, 1, CommandConclusion.FAILED, 3, 11)
    for write in (lambda: setup.registered(KEY, 1, 1, ME), lambda: setup.conclude(KEY, 1, CommandConclusion.PASSED, 0, 12),
                  lambda: setup.start(KEY, 1, B, DIGEST, 13), lambda: setup.conclude(KEY, 2, CommandConclusion.PASSED, 0, 12)):
        with pytest.raises(StoreRefused, match="setup_changed"):
            write()
    assert setup.latest(KEY) == SetupRow(1, B, DIGEST, 0, ME, CommandConclusion.FAILED, 10.0, 11.0)


def test_latest_is_the_highest_run_whatever_the_clock_and_failures_count_only_the_setups_own(registered: sqlite3.Connection) -> None:
    setup = store(registered)
    runs: tuple[tuple[int, CommandConclusion, float], ...] = ((1, CommandConclusion.FAILED, 50.0), (2,
        CommandConclusion.INTERRUPTED, 40.0), (3, CommandConclusion.PASSED, 30.0),
                                                       (4, CommandConclusion.LINGERING, 20.0))
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
    setup.conclude(KEY, 1, CommandConclusion.PASSED, 0, 11)
    assert running(registered, "attempt") is None


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
    setup.conclude(KEY, 1, CommandConclusion.PASSED, 0, 11)
    assert setup.latest(KEY) == SetupRow(1, B, DIGEST, 0, ME, CommandConclusion.PASSED, 10.0, 11.0)
    assert opened.count("registration") == 1


@pytest.mark.parametrize(("conclusion", "held"), [(None, True), (CommandConclusion.LINGERING, True),
    (CommandConclusion.TIMED_OUT, True), (CommandConclusion.FAILED, False),
                                                  (CommandConclusion.PASSED, False), (CommandConclusion.DIRTY,
                                                      False), (CommandConclusion.INTERRUPTED, False)])
def test_a_run_holds_the_slot_while_unfinished_or_concluded_with_a_group_maybe_left(
    conclusion: CommandConclusion | None, held: bool,
) -> None:
    assert SetupRow(1, B, DIGEST, 0, ME, conclusion, 10.0, None).unsettled == (ME if held else None)


def test_a_checks_attempts_setup_runs_are_fenced_by_its_own_held_reservation(checking: sqlite3.Connection) -> None:
    """`setup_run` names an agent attempt or a checks attempt: `HELD` is the union of the two fences."""
    setup = store(checking)
    setup.start(CHECKS, 1, X, DIGEST, 10)
    setup.registered(CHECKS, 1, 0, ME)
    setup.conclude(CHECKS, 1, CommandConclusion.FAILED, 2, 11)
    setup.start(CHECKS, 2, X, DIGEST, 12)
    assert setup.latest(CHECKS) == SetupRow(2, X, DIGEST, 0, None, None, 12.0, None) and setup.failures(CHECKS) == 1
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
    for write in (lambda: setup.registered(CHECKS, 1, 0, ME), lambda: setup.conclude(CHECKS, 1, CommandConclusion.PASSED, 0, 11),
                  lambda: setup.start(CHECKS, 2, X, DIGEST, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert checking.execute("SELECT run,pid,conclusion FROM setup_run").fetchall() == [(1, None, None)]


def test_a_land_candidates_setup_runs_are_fenced_by_its_own_held_reservation_while_pending(landing: sqlite3.Connection) -> None:
    """The third part of `HELD`: a land candidate's setup at S; the released checks attempt's key no longer matches."""
    setup = store(landing)
    setup.start(CANDIDATE, 1, SQUASH, DIGEST, 10)
    setup.registered(CANDIDATE, 1, 0, ME)
    setup.conclude(CANDIDATE, 1, CommandConclusion.PASSED, 0, 11)
    assert setup.latest(CANDIDATE) == SetupRow(1, SQUASH, DIGEST, 0, ME, CommandConclusion.PASSED, 10.0, 11.0)
    for key in (AttemptKey("candidate", "other", 1), AttemptKey("candidate", "candidate-token", 2), CHECKS):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            setup.start(key, 2, SQUASH, DIGEST, 12)


@pytest.mark.parametrize("change", [
    "DELETE FROM reservation", "UPDATE reservation SET generation=2", "UPDATE reservation SET slot='s2'",
    "UPDATE land_candidate SET validation='passed',validated_at=5", "UPDATE land_candidate SET superseded='moved',superseded_at=5",
], ids=["released", "generation", "slot", "concluded", "superseded"])
def test_a_land_candidates_setup_needs_its_held_reservation_while_pending(landing: sqlite3.Connection, change: str) -> None:
    setup = store(landing)
    setup.start(CANDIDATE, 1, SQUASH, DIGEST, 10)
    landing.execute(change)
    for write in (lambda: setup.registered(CANDIDATE, 1, 0, ME), lambda: setup.conclude(CANDIDATE, 1, CommandConclusion.PASSED, 0, 11),
                  lambda: setup.start(CANDIDATE, 2, SQUASH, DIGEST, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert landing.execute("SELECT run,pid,conclusion FROM setup_run").fetchall() == [(1, None, None)]


@pytest.mark.parametrize("conclusion", list(CommandConclusion))
def test_setup_uses_the_canonical_vocabulary_with_its_own_policy(
    registered: sqlite3.Connection, conclusion: CommandConclusion,
) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    if conclusion is CommandConclusion.UNDEFINED:
        with pytest.raises(ValueError, match="Setup cannot be undefined"):
            setup.conclude(KEY, 1, conclusion, None, 11)
        row = setup.latest(KEY)
        assert row is not None and row.conclusion is None
    else:
        setup.conclude(KEY, 1, conclusion, None, 11)
        row = setup.latest(KEY)
        assert row is not None and row.conclusion is conclusion
        assert setup.failures(KEY) == int(conclusion in {
            CommandConclusion.FAILED, CommandConclusion.TIMED_OUT, CommandConclusion.LINGERING, CommandConclusion.DIRTY})


@pytest.mark.parametrize("value", ["undefined", "unknown", b"passed", 1])
def test_malformed_setup_conclusions_keep_the_store_explanation(registered: sqlite3.Connection, value: object) -> None:
    setup = store(registered)
    setup.start(KEY, 1, B, DIGEST, 10)
    registered.execute("PRAGMA ignore_check_constraints=ON")
    registered.execute("UPDATE setup_run SET conclusion=?,ended_at=11", (value,))
    with pytest.raises(StoreUnavailable, match="Malformed setup conclusion"):
        setup.latest(KEY)
