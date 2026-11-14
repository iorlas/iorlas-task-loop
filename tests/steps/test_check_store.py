"""`checks_attempt` and `check_result` on real SQLite: every CHECK rejecting its bad row, the store's fences (the key,
the held reservation, `admitted`), its phase and block transitions, the refusal counter, the entry registration without a
deadline refusal, the admission's insert and the release's record; a land candidate's results through `RESULT_HELD`
only, and the abandon fence `LANDING` (v13, tl-8bh9.14.8 section 11)."""

import sqlite3
from collections.abc import Callable

import pytest
from doubles import CANDIDATE, CHECKS, ORIGIN, REQUIRED, SQUASH, TARGET, D, X
from sqlite_store import begin_immediate
from stream_proc import OwnedProcess

from taskloop import check_store, land_store
from taskloop.attempt_reads import AttemptReads, StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, Replaced
from taskloop.check_store import ChecksAdmitted, CheckStore, Conclusion, Recorded, ResultRow, latest_results, record_release, unsettled

ENTRY = (7, "entry-start", "boot")
ME = OwnedProcess(501, 501, "start-501", "boot")
DIGEST = "a" * 64


def store(con: sqlite3.Connection) -> CheckStore:
    return CheckStore(lambda: con)


def columns(con: sqlite3.Connection, sql: str) -> list[tuple[object, ...]]:
    return con.execute(sql).fetchall()


# A valid concluded-and-released checks attempt; each case overrides columns and must fail one CHECK (or the key rules).
ATTEMPT: dict[str, object] = {
    "attempt_id": "other", "dispatch_token": "other-token", "generation": 1, "after_attempt_id": "implement", "number": 2,
    "slot": "s2", "slot_head": D, "target_commit": TARGET, "target_seen": None, "required": "[]", "profile_digest": None,
    "deadline": 100, "phase": "concluded", "rev": 0, "refusal": None, "refusals": 0, "conclusion": "passed", "reason": None,
    "concluded_at": 5, "released_at": 6, "parked": D, "abandoned": 0,
}


def put(con: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    con.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))


@pytest.mark.parametrize("change", [
    {}, {"phase": "admitted", "conclusion": None, "concluded_at": None, "released_at": None, "parked": None},
    {"phase": "admitted", "conclusion": None, "concluded_at": None, "abandoned": 1},
    {"conclusion": "failed", "reason": "test:failed"}, {"target_seen": TARGET, "profile_digest": DIGEST},
])
def test_valid_checks_attempts_are_stored(checking: sqlite3.Connection, change: dict[str, object]) -> None:
    put(checking, "checks_attempt", ATTEMPT | change)


@pytest.mark.parametrize("change", [
    {"number": 0}, {"slot_head": "d" * 39}, {"target_commit": "f" * 12}, {"profile_digest": "a" * 63},
    {"phase": "running"}, {"refusals": -1}, {"conclusion": "ok"}, {"abandoned": 2},
    {"phase": "admitted"}, {"conclusion": None, "concluded_at": None},  # phase and conclusion
    {"concluded_at": None}, {"conclusion": None, "phase": "admitted", "released_at": None, "parked": None},  # concluded_at
    {"conclusion": "failed"}, {"reason": "nothing"},  # a reason exactly when failed
    {"parked": None}, {"released_at": None},  # released and parked together
    {"released_at": None, "parked": None, "abandoned": 1},  # abandoned only once released
    {"phase": "admitted", "conclusion": None, "concluded_at": None},  # released settled only once concluded
    {"refusal": "slot_busy"}, {"refusals": 1},  # a refusal word exactly when counted
    {"entry_pid": 7}, {"entry_pid": 7, "entry_start": "s"}, {"entry_start": "s", "entry_boot": "b"},  # an entry all or none
], ids=lambda change: ",".join(f"{key}={value}" for key, value in change.items()))
def test_every_checks_attempt_check_rejects_its_bad_row(checking: sqlite3.Connection, change: dict[str, object]) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        put(checking, "checks_attempt", ATTEMPT | change)


@pytest.mark.parametrize(("change", "error"), [
    ({"number": 1}, "UNIQUE constraint failed: checks_attempt.after_attempt_id"),
    ({"dispatch_token": "checks-token"}, "UNIQUE constraint failed: checks_attempt.dispatch_token"),
    ({"after_attempt_id": "missing"}, "FOREIGN KEY"),
])
def test_a_checks_attempt_is_unique_per_number_and_names_an_attempt(
    checking: sqlite3.Connection, change: dict[str, object], error: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=error):
        put(checking, "checks_attempt", ATTEMPT | change)


RESULT: dict[str, object] = {
    "attempt_id": "checks", "block": 1, "position": 0, "name": "check", "dispatch_token": "checks-token", "generation": 1,
    "argv_digest": DIGEST, "timeout": 60, "started_at": 1, "ended_at": 2, "rc": 0, "conclusion": "passed",
}
UNDEFINED: dict[str, object] = {"argv_digest": None, "timeout": None, "rc": None, "conclusion": "undefined"}


@pytest.mark.parametrize("change", [{}, {"ended_at": None, "rc": None, "conclusion": None}, UNDEFINED, {"conclusion": "interrupted"},
                                    {"pid": 5, "pgid": 5, "proc_start": "s", "boot": "b"}])
def test_valid_check_results_are_stored(checking: sqlite3.Connection, change: dict[str, object]) -> None:
    put(checking, "check_result", RESULT | change)


@pytest.mark.parametrize("change", [
    {"block": 0}, {"position": -1}, {"argv_digest": "a" * 63}, {"timeout": 0}, {"conclusion": "ok"},
    {"ended_at": None}, {"conclusion": None},  # ended exactly when concluded
    {"argv_digest": None, "timeout": None},  # no argv only when undefined
    UNDEFINED | {"argv_digest": DIGEST, "timeout": 60},  # undefined has no argv
    {"timeout": None}, UNDEFINED | {"timeout": 60},  # a timeout exactly with an argv
    {"pid": 5}, {"pid": 5, "pgid": 5, "proc_start": "s"}, {"pgid": 5, "proc_start": "s", "boot": "b"},  # an identity all or none
    UNDEFINED | {"pid": 5, "pgid": 5, "proc_start": "s", "boot": "b"}, UNDEFINED | {"rc": 0},  # undefined ran nothing
    {"ended_at": None, "conclusion": None},  # an exit only with a conclusion
], ids=lambda change: ",".join(f"{key}={value}" for key, value in change.items()))
def test_every_check_result_check_rejects_its_bad_row(checking: sqlite3.Connection, change: dict[str, object]) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        put(checking, "check_result", RESULT | change)


@pytest.mark.parametrize(("change", "error"), [
    ({"name": "test"}, "UNIQUE constraint failed: check_result.attempt_id, check_result.block, check_result.position"),
    ({"position": 1}, "UNIQUE constraint failed: check_result.attempt_id, check_result.block, check_result.name"),
])
def test_a_result_is_one_per_position_and_name_in_a_block(
    checking: sqlite3.Connection, change: dict[str, object], error: str
) -> None:
    put(checking, "check_result", RESULT)
    with pytest.raises(sqlite3.IntegrityError, match=error):
        put(checking, "check_result", RESULT | change)


def test_the_admitted_row_reads_back_joined_with_its_implement_attempt(checking: sqlite3.Connection) -> None:
    found = store(checking).row(CHECKS)
    assert found is not None and found.key == CHECKS
    assert (found.after, found.number, found.slot, found.slot_head, found.target, found.required, found.deadline) == (
        "implement", 1, "s2", D, TARGET, REQUIRED, 100.0)
    assert (found.backlog, found.task_id, found.repo_id, found.tracker_root, found.commit) == ("tasks", "tl-1", "r", "/tracker", X)
    assert (found.phase, found.entry, found.rev, found.refusal, found.refusals, found.conclusion, found.released_at,
            found.abandoned, found.profile_digest, found.target_seen) == ("admitted", None, 0, None, 0, None, None, False, None, None)
    assert store(checking).of_attempt("implement") == (found,) and store(checking).of_attempt("other") == ()
    assert store(checking).row(AttemptKey("checks", "checks-token", 2)) is None


def admitted(number: int, attempt_id: str = "next", required: tuple[tuple[str, str], ...] = REQUIRED) -> ChecksAdmitted:
    return ChecksAdmitted(AttemptKey(attempt_id, attempt_id + "-token", 1), "implement", number, "s1", D, TARGET, required, 200.0)


def test_a_second_admission_of_the_same_number_lost_the_race_and_writes_nothing(checking: sqlite3.Connection) -> None:
    before = columns(checking, "SELECT attempt_id,number FROM checks_attempt")
    with begin_immediate(checking), pytest.raises(StoreRefused, match="task_attempted"):
        check_store.insert(checking, admitted(1))
    assert columns(checking, "SELECT attempt_id,number FROM checks_attempt") == before
    with begin_immediate(checking):
        check_store.insert(checking, admitted(2))
    assert [row.number for row in store(checking).of_attempt("implement")] == [1, 2]


@pytest.mark.parametrize("required", [(), tuple((f"c{n}", DIGEST) for n in range(33)), (("a", DIGEST), ("a", DIGEST)), (("a", "a" * 40),)],
                         ids=["none", "33", "repeated", "digest"])
def test_the_required_list_is_one_to_32_distinct_names_with_digests(
    checking: sqlite3.Connection, required: tuple[tuple[str, str], ...]
) -> None:
    with pytest.raises(ValueError, match="required"):
        check_store.insert(checking, admitted(2, required=required))


@pytest.mark.parametrize("stored", ["not json", "{}", '[["check"]]', "[]", '[["check", 1]]'])
def test_a_malformed_stored_required_list_is_unavailable(checking: sqlite3.Connection, stored: str) -> None:
    checking.execute("UPDATE checks_attempt SET required=?", (stored,))
    with pytest.raises(StoreUnavailable):
        store(checking).row(CHECKS)


def writes(checks: CheckStore, key: AttemptKey) -> dict[str, Callable[[], object]]:
    """Every fenced write of an admitted checks attempt, under `key`."""
    return {
        "refused": lambda: checks.refused(key, "slot_busy"), "profiled": lambda: checks.profiled(key, DIGEST),
        "block": lambda: checks.block(key), "start": lambda: checks.start(key, 1, 1, "test", DIGEST, 60, 3),
        "undefined": lambda: checks.undefined(key, 1, 2, "smoke", 3), "registered": lambda: checks.registered(key, 1, 0, ME),
        "finish": lambda: checks.finish(key, 1, 0, "passed", 0, 4), "conclude": lambda: checks.conclude(key, "passed", None, 5),
    }


def snapshot(con: sqlite3.Connection) -> tuple[list[tuple[object, ...]], ...]:
    return (columns(con, "SELECT * FROM checks_attempt ORDER BY attempt_id"),
            columns(con, "SELECT * FROM check_result ORDER BY attempt_id,block,position"))


@pytest.mark.parametrize("key", [AttemptKey("checks", "other", 1), AttemptKey("checks", "checks-token", 2),
                                 AttemptKey("implement", "implement-token", 1)], ids=["token", "generation", "agent_attempt"])
def test_every_write_under_another_key_is_stale_and_writes_nothing(checking: sqlite3.Connection, key: AttemptKey) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    before = snapshot(checking)
    for name, write in writes(checks, key).items():
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
        assert snapshot(checking) == before, name


@pytest.mark.parametrize("change", ["DELETE FROM reservation", "UPDATE reservation SET generation=2",
                                    "UPDATE reservation SET slot='s1'", "UPDATE checks_attempt SET phase='concluded',"
                                    "conclusion='passed',concluded_at=5"], ids=["released", "generation", "slot", "concluded"])
def test_every_write_needs_the_held_reservation_of_an_admitted_attempt(checking: sqlite3.Connection, change: str) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    checking.execute(change)
    before = snapshot(checking)
    for name, write in writes(checks, CHECKS).items():
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
        assert snapshot(checking) == before, name


def test_a_block_runs_its_results_once_and_only_the_latest_block_is_read(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    assert checks.block(CHECKS) == 1 and checks.block(CHECKS) == 1  # no result yet: still block 1
    checks.undefined(CHECKS, 1, 2, "smoke", 2)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    checks.registered(CHECKS, 1, 0, ME)
    checks.finish(CHECKS, 1, 0, "passed", 0, 3)
    checks.start(CHECKS, 1, 1, "test", DIGEST, 60, 3)
    assert [(row.name, row.conclusion) for row in checks.results(CHECKS)] == [("check", "passed"), ("test", None), ("smoke", "undefined")]
    assert checks.results(CHECKS)[0] == ResultRow(1, 0, "check", DIGEST, 60, ME, 2.0, 3.0, 0, "passed")
    assert checks.results(CHECKS)[2] == ResultRow(1, 2, "smoke", None, None, None, 2.0, 2.0, None, "undefined")
    assert checks.block(CHECKS) == 2
    checks.start(CHECKS, 2, 0, "check", DIGEST, 60, 4)
    assert [(row.block, row.name) for row in checks.results(CHECKS)] == [(2, "check")]
    assert latest_results(checking, "checks") == checks.results(CHECKS)


@pytest.mark.parametrize(("block", "position", "name"), [(1, 3, "lint"), (2, 3, "test"), (2, 0, "lint"), (3, 3, "lint")],
                         ids=["older_block", "name_taken", "position_taken", "skipped_block"])
def test_a_result_start_outside_the_latest_or_next_block_or_taken_is_check_changed(
    checking: sqlite3.Connection, block: int, position: int, name: str
) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    latest = 1 if block == 3 else 2
    checks.start(CHECKS, latest, 2 - latest, "test", DIGEST, 60, 2)  # block 2 position 0, or block 1 position 1
    before = snapshot(checking)
    with pytest.raises(StoreRefused, match="check_changed"):
        checks.start(CHECKS, block, position, name, DIGEST, 60, 3)
    assert snapshot(checking) == before


def test_a_result_registers_once_concludes_once_and_never_in_an_older_block(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    checks.registered(CHECKS, 1, 0, ME)
    for write in (lambda: checks.registered(CHECKS, 1, 0, ME), lambda: checks.registered(CHECKS, 1, 5, ME),
                  lambda: checks.finish(CHECKS, 1, 5, "passed", 0, 3)):
        with pytest.raises(StoreRefused, match="check_changed"):
            write()
    checks.finish(CHECKS, 1, 0, "timed_out", None, 3)
    with pytest.raises(StoreRefused, match="check_changed"):
        checks.finish(CHECKS, 1, 0, "passed", 0, 4)
    checks.start(CHECKS, 1, 1, "test", DIGEST, 60, 4)
    checks.start(CHECKS, 2, 0, "check", DIGEST, 60, 5)
    for write in (lambda: checks.registered(CHECKS, 1, 1, ME), lambda: checks.finish(CHECKS, 1, 1, "interrupted", None, 6)):
        with pytest.raises(StoreRefused, match="check_changed"):  # block 1 is no longer the latest
            write()
    with pytest.raises(ValueError, match="undefined"):
        checks.finish(CHECKS, 2, 0, "undefined", None, 6)
    assert columns(checking, "SELECT block,position,pid,conclusion,rc FROM check_result ORDER BY block,position") == [
        (1, 0, 501, "timed_out", None), (1, 1, None, None, None), (2, 0, None, None, None)]


def test_only_the_identity_write_uses_the_registration_connection(checking: sqlite3.Connection) -> None:
    opened: list[str] = []

    def connect(name: str) -> Callable[[], sqlite3.Connection]:
        return lambda: (opened.append(name), checking)[1]

    checks = CheckStore(connect("main"), registering=AttemptReads(connect("registration")))
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    checks.registered(CHECKS, 1, 0, ME)
    checks.finish(CHECKS, 1, 0, "passed", 0, 3)
    assert opened == ["main", "registration", "main"]


@pytest.mark.parametrize(("conclusion", "listed"), [(None, True), ("lingering", True), ("timed_out", True), ("interrupted", True),
                                                    ("passed", False), ("failed", False), ("dirty", False)])
def test_unsettled_is_every_unfinished_or_live_after_result_of_the_latest_block(
    checking: sqlite3.Connection, conclusion: Conclusion | None, listed: bool
) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)  # an older block's unfinished row is never listed
    checks.start(CHECKS, 2, 0, "check", DIGEST, 60, 3)
    checks.registered(CHECKS, 2, 0, ME)
    checks.undefined(CHECKS, 2, 1, "smoke", 3)
    checks.start(CHECKS, 2, 2, "test", DIGEST, 60, 3)  # never registered: listed, with no identity
    if conclusion is not None:
        checks.finish(CHECKS, 2, 0, conclusion, None, 4)
    found = [(row.position, row.process) for row in unsettled(checking, "checks")]
    assert found == ([(0, ME)] if listed else []) + [(2, None)]


def test_the_refusal_counter_counts_every_relaunch_whatever_its_word_and_only_a_conclusion_clears_it(
    checking: sqlite3.Connection,
) -> None:
    """Two words alternating (an uncertain start, then its command still running) still reach `stuck:checks_refused`;
    `refusal` is the last word, for display."""
    checks = store(checking)

    def counted() -> tuple[object, ...]:
        return checking.execute("SELECT refusal,refusals FROM checks_attempt WHERE attempt_id='checks'").fetchone()

    assert (checks.refused(CHECKS, "environment:uncertain"), checks.refused(CHECKS, "checks:running")) == (1, 2)
    assert counted() == ("checks:running", 2)
    checks.refused(CHECKS, "checks:uncertain")  # raised inside block 1; the relaunch repeats the block
    assert checks.block(CHECKS) == 1 and counted() == ("checks:uncertain", 3)
    checks.conclude(CHECKS, "failed", "expired", 9)
    assert counted() == (None, 0)


def test_the_profile_digest_is_written_once(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    checks.profiled(CHECKS, DIGEST)
    checks.profiled(CHECKS, "b" * 64)
    found = checks.row(CHECKS)
    assert found is not None and found.profile_digest == DIGEST


def test_conclude_is_the_one_phase_change_and_a_concluded_attempt_takes_no_more_writes(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    checks.start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    with pytest.raises(StoreUnavailable):  # a reason exactly when failed (the CHECK)
        checks.conclude(CHECKS, "passed", "test:failed", 5)
    with pytest.raises(StoreUnavailable):
        checks.conclude(CHECKS, "failed", None, 5)
    checks.refused(CHECKS, "slot_busy")
    checks.conclude(CHECKS, "failed", "main_moved", 5, seen="e" * 40)
    found = checks.row(CHECKS)
    assert found is not None
    assert (found.phase, found.conclusion, found.reason, found.concluded_at, found.target_seen, found.rev, found.refusals) == (
        "concluded", "failed", "main_moved", 5.0, "e" * 40, 1, 0)
    before = snapshot(checking)
    for name, write in writes(checks, CHECKS).items():
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
        assert snapshot(checking) == before, name


def entry(checking: sqlite3.Connection) -> tuple[object, ...]:
    return checking.execute("SELECT entry_pid,entry_start,entry_boot,deadline,rev FROM checks_attempt WHERE attempt_id='checks'").fetchone()


def test_one_entry_registers_while_admitted_and_a_passed_deadline_is_not_refused(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    assert checks.register_entry(CHECKS, ENTRY, 500) == "accepted"  # past the deadline: it runs only to conclude `expired`
    assert entry(checking) == (*ENTRY, 100.0, 1)
    assert checks.register_entry(CHECKS, (8, "s", "boot"), 1) == "conflict"  # not naming the stored identity
    assert checks.register_entry(CHECKS, ENTRY, 1, Replaced(ENTRY, "gone")) == "conflict"  # itself
    assert checks.register_entry(CHECKS, (8, "s", "boot"), 1, Replaced(ENTRY, "gone"), renewed=900) == "accepted"
    assert entry(checking) == (8, "s", "boot", 100.0, 2)  # the same boot: no renewal
    assert checks.attempt_of("tasks", "tl-1") == (CHECKS, "admitted", (8, "s", "boot"))


@pytest.mark.parametrize(("renewed", "deadline"), [(900.0, 900.0), (50.0, 100.0), (float("inf"), 100.0), (float("nan"), 100.0)])
def test_another_boots_replacement_renews_the_deadline_to_the_later_finite_one(
    checking: sqlite3.Connection, renewed: float, deadline: float
) -> None:
    checks = store(checking)
    checks.register_entry(CHECKS, ENTRY, 1)
    assert checks.register_entry(CHECKS, (9, "s", "boot-2"), 1, Replaced(ENTRY, "gone"), renewed=renewed) == "accepted"
    assert entry(checking) == (9, "s", "boot-2", deadline, 2)


@pytest.mark.parametrize(("change", "key", "answer"), [
    ("SELECT 1", AttemptKey("checks", "other", 1), "refused"), ("DELETE FROM reservation", CHECKS, "refused"),
    ("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5", CHECKS, "conflict"),
], ids=["key", "reservation", "concluded"])
def test_a_registration_off_the_fence_writes_nothing(checking: sqlite3.Connection, change: str, key: AttemptKey, answer: str) -> None:
    checking.execute(change)
    assert store(checking).register_entry(key, ENTRY, 1) == answer and entry(checking) == (None, None, None, 100.0, 0)


def test_attempt_of_is_the_latest_checks_attempt_of_the_tasks_current_agent_attempt(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    assert checks.attempt_of("tasks", "tl-2") is None
    with begin_immediate(checking):
        check_store.insert(checking, admitted(2))
    assert checks.attempt_of("tasks", "tl-1") == (AttemptKey("next", "next-token", 1), "admitted", None)
    checking.execute(  # a fresh plan after an abandon: the task's current attempt has no checks attempt
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
        input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head) VALUES ('plan','plan-token',1,'plan','beads',
        'tasks','tl-1','/tracker','r','s1','i','d',1,'m','e','{"harness":"codex","sandbox":"workspace-write"}',100,1,3,?)""", (D,))
    assert checks.attempt_of("tasks", "tl-1") is None


def released(con: sqlite3.Connection, read: tuple[int, str], abandoned: bool, key: AttemptKey = CHECKS) -> Recorded:
    with begin_immediate(con):
        return record_release(con, key, read, D, 7, abandoned)


def test_a_settled_release_needs_a_conclusion_and_records_once(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    assert released(checking, (0, "admitted"), False) == "changed"
    checks.conclude(CHECKS, "passed", None, 5)
    assert released(checking, (0, "concluded"), False) == "changed"  # the rev moved since the proof read
    assert released(checking, (1, "admitted"), False) == "changed"
    assert released(checking, (1, "concluded"), False) == "released"
    assert released(checking, (1, "concluded"), False) == "changed"  # released already
    found = checks.row(CHECKS)
    assert found is not None and (found.released_at, found.parked, found.abandoned) == (7.0, D, False)


@pytest.mark.parametrize("change", ["DELETE FROM reservation", "UPDATE reservation SET generation=2"])
def test_a_release_needs_the_held_reservation(checking: sqlite3.Connection, change: str) -> None:
    checking.execute(change)
    assert released(checking, (0, "admitted"), True) == "changed"
    assert released(checking, (0, "admitted"), True, AttemptKey("checks", "other", 1)) == "changed"


def test_an_abandon_releases_an_admitted_attempt_and_an_abandon_of_a_released_one_flips_only_the_latest(
    checking: sqlite3.Connection,
) -> None:
    checks = store(checking)
    assert checks.abandon_released(CHECKS) == "changed"  # not released yet
    checks.conclude(CHECKS, "failed", "test:failed", 5)
    assert released(checking, (1, "concluded"), False) == "released"
    with begin_immediate(checking):
        check_store.insert(checking, admitted(2))
        checking.execute("INSERT INTO reservation VALUES ('s1','r',1,'next')")
    later = AttemptKey("next", "next-token", 1)
    assert checks.abandon_released(CHECKS) == "changed"  # no longer the latest
    assert released(checking, (0, "admitted"), True, later) == "abandoned"  # the abandon of an admitted one releases it abandoned
    assert checks.abandon_released(later) == "changed"  # already abandoned
    assert [(row.number, row.abandoned) for row in checks.of_attempt("implement")] == [(1, False), (2, True)]


def test_an_abandon_of_the_latest_released_checks_attempt_flips_it_once(checking: sqlite3.Connection) -> None:
    checks = store(checking)
    checks.conclude(CHECKS, "passed", None, 5)
    assert released(checking, (1, "concluded"), False) == "released"
    assert checks.abandon_released(CHECKS) == "abandoned" and checks.abandon_released(CHECKS) == "changed"
    assert checks.abandon_released(AttemptKey("checks", "other", 1)) == "changed"
    found = checks.row(CHECKS)
    assert found is not None and found.abandoned


@pytest.mark.parametrize("identity", ["pid=5", "entry_pid=8"], ids=["result", "entry"])
def test_a_partial_stored_identity_is_unavailable_not_a_missing_one(checking: sqlite3.Connection, identity: str) -> None:
    """Only a row written past the CHECKs can hold one: a read refuses it rather than reading no process."""
    store(checking).start(CHECKS, 1, 0, "check", DIGEST, 60, 2)
    checking.execute("PRAGMA ignore_check_constraints=ON")
    checking.execute(f"UPDATE {'check_result' if identity == 'pid=5' else 'checks_attempt'} SET {identity}")
    with pytest.raises(StoreUnavailable, match="identity"):
        store(checking).results(CHECKS) if identity == "pid=5" else store(checking).row(CHECKS)


def test_an_abandoned_or_released_checks_attempt_is_never_offered_to_the_launcher_as_admitted(checking: sqlite3.Connection) -> None:
    """An abandon releases an `admitted` checks attempt without a conclusion: the launcher's read says `released`."""
    checks = store(checking)
    assert released(checking, (0, "admitted"), True) == "abandoned"
    assert checks.attempt_of("tasks", "tl-1") == (CHECKS, "released", None)
    with begin_immediate(checking):
        check_store.insert(checking, admitted(2))
        checking.execute("INSERT INTO reservation VALUES ('s1','r',1,'next')")
    later = AttemptKey("next", "next-token", 1)
    checks.conclude(later, "passed", None, 5)
    assert checks.attempt_of("tasks", "tl-1") == (later, "concluded", None)
    assert released(checking, (1, "concluded"), False, later) == "released"
    assert checks.attempt_of("tasks", "tl-1") == (later, "released", None)


def candidate_rows(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return columns(con, "SELECT block,position,name,pid,conclusion FROM check_result WHERE attempt_id='candidate' ORDER BY block,position")


def test_a_pending_land_candidates_block_and_results_are_written_under_its_own_key(landing: sqlite3.Connection) -> None:
    """`CheckSink` serves a candidate key unchanged: the result and block writes take `RESULT_HELD`."""
    checks = store(landing)
    assert checks.block(CANDIDATE) == 1
    checks.start(CANDIDATE, 1, 0, "check", DIGEST, 60, 11)
    checks.registered(CANDIDATE, 1, 0, ME)
    checks.finish(CANDIDATE, 1, 0, "passed", 0, 12)
    checks.undefined(CANDIDATE, 1, 1, "smoke", 12)
    assert candidate_rows(landing) == [(1, 0, "check", 501, "passed"), (1, 1, "smoke", None, "undefined")]
    assert checks.results(CANDIDATE)[0] == ResultRow(1, 0, "check", DIGEST, 60, ME, 11.0, 12.0, 0, "passed")
    assert columns(landing, "SELECT count(*) FROM check_result WHERE attempt_id='checks'") == [(0,)]


def test_no_checks_attempt_write_can_match_a_land_candidates_key(landing: sqlite3.Connection) -> None:
    """`refused`, `profiled`, `conclude` and the entry registration keep the checks-only fence (`HELD`)."""
    checks = store(landing)
    before = snapshot(landing), columns(landing, "SELECT * FROM land_candidate")
    for name, write in {"refused": lambda: checks.refused(CANDIDATE, "slot_busy"), "profiled": lambda: checks.profiled(CANDIDATE, DIGEST),
                        "conclude": lambda: checks.conclude(CANDIDATE, "passed", None, 5)}.items():
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
        assert (snapshot(landing), columns(landing, "SELECT * FROM land_candidate")) == before, name
    assert checks.register_entry(CANDIDATE, ENTRY, 1) == "refused" and checks.row(CANDIDATE) is None


@pytest.mark.parametrize("change", [
    "DELETE FROM reservation", "UPDATE reservation SET generation=2", "UPDATE reservation SET slot='s2'",
    "UPDATE land_candidate SET validation='failed',reason='test:failed',validated_at=5",
    "UPDATE land_candidate SET superseded='moved',superseded_at=5",
], ids=["released", "generation", "slot", "concluded", "superseded"])
def test_a_candidates_result_writes_need_it_pending_with_its_held_reservation(landing: sqlite3.Connection, change: str) -> None:
    checks = store(landing)
    checks.start(CANDIDATE, 1, 0, "check", DIGEST, 60, 11)
    landing.execute(change)
    for write in (lambda: checks.block(CANDIDATE), lambda: checks.start(CANDIDATE, 1, 1, "test", DIGEST, 60, 12),
                  lambda: checks.undefined(CANDIDATE, 1, 2, "smoke", 12), lambda: checks.registered(CANDIDATE, 1, 0, ME),
                  lambda: checks.finish(CANDIDATE, 1, 0, "passed", 0, 12)):
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
    assert candidate_rows(landing) == [(1, 0, "check", None, None)]


def candidate(con: sqlite3.Connection, number: int, **columns: object) -> None:
    """A candidate of `CHECKS` put directly (no store fence), with its columns."""
    row: dict[str, object] = {"candidate_id": f"c{number}", "dispatch_token": f"c{number}-token", "generation": 1,
                              "checks_attempt_id": "checks", "number": number, "origin_commit": ORIGIN, "commit_sha": SQUASH,
                              "tree_same": 1, "required": "[]", "validation": "same_tree", "validated_at": 1}
    put(con, "land_candidate", row | columns)


SLOTTED: dict[str, object] = {"tree_same": 0, "slot": "s1", "slot_head": D, "deadline": 300, "validation": None, "validated_at": None}
PUSHED: dict[str, object] = {"delivery": "pushed", "delivered_at": 4, "remote_head": SQUASH}
LAND_STATES = [  # (the latest candidate's columns, the abandon's word)
    ({}, "landing"),  # pushable: same tree
    (SLOTTED, "landing"),  # pending, holding its slot
    (SLOTTED | {"validation": "failed", "validated_at": 2, "reason": "test:failed"}, "landing"),  # failed, still holding it
    (SLOTTED | {"validation": "passed", "validated_at": 2, "released_at": 3, "parked": D}, "landing"),  # pushable: passed
    (PUSHED, "landed"), (SLOTTED | {"validation": "passed", "validated_at": 2} | PUSHED, "landed"),  # delivered
    (PUSHED | {"close": "closed", "closed_at": 5}, "closed"),  # delivered and closed
    ({"superseded": "withdrawn", "superseded_at": 3}, "abandoned"),
    (SLOTTED | {"validation": "failed", "validated_at": 2, "reason": "test:failed", "released_at": 3, "parked": D}, "abandoned"),
    (SLOTTED | {"released_at": 3, "parked": D, "superseded": "abandoned", "superseded_at": 3}, "abandoned"),
]


@pytest.mark.parametrize(("change", "word"), LAND_STATES, ids=["same_tree", "pending", "failed_held", "passed", "pushed",
                                                               "pushed_held", "closed", "withdrawn", "failed", "abandoned"])
def test_the_abandon_of_a_released_checks_attempt_is_fenced_by_its_land_candidates(
    checking: sqlite3.Connection, change: dict[str, object], word: str
) -> None:
    """A candidate first, then the abandon: `LANDING` refuses it (delivered `landed`, `closed` once it closed the task;
    pushable or holding a slot `landing`) and changes nothing; a superseded or released failed one does not."""
    checks = store(checking)
    checks.conclude(CHECKS, "passed", None, 5)
    assert released(checking, (1, "concluded"), False) == "released"
    candidate(checking, 1, superseded="moved", superseded_at=2)  # an earlier, superseded candidate never refuses
    candidate(checking, 2, **change)
    assert checks.abandon_released(CHECKS) == word
    found = checks.row(CHECKS)
    assert found is not None and found.abandoned == (word == "abandoned")


@pytest.mark.parametrize(("change", "word"), LAND_STATES[:7],
                         ids=["same_tree", "pending", "failed_held", "passed", "pushed", "pushed_held", "closed"])
def test_the_abandon_release_of_an_unreleased_checks_attempt_is_fenced_by_its_land_candidates(
    checking: sqlite3.Connection, change: dict[str, object], word: str
) -> None:
    """Only rows put past the store's fences can hold one (a candidate needs a released checks attempt): still refused."""
    candidate(checking, 1, **change)
    assert released(checking, (0, "admitted"), True) == word
    assert columns(checking, "SELECT released_at,abandoned FROM checks_attempt") == [(None, 0)]


def test_the_abandon_first_then_no_candidate_is_inserted_or_delivered(checking: sqlite3.Connection) -> None:
    """The other race order: the abandon committed first; a land's insert refuses `not_checked`, and a delivery of a
    candidate put anyway refuses `abandoned`."""
    checks = store(checking)
    checks.conclude(CHECKS, "passed", None, 5)
    assert released(checking, (1, "concluded"), False) == "released"
    assert checks.abandon_released(CHECKS) == "abandoned"
    admitted = land_store.LandAdmitted(CANDIDATE, "checks", 1, ORIGIN, SQUASH, True, REQUIRED, None, None, None, "same_tree", 9)
    with begin_immediate(checking), pytest.raises(StoreRefused, match="not_checked"):
        land_store.insert(checking, admitted)
    candidate(checking, 1)
    with pytest.raises(StoreRefused, match="abandoned"):
        land_store.LandStore(lambda: checking).record_delivery(AttemptKey("c1", "c1-token", 1), SQUASH, 10)
    assert columns(checking, "SELECT number,delivery FROM land_candidate") == [(1, None)]


def test_the_abandon_of_a_checks_re_run_sees_the_land_candidates_of_the_earlier_checks_attempts(checking: sqlite3.Connection) -> None:
    """A no-change land delivered on the failed checks attempt 1, the close failed, checks re-run (2): the re-run's abandon
    still refuses `landed`, so the claim is not returned while the code is on `main`."""
    checks = store(checking)
    checks.conclude(CHECKS, "failed", "test:failed", 5)
    assert released(checking, (1, "concluded"), False) == "released"
    candidate(checking, 1, validation="no_change", delivery="no_change", delivered_at=1)
    with begin_immediate(checking):
        check_store.insert(checking, admitted(2))
        checking.execute("INSERT INTO reservation VALUES ('s1','r',1,'next')")
    later = AttemptKey("next", "next-token", 1)
    assert released(checking, (0, "admitted"), True, later) == "landed"
    checks.conclude(later, "failed", "test:failed", 6)
    assert released(checking, (1, "concluded"), False, later) == "released"
    assert checks.abandon_released(later) == "landed"
    assert [row.abandoned for row in checks.of_attempt("implement")] == [False, False]
