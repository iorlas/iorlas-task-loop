"""Conditional SQL owner for admitted plan execution; no admission or release writer."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import astuple
from typing import Literal

from any_agent.procs import Worker
from sqlite_store import Schema, begin_immediate

from taskloop.plan_types import Admission, AnswerState, AttemptKey, AttemptRecord, Evidence, ExecutionFacts, FileRef, StoredExecution
from taskloop.repo import RepoId
from taskloop.task import TaskReference, TaskScope

SCHEMA = Schema(version=1, name="factory", steps={}, ddl="""
CREATE TABLE reservation (
 slot TEXT PRIMARY KEY, repo_id TEXT NOT NULL, cwd TEXT NOT NULL,
 generation INTEGER NOT NULL, attempt_id TEXT NOT NULL UNIQUE
);
CREATE TABLE plan_attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 adapter TEXT NOT NULL CHECK(adapter='beads'), backlog TEXT NOT NULL, task_id TEXT NOT NULL,
 repo_id TEXT NOT NULL, slot TEXT NOT NULL, input_path TEXT NOT NULL, input_digest TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version=1), model TEXT NOT NULL, effort TEXT NOT NULL,
 sandbox TEXT NOT NULL, deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','dispatching','registered','captured')),
 rev INTEGER NOT NULL DEFAULT 0, worker_pid INTEGER, worker_pgid INTEGER, worker_start TEXT, worker_boot TEXT,
 session_ref TEXT, session_conflict INTEGER NOT NULL DEFAULT 0 CHECK(session_conflict IN (0,1))
);
CREATE TABLE plan_execution (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_attempt(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 rc INTEGER, timed_out INTEGER NOT NULL, stop TEXT, watch TEXT, work INTEGER NOT NULL, stands INTEGER NOT NULL,
 answered INTEGER, reason TEXT, http_status INTEGER, tokens_known INTEGER NOT NULL, t_in INTEGER, t_cached INTEGER, t_out INTEGER,
 cumulative_known INTEGER NOT NULL, c_in INTEGER, c_cached INTEGER, c_out INTEGER, turns INTEGER,
 stdout_path TEXT NOT NULL, stdout_digest TEXT NOT NULL, stderr_path TEXT NOT NULL, stderr_digest TEXT NOT NULL,
 answer_path TEXT NOT NULL, answer_digest TEXT NOT NULL, diagnostic_path TEXT NOT NULL, diagnostic_digest TEXT NOT NULL,
 answer_kind TEXT NOT NULL DEFAULT 'validation_pending' CHECK(answer_kind IN ('validation_pending','valid','missing','json_invalid','schema_invalid')),
 disposition TEXT, plan_path TEXT, reported_commit TEXT,
 publication TEXT NOT NULL CHECK(publication IN ('complete','pending','conflict','fault'))
);
""")


class StoreUnavailable(Exception):
    """No progress was acknowledged by the store."""


class StoreRefused(Exception):
    """The authoritative admission or reservation fence does not match."""


def _str(value: object) -> str:
    if isinstance(value, str):
        return value
    raise StoreUnavailable("Malformed stored text")


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise StoreUnavailable("Malformed stored integer")


def _nullable_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _nullable_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _identity(worker: Worker) -> tuple[int, str, str]:
    return worker.pid, worker.start, worker.boot


def _facts_values(facts: ExecutionFacts) -> tuple[object, ...]:
    return (facts.rc, facts.timed_out, facts.stop, facts.watch, facts.work, facts.stands, facts.answered,
            facts.reason, facts.http_status, facts.tokens is not None, *(facts.tokens or (None, None, None)),
            facts.cumulative is not None, *(facts.cumulative or (None, None, None)), facts.turns)


class PlanStore:
    def __init__(self, connect: Callable[[], sqlite3.Connection | None]) -> None:
        self.connect = connect

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            con = self.connect()
            if con is None or con.execute("PRAGMA user_version").fetchone() != (1,):
                raise StoreUnavailable("Factory database unavailable or incompatible")
            if write:
                with begin_immediate(con):
                    yield con
            else:
                yield con
        except sqlite3.Error as error:
            raise StoreUnavailable("Factory database operation failed") from error

    def _load(self, con: sqlite3.Connection, key: AttemptKey) -> AttemptRecord | None:
        row: tuple[object, ...] | None = con.execute("""SELECT p.backlog,p.task_id,p.repo_id,p.slot,p.input_path,p.input_digest,
            p.model,p.effort,p.sandbox,p.deadline,p.entry_pid,p.entry_start,p.entry_boot,p.phase,p.rev,
            p.worker_pid,p.worker_pgid,p.worker_start,p.worker_boot,p.session_ref,p.session_conflict,
            (SELECT cwd FROM reservation WHERE slot=p.slot) FROM plan_attempt p
            WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""", astuple(key)).fetchone()
        if row is None:
            return None
        if any(value is None for value in row[10:13]):
            raise StoreRefused("unregistered_entry")
        if not isinstance(row[9], (int, float)):
            raise StoreUnavailable("Malformed deadline")
        admission = Admission(key, TaskReference(TaskScope(_str(row[0])), _str(row[1])), RepoId(_str(row[2])), _str(row[3]),
                              _str(row[21]), FileRef(_str(row[4]), _str(row[5])), _str(row[6]), _str(row[7]), _str(row[8]),
                              float(row[9]), (_int(row[10]), _str(row[11]), _str(row[12])))
        worker = None if row[15] is None else Worker(pid=_int(row[15]), pgid=_int(row[16]), start=_str(row[17]), boot=_str(row[18]))
        return AttemptRecord(admission, _str(row[13]), _int(row[14]), worker, _nullable_str(row[19]), bool(_int(row[20])))

    def load(self, key: AttemptKey) -> AttemptRecord | None:
        with self._connection() as con:
            return self._load(con, key)

    def _fence(self, con: sqlite3.Connection, admission: Admission) -> AttemptRecord:
        record = self._load(con, admission.key)
        if record is None or record.admission != admission:
            raise StoreRefused("changed_admission")
        row = con.execute("SELECT repo_id,cwd,generation,attempt_id FROM reservation WHERE slot=?", (admission.slot,)).fetchone()
        if row != (admission.repo_id, admission.cwd, admission.key.reservation_generation, admission.key.attempt_id):
            raise StoreRefused("stale_reservation")
        return record

    def check(self, admission: Admission) -> None:
        with self._connection() as con:
            self._fence(con, admission)

    def dispatch(self, expected: AttemptRecord) -> Literal["accepted", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, expected.admission)
            if current.phase != "admitted" or current.revision != expected.revision:
                return "conflict"
            con.execute("UPDATE plan_attempt SET phase='dispatching',rev=rev+1 WHERE attempt_id=? AND rev=?",
                        (expected.admission.key.attempt_id, expected.revision))
            return "accepted"

    def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is not None:
                return "already_same" if _identity(current.worker) == _identity(worker) else "conflict"
            if current.phase != "dispatching":
                return "conflict"
            con.execute("""UPDATE plan_attempt SET phase='registered',worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?,rev=rev+1
                WHERE attempt_id=? AND rev=?""", (worker.pid, worker.pgid, worker.start, worker.boot, admission.key.attempt_id, current.revision))
            return "accepted"

    def session(self, admission: Admission, ref: str) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is None:
                raise StoreRefused("unregistered_worker")
            if current.session_ref == ref:
                return "already_same"
            if current.session_ref is not None:
                con.execute("UPDATE plan_attempt SET session_conflict=1,rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
                con.execute("UPDATE plan_execution SET publication='conflict' WHERE attempt_id=?", (admission.key.attempt_id,))
                return "conflict"
            con.execute("UPDATE plan_attempt SET session_ref=?,rev=rev+1 WHERE attempt_id=?", (ref, admission.key.attempt_id))
            return "accepted"

    def capture(self, admission: Admission, worker: Worker, facts: ExecutionFacts, evidence: Evidence,
                publication: Literal["complete", "pending", "conflict", "fault"]) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is None or _identity(current.worker) != _identity(worker):
                raise StoreRefused("worker_mismatch")
            old = self._execution(con, admission.key)
            if old is not None:
                return "already_same" if old.facts == facts and old.evidence == evidence else "conflict"
            if current.phase != "registered":
                return "conflict"
            refs = tuple(value for ref in astuple(evidence) for value in ref)
            values = (*astuple(admission.key), *_facts_values(facts), *refs, publication)
            con.execute("""INSERT INTO plan_execution (attempt_id,dispatch_token,generation,rc,timed_out,stop,watch,work,stands,answered,
                reason,http_status,tokens_known,t_in,t_cached,t_out,cumulative_known,c_in,c_cached,c_out,turns,
                stdout_path,stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,publication)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            con.execute("UPDATE plan_attempt SET phase='captured',rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
            return "accepted"

    def answer(self, admission: Admission, evidence: Evidence, answer: AnswerState) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            self._fence(con, admission)
            current = self._execution(con, admission.key)
            if current is None or current.evidence != evidence:
                return "conflict"
            if current.answer.kind != "validation_pending":
                return "already_same" if current.answer == answer else "conflict"
            con.execute("UPDATE plan_execution SET answer_kind=?,disposition=?,plan_path=?,reported_commit=? WHERE attempt_id=?",
                        (*astuple(answer), admission.key.attempt_id))
            return "accepted"

    def _execution(self, con: sqlite3.Connection, key: AttemptKey) -> StoredExecution | None:
        row: tuple[object, ...] | None = con.execute("SELECT * FROM plan_execution WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)).fetchone()
        if row is None:
            return None
        tokens = tuple(_nullable_int(v) for v in row[13:16]) if row[12] else None
        cumulative = tuple(_nullable_int(v) for v in row[17:20]) if row[16] else None
        facts = ExecutionFacts(_nullable_int(row[3]), bool(row[4]), _nullable_str(row[5]), _nullable_str(row[6]), bool(row[7]), bool(row[8]),
                               None if row[9] is None else bool(row[9]), _nullable_str(row[10]), _nullable_int(row[11]),
                               None if tokens is None else (tokens[0], tokens[1], tokens[2]),
                               None if cumulative is None else (cumulative[0], cumulative[1], cumulative[2]), _nullable_int(row[20]))
        evidence = Evidence(*(FileRef(_str(row[i]), _str(row[i+1])) for i in (21,23,25,27)))
        kind = _str(row[29])
        if kind not in ("validation_pending", "valid", "missing", "json_invalid", "schema_invalid"):
            raise StoreUnavailable("Invalid answer phase")
        publication = _str(row[33])
        if publication not in ("complete", "pending", "conflict", "fault"):
            raise StoreUnavailable("Invalid publication phase")
        return StoredExecution(key, facts, evidence, AnswerState(kind, _nullable_str(row[30]), _nullable_str(row[31]), _nullable_str(row[32])), publication)

    def collect(self, key: AttemptKey) -> StoredExecution | None:
        with self._connection() as con:
            return self._execution(con, key)
