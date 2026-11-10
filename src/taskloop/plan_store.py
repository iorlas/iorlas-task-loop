"""Conditional SQL owner for admitted plan execution; no admission or release writer."""

import json
import math
import sqlite3
from dataclasses import astuple
from typing import Literal

from any_agent.procs import Worker

from taskloop.plan_reads import (
    PlanReads,
    StoreRefused,
    StoreUnavailable,
    as_int,
    as_listed,
    as_nullable_int,
    as_nullable_text,
    as_text,
)
from taskloop.plan_schema import ANSWER, ATTEMPT_LOADED, EVIDENCE, FACTS, VERDICT, prefixed
from taskloop.plan_types import (
    RULES,
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    Evidence,
    ExecutionFacts,
    FileRef,
    Rejected,
    Replaced,
    StoredExecution,
    Verdict,
    Verified,
)
from taskloop.repo import RepoId
from taskloop.task import TaskReference, TaskScope

# A registration write (the entry's or the harness's) waits at most this for the write lock, so it finishes well inside
# the registered start's fixed 5 s window; every other write keeps the library's 5 s.
REGISTRATION_BUSY_MS = 1500


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


def _verdict_values(result: Verdict) -> tuple[str, str | None, str | None, int]:
    if isinstance(result, Verified):
        return "verified", None, result.plan_blob, int(result.reused)
    return "rejected", result.reason, None, 0


def _verdict(row: tuple[object, ...]) -> Verdict | None:
    """The stored verdict of a verification row; None for the all-NULL row of a LEFT JOIN without one."""
    kind, reason, blob, reused = row
    if kind is None:
        return None
    if kind == "verified":
        return Verified(as_text(blob), bool(as_int(reused)))
    rule = next((rule for rule in RULES if rule == reason), None)
    if kind != "rejected" or rule is None:
        raise StoreUnavailable("Invalid stored verdict")
    return Rejected(rule)


class PlanStore(PlanReads):
    """The fenced writes of an admitted attempt and the reads they need; the status reads are `PlanReads`'."""

    def _load(self, con: sqlite3.Connection, key: AttemptKey) -> AttemptRecord | None:
        """The fenced read; `start` (E) is the previous attempt's X, else its B, frozen since this attempt took over."""
        row: tuple[object, ...] | None = con.execute(
            f"""SELECT {prefixed("p", ATTEMPT_LOADED)},
            (SELECT cwd FROM reservation WHERE slot=p.slot AND repo_id=p.repo_id),
            (SELECT coalesce(q.plan_commit, q.base_commit) FROM plan_attempt q WHERE q.attempt_id=p.previous_attempt_id)
            FROM plan_attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
            astuple(key),
        ).fetchone()
        if row is None:
            return None
        if any(value is None for value in row[10:13]):
            raise StoreRefused("unregistered_entry")
        held = con.execute(
            "SELECT repo_id,generation,attempt_id FROM reservation WHERE slot=? AND repo_id=?", (row[3], row[2])
        ).fetchone()
        if held != (row[2], key.reservation_generation, key.attempt_id) or row[25] is None:
            raise StoreRefused("stale_reservation")
        if not isinstance(row[9], (int, float)):
            raise StoreUnavailable("Malformed deadline")
        start = as_nullable_text(row[26])
        if (row[24] is None) != (start is None):  # a later attempt always starts where a captured one ended
            raise StoreUnavailable("Malformed previous attempt")
        admission = Admission(
            key,
            TaskReference(TaskScope(as_text(row[0])), as_text(row[1])),
            RepoId(as_text(row[2])),
            as_text(row[3]),
            as_text(row[25]),
            FileRef(as_text(row[4]), as_text(row[5])),
            as_text(row[6]),
            as_text(row[7]),
            as_text(row[8]),
            float(row[9]),
            (as_int(row[10]), as_text(row[11]), as_text(row[12])),
            as_int(row[23]),
        )
        pid, pgid, began, boot = row[15:19]
        worker = None if pid is None else Worker(pid=as_int(pid), pgid=as_int(pgid), start=as_text(began), boot=as_text(boot))
        session, conflict = as_nullable_text(row[19]), bool(as_int(row[20]))
        base, plan = as_nullable_text(row[21]), as_nullable_text(row[22])
        return AttemptRecord(admission, as_text(row[13]), as_int(row[14]), worker, session, conflict, base, plan, start)

    def load(self, key: AttemptKey) -> AttemptRecord | None:
        with self._connection() as con:
            return self._load(con, key)

    def _fence(self, con: sqlite3.Connection, admission: Admission) -> AttemptRecord:
        record = self._load(con, admission.key)
        if record is None or record.admission != admission:
            raise StoreRefused("changed_admission")
        return record

    def register_entry(
        self, key: AttemptKey, entry: tuple[int, str, str], now: float, replacing: Replaced | None = None,
        renewed: float | None = None,
    ) -> Literal["accepted", "conflict", "refused"]:
        """The only writer of entry_*: one winner while `admitted`; a replacement names the exact stored identity.

        Refused when the key, the held reservation or the deadline does not match. `_load` cannot serve this read: it
        refuses exactly the unregistered row. A replacement of a stored entry from another boot than the registering
        one also renews the deadline in the same write, past or not, to the later of the stored one and `renewed` (at
        most once per reboot: the new entry is this boot's); a renewed deadline that is not finite or not after `now`
        is refused and writes nothing. A same-boot replacement or a first registration never renews.
        """
        with self._connection(write=True) as con:
            row: tuple[object, ...] | None = con.execute(
                """SELECT p.phase,p.deadline,p.entry_pid,p.entry_start,p.entry_boot FROM plan_attempt p
                JOIN reservation r ON r.slot=p.slot AND r.repo_id=p.repo_id AND r.generation=p.generation AND r.attempt_id=p.attempt_id
                WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
                astuple(key),
            ).fetchone()
            if row is None or not isinstance(deadline := row[1], (int, float)):
                return "refused"
            stored = None if None in row[2:5] else (as_int(row[2]), as_text(row[3]), as_text(row[4]))
            if renewed is not None and stored is not None and stored[2] != entry[2]:  # the stored entry is another boot's
                deadline = max(deadline, renewed) if math.isfinite(renewed) else now
            if now >= deadline:
                return "refused"
            if row[0] != "admitted":
                return "conflict"
            if entry == stored or stored != (None if replacing is None else replacing.identity):
                return "conflict"  # replacing an identity with itself would only bump rev under a live dispatch read
            # the row was read in this same immediate transaction, so no revision predicate is needed
            con.execute(
                "UPDATE plan_attempt SET entry_pid=?,entry_start=?,entry_boot=?,deadline=?,rev=rev+1 WHERE attempt_id=?",
                (*entry, deadline, key.attempt_id),
            )
            return "accepted"

    def warm(self) -> None:
        """Open (and on first use check) this store's connection now; StoreUnavailable when it cannot."""
        with self._connection():
            pass

    def dispatch(self, expected: AttemptRecord, base: str) -> Literal["accepted", "conflict"]:
        """`base` is the slot HEAD read just before this write; it is recorded once, with the phase change."""
        with self._connection(write=True) as con:
            current = self._fence(con, expected.admission)
            if current.phase != "admitted" or current.revision != expected.revision:
                return "conflict"
            con.execute(
                "UPDATE plan_attempt SET phase='dispatching',base_commit=?,rev=rev+1 WHERE attempt_id=? AND rev=?",
                (base, expected.admission.key.attempt_id, expected.revision),
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
            paths = json.dumps(list(answer.paths)) if answer.kind == "valid" else None
            con.execute(
                "UPDATE plan_execution SET answer_kind=?,disposition=?,plan_path=?,commit_paths=?,commit_message=? WHERE attempt_id=?",
                (answer.kind, answer.disposition, answer.plan_path, paths, answer.message, admission.key.attempt_id),
            )
            return "accepted"

    def plan_commit(self, admission: Admission, commit: str) -> str:
        """Write once the commit the stage ends at: X != B for `planned`, B itself for `unchanged`, only for a captured,
        clean, completely published valid answer with no verdict stored yet (a `nothing_written` verdict has no commit and
        is never contradicted afterwards). Returns the value now stored: another one than `commit` is the caller's
        `inconsistent`; a refused gate is StoreRefused."""
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                """UPDATE plan_attempt SET plan_commit=?1,rev=rev+1 WHERE attempt_id=?2 AND plan_commit IS NULL AND phase='captured'
                AND EXISTS (SELECT 1 FROM plan_execution e WHERE e.attempt_id=?2 AND e.answer_kind='valid' AND e.rc=0
                AND e.timed_out=0 AND e.publication='complete' AND ((e.disposition='planned' AND ?1<>plan_attempt.base_commit)
                OR (e.disposition='unchanged' AND ?1=plan_attempt.base_commit)))
                AND NOT EXISTS (SELECT 1 FROM plan_verification v WHERE v.attempt_id=?2)""",
                (commit, admission.key.attempt_id),
            )
            row = con.execute("SELECT plan_commit FROM plan_attempt WHERE attempt_id=?", (admission.key.attempt_id,)).fetchone()
        stored = None if row is None else as_nullable_text(row[0])
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored

    def verdict(self, admission: Admission, base: str, commit: str | None, result: Verdict, now: float) -> Verdict:
        """Insert-only: written while the reservation is held, the run was clean, its session publication complete, the
        stored valid answer `planned` or `unchanged`, its base B and its stored `plan_commit` exactly the verified ones;
        `nothing_written` alone has no commit (a `planned` answer, `plan_commit` NULL) and `reused` needs `unchanged`. An
        existing row is kept, never rewritten. Returns the row now stored."""
        values = _verdict_values(result)
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                f"""INSERT INTO plan_verification (attempt_id,dispatch_token,generation,{VERDICT},observed_at)
                SELECT ?,?,?,?,?,?,?,? FROM plan_execution e JOIN plan_attempt p ON p.attempt_id=e.attempt_id
                WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=? AND e.answer_kind='valid'
                AND e.disposition IN ('planned','unchanged') AND e.rc=0 AND e.timed_out=0 AND e.publication='complete'
                AND p.base_commit=? AND CASE WHEN ?='nothing_written' THEN p.plan_commit IS NULL AND e.disposition='planned'
                ELSE p.plan_commit=? END AND (?=0 OR e.disposition='unchanged')
                ON CONFLICT DO NOTHING""",
                (*astuple(admission.key), *values, now, *astuple(admission.key), base, values[1], commit, values[3]),
            )
            row: tuple[object, ...] | None = con.execute(
                f"SELECT {VERDICT} FROM plan_verification WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(admission.key)
            ).fetchone()
        stored = None if row is None else _verdict(row)
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored

    def _execution(self, con: sqlite3.Connection, key: AttemptKey) -> StoredExecution | None:
        row: tuple[object, ...] | None = con.execute(
            f"""SELECT {prefixed("e", FACTS)},{prefixed("e", EVIDENCE)},{prefixed("e", ANSWER)},{prefixed("v", VERDICT)}
            FROM plan_execution e LEFT JOIN plan_verification v
            ON v.attempt_id=e.attempt_id AND v.dispatch_token=e.dispatch_token AND v.generation=e.generation
            WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=?""",
            astuple(key),
        ).fetchone()
        if row is None:
            return None
        tokens = tuple(as_nullable_int(v) for v in row[10:13]) if row[9] else None
        cumulative = tuple(as_nullable_int(v) for v in row[14:17]) if row[13] else None
        facts = ExecutionFacts(
            as_nullable_int(row[0]),
            bool(row[1]),
            as_nullable_text(row[2]),
            as_nullable_text(row[3]),
            bool(row[4]),
            bool(row[5]),
            None if row[6] is None else bool(row[6]),
            as_nullable_text(row[7]),
            as_nullable_int(row[8]),
            None if tokens is None else (tokens[0], tokens[1], tokens[2]),
            None if cumulative is None else (cumulative[0], cumulative[1], cumulative[2]),
            as_nullable_int(row[17]),
            as_nullable_text(row[18]),
        )
        evidence = Evidence(*(FileRef(as_text(row[i]), as_text(row[i + 1])) for i in (19, 21, 23, 25)))
        kind, publication = as_text(row[27]), as_text(row[32])
        if kind not in ("validation_pending", "valid", "missing", "json_invalid", "schema_invalid"):
            raise StoreUnavailable("Invalid answer phase")
        if publication not in ("complete", "pending", "conflict", "fault"):
            raise StoreUnavailable("Invalid publication phase")
        answer = AnswerState(kind, as_nullable_text(row[28]), as_nullable_text(row[29]), as_listed(row[30]), as_nullable_text(row[31]))
        return StoredExecution(key, facts, evidence, answer, publication, _verdict(row[33:37]))

    def collect(self, key: AttemptKey) -> StoredExecution | None:
        with self._connection() as con:
            return self._execution(con, key)
