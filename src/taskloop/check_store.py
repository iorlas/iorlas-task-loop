"""The one writer of `checks_attempt` and `check_result`: a checks attempt from its admission to its release, and its
results block by block (tl-8bh9.14.6 sections 4, 6.1 and 7).

A checks attempt copies no task fact: every read joins its implement attempt (`after_attempt_id`) for the task, the
repository and X (`end_commit`). Every write of an `admitted` attempt is fenced by its key against its held reservation
(`HELD`): a mismatch, or a concluded attempt, is `StoreRefused("stale_reservation")`. A result already concluded or
registered, a position or name already taken in its block, or a block that is not the latest (or, to start one, the next)
is `StoreRefused("check_changed")`. The admission's row (`insert`) and the release's record (`record_release`) are
functions on the caller's connection, inside its transaction. "Latest" is always the highest `number` of one implement
attempt and the highest `block` of one checks attempt, never a clock order.
"""

import json
import math
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import astuple, dataclass
from typing import Final, Literal

from sqlite_store import begin_immediate
from stream_proc import OwnedProcess

from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable, as_int, as_nullable_int, as_nullable_text, as_text
from taskloop.attempt_types import AttemptKey, EntryIdentity, Replaced
from taskloop.factory_schema import CHECK_RESULT, CHECKS_ADMITTED, CHECKS_LOADED, marks, prefixed

type Outcome = Literal["passed", "failed"]
type Conclusion = Literal["passed", "failed", "timed_out", "lingering", "dirty", "undefined", "interrupted"]
type Required = tuple[tuple[str, str], ...]  # each required name with its check's argv digest at the target, in its order
OUTCOMES: Final[tuple[Outcome, ...]] = ("passed", "failed")
CONCLUSIONS: Final[tuple[Conclusion, ...]] = ("passed", "failed", "timed_out", "lingering", "dirty", "undefined", "interrupted")
# Unfinished or so concluded, a result names a command whose group must be proven empty before the slot is reset, set up,
# relaunched or released (`interrupted`: its entry died, and nothing proved the command's group gone).
LIVE_AFTER: Final[tuple[Conclusion, ...]] = ("lingering", "timed_out", "interrupted")
REQUIRED_MAX: Final = 32
RESERVED: Final = """FROM checks_attempt c JOIN attempt a ON a.attempt_id=c.after_attempt_id
JOIN reservation r ON r.repo_id=a.repo_id AND r.slot=c.slot AND r.attempt_id=c.attempt_id AND r.generation=c.generation
WHERE c.attempt_id=? AND c.dispatch_token=? AND c.generation=?"""
HELD: Final = "SELECT 1 " + RESERVED + " AND c.phase='admitted'"  # also the checks half of `setup_store.HELD`
LOADED: Final = (f"SELECT {prefixed('c', CHECKS_LOADED)},a.backlog,a.task_id,a.repo_id,a.tracker_root,a.end_commit "
                 "FROM checks_attempt c JOIN attempt a ON a.attempt_id=c.after_attempt_id")
LATEST_BLOCK: Final = "(SELECT coalesce(max(block),0) FROM check_result WHERE attempt_id=?)"


@dataclass(frozen=True)
class ChecksAdmitted:
    """What the admission stores: D (the free slot's HEAD), the target (`main`'s commit when the required names were
    read) and the names."""

    key: AttemptKey
    after: str  # the done implement attempt
    number: int
    slot: str
    slot_head: str
    target: str
    required: Required
    deadline: float


@dataclass(frozen=True)
class ChecksRow:
    """One checks attempt joined with its implement attempt (the task, the repository, X); the key is for further reads."""

    key: AttemptKey
    after: str
    number: int
    slot: str
    slot_head: str  # D: the release parks here
    target: str  # `main`'s commit when the required names were read
    target_seen: str | None  # `main` when found moved
    required: Required
    profile_digest: str | None
    deadline: float
    entry: EntryIdentity | None
    phase: Literal["admitted", "concluded"]
    rev: int
    refusal: str | None
    refusals: int
    conclusion: Outcome | None
    reason: str | None
    concluded_at: float | None
    released_at: float | None
    parked: str | None
    abandoned: bool
    backlog: str
    task_id: str
    repo_id: str
    tracker_root: str
    commit: str  # X


@dataclass(frozen=True)
class ResultRow:
    """One check's result in one block; `process` is its registered identity (None before registration)."""

    block: int
    position: int
    name: str
    argv_digest: str | None
    timeout: int | None
    process: OwnedProcess | None
    started_at: float
    ended_at: float | None
    rc: int | None
    conclusion: Conclusion | None

    @property
    def unsettled(self) -> bool:
        return self.conclusion is None or self.conclusion in LIVE_AFTER


def _real(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise StoreUnavailable("Malformed stored time")


def _nullable_real(value: object) -> float | None:
    return None if value is None else _real(value)


def _word[W: str](value: object, words: tuple[W, ...]) -> W | None:
    found = next((each for each in words if each == value), None)
    if (found is None) != (value is None):
        raise StoreUnavailable("Malformed stored conclusion")
    return found


def required_json(required: Required) -> str:
    """The stored list: 1 to `REQUIRED_MAX` distinct names, each with a sha256 argv digest."""
    names = {name for name, _ in required}
    if not 1 <= len(required) <= REQUIRED_MAX or len(names) != len(required) or any(len(digest) != 64 for _, digest in required):
        raise ValueError("required: 1 to 32 distinct names, each with its sha256 argv digest")
    return json.dumps([[name, digest] for name, digest in required], separators=(",", ":"))


def _required(value: object) -> Required:
    try:
        found = json.loads(as_text(value))
    except ValueError as error:
        raise StoreUnavailable("Malformed required names") from error
    pairs = found if isinstance(found, list) else []
    if not all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(each, str) for each in pair) for pair in pairs):
        raise StoreUnavailable("Malformed required names")
    required = tuple((str(pair[0]), str(pair[1])) for pair in pairs)
    try:
        required_json(required)
    except ValueError as error:
        raise StoreUnavailable("Malformed required names") from error
    return required


def _entry(values: tuple[object, ...]) -> EntryIdentity | None:
    """A stored entry identity (pid, start, boot): all set or none (the CHECK), else a broken row."""
    if all(value is None for value in values):
        return None
    if None in values:
        raise StoreUnavailable("Malformed stored identity")
    return as_int(values[0]), as_text(values[1]), as_text(values[2])


def _process(values: tuple[object, ...]) -> OwnedProcess | None:
    """A stored command identity (pid, pgid, start, boot): all set or none (the CHECK), else a broken row."""
    if all(value is None for value in values):
        return None
    if None in values:
        raise StoreUnavailable("Malformed stored identity")
    return OwnedProcess(as_int(values[0]), as_int(values[1]), as_text(values[2]), as_text(values[3]))


def _checks(row: tuple[object, ...]) -> ChecksRow:
    entry = _entry(row[12:15])
    phase = "concluded" if row[15] == "concluded" else "admitted" if row[15] == "admitted" else None
    if phase is None:
        raise StoreUnavailable("Malformed checks phase")
    return ChecksRow(
        AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), as_text(row[3]), as_int(row[4]), as_text(row[5]),
        as_text(row[6]), as_text(row[7]), as_nullable_text(row[8]), _required(row[9]), as_nullable_text(row[10]), _real(row[11]),
        entry, phase, as_int(row[16]), as_nullable_text(row[17]), as_int(row[18]), _word(row[19], OUTCOMES),
        as_nullable_text(row[20]), _nullable_real(row[21]), _nullable_real(row[22]), as_nullable_text(row[23]), bool(as_int(row[24])),
        as_text(row[25]), as_text(row[26]), as_text(row[27]), as_text(row[28]), as_text(row[29]),
    )


def _result(row: tuple[object, ...]) -> ResultRow:
    return ResultRow(as_int(row[0]), as_int(row[1]), as_text(row[2]), as_nullable_text(row[3]), as_nullable_int(row[4]), _process(row[5:9]),
                     _real(row[9]), _nullable_real(row[10]), as_nullable_int(row[11]), _word(row[12], CONCLUSIONS))


def latest_results(con: sqlite3.Connection, attempt_id: str) -> tuple[ResultRow, ...]:
    """The latest block's results, by position (empty before the first)."""
    rows = con.execute(f"SELECT {CHECK_RESULT} FROM check_result WHERE attempt_id=? AND block={LATEST_BLOCK} ORDER BY position",
                       (attempt_id, attempt_id)).fetchall()
    return tuple(_result(row) for row in rows)


def unsettled(con: sqlite3.Connection, attempt_id: str) -> tuple[ResultRow, ...]:
    """What the entry's reconcile and the release must prove gone: every latest-block result unfinished or `LIVE_AFTER`
    (an unfinished one may have no identity: it never executed)."""
    return tuple(row for row in latest_results(con, attempt_id) if row.unsettled)


def insert(con: sqlite3.Connection, admitted: ChecksAdmitted) -> None:
    """The admission's row, in the admission's own write transaction (after `admit.reserve`); a checks attempt with the
    same number for the implement attempt is a lost race: `StoreRefused("task_attempted")`."""
    taken = "SELECT 1 FROM checks_attempt WHERE after_attempt_id=? AND number=?"
    if con.execute(taken, (admitted.after, admitted.number)).fetchone() is not None:
        raise StoreRefused("task_attempted")
    values = (*astuple(admitted.key), admitted.after, admitted.number, admitted.slot, admitted.slot_head, admitted.target,
              required_json(admitted.required), admitted.deadline)
    con.execute(f"INSERT INTO checks_attempt ({CHECKS_ADMITTED}) VALUES ({marks(CHECKS_ADMITTED)})", values)


def record_release(con: sqlite3.Connection, key: AttemptKey, read: tuple[int, str], parked: str, now: float, abandoned: bool) -> bool:
    """The release's record, in the release's transaction: fenced on the `rev` and phase its stop proof `read`, the held
    reservation and no earlier release; settled (not `abandoned`) only once concluded. False when the fence fails."""
    fenced = con.execute("SELECT c.rev,c.phase,c.released_at " + RESERVED, astuple(key)).fetchone()
    if fenced is None or (fenced[0], fenced[1]) != read or fenced[2] is not None or not (abandoned or read[1] == "concluded"):
        return False
    con.execute("UPDATE checks_attempt SET released_at=?,parked=?,abandoned=? WHERE attempt_id=?",
                (now, parked, int(abandoned), key.attempt_id))
    return True


class CheckStore(StoreConnection):
    """The fenced writes and the reads of checks attempts and their results; no agent attempt read (a checks key never
    reads the `attempt` table as its own). Only the identity write runs inside the registered start's window: it goes
    through `registering` (composition's bounded connection); every other read and write through the store's own
    connection."""

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
        registering: StoreConnection | None = None,
    ) -> None:
        super().__init__(connect, begin)
        self.registering = self if registering is None else registering

    def attempt_of(self, backlog: str, task_id: str) -> tuple[AttemptKey, str, EntryIdentity | None] | None:
        """The launcher's read (the agent store's, for checks attempts): the latest checks attempt of the task's current
        agent attempt (its highest `seq`), its state and registered entry; None when that attempt has none. The state is
        `released` once released (an abandon may release an `admitted` one), else the phase: only `admitted` launches."""
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                """SELECT attempt_id,dispatch_token,generation,CASE WHEN released_at IS NULL THEN phase ELSE 'released' END,
                entry_pid,entry_start,entry_boot FROM checks_attempt
                WHERE after_attempt_id=(SELECT attempt_id FROM attempt WHERE adapter='beads' AND backlog=? AND task_id=?
                ORDER BY seq DESC LIMIT 1) ORDER BY number DESC LIMIT 1""", (backlog, task_id)).fetchone()
        if row is None:
            return None
        return AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), as_text(row[3]), _entry(row[4:7])

    def row(self, key: AttemptKey) -> ChecksRow | None:
        with self._connection() as con:
            found = con.execute(LOADED + " WHERE c.attempt_id=? AND c.dispatch_token=? AND c.generation=?", astuple(key)).fetchone()
        return None if found is None else _checks(found)

    def of_attempt(self, after: str) -> tuple[ChecksRow, ...]:
        """Every checks attempt of one implement attempt, by number: the last is the latest."""
        with self._connection() as con:
            rows = con.execute(LOADED + " WHERE c.after_attempt_id=? ORDER BY c.number", (after,)).fetchall()
        return tuple(_checks(row) for row in rows)

    def results(self, key: AttemptKey) -> tuple[ResultRow, ...]:
        with self._connection() as con:
            return latest_results(con, key.attempt_id)

    def register_entry(
        self, key: AttemptKey, entry: EntryIdentity, now: float, replacing: Replaced | None = None, renewed: float | None = None,
    ) -> Literal["accepted", "conflict", "refused"]:
        """`AttemptStore.register_entry`'s rule (one winner while `admitted`; a replacement names the exact stored
        identity; a replacement of another boot's entry renews the deadline to the later of the two, once per reboot)
        without its deadline refusal: an entry past the deadline runs nothing and concludes `expired`. `now` is unused."""
        del now
        with self._connection(write=True) as con:
            row = con.execute("SELECT c.phase,c.deadline,c.entry_pid,c.entry_start,c.entry_boot " + RESERVED, astuple(key)).fetchone()
            if row is None:
                return "refused"
            deadline = _real(row[1])
            stored = _entry(row[2:5])
            if renewed is not None and stored is not None and stored[2] != entry[2] and math.isfinite(renewed):
                deadline = max(deadline, renewed)
            if row[0] != "admitted" or entry == stored or stored != (None if replacing is None else replacing.identity):
                return "conflict"
            con.execute("UPDATE checks_attempt SET entry_pid=?,entry_start=?,entry_boot=?,deadline=?,rev=rev+1 WHERE attempt_id=?",
                        (*entry, deadline, key.attempt_id))
            return "accepted"

    def _held(self, con: sqlite3.Connection, key: AttemptKey) -> None:
        if con.execute(HELD, astuple(key)).fetchone() is None:
            raise StoreRefused("stale_reservation")

    def refused(self, key: AttemptKey, word: str) -> int:
        """A relaunchable refusal (section 6.1): the same word as the last one counts one more, another starts at 1.
        Returns the count."""
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute("UPDATE checks_attempt SET refusals=CASE WHEN refusal=? THEN refusals+1 ELSE 1 END,refusal=? WHERE attempt_id=?",
                        (word, word, key.attempt_id))
            return as_int(con.execute("SELECT refusals FROM checks_attempt WHERE attempt_id=?", (key.attempt_id,)).fetchone()[0])

    def profiled(self, key: AttemptKey, digest: str) -> None:
        """The profile digest at X, written by the first block only (X is immutable: a later one is never compared)."""
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute("UPDATE checks_attempt SET profile_digest=coalesce(profile_digest,?) WHERE attempt_id=?", (digest, key.attempt_id))

    def block(self, key: AttemptKey) -> int:
        """A block starts: returns its number, the latest plus one. The refusal count stands: a block that repeats after a
        refusal inside it still counts toward `stuck:checks_refused`; only the conclusion clears it."""
        with self._connection(write=True) as con:
            self._held(con, key)
            return as_int(con.execute(f"SELECT {LATEST_BLOCK}", (key.attempt_id,)).fetchone()[0]) + 1

    def start(self, key: AttemptKey, block: int, position: int, name: str, argv_digest: str, timeout: int, now: float) -> None:
        """A check of the profile at X starts (before its command is started)."""
        self._new(key, (block, position, name, argv_digest, timeout, now, None, None))

    def undefined(self, key: AttemptKey, block: int, position: int, name: str, now: float) -> None:
        """A stored required name the profile at X does not define: its result, with no process and no argv."""
        self._new(key, (block, position, name, None, None, now, now, "undefined"))

    def _new(self, key: AttemptKey, values: tuple[object, ...]) -> None:
        block, position, name = values[0], values[1], values[2]
        with self._connection(write=True) as con:
            self._held(con, key)
            latest = as_int(con.execute(f"SELECT {LATEST_BLOCK}", (key.attempt_id,)).fetchone()[0])
            taken = con.execute("SELECT 1 FROM check_result WHERE attempt_id=? AND block=? AND (position=? OR name=?)",
                                (key.attempt_id, block, position, name)).fetchone()
            if block not in (latest, latest + 1) or taken is not None:
                raise StoreRefused("check_changed")
            con.execute(
                """INSERT INTO check_result (block,position,name,argv_digest,timeout,started_at,ended_at,conclusion,
                attempt_id,dispatch_token,generation) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (*values, *astuple(key)))

    def registered(self, key: AttemptKey, block: int, position: int, process: OwnedProcess) -> None:
        """The check command's identity, committed before it executes (the registered start's callback); once."""
        with self.registering._connection(write=True) as con:
            self._changed(con, key, block, position, "pid=?,pgid=?,proc_start=?,boot=?",
                          (process.pid, process.pgid, process.start, process.boot), " AND pid IS NULL")

    def finish(self, key: AttemptKey, block: int, position: int, conclusion: Conclusion, rc: int | None, now: float) -> None:
        """A started check's conclusion (never `undefined`, which only `undefined` writes); `interrupted` is the
        reconcile's word for one whose command was proven gone without a conclusion."""
        if conclusion == "undefined":
            raise ValueError("an undefined result is written by `undefined`")
        with self._connection(write=True) as con:
            self._changed(con, key, block, position, "conclusion=?,rc=?,ended_at=?", (conclusion, rc, now), "")

    def _changed(self, con: sqlite3.Connection, key: AttemptKey, block: int, position: int, assignments: str,
                 values: tuple[object, ...], also: str) -> None:
        self._held(con, key)
        changed = con.execute(
            f"UPDATE check_result SET {assignments} WHERE attempt_id=? AND block=? AND position=? AND conclusion IS NULL"
            f" AND block={LATEST_BLOCK}{also}", (*values, key.attempt_id, block, position, key.attempt_id)).rowcount
        if changed != 1:
            raise StoreRefused("check_changed")

    def conclude(self, key: AttemptKey, conclusion: Outcome, reason: str | None, now: float, seen: str | None = None) -> None:
        """The attempt's one conclusion (a reason exactly when `failed`), clearing the refusal count; `seen` is `main`
        when found moved (`main_moved`)."""
        with self._connection(write=True) as con:
            self._held(con, key)
            con.execute(
                """UPDATE checks_attempt SET phase='concluded',conclusion=?,reason=?,concluded_at=?,
                target_seen=coalesce(?,target_seen),refusal=NULL,refusals=0,rev=rev+1 WHERE attempt_id=?""",
                (conclusion, reason, now, seen, key.attempt_id))

    def abandon_released(self, key: AttemptKey) -> bool:
        """The abandon of an already released checks attempt: the latest one of its implement attempt, not abandoned,
        flipped in one fenced write. False when another call changed it first or it is not the latest."""
        with self._connection(write=True) as con:
            return con.execute(
                """UPDATE checks_attempt SET abandoned=1 WHERE attempt_id=? AND dispatch_token=? AND generation=?
                AND released_at IS NOT NULL AND abandoned=0 AND number=(SELECT max(d.number) FROM checks_attempt d
                WHERE d.after_attempt_id=checks_attempt.after_attempt_id)""", astuple(key)).rowcount == 1
