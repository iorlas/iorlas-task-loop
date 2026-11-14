"""The conflict slice's reservation predicate for candidate admission's transaction."""

import sqlite3


def holds_source(con: sqlite3.Connection, checks: str) -> bool:
    return con.execute(
        "SELECT 1 FROM land_conflict f JOIN checks_attempt c ON c.after_attempt_id=f.implement_id "
        "JOIN reservation q ON q.repo_id=f.repo_id AND q.slot=f.slot "
        "AND q.attempt_id=f.operation_id AND q.generation=f.generation WHERE c.attempt_id=?",
        (checks,),
    ).fetchone() is not None
