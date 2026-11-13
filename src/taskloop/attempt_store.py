"""Conditional SQL owner for an admitted attempt's execution; no admission or release writer."""

import json
import math
import sqlite3
from dataclasses import astuple
from typing import Literal

from any_agent.procs import Worker

from taskloop.attempt_loads import AttemptLoads, verdict_of
from taskloop.attempt_reads import (
    StoreRefused,
    as_int,
    as_nullable_text,
    as_text,
)
from taskloop.attempt_types import (
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    EntryIdentity,
    Evidence,
    ExecutionFacts,
    Replaced,
    Verdict,
    Verified,
    entry_identity,
)
from taskloop.drain.models import ActionKind
from taskloop.drain.store import DrainStore, blocked
from taskloop.factory_schema import EVIDENCE, FACTS, VERDICT

# A registration write (the entry's or the harness's) waits at most this for the write lock, so it finishes well inside
# the registered start's fixed 5 s window; every other write keeps the library's 5 s.
REGISTRATION_BUSY_MS = 1500


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
        *(facts.tokens or (None, None, None)),  # unknown counts stay NULL, never 0
        *(facts.cumulative or (None, None, None)),
        facts.turns,
        facts.session,
    )


def _verdict_values(result: Verdict) -> tuple[str, str | None, str | None, int]:
    if isinstance(result, Verified):
        return "verified", None, result.blob, int(result.reused)
    return "rejected", result.reason, None, 0


class AttemptStore(AttemptLoads):
    """The fenced writes of an admitted attempt; the reads they need are `AttemptLoads`', the status reads `AttemptReads`'."""

    def _fence(self, con: sqlite3.Connection, admission: Admission) -> AttemptRecord:
        record = self._load(con, admission.key)
        if record is None or record.admission != admission:
            raise StoreRefused("changed_admission")
        return record

    def register_entry(
        self, key: AttemptKey, entry: EntryIdentity, now: float, replacing: Replaced | None = None,
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
            if blocked(con) and not any(action.kind is ActionKind.DISPATCH and action.subject == key.attempt_id
                                        for action in DrainStore(lambda: con, self.begin).pending()):
                return "refused"
            row: tuple[object, ...] | None = con.execute(
                """SELECT p.phase,p.deadline,p.entry_pid,p.entry_start,p.entry_boot FROM attempt p
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
                "UPDATE attempt SET entry_pid=?,entry_start=?,entry_boot=?,deadline=?,rev=rev+1 WHERE attempt_id=?",
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
                "UPDATE attempt SET phase='dispatching',base_commit=?,rev=rev+1 WHERE attempt_id=? AND rev=?",
                (base, expected.admission.key.attempt_id, expected.revision),
            )
            return "accepted"

    def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is not None:
                return "already_same" if entry_identity(current.worker) == entry_identity(worker) else "conflict"
            if current.phase != "dispatching":
                return "conflict"
            con.execute(
                """UPDATE attempt SET phase='registered',worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?,rev=rev+1
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
                con.execute("UPDATE attempt SET session_conflict=1,rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
                con.execute("UPDATE execution SET session_state='conflict' WHERE attempt_id=?", (admission.key.attempt_id,))
                return "conflict"
            con.execute("UPDATE attempt SET session_ref=?,rev=rev+1 WHERE attempt_id=?", (ref, admission.key.attempt_id))
            return "accepted"

    def capture(
        self,
        admission: Admission,
        worker: Worker | None,
        facts: ExecutionFacts,
        evidence: Evidence,
        session_state: Literal["complete", "pending", "conflict", "fault"],
    ) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._fence(con, admission)
            if current.worker is None or (worker is not None and entry_identity(current.worker) != entry_identity(worker)):
                raise StoreRefused("worker_mismatch")
            if current.session_conflict:
                session_state = "conflict"  # a recorded differing session is never stored as complete
            old = self._execution(con, admission.key)
            if old is not None:
                if old.facts != facts or old.evidence != evidence:
                    return "conflict"
                if old.session_state in ("pending", "fault") and session_state in ("complete", "conflict"):
                    con.execute(
                        "UPDATE execution SET session_state=? WHERE attempt_id=? AND session_state IN ('pending','fault')",
                        (session_state, admission.key.attempt_id),
                    )
                    return "accepted"
                return "already_same"
            if current.phase != "registered":
                return "conflict"
            refs = tuple(value for ref in astuple(evidence) for value in ref)
            values = (*astuple(admission.key), *_facts_values(facts), *refs, session_state)
            marks = ",".join("?" * len(values))
            con.execute(
                f"INSERT INTO execution (attempt_id,dispatch_token,generation,{FACTS},{EVIDENCE},session_state) VALUES ({marks})", values
            )
            con.execute("UPDATE attempt SET phase='captured',rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
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
                "UPDATE execution SET answer_kind=?,disposition=?,effect=?,commit_paths=?,commit_message=? WHERE attempt_id=?",
                (answer.kind, answer.disposition, answer.effect, paths, answer.message, admission.key.attempt_id),
            )
            return "accepted"

    def end_commit(self, admission: Admission, commit: str) -> str:
        """Write once the commit the step ends at: X != B for effect `commit`, B itself for `keep`, only for a captured,
        clean valid answer with its session complete, with no verdict stored yet (a `nothing_written` verdict has no commit and
        is never contradicted afterwards). Returns the value now stored: another one than `commit` is the caller's
        `inconsistent`; a refused registration write is StoreRefused."""
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                """UPDATE attempt SET end_commit=?1,rev=rev+1 WHERE attempt_id=?2 AND end_commit IS NULL AND phase='captured'
                AND EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=?2 AND e.answer_kind='valid' AND e.rc=0
                AND e.timed_out=0 AND e.session_state='complete' AND ((e.effect='commit' AND ?1<>attempt.base_commit)
                OR (e.effect='keep' AND ?1=attempt.base_commit)))
                AND NOT EXISTS (SELECT 1 FROM verification v WHERE v.attempt_id=?2)""",
                (commit, admission.key.attempt_id),
            )
            row = con.execute("SELECT end_commit FROM attempt WHERE attempt_id=?", (admission.key.attempt_id,)).fetchone()
        stored = None if row is None else as_nullable_text(row[0])
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored

    def verdict(self, admission: Admission, base: str, commit: str | None, result: Verdict, now: float) -> Verdict:
        """Insert-only: written while the reservation is held, the run was clean, its session state complete, the
        stored valid answer's effect `commit` or `keep`, its base B and its stored `end_commit` exactly the verified ones;
        `nothing_written` alone has no commit (effect `commit`, `end_commit` NULL) and `reused` needs `keep`. An
        existing row is kept, never rewritten. Returns the row now stored."""
        values = _verdict_values(result)
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                f"""INSERT INTO verification (attempt_id,dispatch_token,generation,{VERDICT},observed_at)
                SELECT ?,?,?,?,?,?,?,? FROM execution e JOIN attempt p ON p.attempt_id=e.attempt_id
                WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=? AND e.answer_kind='valid'
                AND e.effect IN ('commit','keep') AND e.rc=0 AND e.timed_out=0 AND e.session_state='complete'
                AND p.base_commit=? AND CASE WHEN ?='nothing_written' THEN p.end_commit IS NULL AND e.effect='commit'
                ELSE p.end_commit=? END AND (?=0 OR e.effect='keep')
                ON CONFLICT DO NOTHING""",
                (*astuple(admission.key), *values, now, *astuple(admission.key), base, values[1], commit, values[3]),
            )
            row: tuple[object, ...] | None = con.execute(
                f"SELECT {VERDICT} FROM verification WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(admission.key)
            ).fetchone()
        stored = None if row is None else verdict_of(row)
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored
