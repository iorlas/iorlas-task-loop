"""`task_hold` and `attempt.label` on real SQLite (v14, tl-8bh9.14.9 section 8): every CHECK rejecting its bad row by its
own expression (each nullable operand's NULL case included); the store's insert fence (current attempt with a label, the
cause current, one hold per attempt), each phase fenced on `rev` and its own predecessor, the comment lease (a live lease
blocks a second poster, an expired one is retaken), the clearing (`superseded` for an unfinished label step) and the
`uncleared` listing; a v13 factory.db refused."""

import re
import sqlite3

import pytest
from doubles import D, X
from sqlite_store import begin_immediate

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.factory_schema import SCHEMA, current
from taskloop.hold_store import COMMENT_LEASE, HoldInsert, HoldRow, HoldStore, Labelled, Uncleared

LABELS_IN = "labels IS NULL OR labels IN ('moved','absent','not_ours','closed','missing','superseded')"
LABELLED_AT = "(labels IS NULL) = (labelled_at IS NULL)"
LEASED = "commented_at IS NULL OR commenting_at IS NOT NULL"
COMMENTS = "commented_at IS NULL OR (labels IS NOT NULL AND labels IN ('moved','absent','not_ours'))"
CLEARED = "cleared_at IS NULL OR labels IS NOT NULL"
REASON = "length(reason) BETWEEN 1 AND 200"
LABEL = "label IS NULL OR length(label) BETWEEN 1 AND 200"


def attempt(con: sqlite3.Connection, attempt_id: str, *, task: str = "tl-1", seq: int = 1, label: str | None = "auto") -> None:
    """An admitted plan attempt 1 of `task` at `seq`, taken under `label` (None: by hand)."""
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,sandbox,deadline,number,seq,slot_head,label) VALUES
        (?,?,1,'plan','beads','tasks',?,'/tracker','r','s1','input.txt','digest',1,'m','e','workspace-write',100,1,?,?,?)""",
        (attempt_id, attempt_id + "-token", task, seq, D, label))


def checks(con: sqlite3.Connection, checks_id: str, after: str, number: int, *, abandoned: bool = False) -> None:
    """A checks attempt `number` of `after` (released and abandoned when `abandoned`)."""
    released = (1.0, D, 1) if abandoned else (None, None, 0)
    con.execute(
        """INSERT INTO checks_attempt (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,
        required,deadline,released_at,parked,abandoned) VALUES (?,?,1,?,?,'s2',?,?,'[]',100,?,?,?)""",
        (checks_id, checks_id + "-token", after, number, D, X, *released))


def put(con: sqlite3.Connection, row: dict[str, object]) -> None:
    con.execute(f"INSERT INTO task_hold ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    """tl-1's current attempt `a` taken under `auto`; tl-2's attempt `hand`, started by hand."""
    with begin_immediate(factory):
        attempt(factory, "a")
        attempt(factory, "hand", task="tl-2", label=None)
    return factory


def store(con: sqlite3.Connection) -> HoldStore:
    return HoldStore(lambda: con)


def held(con: sqlite3.Connection, attempt_id: str = "a", cause: str = "a", now: float = 10.0) -> HoldRow:
    return store(con).insert(HoldInsert(attempt_id, cause, "failed:answer:needs_owner", now))


def later(con: sqlite3.Connection, attempt_id: str = "b", task: str = "tl-1", seq: int = 2) -> None:
    """The task taken again: a later attempt, so the held one is no longer current."""
    with begin_immediate(con):
        attempt(con, attempt_id, task=task, seq=seq)


HELD: dict[str, object] = {"attempt_id": "a", "cause_id": "a", "reason": "failed:run:timeout", "held_at": 10}
MOVED = HELD | {"labels": "moved", "labelled_at": 11}
LEASE = MOVED | {"commenting_at": 12}
COMMENTED = LEASE | {"commented_at": 13}


@pytest.mark.parametrize("row", [
    HELD, MOVED, LEASE, COMMENTED, MOVED | {"labels": "not_ours"}, COMMENTED | {"labels": "absent", "cleared_at": 14},
    HELD | {"labels": "closed", "labelled_at": 11}, HELD | {"labels": "superseded", "labelled_at": 11, "cleared_at": 11},
    HELD | {"commenting_at": 12}, HELD | {"reason": "r" * 200},
], ids=["held", "moved", "lease", "commented", "not_ours", "cleared", "closed", "superseded", "early_lease", "long_reason"])
def test_valid_holds_are_stored(con: sqlite3.Connection, row: dict[str, object]) -> None:
    put(con, row)
    assert con.execute("SELECT rev FROM task_hold").fetchone() == (0,)


@pytest.mark.parametrize(("row", "check"), [
    (HELD | {"reason": ""}, REASON), (HELD | {"reason": "r" * 201}, REASON),
    (HELD | {"labels": "other", "labelled_at": 11}, LABELS_IN),
    (HELD | {"labelled_at": 11}, LABELLED_AT), (MOVED | {"labelled_at": None}, LABELLED_AT),
    (MOVED | {"commented_at": 13}, LEASED),
    (LEASE | {"labels": "closed", "commented_at": 13}, COMMENTS), (LEASE | {"labels": "missing", "commented_at": 13}, COMMENTS),
    (LEASE | {"labels": "superseded", "commented_at": 13}, COMMENTS),
    (HELD | {"commenting_at": 12, "commented_at": 13}, COMMENTS),  # NULL labels with a comment
    (HELD | {"cleared_at": 14}, CLEARED),
], ids=lambda value: ",".join(f"{key}={each}" for key, each in value.items() if HELD.get(key, "-") != each)
    if isinstance(value, dict) else "")
def test_every_hold_check_rejects_its_bad_row(con: sqlite3.Connection, row: dict[str, object], check: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=f"^CHECK constraint failed: {re.escape(check)}$"):
        put(con, row)


@pytest.mark.parametrize(("row", "error"), [
    (HELD | {"reason": None}, "NOT NULL constraint failed: task_hold.reason"),
    (HELD | {"cause_id": None}, "NOT NULL constraint failed: task_hold.cause_id"),
    (HELD | {"held_at": None}, "NOT NULL constraint failed: task_hold.held_at"),
    (HELD | {"attempt_id": "nobody"}, "FOREIGN KEY constraint failed"),
])
def test_a_hold_names_an_attempt_and_has_its_record(con: sqlite3.Connection, row: dict[str, object], error: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=f"^{re.escape(error)}$"):
        put(con, row)


def test_one_hold_per_attempt(con: sqlite3.Connection) -> None:
    put(con, HELD)
    with pytest.raises(sqlite3.IntegrityError, match=r"^UNIQUE constraint failed: task_hold\.attempt_id$"):
        put(con, HELD | {"reason": "other"})


@pytest.mark.parametrize("label", ["", "l" * 201])
def test_the_attempt_label_is_null_or_one_to_200_characters(factory: sqlite3.Connection, label: str) -> None:
    attempt(factory, "x", label="l" * 200)
    attempt(factory, "y", task="tl-2", label=None)
    with pytest.raises(sqlite3.IntegrityError, match=f"^CHECK constraint failed: {re.escape(LABEL)}$"):
        attempt(factory, "z", task="tl-3", label=label)


def test_the_insert_records_the_hold_joined_with_its_attempt(con: sqlite3.Connection) -> None:
    found = held(con)
    assert found == HoldRow("a", "a", "failed:answer:needs_owner", 10.0, None, None, None, None, None, 0, "tasks", "tl-1", "/tracker",
                            "auto")
    assert store(con).of_attempts(("a", "hand", "nobody")) == {"a": found} and store(con).of_attempts(()) == {}


def test_a_hand_started_attempt_is_never_held(con: sqlite3.Connection) -> None:
    with pytest.raises(StoreRefused, match="unlabelled"):
        held(con, "hand", "hand")
    assert store(con).of_attempts(("hand",)) == {}


def test_a_second_insert_or_a_missing_or_superseded_attempt_is_changed(con: sqlite3.Connection) -> None:
    with pytest.raises(StoreRefused, match="changed"):
        held(con, "nobody", "nobody")
    later(con, "c", task="tl-3", seq=2)  # another task's later attempt changes nothing for tl-1
    first = held(con)
    with pytest.raises(StoreRefused, match="changed"):
        held(con, now=20.0)
    assert store(con).of_attempts(("a",)) == {"a": first}
    with begin_immediate(con):
        attempt(con, "a2", task="tl-4")
    later(con, "b2", task="tl-4", seq=2)
    with pytest.raises(StoreRefused, match="changed"):
        held(con, "a2", "a2")


def test_the_cause_must_be_current_agent_attempt_or_its_latest_live_checks_attempt(con: sqlite3.Connection) -> None:
    with begin_immediate(con):
        checks(con, "k1", "a", 1, abandoned=True)
        checks(con, "k2", "a", 2)
    for cause in ("a", "k1", "nobody"):  # a live checks attempt is the task's current: A is no cause; k1 is not the latest
        with pytest.raises(StoreRefused, match="changed"):
            held(con, cause=cause)
    assert held(con, cause="k2").cause_id == "k2"


def test_an_abandoned_latest_checks_attempt_is_no_cause_and_its_agent_attempt_is(con: sqlite3.Connection) -> None:
    with begin_immediate(con):
        checks(con, "k1", "a", 1, abandoned=True)
    with pytest.raises(StoreRefused, match="changed"):
        held(con, cause="k1")
    assert held(con, cause="a").cause_id == "a"


def test_a_checks_cause_of_a_superseded_agent_attempt_is_changed(con: sqlite3.Connection) -> None:
    with begin_immediate(con):
        checks(con, "k1", "a", 1)
    later(con)
    with pytest.raises(StoreRefused, match="changed"):
        held(con, cause="k1")


def test_the_label_step_is_recorded_once_on_the_read_rev(con: sqlite3.Connection) -> None:
    first = held(con)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).labelled("a", first.rev + 1, "moved", 11.0)
    found = store(con).labelled("a", first.rev, "absent", 11.0)
    assert (found.labels, found.labelled_at, found.rev) == ("absent", 11.0, 1)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).labelled("a", found.rev, "moved", 12.0)
    assert store(con).of_attempts(("a",))["a"] == found


@pytest.mark.parametrize("labels", ["closed", "missing"])
def test_no_lease_before_the_label_step_or_after_a_word_that_writes_no_comment(con: sqlite3.Connection, labels: Labelled) -> None:
    first = held(con)
    assert store(con).commenting("a", first.rev, 12.0) is None
    labelled = store(con).labelled("a", first.rev, labels, 11.0)
    assert store(con).commenting("a", labelled.rev, 12.0) is None
    assert store(con).of_attempts(("a",))["a"] == labelled


@pytest.mark.parametrize("labels", ["moved", "absent", "not_ours"])
def test_a_live_lease_blocks_a_second_poster_and_an_expired_one_is_retaken(con: sqlite3.Connection, labels: Labelled) -> None:
    ready = store(con).labelled("a", held(con).rev, labels, 11.0)
    lease = store(con).commenting("a", ready.rev, 100.0)
    assert lease is not None and (lease.commenting_at, lease.rev) == (100.0, ready.rev + 1)
    assert store(con).commenting("a", ready.rev, 100.0) is None  # the loser read before the winner: `rev` moved
    assert store(con).commenting("a", lease.rev, 100.0 + COMMENT_LEASE) is None  # still live at exactly the lease
    retaken = store(con).commenting("a", lease.rev, 100.5 + COMMENT_LEASE)
    assert retaken is not None and retaken.commenting_at == 100.5 + COMMENT_LEASE
    with pytest.raises(StoreRefused, match="changed"):  # the first poster's late record: its lease was retaken
        store(con).commented("a", lease.rev, 300.0)
    done = store(con).commented("a", retaken.rev, 301.0)
    assert (done.commented_at, done.commenting_at) == (301.0, retaken.commenting_at)
    assert store(con).commenting("a", done.rev, 1000.0) is None  # commented: never again
    with pytest.raises(StoreRefused, match="changed"):
        store(con).commented("a", done.rev, 302.0)


def test_the_comment_is_recorded_only_under_a_lease(con: sqlite3.Connection) -> None:
    ready = store(con).labelled("a", held(con).rev, "moved", 11.0)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).commented("a", ready.rev, 12.0)


def test_a_hold_is_cleared_only_after_the_task_was_taken_again(con: sqlite3.Connection) -> None:
    moved = store(con).labelled("a", held(con).rev, "moved", 11.0)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).cleared("a", moved.rev, 20.0)  # still the task's current attempt
    later(con)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).cleared("a", moved.rev + 1, 20.0)
    found = store(con).cleared("a", moved.rev, 20.0)
    assert (found.labels, found.labelled_at, found.cleared_at, found.rev) == ("moved", 11.0, 20.0, moved.rev + 1)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).cleared("a", found.rev, 21.0)


def test_an_unfinished_label_step_is_cleared_as_superseded_in_one_write(con: sqlite3.Connection) -> None:
    first = held(con)
    later(con)
    found = store(con).cleared("a", first.rev, 20.0)
    assert (found.labels, found.labelled_at, found.cleared_at) == ("superseded", 20.0, 20.0)


@pytest.mark.parametrize("labels", ["not_ours", "closed", "missing"])
def test_a_hold_that_added_no_label_is_never_cleared(con: sqlite3.Connection, labels: Labelled) -> None:
    found = store(con).labelled("a", held(con).rev, labels, 11.0)
    later(con)
    with pytest.raises(StoreRefused, match="changed"):
        store(con).cleared("a", found.rev, 20.0)
    assert store(con).uncleared() == ()


# tl-3 .. tl-9: each one's hold `t<n>`, the label step's word (None: unfinished), and whether it is cleared already.
UNCLEARED: tuple[tuple[int, Labelled | None, bool], ...] = (
    (3, "moved", False), (4, "absent", False), (5, None, False), (6, "not_ours", False), (7, "closed", False), (8, "missing", False),
    (9, "moved", True),
)


def test_uncleared_lists_the_holds_that_may_have_added_held_once_their_task_was_taken_again(con: sqlite3.Connection) -> None:
    with begin_immediate(con):
        for number, _, _ in UNCLEARED:
            attempt(con, f"t{number}", task=f"tl-{number}")
    for number, labels, _ in UNCLEARED:
        first = held(con, f"t{number}", f"t{number}", now=float(number))
        if labels is not None:
            store(con).labelled(f"t{number}", first.rev, labels, 11.0)
    store(con).labelled("a", held(con).rev, "moved", 11.0)  # tl-1: still its task's current attempt
    assert store(con).uncleared() == ()
    for number, _, cleared in UNCLEARED:
        later(con, f"n{number}", task=f"tl-{number}", seq=2)
        if cleared:
            store(con).cleared(f"t{number}", 1, 20.0)
    held(con, "n5", "n5", now=30.0)  # tl-5 taken again and held again: its new hold owns `held`
    found = store(con).uncleared()
    assert [(each.row.attempt_id, each.held_again) for each in found] == [("t3", False), ("t4", False), ("t5", True)]
    assert found[0] == Uncleared(store(con).of_attempts(("t3",))["t3"], False)


def test_a_v13_factory_db_is_refused(con: sqlite3.Connection) -> None:
    assert SCHEMA.version == 14 and current(con)
    con.execute("PRAGMA user_version=13")
    for call in (lambda: store(con).of_attempts(("a",)), lambda: held(con), lambda: store(con).uncleared(),
                 lambda: store(con).labelled("a", 0, "moved", 1.0)):
        with pytest.raises(StoreUnavailable):
            call()
