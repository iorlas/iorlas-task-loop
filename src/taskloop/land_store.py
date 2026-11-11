"""The one writer of `land_candidate`: a land candidate S of a checked X onto origin's `main` at O, from its insert to its
validation, release, delivery and close (tl-8bh9.14.8 section 11).

A candidate copies no task fact: every read joins its checks attempt and that attempt's implement attempt for the task,
the repository, the tracker root and X. "Latest" is always the highest `number` of one checks attempt, never a clock
order. The insert (`insert`) and the release's record (`record_release`) are functions on the caller's connection,
inside its write transaction (the one that reserves the slot, the one that frees it). Every validation write of a
candidate (`hold`, `renew`, `profiled`, `conclude`) is fenced by `HELD`: its key, pending (no validation, not
superseded) and its reservation held at the key's generation; a mismatch is `StoreRefused("stale_reservation")`. Its
results and setup runs go to `check_result` and `setup_run` under its key, through `check_store.RESULT_HELD` and
`setup_store.HELD`. A delivery or close off its fence is `StoreRefused("land_changed")`, a delivery for an abandoned
checks attempt `StoreRefused("abandoned")`.
"""

import math
import sqlite3
from dataclasses import astuple, dataclass
from typing import Final, Literal

from taskloop.attempt_reads import StoreConnection, StoreRefused, as_int, as_nullable_text, as_text
from taskloop.attempt_types import AttemptKey, EntryIdentity, Replaced
from taskloop.check_store import (
    Outcome,
    Required,
    required_json,
    stored_entry,
    stored_nullable_real,
    stored_required,
    stored_word,
)
from taskloop.factory_schema import CANDIDATE_HELD, CANDIDATE_RESERVED, LAND_ADMITTED, LAND_LOADED, LATER, marks, prefixed

type Validation = Literal["same_tree", "no_change", "passed", "failed"]
type Settled = Literal["same_tree", "no_change"]  # a candidate inserted validated, with no slot
type Superseded = Literal["moved", "withdrawn", "gone", "abandoned"]
type Delivery = Literal["pushed", "no_change"]
type Close = Literal["closed", "already_closed"]
VALIDATIONS: Final[tuple[Validation, ...]] = ("same_tree", "no_change", "passed", "failed")
PUSHABLE: Final[tuple[Validation, ...]] = ("same_tree", "passed")
SUPERSEDED: Final[tuple[Superseded, ...]] = ("moved", "withdrawn", "gone", "abandoned")
DELIVERIES: Final[tuple[Delivery, ...]] = ("pushed", "no_change")
CLOSES: Final[tuple[Close, ...]] = ("closed", "already_closed")
HELD: Final = CANDIDATE_HELD  # bound with the key; also the land half of `check_store.RESULT_HELD`
KEYED: Final = " WHERE candidate_id=? AND dispatch_token=? AND generation=?"
LOADED: Final = (f"SELECT {prefixed('l', LAND_LOADED)},a.backlog,a.task_id,a.repo_id,a.tracker_root,a.end_commit,c.abandoned "
                 "FROM land_candidate l JOIN checks_attempt c ON c.attempt_id=l.checks_attempt_id "
                 "JOIN attempt a ON a.attempt_id=c.after_attempt_id")
# The insert's checks fence: the checks attempt is the latest of its implement attempt, released and not abandoned (so
# concluded); the implement attempt current (no `LATER` attempt of the task) and its claim `kept`.
CHECKED: Final = """SELECT c.conclusion,(SELECT 1 FROM attempt p JOIN slot_release x ON x.attempt_id=p.attempt_id
WHERE p.attempt_id=c.after_attempt_id AND x.claim='kept' AND NOT """ + LATER + """)
FROM checks_attempt c WHERE c.attempt_id=? AND c.released_at IS NOT NULL AND c.abandoned=0
AND c.number=(SELECT max(d.number) FROM checks_attempt d WHERE d.after_attempt_id=c.after_attempt_id)"""


@dataclass(frozen=True)
class LandAdmitted:
    """What the insert stores: O, S, whether S's tree is X's, the required names at O; the slot, its D and the deadline
    when S is validated in a slot (`validation` None), else none of them and `validation` `same_tree` or `no_change`."""

    key: AttemptKey  # the candidate id, its dispatch token and its reservation's generation
    checks: str  # the checks attempt of X
    number: int
    origin: str  # O
    commit: str  # S
    tree_same: bool
    required: Required
    slot: str | None
    slot_head: str | None
    deadline: float | None
    validation: Settled | None
    now: float


@dataclass(frozen=True)
class LandRow:
    """One candidate joined with its checks attempt and implement attempt (the task, the repository, X)."""

    key: AttemptKey
    checks: str
    number: int
    origin: str  # O
    commit: str  # S
    tree_same: bool
    required: Required
    slot: str | None
    slot_head: str | None  # D: the release parks here
    deadline: float | None
    profile_digest: str | None
    entry: EntryIdentity | None  # the land process holding the slot's custody
    validation: Validation | None
    reason: str | None
    validated_at: float | None
    released_at: float | None
    parked: str | None
    superseded: Superseded | None
    superseded_at: float | None
    delivery: Delivery | None
    delivered_at: float | None
    remote_head: str | None
    close: Close | None
    closed_at: float | None
    rev: int
    backlog: str
    task_id: str
    repo_id: str
    tracker_root: str
    checked: str  # X
    checks_abandoned: bool

    @property
    def holds_slot(self) -> bool:
        return self.slot is not None and self.released_at is None

    @property
    def pending(self) -> bool:
        """Validating in its slot: no validation yet, not superseded."""
        return self.holds_slot and self.validation is None and self.superseded is None

    @property
    def pushable(self) -> bool:
        return self.validation in PUSHABLE and self.delivery is None and self.superseded is None


def _row(row: tuple[object, ...]) -> LandRow:
    return LandRow(
        AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), as_text(row[3]), as_int(row[4]), as_text(row[5]),
        as_text(row[6]), bool(as_int(row[7])), stored_required(row[8]), as_nullable_text(row[9]), as_nullable_text(row[10]),
        stored_nullable_real(row[11]), as_nullable_text(row[12]), stored_entry(row[13:16]), stored_word(row[16], VALIDATIONS),
        as_nullable_text(row[17]), stored_nullable_real(row[18]), stored_nullable_real(row[19]), as_nullable_text(row[20]),
        stored_word(row[21], SUPERSEDED), stored_nullable_real(row[22]), stored_word(row[23], DELIVERIES), stored_nullable_real(row[24]),
        as_nullable_text(row[25]), stored_word(row[26], CLOSES), stored_nullable_real(row[27]), as_int(row[28]), as_text(row[29]),
        as_text(row[30]), as_text(row[31]), as_text(row[32]), as_text(row[33]), bool(as_int(row[34])),
    )


def of_checks_on(con: sqlite3.Connection, checks: str) -> tuple[LandRow, ...]:
    """Every candidate of one checks attempt, by number (the last is the latest), on the caller's connection."""
    return tuple(_row(row) for row in con.execute(LOADED + " WHERE l.checks_attempt_id=? ORDER BY l.number", (checks,)).fetchall())


def insert(con: sqlite3.Connection, admitted: LandAdmitted) -> None:
    """The candidate's row, in the caller's write transaction (with `admit.reserve` when it validates in a slot). Fenced:
    the checks attempt the latest of its implement attempt, released, not abandoned and `passed` (any conclusion for
    `no_change`), else `not_checked`; the implement attempt current with its claim `kept`, else `not_done`; no candidate
    of it delivered, the latest neither holding a slot nor pushable, and `number` the latest plus one, else `landing`."""
    checked = con.execute(CHECKED, (admitted.checks,)).fetchone()
    if checked is None or (checked[0] != "passed" and admitted.validation != "no_change"):
        raise StoreRefused("not_checked")
    if checked[1] is None:
        raise StoreRefused("not_done")
    earlier = of_checks_on(con, admitted.checks)
    latest = earlier[-1] if earlier else None
    blocked = latest is not None and (latest.holds_slot or latest.pushable)
    if blocked or any(row.delivery is not None for row in earlier) or admitted.number != len(earlier) + 1:
        raise StoreRefused("landing")
    no_change = admitted.validation == "no_change"  # delivered at insert: no slot, no push
    values = (*astuple(admitted.key), admitted.checks, admitted.number, admitted.origin, admitted.commit, int(admitted.tree_same),
              required_json(admitted.required), admitted.slot, admitted.slot_head, admitted.deadline, admitted.validation,
              None if admitted.validation is None else admitted.now, "no_change" if no_change else None,
              admitted.now if no_change else None)
    con.execute(f"INSERT INTO land_candidate ({LAND_ADMITTED}) VALUES ({marks(LAND_ADMITTED)})", values)


def record_release(
    con: sqlite3.Connection, key: AttemptKey, read: tuple[int, Validation | None], parked: str, now: float, abandoned: bool,
) -> bool:
    """The release's record, in the release's transaction: fenced on the `rev` and validation its stop proof `read`, the
    held reservation and no earlier release; settled (not `abandoned`) only once validated. An abandon releases only a
    pending or failed candidate (never a pushable or delivered one) and marks it superseded `abandoned`. False off the
    fence."""
    fenced = con.execute("SELECT l.rev,l.validation,l.released_at,l.superseded,l.delivery " + CANDIDATE_RESERVED, astuple(key)).fetchone()
    if fenced is None or (fenced[0], fenced[1]) != read or fenced[2] is not None:
        return False
    if not abandoned:
        if read[1] is None:
            return False
        con.execute("UPDATE land_candidate SET released_at=?,parked=? WHERE candidate_id=?", (now, parked, key.attempt_id))
        return True
    if read[1] not in (None, "failed") or fenced[3] is not None or fenced[4] is not None:
        return False
    con.execute("UPDATE land_candidate SET released_at=?,parked=?,superseded='abandoned',superseded_at=? WHERE candidate_id=?",
                (now, parked, now, key.attempt_id))
    return True


class LandStore(StoreConnection):
    """The fenced writes and the reads of land candidates."""

    def latest(self, checks: str) -> LandRow | None:
        """The checks attempt's latest candidate (its highest `number`); None before the first."""
        found = self.of_checks(checks)
        return found[-1] if found else None

    def of_checks(self, checks: str) -> tuple[LandRow, ...]:
        with self._connection() as con:
            return of_checks_on(con, checks)

    def _held(self, con: sqlite3.Connection, key: AttemptKey) -> None:
        if con.execute(HELD, astuple(key)).fetchone() is None:
            raise StoreRefused("stale_reservation")

    def hold(self, key: AttemptKey, entry: EntryIdentity, replacing: Replaced | None = None) -> Literal["accepted", "conflict", "refused"]:
        """The land process's identity, written under the slot's custody (`register_entry`'s rule): one while pending; a
        replacement names the exact stored identity (observed gone); `refused` off `HELD`."""
        with self._connection(write=True) as con:
            if con.execute(HELD, astuple(key)).fetchone() is None:
                return "refused"
            found = con.execute("SELECT entry_pid,entry_start,entry_boot FROM land_candidate" + KEYED, astuple(key)).fetchone()
            stored = stored_entry(tuple(found))
            if entry == stored or stored != (None if replacing is None else replacing.identity):
                return "conflict"
            con.execute("UPDATE land_candidate SET entry_pid=?,entry_start=?,entry_boot=?,rev=rev+1 WHERE candidate_id=?",
                        (*entry, key.attempt_id))
            return "accepted"

    def renew(self, key: AttemptKey, deadline: float) -> None:
        """A rerun's new deadline (`now + --minutes`: the person's new command is new consent)."""
        if not math.isfinite(deadline):
            raise ValueError("deadline: a finite time")
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute("UPDATE land_candidate SET deadline=? WHERE candidate_id=?", (deadline, key.attempt_id))

    def profiled(self, key: AttemptKey, digest: str) -> None:
        """The profile digest at S, written once (S is immutable)."""
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute("UPDATE land_candidate SET profile_digest=coalesce(profile_digest,?) WHERE candidate_id=?",
                        (digest, key.attempt_id))

    def conclude(self, key: AttemptKey, outcome: Outcome, reason: str | None, now: float) -> None:
        """The validation's one conclusion (a reason exactly when `failed`: the CHECK)."""
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute("UPDATE land_candidate SET validation=?,reason=?,validated_at=?,rev=rev+1 WHERE candidate_id=?",
                        (outcome, reason, now, key.attempt_id))

    def supersede(self, key: AttemptKey, why: Literal["moved", "withdrawn", "gone"], now: float) -> bool:
        """History from now on: fenced not delivered and not already superseded. False off the fence."""
        with self._connection(write=True) as con:
            fenced = " AND delivery IS NULL AND superseded IS NULL"
            changed = con.execute("UPDATE land_candidate SET superseded=?,superseded_at=?" + KEYED + fenced, (why, now, *astuple(key)))
            return changed.rowcount == 1

    def record_delivery(self, key: AttemptKey, remote_head: str, now: float) -> None:
        """S observed on origin's `main` (`remote_head` S, or a later tip containing it): fenced pushable and its checks
        attempt not abandoned (`abandoned`: by `LANDING` it cannot happen after a pushable candidate)."""
        with self._connection(write=True) as con:
            abandoned = con.execute("SELECT c.abandoned FROM land_candidate l JOIN checks_attempt c ON c.attempt_id=l.checks_attempt_id "
                                    "WHERE l.candidate_id=? AND l.dispatch_token=? AND l.generation=?", astuple(key)).fetchone()
            if abandoned is not None and abandoned[0]:
                raise StoreRefused("abandoned")
            try:
                changed = con.execute(
                    "UPDATE land_candidate SET delivery='pushed',remote_head=?,delivered_at=?" + KEYED
                    + " AND delivery IS NULL AND superseded IS NULL AND validation IN ('same_tree','passed')",
                    (remote_head, now, *astuple(key))).rowcount
            except sqlite3.IntegrityError as error:  # another candidate of the checks attempt delivered (`land_delivered`)
                raise StoreRefused("land_changed") from error
            if changed != 1:
                raise StoreRefused("land_changed")

    def record_close(self, key: AttemptKey, close: Close, now: float) -> None:
        """The task closed in the tracker (`closed`, or `already_closed` when found so): once, fenced delivered."""
        with self._connection(write=True) as con:
            changed = con.execute("UPDATE land_candidate SET close=?,closed_at=?" + KEYED + " AND delivery IS NOT NULL AND close IS NULL",
                                  (close, now, *astuple(key))).rowcount
            if changed != 1:
                raise StoreRefused("land_changed")
