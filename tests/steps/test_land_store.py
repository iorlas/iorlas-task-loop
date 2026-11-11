"""`land_candidate` on real SQLite (v13, tl-8bh9.14.8 section 11): every CHECK rejecting its bad row by its own
expression (each nullable operand's NULL case included), the keys and the partial unique `land_delivered` index; the
store's insert fences, its validation writes off `HELD`, the release's record, supersede, delivery and close."""

import dataclasses
import re
import sqlite3
from collections.abc import Callable

import pytest
from doubles import CANDIDATE, CHECKS, ORIGIN, REQUIRED, SQUASH, D, X
from sqlite_store import begin_immediate

from taskloop import land_store
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, Replaced
from taskloop.check_store import Outcome, Recorded, required_json
from taskloop.factory_schema import SCHEMA, current
from taskloop.land_store import LandAdmitted, LandRow, LandStore, Settled, Validation

ENTRY = (7, "land-start", "boot")
DIGEST = "a" * 64
FAILED_ROW: dict[str, object] = {"validation": "failed", "validated_at": 2, "reason": "test:failed"}


def store(con: sqlite3.Connection) -> LandStore:
    return LandStore(lambda: con)


def rows(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute("SELECT * FROM land_candidate ORDER BY number").fetchall()


def put(con: sqlite3.Connection, row: dict[str, object]) -> None:
    con.execute(f"INSERT INTO land_candidate ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))


# Valid rows of `CHECKS`'s candidate 1; each case below changes one and must fail exactly the CHECK it names.
PENDING: dict[str, object] = {
    "candidate_id": "c1", "dispatch_token": "c1-token", "generation": 1, "checks_attempt_id": "checks", "number": 1,
    "origin_commit": ORIGIN, "commit_sha": SQUASH, "tree_same": 0, "required": required_json(REQUIRED), "slot": "s1", "slot_head": D,
    "deadline": 300,
}
SAME = PENDING | {"tree_same": 1, "slot": None, "slot_head": None, "deadline": None, "validation": "same_tree", "validated_at": 1}
NO_CHANGE = SAME | {"validation": "no_change", "delivery": "no_change", "delivered_at": 1}
PASSED = PENDING | {"validation": "passed", "validated_at": 2}
FAILED = PENDING | FAILED_ROW
RELEASED = PASSED | {"released_at": 3, "parked": D}
PUSHED = SAME | {"delivery": "pushed", "delivered_at": 4, "remote_head": SQUASH}
HOLDING = PENDING | {"entry_pid": 7, "entry_start": "s", "entry_boot": "b"}


@pytest.mark.parametrize("row", [
    PENDING, SAME, NO_CHANGE, PASSED, FAILED, RELEASED, PUSHED, HOLDING, PENDING | {"profile_digest": DIGEST},
    PUSHED | {"close": "closed", "closed_at": 5}, NO_CHANGE | {"close": "already_closed", "closed_at": 5},
    RELEASED | {"delivery": "pushed", "delivered_at": 4, "remote_head": "e" * 40}, SAME | {"superseded": "moved", "superseded_at": 4},
    PENDING | {"released_at": 3, "parked": D, "superseded": "abandoned", "superseded_at": 3},
], ids=["pending", "same_tree", "no_change", "passed", "failed", "released", "pushed", "holding", "profiled", "closed",
        "no_change_closed", "released_pushed", "superseded", "abandoned"])
def test_valid_candidates_are_stored(checking: sqlite3.Connection, row: dict[str, object]) -> None:
    put(checking, row)


SLOTTED = "(slot IS NULL) = (slot_head IS NULL) AND (slot IS NULL) = (deadline IS NULL)"
NO_SLOT = "(slot IS NULL) = (validation IS NOT NULL AND validation IN ('same_tree','no_change'))"
NO_CHANGE_BOTH = "(validation IS 'no_change') = (delivery IS 'no_change')"
VALIDATED = "(validation IS NULL) = (validated_at IS NULL)"
REASON = "(validation IS 'failed') = (reason IS NOT NULL)"
ENTRY_ALL = "(entry_pid IS NULL) = (entry_start IS NULL) AND (entry_pid IS NULL) = (entry_boot IS NULL)"
PARKED = "(released_at IS NULL) = (parked IS NULL)"
SUPERSEDED_AT = "(superseded IS NULL) = (superseded_at IS NULL)"
DELIVERED_AT = "(delivery IS NULL) = (delivered_at IS NULL)"
REMOTE = "(delivery IS 'pushed') = (remote_head IS NOT NULL)"
DELIVERABLE = "delivery IS NULL OR (validation IS NOT NULL AND validation IN ('same_tree','no_change','passed'))"
CLOSED_AT = "(close IS NULL) = (closed_at IS NULL)"


@pytest.mark.parametrize(("row", "check"), [
    (PENDING | {"number": 0}, "number >= 1"), (PENDING | {"origin_commit": "0" * 39}, "length(origin_commit) IN (40,64)"),
    (PENDING | {"commit_sha": "5" * 12}, "length(commit_sha) IN (40,64)"), (PENDING | {"tree_same": 2}, "tree_same IN (0,1)"),
    (PENDING | {"slot_head": "d" * 39}, "slot_head IS NULL OR length(slot_head) IN (40,64)"),
    (PENDING | {"profile_digest": "a" * 63}, "profile_digest IS NULL OR length(profile_digest)=64"),
    (PENDING | {"validation": "ok", "validated_at": 1}, "validation IS NULL OR validation IN ('same_tree','no_change','passed','failed')"),
    (RELEASED | {"parked": "d" * 39}, "parked IS NULL OR length(parked) IN (40,64)"),
    (SAME | {"superseded": "other", "superseded_at": 1}, "superseded IS NULL OR superseded IN ('moved','withdrawn','gone','abandoned')"),
    (SAME | {"delivery": "other", "delivered_at": 1}, "delivery IS NULL OR delivery IN ('pushed','no_change')"),
    (PUSHED | {"remote_head": "5" * 39}, "remote_head IS NULL OR length(remote_head) IN (40,64)"),
    (PUSHED | {"close": "other", "closed_at": 1}, "close IS NULL OR close IN ('closed','already_closed')"),
    (PENDING | {"slot_head": None}, SLOTTED), (PENDING | {"deadline": None}, SLOTTED), (SAME | {"slot_head": D}, SLOTTED),
    (SAME | {"deadline": 1}, SLOTTED),
    (PENDING | {"slot": None, "slot_head": None, "deadline": None}, NO_SLOT),  # NULL validation with no slot
    (PASSED | {"slot": None, "slot_head": None, "deadline": None}, NO_SLOT),
    (PENDING | {"validation": "same_tree", "validated_at": 1}, NO_SLOT),
    (NO_CHANGE | {"delivery": None, "delivered_at": None}, NO_CHANGE_BOTH),
    (SAME | {"delivery": "no_change", "delivered_at": 1}, NO_CHANGE_BOTH),
    (PENDING | {"delivery": "no_change", "delivered_at": 1}, NO_CHANGE_BOTH),  # NULL validation with a no-change delivery
    (PENDING | {"validated_at": 1}, VALIDATED), (PASSED | {"validated_at": None}, VALIDATED),
    (FAILED | {"reason": None}, REASON), (PASSED | {"reason": "x"}, REASON), (PENDING | {"reason": "x"}, REASON),  # NULL validation
    (PENDING | {"entry_pid": 7}, ENTRY_ALL), (PENDING | {"entry_pid": 7, "entry_start": "s"}, ENTRY_ALL),
    (PENDING | {"entry_start": "s", "entry_boot": "b"}, ENTRY_ALL),
    (SAME | {"entry_pid": 7, "entry_start": "s", "entry_boot": "b"}, "entry_pid IS NULL OR slot IS NOT NULL"),
    (RELEASED | {"parked": None}, PARKED), (PASSED | {"parked": D}, PARKED),
    (SAME | {"released_at": 3, "parked": D}, "released_at IS NULL OR slot IS NOT NULL"),
    (SAME | {"superseded": "moved"}, SUPERSEDED_AT), (SAME | {"superseded_at": 4}, SUPERSEDED_AT),
    (PUSHED | {"superseded": "moved", "superseded_at": 5}, "superseded IS NULL OR delivery IS NULL"),
    (SAME | {"delivered_at": 4}, DELIVERED_AT), (PUSHED | {"delivered_at": None}, DELIVERED_AT),
    (PUSHED | {"remote_head": None}, REMOTE), (SAME | {"remote_head": SQUASH}, REMOTE), (NO_CHANGE | {"remote_head": SQUASH}, REMOTE),
    (FAILED | {"delivery": "pushed", "delivered_at": 4, "remote_head": SQUASH}, DELIVERABLE),
    (PENDING | {"delivery": "pushed", "delivered_at": 4, "remote_head": SQUASH}, DELIVERABLE),  # NULL validation with a delivery
    (PUSHED | {"close": "closed"}, CLOSED_AT), (PUSHED | {"closed_at": 5}, CLOSED_AT),
    (SAME | {"close": "closed", "closed_at": 5}, "close IS NULL OR delivery IS NOT NULL"),
], ids=lambda value: ",".join(f"{key}={each}" for key, each in value.items() if PENDING.get(key, "-") != each)
    if isinstance(value, dict) else "")
def test_every_candidate_check_rejects_its_bad_row(checking: sqlite3.Connection, row: dict[str, object], check: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=f"^CHECK constraint failed: {re.escape(check)}$"):
        put(checking, row)


@pytest.mark.parametrize(("row", "error"), [
    (SAME | {"candidate_id": "c2", "dispatch_token": "c2-token"},
     "UNIQUE constraint failed: land_candidate.checks_attempt_id, land_candidate.number"),
    (SAME | {"candidate_id": "c2", "number": 2}, "UNIQUE constraint failed: land_candidate.dispatch_token"),
    (SAME | {"candidate_id": "c2", "dispatch_token": "c2-token", "number": 2, "checks_attempt_id": "missing"}, "FOREIGN KEY"),
])
def test_a_candidate_is_unique_per_number_and_names_a_checks_attempt(
    checking: sqlite3.Connection, row: dict[str, object], error: str
) -> None:
    put(checking, SAME)
    with pytest.raises(sqlite3.IntegrityError, match=error):
        put(checking, row)


def numbered(row: dict[str, object], number: int) -> dict[str, object]:
    return row | {"candidate_id": f"c{number}", "dispatch_token": f"c{number}-token", "number": number}


def test_at_most_one_candidate_of_a_checks_attempt_is_delivered(checking: sqlite3.Connection) -> None:
    put(checking, PUSHED)
    put(checking, numbered(SAME, 2))  # undelivered ones beside it
    put(checking, numbered(FAILED, 3))
    for delivered in (numbered(PUSHED, 4), numbered(NO_CHANGE, 4)):
        with pytest.raises(sqlite3.IntegrityError, match=r"^UNIQUE constraint failed: land_candidate\.checks_attempt_id$"):
            put(checking, delivered)
    assert [row[4] for row in rows(checking)] == [1, 2, 3]


def test_v13_is_current_and_a_v12_factory_db_is_refused(landing: sqlite3.Connection) -> None:
    assert SCHEMA.version == 13 and current(landing) and store(landing).latest("checks") is not None
    landing.execute("PRAGMA user_version=12")
    for call in (lambda: store(landing).latest("checks"), lambda: store(landing).profiled(CANDIDATE, DIGEST)):
        with pytest.raises(StoreUnavailable):
            call()


def test_the_inserted_candidate_reads_back_joined_with_its_task(landing: sqlite3.Connection) -> None:
    found = store(landing).latest("checks")
    assert found is not None and found.key == CANDIDATE and store(landing).of_checks("checks") == (found,)
    assert (found.checks, found.number, found.origin, found.commit, found.tree_same, found.required) == (
        "checks", 1, ORIGIN, SQUASH, False, REQUIRED)
    assert (found.slot, found.slot_head, found.deadline, found.validation, found.validated_at, found.delivery, found.rev) == (
        "s1", D, 300.0, None, None, None, 0)
    assert (found.backlog, found.task_id, found.repo_id, found.tracker_root, found.checked, found.checks_abandoned) == (
        "tasks", "tl-1", "r", "/tracker", X, False)
    assert (found.holds_slot, found.pending, found.pushable) == (True, True, False)
    assert store(landing).latest("other") is None and store(landing).of_checks("other") == ()


def checked(con: sqlite3.Connection, conclusion: str = "passed") -> None:
    """`CHECKS` concluded and released (the `checking` fixture's attempt), its slot s2 free."""
    reason = None if conclusion == "passed" else "test:failed"
    con.execute("""UPDATE checks_attempt SET phase='concluded',conclusion=?,reason=?,concluded_at=5,released_at=6,parked=?
    WHERE attempt_id='checks'""", (conclusion, reason, D))
    con.execute("DELETE FROM reservation")


def admitted(number: int = 1, validation: Settled | None = "same_tree") -> LandAdmitted:
    key = AttemptKey(f"n{number}", f"n{number}-token", 1)
    slot = ("s1", D, 300.0) if validation is None else (None, None, None)
    return LandAdmitted(key, "checks", number, ORIGIN, SQUASH, validation == "same_tree", REQUIRED, *slot, validation, 9.0)


def insert(con: sqlite3.Connection, candidate: LandAdmitted) -> None:
    with begin_immediate(con):
        land_store.insert(con, candidate)


@pytest.mark.parametrize("validation", ["same_tree", "no_change"])
def test_a_candidate_without_a_slot_is_inserted_validated_and_a_no_change_one_delivered(
    checking: sqlite3.Connection, validation: Settled
) -> None:
    checked(checking)
    insert(checking, admitted(validation=validation))
    found = store(checking).latest("checks")
    assert found is not None and (found.slot, found.validation, found.validated_at) == (None, validation, 9.0)
    assert (found.delivery, found.delivered_at) == (("no_change", 9.0) if validation == "no_change" else (None, None))
    assert found.pushable == (validation == "same_tree")


@pytest.mark.parametrize(("change", "validation", "word"), [
    ("SELECT 1", "same_tree", None), ("UPDATE checks_attempt SET released_at=NULL,parked=NULL", "same_tree", "not_checked"),
    ("UPDATE checks_attempt SET abandoned=1", "same_tree", "not_checked"),
    ("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'", "same_tree", "not_checked"),
    ("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'", "no_change", None),  # any conclusion for no change
    ("""INSERT INTO checks_attempt (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,
     required,deadline) VALUES ('rerun','rerun-token',1,'implement',2,'s2',?,?,'[]',100)""", "no_change", "not_checked"),
    ("""INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
     input_digest,schema_version,model,effort,sandbox,deadline,number,seq,slot_head) VALUES ('plan','plan-token',1,'plan','beads',
     'tasks','tl-1','/tracker','r','s1','i','d',1,'m','e','workspace-write',100,1,3,?)""", "same_tree", "not_done"),
    ("UPDATE slot_release SET claim='unclaiming'", "no_change", "not_done"),
], ids=["fenced", "unreleased", "abandoned", "failed", "failed_no_change", "not_latest", "later_attempt", "claim"])
def test_the_insert_needs_the_latest_released_passed_checks_attempt_of_the_current_implement_attempt(
    checking: sqlite3.Connection, change: str, validation: Settled, word: str | None
) -> None:
    checked(checking)
    checking.execute(change, (D,) * change.count("?"))
    if word is None:
        insert(checking, admitted(validation=validation))
        assert len(rows(checking)) == 1
        return
    with pytest.raises(StoreRefused, match=word):
        insert(checking, admitted(validation=validation))
    assert rows(checking) == []


@pytest.mark.parametrize(("latest", "number", "word"), [
    (SAME, 2, "landing"), (PENDING, 2, "landing"), (FAILED, 2, "landing"), (RELEASED, 2, "landing"), (PUSHED, 2, "landing"),
    (RELEASED | {"superseded": "withdrawn", "superseded_at": 4}, 3, "landing"),
    (SAME | {"superseded": "moved", "superseded_at": 4}, 1, "landing"),
    (SAME | {"superseded": "moved", "superseded_at": 4}, 2, None), (FAILED | {"released_at": 3, "parked": D}, 2, None),
], ids=["pushable", "pending", "failed_holding", "passed", "delivered", "skipped_number", "taken_number", "superseded", "failed"])
def test_the_insert_is_refused_landing_while_a_candidate_is_delivered_pushable_or_holds_its_slot(
    checking: sqlite3.Connection, latest: dict[str, object], number: int, word: str | None
) -> None:
    checked(checking)
    put(checking, latest)
    before = rows(checking)
    if word is None:
        insert(checking, admitted(number))
        assert [row[4] for row in rows(checking)] == [1, 2]
        return
    with pytest.raises(StoreRefused, match=word):
        insert(checking, admitted(number))
    assert rows(checking) == before


def test_a_delivered_earlier_candidate_refuses_any_later_insert(checking: sqlite3.Connection) -> None:
    checked(checking)
    put(checking, PUSHED)
    put(checking, numbered(SAME | {"superseded": "moved", "superseded_at": 5}, 2))  # only past the store's fences
    with pytest.raises(StoreRefused, match="landing"):
        insert(checking, admitted(3))


def validation_writes(lands: LandStore, key: AttemptKey) -> dict[str, Callable[[], object]]:
    return {"renew": lambda: lands.renew(key, 900), "profiled": lambda: lands.profiled(key, DIGEST),
            "conclude": lambda: lands.conclude(key, "passed", None, 20)}


@pytest.mark.parametrize(("change", "key"), [
    ("SELECT 1", AttemptKey("candidate", "other", 1)), ("SELECT 1", AttemptKey("candidate", "candidate-token", 2)),
    ("SELECT 1", CHECKS), ("DELETE FROM reservation", CANDIDATE), ("UPDATE reservation SET slot='s2'", CANDIDATE),
    ("UPDATE land_candidate SET validation='failed',reason='x',validated_at=5", CANDIDATE),
    ("UPDATE land_candidate SET superseded='moved',superseded_at=5", CANDIDATE),
], ids=["token", "generation", "checks_key", "released", "slot", "concluded", "superseded"])
def test_every_validation_write_needs_a_pending_candidate_holding_its_reservation(
    landing: sqlite3.Connection, change: str, key: AttemptKey
) -> None:
    lands = store(landing)
    landing.execute(change)
    before = rows(landing)
    for name, write in validation_writes(lands, key).items():
        with pytest.raises(StoreRefused, match="stale_reservation"):
            write()
        assert rows(landing) == before, name
    assert lands.hold(key, ENTRY) == "refused" and rows(landing) == before


def latest(con: sqlite3.Connection) -> LandRow:
    found = store(con).latest("checks")
    assert found is not None
    return found


def test_the_land_process_holds_once_and_is_replaced_only_naming_the_stored_identity(landing: sqlite3.Connection) -> None:
    lands = store(landing)
    assert lands.hold(CANDIDATE, ENTRY) == "accepted"
    assert (latest(landing).entry, latest(landing).rev) == (ENTRY, 1)
    assert lands.hold(CANDIDATE, ENTRY) == "conflict"  # itself
    assert lands.hold(CANDIDATE, (8, "s", "boot")) == "conflict"  # not naming the stored one
    assert lands.hold(CANDIDATE, (8, "s", "boot"), Replaced((9, "x", "boot"), "gone")) == "conflict"  # naming another
    assert lands.hold(CANDIDATE, (8, "s", "boot"), Replaced(ENTRY, "gone")) == "accepted"
    assert (latest(landing).entry, latest(landing).rev) == ((8, "s", "boot"), 2)


def test_renew_profiled_and_conclude_write_a_pending_candidate(landing: sqlite3.Connection) -> None:
    lands = store(landing)
    lands.renew(CANDIDATE, 900)
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError, match="finite"):
            lands.renew(CANDIDATE, bad)
    lands.profiled(CANDIDATE, DIGEST)
    lands.profiled(CANDIDATE, "b" * 64)
    with pytest.raises(StoreUnavailable):  # a reason exactly when failed (the CHECK)
        lands.conclude(CANDIDATE, "passed", "test:failed", 20)
    lands.conclude(CANDIDATE, "failed", "test:failed", 20)
    found = latest(landing)
    assert (found.deadline, found.profile_digest, found.validation, found.reason, found.validated_at, found.rev) == (
        900.0, DIGEST, "failed", "test:failed", 20.0, 1)
    assert (found.pending, found.pushable, found.holds_slot) == (False, False, True)


def released(con: sqlite3.Connection, read: tuple[int, Validation | None], abandoned: bool, key: AttemptKey = CANDIDATE) -> bool:
    """Whether the record released it (`released` or `abandoned`); `recorded` gives the word."""
    return recorded(con, read, abandoned, key) in ("released", "abandoned")


def recorded(con: sqlite3.Connection, read: tuple[int, Validation | None], abandoned: bool, key: AttemptKey = CANDIDATE) -> Recorded:
    with begin_immediate(con):
        return land_store.record_release(con, key, read, D, 30, abandoned)


def release_columns(con: sqlite3.Connection) -> tuple[object, ...]:
    return con.execute("SELECT released_at,parked,superseded,superseded_at FROM land_candidate").fetchone()


def test_a_settled_release_needs_a_validation_and_the_proofs_rev_and_records_once(landing: sqlite3.Connection) -> None:
    assert not released(landing, (0, None), False)  # pending: only an abandon releases it
    store(landing).conclude(CANDIDATE, "passed", None, 20)
    assert not released(landing, (0, "passed"), False)  # the rev moved since the proof read
    assert not released(landing, (1, None), False)
    assert not released(landing, (1, "passed"), False, AttemptKey("candidate", "other", 1))
    assert released(landing, (1, "passed"), False)
    assert not released(landing, (1, "passed"), False)  # released already
    assert release_columns(landing) == (30.0, D, None, None) and latest(landing).pushable


@pytest.mark.parametrize(("outcome", "reason"), [(None, None), ("failed", "test:failed")])
def test_an_abandon_releases_a_pending_or_failed_candidate_and_supersedes_it(
    landing: sqlite3.Connection, outcome: str | None, reason: str | None
) -> None:
    if outcome == "failed":
        store(landing).conclude(CANDIDATE, "failed", reason, 20)
    read = (0, None) if outcome is None else (1, "failed")
    assert released(landing, read, True)
    assert release_columns(landing) == (30.0, D, "abandoned", 30.0) and not released(landing, read, True)


@pytest.mark.parametrize(("change", "word"), [
    ("UPDATE land_candidate SET validation='passed',validated_at=20", "landing"),
    ("UPDATE land_candidate SET validation='passed',validated_at=20,delivery='pushed',delivered_at=21,remote_head=commit_sha", "landed"),
    ("DELETE FROM reservation", "changed"),
], ids=["pushable", "delivered", "unreserved"])
def test_an_abandon_never_releases_a_pushable_delivered_or_unreserved_candidate(
    landing: sqlite3.Connection, change: str, word: str
) -> None:
    """The checks record's words: `landing` (S may be on origin), `landed` (it is), `changed` off the fence."""
    landing.execute(change)
    validation = latest(landing).validation
    assert recorded(landing, (0, validation), True) == word
    assert release_columns(landing)[0] is None


def test_a_pending_candidate_is_never_superseded_but_by_its_abandon_release(landing: sqlite3.Connection) -> None:
    """Superseded while it holds its slot unvalidated, it could neither conclude (`HELD`) nor be released settled: its
    reservation would be held for ever. Only the abandon release supersedes it (`abandoned`)."""
    lands = store(landing)
    assert not lands.supersede(CANDIDATE, "moved", 7) and not lands.supersede(CANDIDATE, "withdrawn", 7)
    assert not lands.supersede(CANDIDATE, "gone", 7)
    assert latest(landing).pending
    assert released(landing, (0, None), True) and release_columns(landing) == (30.0, D, "abandoned", 30.0)


@pytest.mark.parametrize(("outcome", "reason"), [("passed", None), ("failed", "test:failed")], ids=["passed", "failed"])
@pytest.mark.parametrize("abandon", [False, True], ids=["settled", "abandon"])
def test_a_superseded_validated_candidate_still_holding_its_slot_is_released_by_either_mode(
    landing: sqlite3.Connection, outcome: Outcome, reason: str | None, abandon: bool
) -> None:
    """A rerun of the land finds its passed candidate's release held, then origin moved: superseded `moved` with the slot
    still reserved; the release (`Next: release`, or the task's abandon) frees it and keeps the reason."""
    lands = store(landing)
    lands.conclude(CANDIDATE, outcome, reason, 20)
    assert lands.supersede(CANDIDATE, "moved", 25)
    assert latest(landing).holds_slot and not latest(landing).pushable
    assert released(landing, (1, outcome), abandon)
    assert release_columns(landing) == (30.0, D, "moved", 25.0)
    assert landing.execute("SELECT count(*) FROM reservation").fetchone() == (1,)  # the reservation is the caller's `free`


def test_a_pending_candidate_superseded_past_the_fences_is_still_released_by_the_abandon(landing: sqlite3.Connection) -> None:
    landing.execute("UPDATE land_candidate SET superseded='moved',superseded_at=20")
    assert not released(landing, (0, None), False)  # not validated: no settled release
    assert released(landing, (0, None), True) and release_columns(landing) == (30.0, D, "moved", 20.0)


def test_supersede_is_fenced_not_delivered_and_once(checking: sqlite3.Connection) -> None:
    put(checking, SAME)
    put(checking, numbered(PUSHED, 2))
    lands = store(checking)
    assert lands.supersede(AttemptKey("c1", "c1-token", 1), "withdrawn", 7)
    assert not lands.supersede(AttemptKey("c1", "c1-token", 1), "moved", 8)  # once
    assert not lands.supersede(AttemptKey("c2", "c2-token", 1), "gone", 8)  # delivered
    assert not lands.supersede(AttemptKey("c1", "other", 1), "gone", 8)
    assert [(row.superseded, row.superseded_at, row.pushable) for row in lands.of_checks("checks")] == [
        ("withdrawn", 7.0, False), (None, None, False)]


@pytest.mark.parametrize(("row", "word"), [
    (SAME, None), (RELEASED, None), (PASSED, None), (PENDING, "land_changed"), (FAILED, "land_changed"), (NO_CHANGE, "land_changed"),
    (PUSHED, "land_changed"), (SAME | {"superseded": "gone", "superseded_at": 3}, "land_changed"),
], ids=["same_tree", "released", "passed_holding", "pending", "failed", "no_change", "delivered", "superseded"])
def test_a_delivery_is_recorded_once_and_only_for_a_pushable_candidate(
    checking: sqlite3.Connection, row: dict[str, object], word: str | None
) -> None:
    put(checking, row)
    key = AttemptKey("c1", "c1-token", 1)
    if word is not None:
        before = rows(checking)
        with pytest.raises(StoreRefused, match=word):
            store(checking).record_delivery(key, "e" * 40, 7)
        assert rows(checking) == before
        return
    store(checking).record_delivery(key, "e" * 40, 7)
    found = latest(checking)
    assert (found.delivery, found.remote_head, found.delivered_at, found.pushable) == ("pushed", "e" * 40, 7.0, False)


def test_a_second_delivered_candidate_of_one_checks_attempt_is_refused(checking: sqlite3.Connection) -> None:
    put(checking, PUSHED)
    put(checking, numbered(SAME, 2))  # only past the store's insert fence
    with pytest.raises(StoreRefused, match="land_changed"):
        store(checking).record_delivery(AttemptKey("c2", "c2-token", 1), SQUASH, 8)
    assert [row.delivery for row in store(checking).of_checks("checks")] == ["pushed", None]


@pytest.mark.parametrize("row", [PUSHED, NO_CHANGE], ids=["pushed", "no_change"])
def test_a_close_is_recorded_once_for_a_delivered_candidate(checking: sqlite3.Connection, row: dict[str, object]) -> None:
    put(checking, row)
    put(checking, numbered(SAME | {"superseded": "moved", "superseded_at": 3}, 2))
    lands, key = store(checking), AttemptKey("c1", "c1-token", 1)
    for refused in (AttemptKey("c2", "c2-token", 1), AttemptKey("c1", "other", 1)):
        with pytest.raises(StoreRefused, match="land_changed"):
            lands.record_close(refused, "closed", 8)
    lands.record_close(key, "already_closed", 8)
    with pytest.raises(StoreRefused, match="land_changed"):
        lands.record_close(key, "closed", 9)
    assert (lands.of_checks("checks")[0].close, lands.of_checks("checks")[0].closed_at) == ("already_closed", 8.0)


@pytest.mark.parametrize("column", ["validation='ok'", "superseded='ok'", "entry_pid=8", "required='[]'"])
def test_a_malformed_stored_candidate_is_unavailable(landing: sqlite3.Connection, column: str) -> None:
    landing.execute("PRAGMA ignore_check_constraints=ON")
    landing.execute(f"UPDATE land_candidate SET {column}")
    with pytest.raises(StoreUnavailable):
        store(landing).latest("checks")


def rerun(con: sqlite3.Connection) -> None:
    """`CHECKS` failed and released, then its re-run `rerun` (number 2) passed and released: candidates put directly."""
    checked(con, "failed")
    con.execute("""INSERT INTO checks_attempt (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,
    required,deadline,phase,conclusion,concluded_at,released_at,parked) VALUES ('rerun','rerun-token',1,'implement',2,'s2',?,?,?,100,
    'concluded','passed',7,8,?)""", (D, ORIGIN, required_json(REQUIRED), D))


def test_one_delivery_per_task_across_a_checks_re_run(checking: sqlite3.Connection) -> None:
    """A no-change land delivered on the failed checks attempt 1 (its close failed), then checks re-run (only past the
    admission's fence): neither a new candidate of the re-run nor a delivery of one put anyway is accepted."""
    rerun(checking)
    put(checking, NO_CHANGE)
    with pytest.raises(StoreRefused, match="landing"):
        insert(checking, dataclasses.replace(admitted(), checks="rerun"))
    put(checking, numbered(SAME, 2) | {"checks_attempt_id": "rerun", "number": 1})
    with pytest.raises(StoreRefused, match="land_changed"):
        store(checking).record_delivery(AttemptKey("c2", "c2-token", 1), SQUASH, 9)
    assert [row.delivery for row in store(checking).of_checks("rerun")] == [None]
