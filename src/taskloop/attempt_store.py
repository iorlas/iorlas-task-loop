"""SQL owner for attempt loads and composition of status reads and fenced writes."""

import sqlite3
from dataclasses import astuple

from taskloop.attempt_loads import AttemptLoads as LoadDecoding
from taskloop.attempt_loads import RetainedInputs
from taskloop.attempt_reads import as_text, stored_setting
from taskloop.attempt_status_store import AttemptReads
from taskloop.attempt_types import AttemptKey, FileRef
from taskloop.attempt_write_store import AttemptWrites
from taskloop.factory_schema import ANSWER, ATTEMPT_LOADED, EVIDENCE, FACTS, VERDICT, prefixed
from taskloop.step import Step

__all__ = ["REGISTRATION_BUSY_MS", "AttemptLoads", "AttemptReads", "AttemptStore", "configure_registration", "retained_on"]

# A registration write (the entry's or the harness's) waits at most this for the write lock, so it finishes well inside
# the registered start's fixed 5 s window; every other write keeps the library's 5 s.
REGISTRATION_BUSY_MS = 1500


def configure_registration(con: sqlite3.Connection) -> None:
    """Keep registration lock waits inside the registered start's fixed window."""
    con.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")


def retained_on(con: sqlite3.Connection, key: AttemptKey) -> RetainedInputs | None:
    """Read the original implement inputs on the caller's connection, including inside conflict admission."""
    row = con.execute(
        "SELECT repo_id,backlog,task_id,tracker_root,end_commit,input_path,input_digest,harness,provider,model,effort,access_policy,"
        "compaction_token_limit "
        "FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=? AND step=?",
        (*astuple(key), Step.IMPLEMENT),
    ).fetchone()
    if row is None:
        return None
    return RetainedInputs(key=key, repo_id=as_text(row[0]), backlog=as_text(row[1]), task_id=as_text(row[2]),
                          tracker_root=as_text(row[3]), checked=as_text(row[4]),
                          input_ref=FileRef(as_text(row[5]), as_text(row[6])),
                          setting=stored_setting(*row[7:13]))


class AttemptLoads(LoadDecoding):
    """Concrete queries for SQL-free attempt decoding and fencing."""

    def _retained(self, con: sqlite3.Connection, key: AttemptKey) -> RetainedInputs | None:
        return retained_on(con, key)

    def _plan_row(self, con: sqlite3.Connection, repo_id: str, backlog: str, task_id: str,
                  tracker_root: str) -> tuple[object, ...] | None:
        return con.execute(
            "SELECT p.attempt_id,p.dispatch_token,p.generation,p.rev,p.end_commit,v.blob,v.verdict "
            "FROM attempt p LEFT JOIN factory_commit v ON v.attempt_id=p.attempt_id "
            "AND v.dispatch_token=p.dispatch_token AND v.generation=p.generation "
            "WHERE p.repo_id=? AND p.adapter='beads' AND p.backlog=? AND p.task_id=? AND p.tracker_root=? "
            "AND p.step=? ORDER BY p.seq DESC LIMIT 1", (repo_id, backlog, task_id, tracker_root, Step.PLAN),
        ).fetchone()

    def _earlier_row(self, con: sqlite3.Connection, repo_id: str, backlog: str, task_id: str,
                     tracker_root: str) -> tuple[object, ...] | None:
        return con.execute(
            """SELECT attempt_id,dispatch_token,generation,rev,slot,step,end_commit FROM attempt
            WHERE repo_id=? AND adapter='beads' AND backlog=? AND task_id=? AND tracker_root=?
            ORDER BY seq DESC LIMIT 1""", (repo_id, backlog, task_id, tracker_root),
        ).fetchone()

    def _scope_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None:
        return con.execute(
            "SELECT repo_id,backlog,task_id,tracker_root FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
            astuple(key),
        ).fetchone()

    def _attempt_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None:
        return con.execute(
            f"""SELECT {prefixed("p", ATTEMPT_LOADED)},
            (SELECT path FROM slot WHERE name=p.slot AND repo_id=p.repo_id),
            (SELECT coalesce(q.end_commit, q.base_commit) FROM attempt q WHERE q.attempt_id=p.previous_attempt_id),p.repair_context,
            p.declared_start
            FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
            astuple(key),
        ).fetchone()

    def _reservation_row(self, con: sqlite3.Connection, slot: object, repo_id: object) -> tuple[object, ...] | None:
        return con.execute(
            "SELECT repo_id,generation,attempt_id FROM reservation WHERE slot=? AND repo_id=?", (slot, repo_id)
        ).fetchone()

    def _repair_row(self, con: sqlite3.Connection, previous: str) -> tuple[object, ...] | None:
        return con.execute(
            "SELECT p.session_ref,p.base_commit,p.number,p.deadline,p.harness,p.provider,p.model,p.effort,p.access_policy,"
            "p.compaction_token_limit,p.repair_context,e.answer_failure FROM attempt p JOIN execution e "
            "ON e.attempt_id=p.attempt_id WHERE p.attempt_id=?", (previous,),
        ).fetchone()

    def _slot_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None:
        return con.execute("SELECT slot_head FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                           astuple(key)).fetchone()

    def _execution_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None:
        return con.execute(
            f"""SELECT {prefixed("e", FACTS)},{prefixed("e", EVIDENCE)},{prefixed("e", ANSWER)},{prefixed("v", VERDICT)}
            FROM execution e LEFT JOIN factory_commit v
            ON v.attempt_id=e.attempt_id AND v.dispatch_token=e.dispatch_token AND v.generation=e.generation
            WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=?""",
            astuple(key),
        ).fetchone()

    def _callback_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[str | bytes | None] | None:
        return con.execute("SELECT recovery_callback FROM execution WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                           astuple(key)).fetchone()


class AttemptStore(AttemptWrites, AttemptLoads, AttemptReads):
    """The attempt store's public API: fenced loads and writes, with historical status reads."""
