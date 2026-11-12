"""The admission's row writes, inside the caller's write transaction: a new `reservation`, the admitted `attempt` row and the
slot's counter (`generation`, the last reservation generation issued for it)."""

import sqlite3
from collections.abc import Mapping

from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import ATTEMPT_ADMITTED, RESERVATION, marks
from taskloop.repo import RepoId


def reserve(con: sqlite3.Connection, repo_id: RepoId, slot: str, key: AttemptKey) -> None:
    """The new reservation of a free slot for the attempt `key`, and the slot's counter, inside the caller's write
    transaction."""
    held = {"slot": slot, "repo_id": repo_id, "generation": key.reservation_generation, "attempt_id": key.attempt_id}
    con.execute(f"INSERT INTO reservation ({RESERVATION}) VALUES ({marks(RESERVATION)})", bound(RESERVATION, held))
    issue(con, repo_id, slot, key.reservation_generation)


def insert_attempt(con: sqlite3.Connection, attempt: Mapping[str, object]) -> None:
    """The admitted attempt row, inside the caller's write transaction."""
    con.execute(f"INSERT INTO attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", bound(ATTEMPT_ADMITTED, attempt))


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
