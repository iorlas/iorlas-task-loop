"""The sole age-retention SQL for authoritative factory history."""

import sqlite3

import sqlite_store

HISTORY = ("ask_ledger", "check_round", "step", "attempt", "effect", "run")
ELIGIBLE = """SELECT r.run FROM run AS r
    WHERE r.ended < ? AND r.state NOT IN ('created','running')
    AND NOT EXISTS (SELECT 1 FROM temp.prune_keep_bead AS k WHERE k.bead=r.bead)
    AND NOT EXISTS (SELECT 1 FROM lease AS l WHERE l.run=r.run)
    AND NOT EXISTS (SELECT 1 FROM wait AS w WHERE w.run=r.run)
    AND NOT EXISTS (SELECT 1 FROM signal AS s WHERE s.run=r.run AND s.taken IS NULL)
    AND NOT EXISTS (SELECT 1 FROM ask AS a WHERE a.bead=r.bead AND a.status IN ('open','open_soft'))"""
PREDICATES = {
    "ask_ledger": """t < ?
        AND NOT EXISTS (SELECT 1 FROM temp.prune_keep_bead AS k WHERE k.bead=ask_ledger.bead)
        AND NOT EXISTS (SELECT 1 FROM ask AS a JOIN temp.prune_keep_bead AS k ON k.bead=a.bead
            WHERE a.id=ask_ledger.ask)
        AND NOT EXISTS (SELECT 1 FROM ask AS a
            WHERE (a.id=ask_ledger.ask OR a.bead=ask_ledger.bead) AND a.status IN ('open','open_soft'))
        AND NOT EXISTS (SELECT 1 FROM run AS r
            WHERE r.bead=ask_ledger.bead AND r.state IN ('created','running'))""",
    "check_round": f"""ts < ? AND NOT EXISTS (
        SELECT 1 FROM run AS parent WHERE parent.run=check_round.run AND parent.run NOT IN ({ELIGIBLE}))""",
    "step": f"run IN ({ELIGIBLE})",
    "attempt": f"run IN ({ELIGIBLE})",
    "effect": f"run IN ({ELIGIBLE})",
    "run": f"""run IN ({ELIGIBLE})
        AND NOT EXISTS (SELECT 1 FROM step WHERE step.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM attempt WHERE attempt.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM effect WHERE effect.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM check_round WHERE check_round.run=run.run)""",
}


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
        for table in HISTORY:
            if table in selected:
                params = (cutoff_t, cutoff_t) if table == "check_round" else (cutoff_t,)
                counts[table] = con.execute(f'DELETE FROM "{table}" WHERE {PREDICATES[table]}', params).rowcount
        con.execute("DROP TABLE temp.prune_keep_bead")
        if dry_run:
            con.rollback()
    return counts
