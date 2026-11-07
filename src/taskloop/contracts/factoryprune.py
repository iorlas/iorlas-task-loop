"""The sole age-retention SQL for authoritative factory history."""

import sqlite3

import sqlite_store

from taskloop.contracts import dbparts, factoryparts  # noqa: F401  (registers the parts whose rules these are)

ORDER = dbparts.prune_order()  # every part's rules, children before parents (the parts declare it: factoryparts)
HISTORY = tuple(rule.table for rule in ORDER)


def prune_older_than(
    con: sqlite3.Connection,
    cutoff_t: float,
    tables: tuple[str, ...] = HISTORY,
    keep_beads: frozenset[str] = frozenset(),
    dry_run: bool = False,
) -> dict[str, int]:
    """Atomically prune selected history tables; return deleted row counts.

    Run history ages from ended, never started. Live runs, runs of keep_beads,
    and runs referenced by any lease or wait, an untaken signal, or an open ask
    stay with their history. Kept beads retain their ask audit too. Current
    state tables are never pruned. Subsets retain parents with remaining
    history children. The caller must not already have a transaction open.
    Dry runs execute the same DELETEs under the writer lock then roll back.
    Bound single-row inserts make exemptions independent of SQL variable limits.
    """
    selected = set(tables)
    if selected - set(HISTORY):
        raise ValueError("only history tables may be pruned")
    counts: dict[str, int] = {}
    with sqlite_store.begin_immediate(con):
        con.execute("CREATE TEMP TABLE prune_keep_bead (bead TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO temp.prune_keep_bead VALUES (?)", ((b,) for b in keep_beads))
        for rule in ORDER:
            if rule.table in selected:
                counts[rule.table] = con.execute(f'DELETE FROM "{rule.table}" WHERE {rule.where}', (cutoff_t,) * rule.cutoffs).rowcount
        con.execute("DROP TABLE temp.prune_keep_bead")
        if dry_run:
            con.rollback()
    return counts
