"""Conditional SQL owner for admitted plan execution; no admission or release writer."""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import astuple
from typing import Literal

from any_agent.procs import Worker
from sqlite_store import begin_immediate

from taskloop.plan_schema import ANSWER, ATTEMPT_LOADED, EVIDENCE, FACTS, current, prefixed
from taskloop.plan_types import Admission, AnswerState, AttemptKey, AttemptRecord, Evidence, ExecutionFacts, FileRef, StoredExecution
from taskloop.repo import RepoId
from taskloop.task import TaskReference, TaskScope


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
    return (
        facts.rc,
        facts.timed_out,
        facts.stop,
        facts.watch,
        facts.work,
        facts.stands,
        facts.answered,
        facts.reason,
        facts.http_status,
        facts.tokens is not None,
        *(facts.tokens or (None, None, None)),
        facts.cumulative is not None,
        *(facts.cumulative or (None, None, None)),
        facts.turns,
        facts.session,
    )


class PlanStore:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
    ) -> None:
        """`begin` is the writer transaction; a composition on a Store passes its begin_immediate, which evicts a failed shared writer."""
        self.connect, self.begin = connect, begin

    @contextmanager
    def _connection(self, *, write: bool = False) -> Generator[sqlite3.Connection]:
        try:
            con = self.connect()
            if con is None or not current(con):
                raise StoreUnavailable("Factory database unavailable or incompatible")
            if write:
                with self.begin(con):
                    yield con
            else:
                yield con
        except sqlite3.Error as error:
            raise StoreUnavailable("Factory database operation failed") from error

    def _load(self, con: sqlite3.Connection, key: AttemptKey) -> AttemptRecord | None:
        row: tuple[object, ...] | None = con.execute(
            f"""SELECT {prefixed("p", ATTEMPT_LOADED)},
            (SELECT cwd FROM reservation WHERE slot=p.slot AND repo_id=p.repo_id) FROM plan_attempt p
            WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
            astuple(key),
        ).fetchone()
        if row is None:
            return None
        if any(value is None for value in row[10:13]):
            raise StoreRefused("unregistered_entry")
        held = con.execute(
            "SELECT repo_id,generation,attempt_id FROM reservation WHERE slot=? AND repo_id=?", (row[3], row[2])
        ).fetchone()
        if held != (row[2], key.reservation_generation, key.attempt_id) or row[21] is None:
            raise StoreRefused("stale_reservation")
        if not isinstance(row[9], (int, float)):
            raise StoreUnavailable("Malformed deadline")
        admission = Admission(
            key,
            TaskReference(TaskScope(_str(row[0])), _str(row[1])),
            RepoId(_str(row[2])),
            _str(row[3]),
            _str(row[21]),
            FileRef(_str(row[4]), _str(row[5])),
            _str(row[6]),
            _str(row[7]),
            _str(row[8]),
            float(row[9]),
            (_int(row[10]), _str(row[11]), _str(row[12])),
        )
        worker = None if row[15] is None else Worker(pid=_int(row[15]), pgid=_int(row[16]), start=_str(row[17]), boot=_str(row[18]))
        return AttemptRecord(admission, _str(row[13]), _int(row[14]), worker, _nullable_str(row[19]), bool(_int(row[20])))

    def load(self, key: AttemptKey) -> AttemptRecord | None:
        with self._connection() as con:
            return self._load(con, key)

    def _fence(self, con: sqlite3.Connection, admission: Admission) -> AttemptRecord:
        record = self._load(con, admission.key)
        if record is None or record.admission != admission:
            raise StoreRefused("changed_admission")
        return record

    def state(self, key: AttemptKey) -> tuple[str, bool] | None:
        """Dispatch phase and recorded session conflict, without needing a live reservation (historical reads)."""
        with self._connection() as con:
            row = con.execute(
                "SELECT phase,session_conflict FROM plan_attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
            ).fetchone()
            return None if row is None else (_str(row[0]), bool(_int(row[1])))

    def dispatch(self, expected: AttemptRecord) -> Literal["accepted", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, expected.admission)
            if current.phase != "admitted" or current.revision != expected.revision:
                return "conflict"
            con.execute(
                "UPDATE plan_attempt SET phase='dispatching',rev=rev+1 WHERE attempt_id=? AND rev=?",
                (expected.admission.key.attempt_id, expected.revision),
            )
            return "accepted"

    def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is not None:
                return "already_same" if _identity(current.worker) == _identity(worker) else "conflict"
            if current.phase != "dispatching":
                return "conflict"
            con.execute(
                """UPDATE plan_attempt SET phase='registered',worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?,rev=rev+1
                WHERE attempt_id=? AND rev=?""",
                (worker.pid, worker.pgid, worker.start, worker.boot, admission.key.attempt_id, current.revision),
            )
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

    def capture(
        self,
        admission: Admission,
        worker: Worker | None,
        facts: ExecutionFacts,
        evidence: Evidence,
        publication: Literal["complete", "pending", "conflict", "fault"],
    ) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is None or (worker is not None and _identity(current.worker) != _identity(worker)):
                raise StoreRefused("worker_mismatch")
            if current.session_conflict:
                publication = "conflict"  # a recorded differing session is never published as complete
            old = self._execution(con, admission.key)
            if old is not None:
                if old.facts != facts or old.evidence != evidence:
                    return "conflict"
                if old.publication in ("pending", "fault") and publication in ("complete", "conflict"):
                    con.execute(
                        "UPDATE plan_execution SET publication=? WHERE attempt_id=? AND publication IN ('pending','fault')",
                        (publication, admission.key.attempt_id),
                    )
                    return "accepted"
                return "already_same"
            if current.phase != "registered":
                return "conflict"
            refs = tuple(value for ref in astuple(evidence) for value in ref)
            values = (*astuple(admission.key), *_facts_values(facts), *refs, publication)
            marks = ",".join("?" * len(values))
            con.execute(
                f"INSERT INTO plan_execution (attempt_id,dispatch_token,generation,{FACTS},{EVIDENCE},publication) VALUES ({marks})", values
            )
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
            con.execute(
                "UPDATE plan_execution SET answer_kind=?,disposition=?,plan_path=?,reported_commit=? WHERE attempt_id=?",
                (*astuple(answer), admission.key.attempt_id),
            )
            return "accepted"

    def _execution(self, con: sqlite3.Connection, key: AttemptKey) -> StoredExecution | None:
        row: tuple[object, ...] | None = con.execute(
            f"SELECT {FACTS},{EVIDENCE},{ANSWER} FROM plan_execution WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
        ).fetchone()
        if row is None:
            return None
        tokens = tuple(_nullable_int(v) for v in row[10:13]) if row[9] else None
        cumulative = tuple(_nullable_int(v) for v in row[14:17]) if row[13] else None
        facts = ExecutionFacts(
            _nullable_int(row[0]),
            bool(row[1]),
            _nullable_str(row[2]),
            _nullable_str(row[3]),
            bool(row[4]),
            bool(row[5]),
            None if row[6] is None else bool(row[6]),
            _nullable_str(row[7]),
            _nullable_int(row[8]),
            None if tokens is None else (tokens[0], tokens[1], tokens[2]),
            None if cumulative is None else (cumulative[0], cumulative[1], cumulative[2]),
            _nullable_int(row[17]),
            _nullable_str(row[18]),
        )
        evidence = Evidence(*(FileRef(_str(row[i]), _str(row[i + 1])) for i in (19, 21, 23, 25)))
        kind, publication = _str(row[27]), _str(row[31])
        if kind not in ("validation_pending", "valid", "missing", "json_invalid", "schema_invalid"):
            raise StoreUnavailable("Invalid answer phase")
        if publication not in ("complete", "pending", "conflict", "fault"):
            raise StoreUnavailable("Invalid publication phase")
        return StoredExecution(
            key, facts, evidence, AnswerState(kind, _nullable_str(row[28]), _nullable_str(row[29]), _nullable_str(row[30])), publication
        )

    def collect(self, key: AttemptKey) -> StoredExecution | None:
        with self._connection() as con:
            return self._execution(con, key)
