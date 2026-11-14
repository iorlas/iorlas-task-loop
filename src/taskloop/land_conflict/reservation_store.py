"""The conflict slice's reservation predicate for candidate admission's transaction."""

import sqlite3

from taskloop.attempt_types import AttemptKey


def owns(con: sqlite3.Connection, key: AttemptKey) -> bool:
    """Authorize the exact conflict key against both the reservation and current slot identity."""
    return con.execute(
        "SELECT 1 FROM land_conflict f JOIN reservation r ON r.repo_id=f.repo_id AND r.slot=f.slot "
        "AND r.attempt_id=f.operation_id AND r.generation=f.generation "
        "JOIN slot s ON s.repo_id=f.repo_id AND s.name=f.slot AND s.generation=f.generation "
        "AND s.path=json_extract(f.data,'$.slot_path') "
        "WHERE f.operation_id=? AND f.dispatch_token=? AND f.generation=?",
        (key.attempt_id, key.dispatch_token, key.reservation_generation),
    ).fetchone() is not None


def holds_source(con: sqlite3.Connection, checks: str) -> bool:
    return con.execute(
        "SELECT 1 FROM land_conflict f JOIN checks_attempt c ON c.after_attempt_id=f.implement_id "
        "JOIN reservation q ON q.repo_id=f.repo_id AND q.slot=f.slot "
        "AND q.attempt_id=f.operation_id AND q.generation=f.generation WHERE c.attempt_id=?",
        (checks,),
    ).fetchone() is not None
