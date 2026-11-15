"""Release persistence: fenced snapshots, claim progress and atomic reservation removal."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import astuple, dataclass, replace
from typing import Final, Literal

from any_agent.procs import Worker
from stream_proc import OwnedProcess

from taskloop.attempt_reads import StoreUnavailable, as_int, as_nullable_text, as_text
from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import RELEASE, SUCCESSOR, current, marks
from taskloop.recovery.models import Intent
from taskloop.recovery.store import RecoveryStore
from taskloop.release_proof import Stopping
from taskloop.setup_store import running

type Claimed = Literal["kept", "unclaiming", "unclaimed", "not_held"]
CLAIMS: Final[tuple[Claimed, ...]] = ("kept", "unclaiming", "unclaimed", "not_held")
ROW: Final = """SELECT p.task_id,p.repo_id,p.slot,p.phase,p.rev,p.entry_pid,p.entry_start,p.entry_boot,p.worker_pid,p.worker_pgid,
p.worker_start,p.worker_boot,p.slot_head,p.tracker_root,
(SELECT s.path FROM reservation r JOIN slot s ON s.repo_id=r.repo_id AND s.name=r.slot
 WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id AND r.generation=p.generation),
""" + SUCCESSOR + """,x.claim,
EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id),
EXISTS (SELECT 1 FROM task_hold h WHERE h.attempt_id=p.attempt_id)
FROM attempt p LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""
# Still the proof's rev and phase, the task's current attempt, the reservation at the key's generation, and no release row.
FENCE: Final = """SELECT 1 FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND p.rev=? AND p.phase=?
AND NOT """ + SUCCESSOR + """
AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND NOT EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id)"""

# An abandon of a settled release: still `kept` and still the task's current attempt.
FLIP: Final = """UPDATE slot_release SET claim='unclaiming' WHERE attempt_id=? AND claim='kept'
AND NOT EXISTS (SELECT 1 FROM attempt p WHERE p.attempt_id=slot_release.attempt_id AND """ + SUCCESSOR + ")"


@dataclass(frozen=True)
class ReleaseRow:
    key: AttemptKey
    task_id: str
    repo_id: str
    slot: str
    rev: int
    stopping: Stopping
    slot_head: str
    tracker_root: str
    slot_path: str | None  # the held reservation's slot path; None when it is not held at the key's generation
    successor: bool  # a later attempt of the task, or its unabandoned latest checks attempt; no longer current
    released: Claimed | None  # the claim of an existing release row: abandoned unless `kept`
    captured: bool
    held: bool
    setup: OwnedProcess | None = None  # the latest setup run's unsettled command, if any
    reconciling: bool = False
    recovery: Intent | None = None


def _claim(value: object) -> Claimed:
    found = next((claim for claim in CLAIMS if claim == value), None)
    if found is None:
        raise StoreUnavailable("Malformed release claim")
    return found


def _row(row: tuple[object, ...], key: AttemptKey) -> ReleaseRow:
    entry = None if any(value is None for value in row[5:8]) else (as_int(row[5]), as_text(row[6]), as_text(row[7]))
    worker = None if row[8] is None else Worker(pid=as_int(row[8]), pgid=as_int(row[9]), start=as_text(row[10]), boot=as_text(row[11]))
    released = None if row[16] is None else _claim(row[16])
    stopping = Stopping(as_text(row[3]), entry, worker)
    return ReleaseRow(key, as_text(row[0]), as_text(row[1]), as_text(row[2]), as_int(row[4]), stopping,
                      as_text(row[12]), as_text(row[13]), as_nullable_text(row[14]), bool(as_int(row[15])), released,
                      bool(as_int(row[17])), bool(as_int(row[18])))


def free(con: sqlite3.Connection, repo_id: str, slot: str, attempt_id: str, generation: int) -> int:
    """Delete a reservation inside the caller's fenced release transaction; return the number removed."""
    return con.execute("DELETE FROM reservation WHERE repo_id=? AND slot=? AND attempt_id=? AND generation=?",
                       (repo_id, slot, attempt_id, generation)).rowcount


@dataclass(frozen=True)
class SlotReleaseStore:
    connect: Callable[[], sqlite3.Connection | None]
    begin: Callable[[sqlite3.Connection], AbstractContextManager[None]]

    def _connected(self) -> sqlite3.Connection:
        con = self.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        return con

    def read(self, key: AttemptKey) -> ReleaseRow | None:
        """The release's fenced read, including an admitted attempt that never registered its entry."""
        return self._read_on(self._connected(), key)

    def _read_on(self, con: sqlite3.Connection, key: AttemptKey) -> ReleaseRow | None:
        row: tuple[object, ...] | None = con.execute(ROW, astuple(key)).fetchone()
        if row is None:
            return None
        found = _row(row, key)
        recovery = None if found.released is not None else RecoveryStore(lambda: con, self.begin).release_intent(key)
        return replace(found, setup=running(con, key.attempt_id), recovery=recovery)

    def record_release(self, row: ReleaseRow, head: str, now: float, abandon: bool) -> bool:
        """Compare the proof's snapshot and fence, insert the release and remove its reservation in one transaction."""
        key, con = row.key, self._connected()
        with self.begin(con):
            if self._read_on(con, key) != replace(row, reconciling=False):
                return False
            if con.execute(FENCE, (*astuple(key), row.rev, row.stopping.phase)).fetchone() is None:
                return False
            values = (*astuple(key), head, now, "unclaiming" if abandon else "kept")
            con.execute(f"INSERT INTO slot_release ({RELEASE}) VALUES ({marks(RELEASE)})", values)
            free(con, row.repo_id, row.slot, key.attempt_id, key.reservation_generation)
        return True

    def flip(self, attempt_id: str) -> int:
        """Abandon a settled release only while it still owns the claim; return the number changed."""
        con = self._connected()
        with self.begin(con):
            return con.execute(FLIP, (attempt_id,)).rowcount

    def complete(self, attempt_id: str, claim: Literal["unclaimed", "not_held"]) -> None:
        """Record the tracker answer only while its claim return remains pending."""
        con = self._connected()
        with self.begin(con):
            con.execute("UPDATE slot_release SET claim=? WHERE attempt_id=? AND claim='unclaiming'", (claim, attempt_id))
