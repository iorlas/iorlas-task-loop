"""The attempt store's connection and its status reads (SELECT only, no reservation or deadline check): a task's current
attempt (its highest `seq`), every attempt (with its release and its published task branch), a dispatch phase, an
attempt's tracker root, its release, the attempts of one step, and the slots' use. `AttemptStore` adds the fenced writes."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import astuple, dataclass

from sqlite_store import begin_immediate

from taskloop.attempt_types import ATTEMPTS, AttemptKey, ChainLink, FileRef
from taskloop.factory_schema import current


@dataclass(frozen=True)
class ReleaseRow:
    """How an attempt ended its reservation (`slot_release`): where the slot was left, when, whether it was abandoned
    (the task can be started again) and the tracker claim's state."""

    head: str
    released_at: float
    abandoned: bool
    claim: str


@dataclass(frozen=True)
class PublishedRow:
    """The attempt's verified commit on origin's `task/<id>` (`published_branch`): X pushed, the remote tip confirmed (X,
    or a later commit that contains X), and when."""

    commit: str
    remote_head: str
    published_at: float


@dataclass(frozen=True)
class AttemptRow:
    """One attempt as the status reads see it; the key is for further reads only, never for display. `successor`: a
    later attempt of the step names this one (it was repeated, so it is fenced and superseded)."""

    key: AttemptKey
    backlog: str
    task_id: str
    slot: str
    phase: str
    entry: tuple[int, str, str] | None
    deadline: float
    worker: tuple[int, int] | None  # the agent's pid and process group, once registered
    number: int
    previous_attempt_id: str | None
    repeat_reason: str | None
    successor: bool
    step: str  # the step the attempt belongs to (`plan`)
    seq: int = 1  # the attempt's order among its task's attempts
    held: bool = False  # it still holds its reservation
    release: ReleaseRow | None = None
    published: PublishedRow | None = None


@dataclass(frozen=True)
class SlotUse:
    """Every adopted slot of factory.db against the reservation rows, across repos: `free`, the adopted slots with no
    reservation row (not proof a slot is free: it may be dirty or locked); `held`, each reserved (repo_id, slot), every
    backlog's: a repeat's takeover rewrites the row's attempt but keeps the slot reserved. The release (`slot_release`)
    is the one owner of a row's removal."""

    free: int
    held: frozenset[tuple[str, str]]


class StoreUnavailable(Exception):
    """No progress was acknowledged by the store."""


class StoreRefused(Exception):
    """The authoritative admission or reservation fence does not match."""


def as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    raise StoreUnavailable("Malformed stored text")


def as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise StoreUnavailable("Malformed stored integer")


def as_nullable_int(value: object) -> int | None:
    return None if value is None else as_int(value)


def as_nullable_text(value: object) -> str | None:
    return None if value is None else as_text(value)


def as_listed(value: object) -> tuple[str, ...]:
    """The stored `commit_paths` JSON array (NULL for an answer that is not valid)."""
    if value is None:
        return ()
    try:
        paths = json.loads(as_text(value))
    except ValueError as error:
        raise StoreUnavailable("Malformed stored paths") from error
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise StoreUnavailable("Malformed stored paths")
    return tuple(str(path) for path in paths)


STEP = """SELECT p.number,p.base_commit,p.end_commit,p.input_path,p.input_digest,e.disposition,e.commit_paths,p.previous_attempt_id
FROM attempt p LEFT JOIN execution e ON e.attempt_id=p.attempt_id"""


RELEASED = "SELECT head,released_at,abandoned,claim FROM slot_release"


def _released(row: tuple[object, ...]) -> ReleaseRow | None:
    """A release row (head, released_at, abandoned, claim), None for the all-NULL row of a LEFT JOIN without one."""
    if row[0] is None:
        return None
    if not isinstance(row[1], (int, float)):
        raise StoreUnavailable("Malformed release time")
    return ReleaseRow(as_text(row[0]), float(row[1]), bool(as_int(row[2])), as_text(row[3]))


def _published(row: tuple[object, ...]) -> PublishedRow | None:
    """A published row (commit_sha, remote_head, published_at), None for the all-NULL row of a LEFT JOIN without one."""
    if row[0] is None:
        return None
    if not isinstance(row[2], (int, float)):
        raise StoreUnavailable("Malformed publication time")
    return PublishedRow(as_text(row[0]), as_text(row[1]), float(row[2]))


def _step(row: tuple[object, ...]) -> ChainLink:
    """A dispatched attempt: its B is recorded (a broken chain otherwise)."""
    base, commit = as_text(row[1]), as_nullable_text(row[2])
    return ChainLink(as_int(row[0]), base, commit, as_nullable_text(row[5]), as_listed(row[6]), FileRef(as_text(row[3]), as_text(row[4])))


class AttemptReads:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
    ) -> None:
        """`begin` is the writer transaction; a composition on a Store passes its begin_immediate, which evicts a failed shared writer."""
        self.connect, self.begin = connect, begin

    @contextmanager
    def _connection(self, *, write: bool = False) -> Generator[sqlite3.Connection]:
        try:
            con = self.connect()
            if con is None or not current(con):
                raise StoreUnavailable("Factory database unavailable or incompatible")
            if write:
                with self.begin(con):
                    yield con
            else:
                yield con
        except sqlite3.Error as error:
            raise StoreUnavailable("Factory database operation failed") from error

    def state(self, key: AttemptKey) -> tuple[str, bool] | None:
        """Dispatch phase and recorded session conflict, without needing a live reservation (historical reads)."""
        with self._connection() as con:
            row = con.execute(
                "SELECT phase,session_conflict FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
            ).fetchone()
            return None if row is None else (as_text(row[0]), bool(as_int(row[1])))

    def attempt_of(self, backlog: str, task_id: str) -> tuple[AttemptKey, str, tuple[int, str, str] | None] | None:
        """The recovery read: a task's current attempt (its highest `seq`) key, phase and registered entry, with no
        reservation or deadline check."""
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                """SELECT attempt_id,dispatch_token,generation,phase,entry_pid,entry_start,entry_boot FROM attempt
                WHERE adapter='beads' AND backlog=? AND task_id=? ORDER BY seq DESC LIMIT 1""",
                (backlog, task_id),
            ).fetchone()
        if row is None:
            return None
        entry = None if any(value is None for value in row[4:7]) else (as_int(row[4]), as_text(row[5]), as_text(row[6]))
        return AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), as_text(row[3]), entry

    def tracker_root(self, key: AttemptKey) -> str | None:
        """The absolute tracker root the attempt's claim was taken at (stored by admission, copied by a repeat)."""
        with self._connection() as con:
            row = con.execute(
                "SELECT tracker_root FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
            ).fetchone()
        return None if row is None else as_text(row[0])

    def release_of(self, key: AttemptKey) -> ReleaseRow | None:
        """The attempt's release, None while it holds (or never held) its reservation."""
        with self._connection() as con:
            row = con.execute(RELEASED + " WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)).fetchone()
        return None if row is None else _released(row)

    def attempts(self, backlog: str | None = None, task_id: str | None = None) -> tuple[AttemptRow, ...]:
        """Every attempt (or one backlog's, or one task's), by backlog, task and `seq`, the current attempt of each task
        first, with whether it still holds its reservation and its release: SELECT only, no deadline check."""
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute(
                """SELECT p.attempt_id,p.dispatch_token,p.generation,p.backlog,p.task_id,p.slot,p.phase,p.entry_pid,p.entry_start,
                p.entry_boot,p.deadline,p.worker_pid,p.worker_pgid,p.number,p.previous_attempt_id,p.repeat_reason,
                EXISTS (SELECT 1 FROM attempt s WHERE s.previous_attempt_id=p.attempt_id),p.seq,
                EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
                 AND r.generation=p.generation),x.head,x.released_at,x.abandoned,x.claim,b.commit_sha,b.remote_head,b.published_at,p.step
                FROM attempt p LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id
                LEFT JOIN published_branch b ON b.attempt_id=p.attempt_id
                WHERE p.adapter='beads' AND (?1 IS NULL OR p.backlog=?1) AND (?2 IS NULL OR p.task_id=?2)
                ORDER BY p.backlog,p.task_id,p.seq DESC""",
                (backlog, task_id),
            ).fetchall()
        found: list[AttemptRow] = []
        for row in rows:
            entry = None if any(value is None for value in row[7:10]) else (as_int(row[7]), as_text(row[8]), as_text(row[9]))
            if not isinstance(row[10], (int, float)):
                raise StoreUnavailable("Malformed deadline")
            key = AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2]))
            worker = None if row[11] is None or row[12] is None else (as_int(row[11]), as_int(row[12]))
            found.append(
                AttemptRow(key, as_text(row[3]), as_text(row[4]), as_text(row[5]), as_text(row[6]), entry, float(row[10]), worker,
                           as_int(row[13]), as_nullable_text(row[14]), as_nullable_text(row[15]), bool(as_int(row[16])), as_text(row[26]),
                           as_int(row[17]), bool(as_int(row[18])), _released(row[19:23]), _published(row[23:26]))
            )
        return tuple(found)

    def slot_use(self) -> SlotUse:
        """The free-slot gate's and the slot-freed check's read: two SELECTs, no write."""
        with self._connection() as con:
            free = con.execute(
                """SELECT count(*) FROM slot s
                WHERE NOT EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)"""
            ).fetchone()
            rows: list[tuple[object, ...]] = con.execute("SELECT repo_id,slot FROM reservation").fetchall()
        held = frozenset((as_text(row[0]), as_text(row[1])) for row in rows)
        return SlotUse(as_int(free[0]), held)

    def chain(self, key: AttemptKey) -> tuple[ChainLink, ...]:
        """Attempts 1..n of the key's dispatched step, oldest first, followed through `previous_attempt_id` (at most
        ATTEMPTS): the earlier ones are frozen once their successor exists. No reservation check; an absent key, an
        undispatched attempt or a broken chain is StoreUnavailable."""
        found: list[tuple[object, ...]] = []
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                STEP + " WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?", astuple(key)
            ).fetchone()
            while row is not None and len(found) < ATTEMPTS:
                found.append(row)
                row = None if row[7] is None else con.execute(STEP + " WHERE p.attempt_id=?", (row[7],)).fetchone()
        steps = tuple(_step(each) for each in reversed(found))
        if not steps or [step.number for step in steps] != list(range(1, len(steps) + 1)):
            raise StoreUnavailable("Malformed step chain")
        return steps
