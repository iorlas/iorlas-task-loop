"""Compare-and-swap updates within a caller-owned transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    import sqlite3

SqlValue: TypeAlias = str | int | float | bytes | None


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cas_update(
    con: sqlite3.Connection,
    table: str,
    key_col: str,
    key: SqlValue,
    rev: int,
    *,
    revisioned: frozenset[str],
    **cols: SqlValue,
) -> bool:
    """Advance rev once if it matches, refusing revision/key changes."""
    if table not in revisioned or "rev" in cols or key_col in cols:
        message = "unrevisioned table or update of revision/key column"
        raise ValueError(message)
    if not con.in_transaction:
        message = "CAS requires a caller-owned transaction"
        raise ValueError(message)
    assignments = [f"{_identifier(column)}=?" for column in cols]
    assignments.append('"rev"="rev"+1')
    statement = f"UPDATE {_identifier(table)} SET {', '.join(assignments)} WHERE {_identifier(key_col)}=? AND rev=?"
    return con.execute(statement, (*cols.values(), key, rev)).rowcount == 1
