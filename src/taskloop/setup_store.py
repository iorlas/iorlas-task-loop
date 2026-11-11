"""The one writer of `setup_run`: the record of the slot setup an implement attempt's entry runs before its agent.

State only; the output is an evidence file (`EvidenceFiles.setup_log`). "Latest" is always the highest `run` of one
attempt, never a wall-clock order. Every write is fenced by the attempt's key against its held reservation while the
attempt is still `admitted` (setup runs only before dispatch): a mismatch is `StoreRefused("stale_reservation")`, and a
run already concluded or replaced is `StoreRefused("setup_changed")`. Reads need the key only.
"""

import sqlite3
from dataclasses import astuple, dataclass
from typing import Final, Literal

from stream_proc import OwnedProcess

from taskloop.attempt_reads import AttemptReads, StoreRefused, StoreUnavailable, as_int, as_nullable_int, as_nullable_text, as_text
from taskloop.attempt_types import AttemptKey

type Conclusion = Literal["passed", "failed", "timed_out", "lingering", "dirty", "interrupted"]
CONCLUSIONS: Final[tuple[Conclusion, ...]] = ("passed", "failed", "timed_out", "lingering", "dirty", "interrupted")
FAILURES: Final[tuple[Conclusion, ...]] = ("failed", "timed_out", "lingering", "dirty")  # `interrupted` is not the setup's fault
COLUMNS: Final = "run,commit_sha,digest,command,pid,pgid,proc_start,boot,conclusion"
HELD: Final = """SELECT 1 FROM attempt p JOIN reservation r ON r.repo_id=p.repo_id AND r.slot=p.slot
AND r.attempt_id=p.attempt_id AND r.generation=p.generation
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND p.phase='admitted'"""


@dataclass(frozen=True)
class SetupRow:
    """One setup run: B and the setup digest it ran for, the command running or last run (0-based), that command's
    registered identity (None before the first registration) and its conclusion (None while unfinished)."""

    run: int
    commit: str
    digest: str
    command: int
    process: OwnedProcess | None
    conclusion: Conclusion | None


def _conclusion(value: object) -> Conclusion | None:
    found = next((each for each in CONCLUSIONS if each == value), None)
    if (found is None) != (value is None):
        raise StoreUnavailable("Malformed setup conclusion")
    return found


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
    """The registered identity of the attempt's latest run while it has no conclusion: what a slot release must prove
    gone. None when the latest run is concluded, or no command of it ever registered (nothing executed)."""
    found = latest_of(con, attempt_id)
    return None if found is None or found.conclusion is not None else found.process


class SetupStore(AttemptReads):
    """The fenced `setup_run` writes and the reads the preparation needs; composition passes the bounded registration
    connection, so the identity write inside the registered start's window waits at most REGISTRATION_BUSY_MS."""

    def latest(self, key: AttemptKey) -> SetupRow | None:
        with self._connection() as con:
            return latest_of(con, key.attempt_id)

    def failures(self, key: AttemptKey) -> int:
        """Runs of this attempt that ended as the setup's own failure (`FAILURES`)."""
        marks = ",".join("?" * len(FAILURES))
        with self._connection() as con:
            row = con.execute(f"SELECT count(*) FROM setup_run WHERE attempt_id=? AND conclusion IN ({marks})",
                              (key.attempt_id, *FAILURES)).fetchone()
            return as_int(row[0])

    def _held(self, con: sqlite3.Connection, key: AttemptKey) -> None:
        if con.execute(HELD, astuple(key)).fetchone() is None:
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
        self._update(key, run, "command=?,pid=?,pgid=?,proc_start=?,boot=?",
                     (command, process.pid, process.pgid, process.start, process.boot))

    def conclude(self, key: AttemptKey, run: int, conclusion: Conclusion, rc: int | None, now: float) -> None:
        self._update(key, run, "conclusion=?,rc=?,ended_at=?", (conclusion, rc, now))

    def _update(self, key: AttemptKey, run: int, assignments: str, values: tuple[object, ...]) -> None:
        with self._connection(write=True) as con:
            self._held(con, key)
            changed = con.execute(
                f"UPDATE setup_run SET {assignments} WHERE attempt_id=? AND run=? AND conclusion IS NULL",
                (*values, key.attempt_id, run),
            ).rowcount
            if changed != 1:
                raise StoreRefused("setup_changed")
