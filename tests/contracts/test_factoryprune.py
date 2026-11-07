"""History retention counts the real deletes while preserving state and exemptions."""

import sqlite3
from collections.abc import Iterator

import pytest

from taskloop.app.parts import STAGE_PARTS
from tlkernel import dbparts, factorydb

HISTORY = tuple(rule.table for rule in dbparts.prune_order(STAGE_PARTS))


@pytest.fixture
def con() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.executescript(dbparts.ddl(STAGE_PARTS))
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()


def seed(con: sqlite3.Connection, run: str, state: str = "done", ended: float = 2) -> None:
    con.execute("INSERT INTO run(run,repo,repo_key,bead,state,started,ended,manifest) VALUES (?,'r','r',?,?,1,?,'{}')",
                (run, run, state, ended))
    con.execute("INSERT INTO attempt(run,n,started,ended) VALUES (?,1,1,2)", (run,))
    con.execute("INSERT INTO step(run,key,try,attempt,status,started,ended) VALUES (?,'s',1,1,'done',1,2)", (run,))
    con.execute("INSERT INTO effect(key,run,name,state,intent_at,done_at) VALUES (?,?,'e','done',1,2)", (run, run))
    con.execute("INSERT INTO check_round(run,round,ts,body) VALUES (?,1,2,'{}')", (run,))
    con.execute("INSERT INTO timed(run,bead,kind,name,exec_s,wait_s,t) VALUES (?,?,'step','s',1,0,2)", (run, run))
    con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES (?,?,'answered',1,'{}')", (run, run))
    con.execute("INSERT INTO ask_ledger(t,event,ask,bead,body,origin) VALUES (2,'answer',?,?,'{}',?)", (run, run, run))


def counts(con: sqlite3.Connection) -> dict[str, int]:
    return {table: con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in HISTORY}


def test_counts_dry_run_and_exemptions(con: sqlite3.Connection) -> None:
    for run, state, ended in (("old", "done", 2), ("kept", "done", 2), ("lease", "done", 2),
                              ("created", "created", 2), ("running", "running", 2), ("fresh", "done", 10)):
        seed(con, run, state, ended)
    con.execute("INSERT INTO lease(kind,name,holder,run,since) VALUES ('run','l','h','lease',1)")
    # Ledger rows can link to the kept bead via ask alone.
    con.execute("INSERT INTO ask_ledger(t,event,ask,body,origin) VALUES (2,'answer','kept','{}','ask-only')")
    keep = frozenset({"kept", *(f"bead-{i}" for i in range(1200))})
    before = counts(con)
    snapshot = list(con.iterdump())
    planned = factorydb.prune_older_than(con, 10, keep_beads=keep, dry_run=True)
    assert planned == {"ask_ledger": 3, "check_round": 1, "step": 1, "attempt": 1, "effect": 1, "timed": 1, "run": 1}
    assert list(con.iterdump()) == snapshot
    assert not con.in_transaction
    actual = factorydb.prune_older_than(con, 10, keep_beads=keep)
    assert actual == planned
    assert counts(con) == {table: before[table] - actual[table] for table in HISTORY}
    assert con.execute("SELECT run FROM run ORDER BY run").fetchall() == [
        ("created",), ("fresh",), ("kept",), ("lease",), ("running",)]
    assert con.execute("SELECT count(*) FROM ask").fetchone() == (6,)
    assert con.execute("SELECT count(*) FROM lease").fetchone() == (1,)
    assert all(n == 0 for n in factorydb.prune_older_than(con, 10, keep_beads=keep).values())


def test_dry_run_subsets_use_the_same_parent_guards(con: sqlite3.Connection) -> None:
    seed(con, "old")
    assert factorydb.prune_older_than(con, 10, ("run",), dry_run=True) == {"run": 0}
    assert factorydb.prune_older_than(con, 10, ("step",), dry_run=True) == {"step": 1}
    assert counts(con) == dict.fromkeys(HISTORY, 1)
    assert factorydb.prune_older_than(con, 10) == dict.fromkeys(HISTORY, 1)


def test_caller_transaction_is_rejected_without_rolling_it_back(con: sqlite3.Connection) -> None:
    con.execute("BEGIN")
    with pytest.raises(sqlite3.OperationalError):
        factorydb.prune_older_than(con, 10, dry_run=True)
    assert con.in_transaction
    con.rollback()
