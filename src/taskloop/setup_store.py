"""The one writer of `setup_run`: the record of the slot setup an attempt's entry runs before its agent or its checks.

State only; the output is an evidence file (`EvidenceFiles.setup_log`). "Latest" is always the highest `run` of one
attempt, never a wall-clock order. Every write is fenced by the attempt's key against its held reservation while the
attempt is still `admitted` (an agent's setup runs only before dispatch, a checks attempt's before its conclusion, a land
candidate's while it is pending): a
mismatch is `StoreRefused("stale_reservation")`, and a run already concluded or replaced is
`StoreRefused("setup_changed")`. Reads need the key only.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import astuple, dataclass
from typing import Final, Literal, override

from sqlite_store import begin_immediate
from stream_proc import OwnedProcess

from taskloop.attempt_reads import AttemptReads, StoreRefused, StoreUnavailable, as_int, as_nullable_int, as_nullable_text, as_text
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import RESULT_HELD
from taskloop.command_conclusion import SETUP_CONCLUSIONS, CommandConclusion, decode, encode
from taskloop.drain.models import Owner, Role, owners

FAILURES: Final[tuple[CommandConclusion, ...]] = (CommandConclusion.FAILED, CommandConclusion.TIMED_OUT,
    CommandConclusion.LINGERING, CommandConclusion.DIRTY)  # `interrupted` is not the setup's fault
SETUP_RUNS: Final = 2  # failed runs of one attempt before relaunches stop running its setup (`environment:failed`)
# Concluded with a process possibly left in the last command's group (a member that outlived it, or one the deadline's stop
# could not prove gone): until that group is empty the run still holds the slot, like an unfinished one.
LIVE_AFTER: Final[tuple[CommandConclusion, ...]] = (CommandConclusion.LINGERING, CommandConclusion.TIMED_OUT)
type ProcessSeen = Literal["gone", "alive", "unknown"]
type SetupSeen = Callable[[OwnedProcess], ProcessSeen]  # a registered setup command and its group; another boot is gone
COLUMNS: Final = "run,commit_sha,digest,command,pid,pgid,proc_start,boot,conclusion"
# The run's attempt is an agent attempt, a checks attempt or a land candidate (`setup_run` has no foreign key): an agent or
# checks attempt `admitted`, or a candidate pending, holding its reservation at the key's generation. Bound with the key
# three times.
HELD: Final = """SELECT 1 FROM attempt p JOIN reservation r ON r.repo_id=p.repo_id AND r.slot=p.slot
AND r.attempt_id=p.attempt_id AND r.generation=p.generation
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND p.phase='admitted'
UNION ALL """ + RESULT_HELD


@dataclass(frozen=True)
class SetupRow:
    """One setup run: B and the setup digest it ran for, the command running or last run (0-based), that command's
    registered identity (None before the first registration) and its conclusion (None while unfinished)."""

    run: int
    commit: str
    digest: str
    command: int
    process: OwnedProcess | None
    conclusion: CommandConclusion | None

    @property
    def unsettled(self) -> OwnedProcess | None:
        """The registered command whose group must be proven empty before the slot is reset, set up again or released:
        the run's while it is unfinished or concluded `LIVE_AFTER`; None when nothing ever registered."""
        return self.process if self.conclusion is None or self.conclusion in LIVE_AFTER else None


def _conclusion(value: object) -> CommandConclusion | None:
    try:
        found = decode(value)
        if found is not None and found not in SETUP_CONCLUSIONS:
            raise ValueError("Setup cannot be undefined")
        return found
    except ValueError as error:
        raise StoreUnavailable("Malformed setup conclusion") from error


def _row(row: tuple[object, ...]) -> SetupRow:
    pid, pgid, start, boot = as_nullable_int(row[4]), as_nullable_int(row[5]), as_nullable_text(row[6]), as_nullable_text(row[7])
    process = None if pid is None or pgid is None or start is None or boot is None else OwnedProcess(pid, pgid, start, boot)
    return SetupRow(as_int(row[0]), as_text(row[1]), as_text(row[2]), as_int(row[3]), process, _conclusion(row[8]))


def latest_of(con: sqlite3.Connection, attempt_id: str) -> SetupRow | None:
    """The attempt's highest `run`, by attempt id alone (the release's read inside its own connection)."""
    row: tuple[object, ...] | None = con.execute(
        f"SELECT {COLUMNS} FROM setup_run WHERE attempt_id=? ORDER BY run DESC LIMIT 1", (attempt_id,)
    ).fetchone()
    return None if row is None else _row(row)


def running(con: sqlite3.Connection, attempt_id: str) -> OwnedProcess | None:
    """What a slot release must prove gone: the latest run's `unsettled` command."""
    found = latest_of(con, attempt_id)
    return None if found is None else found.unsettled


class SetupStore(AttemptReads):
    """The fenced `setup_run` writes and the reads the preparation needs. Only the identity write runs inside the
    registered start's window: it goes through `registering` (composition's bounded connection, waiting at most
    REGISTRATION_BUSY_MS); every other read and write through the store's own connection."""

    @override
    def drain_processes(self) -> tuple[Owner, ...]:
        """Every recorded execution identity, including historical and already concluded work."""
        with self._connection() as con:
            rows = con.execute("SELECT attempt_id,pid,pgid,proc_start,boot FROM setup_run").fetchall()
        return owners(rows, Role.SETUP, group=True)

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
        registering: AttemptReads | None = None,
    ) -> None:
        super().__init__(connect, begin)
        self.registering = self if registering is None else registering

    def latest(self, key: AttemptKey) -> SetupRow | None:
        with self._connection() as con:
            return latest_of(con, key.attempt_id)

    def failures(self, key: AttemptKey) -> int:
        """Runs of this attempt that ended as the setup's own failure (`FAILURES`)."""
        marks = ",".join("?" * len(FAILURES))
        with self._connection() as con:
            row = con.execute(f"SELECT count(*) FROM setup_run WHERE attempt_id=? AND conclusion IN ({marks})",
                              (key.attempt_id, *(encode(each) for each in FAILURES))).fetchone()
            return as_int(row[0])

    def _held(self, con: sqlite3.Connection, key: AttemptKey) -> None:
        if con.execute(HELD, astuple(key) * 3).fetchone() is None:
            raise StoreRefused("stale_reservation")

    def start(self, key: AttemptKey, run: int, commit: str, digest: str, now: float) -> None:
        """Run `run` (the latest plus one) starts for B `commit` and the setup `digest`; an existing run number is a
        concurrent writer: `setup_changed`."""
        with self._connection(write=True) as con:
            self._held(con, key)
            try:
                con.execute(
                    """INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (key.attempt_id, run, key.dispatch_token, key.reservation_generation, commit, digest, now),
                )
            except sqlite3.IntegrityError as error:
                raise StoreRefused("setup_changed") from error

    def registered(self, key: AttemptKey, run: int, command: int, process: OwnedProcess) -> None:
        """Command `command`'s identity, committed before it executes (the registered start's callback)."""
        with self.registering._connection(write=True) as con:
            self._changed(con, key, run, "command=?,pid=?,pgid=?,proc_start=?,boot=?",
                          (command, process.pid, process.pgid, process.start, process.boot))

    def conclude(self, key: AttemptKey, run: int, conclusion: CommandConclusion, rc: int | None, now: float) -> None:
        if conclusion not in SETUP_CONCLUSIONS:
            raise ValueError("Setup cannot be undefined")
        self._update(key, run, "conclusion=?,rc=?,ended_at=?", (encode(conclusion), rc, now))

    def _update(self, key: AttemptKey, run: int, assignments: str, values: tuple[object, ...]) -> None:
        with self._connection(write=True) as con:
            self._changed(con, key, run, assignments, values)

    def _changed(self, con: sqlite3.Connection, key: AttemptKey, run: int, assignments: str, values: tuple[object, ...]) -> None:
        self._held(con, key)
        changed = con.execute(
            f"UPDATE setup_run SET {assignments} WHERE attempt_id=? AND run=? AND conclusion IS NULL",
            (*values, key.attempt_id, run),
        ).rowcount
        if changed != 1:
            raise StoreRefused("setup_changed")
