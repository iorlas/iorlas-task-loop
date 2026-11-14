"""The admission's row writes, inside the caller's write transaction: a new `reservation`, the admitted `attempt` row and the
slot's counter (`generation`, the last reservation generation issued for it)."""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import ATTEMPT_ADMITTED, RESERVATION, marks
from taskloop.repo import RepoId
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore


@dataclass(frozen=True)
class Free:
    """An observed-free slot's HEAD, selected task source and recorded park destination."""

    name: str
    head: str
    source: str
    park_commit: str


def unheld(con: sqlite3.Connection, repo_id: RepoId, free: Free, generation: int) -> tuple[str, str] | None:
    """The slot's name and park destination, when unreserved with its counter below `generation`."""
    row: tuple[object, ...] | None = con.execute(
        "SELECT name FROM slot s WHERE repo_id=? AND name=? AND generation<? AND NOT EXISTS "
        "(SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)",
        (repo_id, free.name, generation),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[0], str):
        raise sqlite3.DatabaseError("Malformed slot row")
    return row[0], free.park_commit


def reserve(con: sqlite3.Connection, repo_id: RepoId, slot: str, key: AttemptKey) -> None:
    """The new reservation of a free slot for the attempt `key`, and the slot's counter, inside the caller's write
    transaction."""
    held = {"slot": slot, "repo_id": repo_id, "generation": key.reservation_generation, "attempt_id": key.attempt_id}
    con.execute(f"INSERT INTO reservation ({RESERVATION}) VALUES ({marks(RESERVATION)})", bound(RESERVATION, held))
    issue(con, repo_id, slot, key.reservation_generation)


def insert_attempt(con: sqlite3.Connection, attempt: Mapping[str, object], content_digest: TaskContentDigest | None = None) -> None:
    """The admitted attempt row, inside the caller's write transaction."""
    values = bound(ATTEMPT_ADMITTED, {"source_checks_id": None, "repair_context": None, **attempt})
    if attempt["step"] == "plan" and content_digest is None:
        raise sqlite3.IntegrityError("Plan admission requires task-content evidence")
    con.execute(f"INSERT INTO attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", values)
    if attempt["step"] == "plan" and content_digest is not None:
        TaskContentStore.insert(con, str(attempt["attempt_id"]), content_digest)


def issue(con: sqlite3.Connection, repo_id: object, slot: object, generation: int) -> None:
    """The slot's counter: the last reservation generation issued for it."""
    con.execute("UPDATE slot SET generation=? WHERE repo_id=? AND name=?", (generation, repo_id, slot))


def bound(columns: str, values: Mapping[str, object]) -> tuple[object, ...]:
    """Values in the order of the owning column list, by name; a missing or extra column is a programming error."""
    names = columns.split(",")
    if set(names) != set(values):
        raise ValueError(f"Columns {sorted(set(names) ^ set(values))} do not match {columns}")
    return tuple(values[name] for name in names)


def as_count(value: object) -> int:
    if isinstance(value, int):
        return value
    raise sqlite3.DatabaseError("Malformed stored integer")


def issued(con: sqlite3.Connection, repo_id: RepoId, names: tuple[str, ...]) -> int:
    """The highest generation issued for any of the named slots (0 when none was)."""
    marked = ",".join("?" * len(names))
    found = f"SELECT coalesce(max(generation),0) FROM slot WHERE repo_id=? AND name IN ({marked})"
    row = con.execute(found, (repo_id, *names)).fetchone()
    return as_count(None if row is None else row[0])


def next_seq(con: sqlite3.Connection, backlog: str, task_id: str) -> int:
    row = con.execute(
        "SELECT coalesce(max(seq),0)+1 FROM attempt WHERE adapter='beads' AND backlog=? AND task_id=?", (backlog, task_id),
    ).fetchone()
    return as_count(None if row is None else row[0])


def task_attempted(con: sqlite3.Connection, backlog: str, task_id: str) -> bool:
    """Only an abandoned current attempt whose claim was returned permits a fresh admission."""
    found = con.execute(
        """SELECT EXISTS (SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id
        AND r.claim IN ('unclaimed','not_held')) FROM attempt p
        WHERE p.adapter='beads' AND p.backlog=? AND p.task_id=? ORDER BY p.seq DESC LIMIT 1""", (backlog, task_id),
    ).fetchone()
    return found is not None and not found[0]
