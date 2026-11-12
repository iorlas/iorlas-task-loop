"""The one writer of `task_hold`: a hold of a round-taken task's agent attempt A, from its record to its tracker writes'
phases and its clearing (tl-8bh9.14.9 sections 5, 7.3 and 8).

A hold row copies no task fact: every read joins A for the task, its tracker root and the approval label it was taken
under (`attempt.label`). The insert is fenced on A being the task's current attempt with a label and its cause still
current (A itself, or A's latest checks attempt, not abandoned), and on no hold of A existing. Every later write is
fenced on the `rev` its caller read and on its own phase, and bumps `rev`; a write off its fence is
`StoreRefused("changed")`, except the comment lease, whose loser gets None and does nothing.

Phases, in order: `labels` with `labelled_at` (the tracker's label step, 5.2's word), `commenting_at` (the comment lease:
taken only while no comment is recorded and no live lease exists, one live lease at a time for `COMMENT_LEASE` seconds),
`commented_at` (the comment is posted), `cleared_at` (the task was taken again: `held` is the factory's to remove; a row
whose label step never finished is `superseded` in the same write). A hold whose cause is gone before it finished is
deleted (`retire`); a failed comment call gives its lease back (`uncommenting`).
"""

import sqlite3
from dataclasses import dataclass
from typing import Final, Literal

from taskloop.attempt_reads import StoreConnection, StoreRefused, as_int, as_text
from taskloop.check_store import stored_nullable_real, stored_real, stored_word
from taskloop.factory_schema import HOLD, LATER, LATEST_CHECKS, SUCCESSOR, marks, prefixed

type Labels = Literal["moved", "absent", "not_ours", "closed", "missing", "superseded"]
type Labelled = Literal["moved", "absent", "not_ours", "closed", "missing"]  # the label step's own words (5.2)
LABELS: Final[tuple[Labels, ...]] = ("moved", "absent", "not_ours", "closed", "missing", "superseded")
COMMENTED: Final = "('moved','absent','not_ours')"  # the label words after which the hold writes its comment
COMMENT_LEASE: Final = 120.0  # seconds: longer than one bd call of `TrackerHolds` (one try, `claim_lease.BD_TIMEOUT_S`, 30 s)
COLUMNS: Final = f"SELECT {prefixed('h', HOLD)},p.backlog,p.task_id,p.tracker_root,p.label"
JOINED: Final = " FROM task_hold h JOIN attempt p ON p.attempt_id=h.attempt_id"
LOADED: Final = COLUMNS + JOINED
# The insert's fence of A (`p`): it has a label; it is current with its cause: cause A while no checks attempt of A is
# current (`SUCCESSOR` false), or the checks cause while that is A's latest, not abandoned, and A has no later attempt;
# a hold of A exists.
FENCE: Final = f"""SELECT p.label IS NOT NULL,
CASE WHEN ?=p.attempt_id THEN NOT {SUCCESSOR} ELSE NOT {LATER} AND EXISTS (SELECT 1 FROM checks_attempt c WHERE c.attempt_id=?
 AND {LATEST_CHECKS}) END,
EXISTS (SELECT 1 FROM task_hold h WHERE h.attempt_id=p.attempt_id)
FROM attempt p WHERE p.attempt_id=?"""
# Not current: a later attempt of A's task exists (a hold's own abandon leaves A current until the task is taken again).
SUPERSEDED: Final = f"EXISTS (SELECT 1 FROM attempt p WHERE p.attempt_id=task_hold.attempt_id AND {LATER})"
# The rows that may have added `held` (labels NULL, `moved`, `absent`), not cleared, whose attempt is not current; with
# whether the task's current attempt (its highest `seq`) has a hold of its own that may own `held` (labels NULL, `moved`
# or `absent`; a `not_ours`, `closed` or `missing` one wrote no label, so the old `held` is still the factory's to remove).
UNCLEARED: Final = COLUMNS + """,(SELECT EXISTS (SELECT 1 FROM task_hold g WHERE g.attempt_id=q.attempt_id
 AND (g.labels IS NULL OR g.labels IN ('moved','absent'))) FROM attempt q
 WHERE q.adapter=p.adapter AND q.backlog=p.backlog AND q.task_id=p.task_id ORDER BY q.seq DESC LIMIT 1)""" + JOINED + f"""
 WHERE p.backlog=? AND h.cleared_at IS NULL AND (h.labels IS NULL OR h.labels IN ('moved','absent')) AND {LATER}
 ORDER BY h.held_at,h.attempt_id"""


@dataclass(frozen=True)
class HoldInsert:
    """What the record stores: A, the cause (A or its latest checks attempt), the reason word and when."""

    attempt_id: str
    cause_id: str
    reason: str
    now: float


@dataclass(frozen=True)
class HoldRow:
    """One hold joined with its agent attempt A: the task, its tracker root and the label A was taken under."""

    attempt_id: str
    cause_id: str
    reason: str
    held_at: float
    labels: Labels | None
    labelled_at: float | None
    commenting_at: float | None
    commented_at: float | None
    cleared_at: float | None
    rev: int
    backlog: str
    task_id: str
    tracker_root: str
    label: str


@dataclass(frozen=True)
class Uncleared:
    """A hold whose task was taken again; `held_again`: the task's current attempt has its own hold (it owns `held`)."""

    row: HoldRow
    held_again: bool


def _row(row: tuple[object, ...]) -> HoldRow:
    return HoldRow(
        as_text(row[0]), as_text(row[1]), as_text(row[2]), stored_real(row[3]), stored_word(row[4], LABELS),
        stored_nullable_real(row[5]), stored_nullable_real(row[6]), stored_nullable_real(row[7]), stored_nullable_real(row[8]),
        as_int(row[9]), as_text(row[10]), as_text(row[11]), as_text(row[12]), as_text(row[13]),
    )


class HoldStore(StoreConnection):
    """The fenced writes and the reads of holds."""

    def of_attempts(self, ids: tuple[str, ...]) -> dict[str, HoldRow]:
        """The holds of the given agent attempts, by attempt id (one query for a listing; absent ids have none)."""
        if not ids:
            return {}
        with self._connection() as con:
            found = con.execute(LOADED + f" WHERE h.attempt_id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {each.attempt_id: each for each in map(_row, found)}

    def uncleared(self, backlog: str) -> tuple[Uncleared, ...]:
        """Holds of `backlog` whose task was taken again (A not current) and whose `held` may still be on the task:
        labels NULL, `moved` or `absent`, not cleared. `not_ours`, `closed` and `missing` added nothing and are never
        listed."""
        with self._connection() as con:
            found = con.execute(UNCLEARED, (backlog,)).fetchall()
        return tuple(Uncleared(_row(each[:14]), bool(as_int(each[14]))) for each in found)

    def current_hold(self, attempt_id: str) -> HoldRow | None:
        """The hold of the current attempt (highest `seq`) of `attempt_id`'s task, when that is another attempt."""
        with self._connection() as con:
            found = con.execute(LOADED + """ WHERE h.attempt_id=(SELECT q.attempt_id FROM attempt q JOIN attempt a
             ON q.adapter=a.adapter AND q.backlog=a.backlog AND q.task_id=a.task_id WHERE a.attempt_id=?1 ORDER BY q.seq DESC
             LIMIT 1) AND h.attempt_id<>?1""", (attempt_id,)).fetchone()
        return None if found is None else _row(found)

    def insert(self, hold: HoldInsert) -> HoldRow:
        """The hold's record (5.1 step 1): `unlabelled` when A was started by hand (no label: never held), `changed`
        when A or its cause is no longer current or A already has a hold (a concurrent caller recorded it)."""
        with self._connection(write=True) as con:
            fenced = con.execute(FENCE, (hold.cause_id, hold.cause_id, hold.attempt_id)).fetchone()
            if fenced is not None and not fenced[0]:
                raise StoreRefused("unlabelled")
            if fenced is None or not fenced[1] or fenced[2]:
                raise StoreRefused("changed")
            con.execute(f"INSERT INTO task_hold ({HOLD}) VALUES ({marks(HOLD)})",
                        (hold.attempt_id, hold.cause_id, hold.reason, hold.now, None, None, None, None, None, 0))
            return self._read(con, hold.attempt_id)

    def labelled(self, attempt_id: str, rev: int, labels: Labelled, now: float) -> HoldRow:
        """The label step's word (5.2), once, while A is still its task's current attempt (taken again meanwhile:
        `changed`, and `cleared` supersedes the row)."""
        return self._update(attempt_id, rev, "labels=?,labelled_at=?", (labels, now), f"labels IS NULL AND NOT {SUPERSEDED}")

    def commenting(self, attempt_id: str, rev: int, now: float) -> HoldRow | None:
        """The comment lease (5.1 step 5): taken when the label step's word comments, no comment is recorded and no lease
        is live (none, or one taken more than `COMMENT_LEASE` seconds before `now`), and the hold is not cleared. None: not
        taken (another caller's live lease, a recorded comment, a word that writes none, a cleared hold, or `rev` moved):
        the caller posts nothing."""
        try:
            return self._update(attempt_id, rev, "commenting_at=?", (now,), f"""labels IN {COMMENTED} AND commented_at IS NULL
            AND cleared_at IS NULL AND (commenting_at IS NULL OR commenting_at<?)""", (now - COMMENT_LEASE,))
        except StoreRefused:
            return None

    def commented(self, attempt_id: str, rev: int, now: float) -> HoldRow:
        """The comment is posted, by the lease holder (its `rev` from `commenting`)."""
        return self._update(attempt_id, rev, "commented_at=?", (now,), "commenting_at IS NOT NULL AND commented_at IS NULL")

    def cleared(self, attempt_id: str, rev: int, now: float) -> HoldRow:
        """`held` is off the task, or owned by its new hold (7.3): only for a row `uncleared` lists (A not current). A row
        whose label step never finished becomes `superseded` in the same write, so `cleared_at` always has a word."""
        return self._update(attempt_id, rev, "labels=coalesce(labels,'superseded'),labelled_at=coalesce(labelled_at,?),cleared_at=?",
                            (now, now), f"cleared_at IS NULL AND (labels IS NULL OR labels IN ('moved','absent')) AND {SUPERSEDED}")

    def uncommenting(self, attempt_id: str, rev: int) -> None:
        """The lease given back after a failed comment call (no comment recorded), so the next round retries at once;
        best effort: off its fence (`rev` moved, another caller's lease) nothing changes."""
        try:
            self._update(attempt_id, rev, "commenting_at=NULL", (), "commenting_at IS NOT NULL AND commented_at IS NULL")
        except StoreRefused:
            return

    def retire(self, attempt_id: str, rev: int) -> None:
        """An unfinished hold whose cause is gone (the work was restarted after it was recorded) is deleted, so it never
        abandons that work and a later stop of A can be held afresh; `changed` off its `rev` or once cleared."""
        with self._connection(write=True) as con:
            if con.execute("DELETE FROM task_hold WHERE attempt_id=? AND rev=? AND cleared_at IS NULL", (attempt_id, rev)).rowcount != 1:
                raise StoreRefused("changed")

    def _update(self, attempt_id: str, rev: int, sets: str, values: tuple[object, ...], phase: str,
                bound: tuple[object, ...] = ()) -> HoldRow:
        with self._connection(write=True) as con:
            changed = con.execute(f"UPDATE task_hold SET {sets},rev=rev+1 WHERE attempt_id=? AND rev=? AND {phase}",
                                  (*values, attempt_id, rev, *bound)).rowcount
            if changed != 1:
                raise StoreRefused("changed")
            return self._read(con, attempt_id)

    def _read(self, con: sqlite3.Connection, attempt_id: str) -> HoldRow:
        found = con.execute(LOADED + " WHERE h.attempt_id=?", (attempt_id,)).fetchone()
        if found is None:
            raise StoreRefused("changed")
        return _row(found)
