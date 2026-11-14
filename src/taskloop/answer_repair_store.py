"""Atomic answer-repair admission on the attempt store's reservation fences."""

import math
import sqlite3
from dataclasses import astuple

from pydantic import BaseModel, ConfigDict, Field

from taskloop.admit_chain import transfer
from taskloop.admit_rows import insert_attempt
from taskloop.answer_repair_models import RepairContext, RepairOutcome
from taskloop.attempt_reads import StoreRefused, as_int, as_text
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptRecord, FileRef, StoredExecution
from taskloop.drain.store import blocked
from taskloop.factory_schema import ATTEMPT_ADMITTED, SUCCESSOR
from taskloop.task_content_store import TaskContentStore


class RepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: RepairOutcome
    explanation: str = Field(min_length=1)
    key: AttemptKey | None = None


class AnswerRepairStore(AttemptStore):
    def existing(self, previous: AttemptKey) -> RepairResult | None:
        with self._connection() as con:
            return self._existing(con, previous)

    def _existing(self, con: sqlite3.Connection, previous: AttemptKey) -> RepairResult | None:
        row = con.execute(
            "SELECT s.attempt_id,s.dispatch_token,s.generation,s.repair_context FROM attempt p JOIN attempt s "
            "ON s.previous_attempt_id=p.attempt_id WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?",
            astuple(previous),
        ).fetchone()
        if row is None:
            return None
        if row[3] is None:
            return RepairResult(outcome=RepairOutcome.REFUSED, explanation="The attempt already has a successor.")
        RepairContext.model_validate_json(as_text(row[3]))
        return RepairResult(outcome=RepairOutcome.EXISTING, explanation="The saved answer repair already owns admission.",
                            key=AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])))

    def admit(
        self, expected: AttemptRecord, execution: StoredExecution, context: RepairContext,
        key: AttemptKey, ref: FileRef, now: float,
    ) -> RepairResult:
        with self._connection(write=True) as con:
            existing = self._existing(con, expected.admission.key)
            if existing is not None:
                return existing
            current = self._fence(con, expected.admission)
            if current != expected or self._execution(con, expected.admission.key) != execution:
                return RepairResult(outcome=RepairOutcome.REFUSED, explanation="The failed attempt changed during repair admission.")
            problem = self._problem(con, current, execution, now)
            if problem is not None:
                return RepairResult(outcome=RepairOutcome.REFUSED, explanation=problem)
            if (context.session != current.session_ref or context.base_commit != current.base_commit
                    or context.failure != execution.answer.failure
                    or key.reservation_generation != current.admission.key.reservation_generation + 1):
                return RepairResult(outcome=RepairOutcome.REFUSED, explanation="The repair context does not match the failed attempt.")
            return self._insert(con, current, context, key, ref)

    def _problem(self, con: sqlite3.Connection, record: AttemptRecord, execution: StoredExecution, now: float) -> str | None:
        admission, facts = record.admission, execution.facts
        if blocked(con):
            return "Answer repair admission is closed while the factory drains."
        if not math.isfinite(now) or not math.isfinite(admission.deadline) or now >= admission.deadline:
            return "The failed attempt's original deadline has expired."
        if admission.repair is not None:
            return "An answer repair cannot itself be repaired."
        if (record.phase != "captured" or execution.answer.failure is None or facts.rc != 0 or facts.timed_out
                or facts.stop is not None or execution.verification is not None):
            return "A completed execution with a rejected answer and no verdict is required."
        if (not record.session_ref or record.session_conflict or execution.session_state != "complete"
                or (facts.session is not None and facts.session != record.session_ref) or record.base_commit is None):
            return "The failed attempt needs a complete, consistent saved session and base."
        row = con.execute(
            f"SELECT {SUCCESSOR},EXISTS(SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id),"
            "EXISTS(SELECT 1 FROM task_hold h WHERE h.attempt_id=p.attempt_id),"
            f"EXISTS(SELECT 1 FROM attempt p2 WHERE p2.session_ref=p.session_ref AND p2.harness=p.harness "
            "AND p2.attempt_id<>p.attempt_id AND NOT EXISTS(SELECT 1 FROM slot_release r WHERE r.attempt_id=p2.attempt_id) "
            "AND NOT EXISTS(SELECT 1 FROM attempt later WHERE later.adapter=p2.adapter AND later.backlog=p2.backlog "
            "AND later.task_id=p2.task_id AND later.seq>p2.seq)) "
            "FROM attempt p WHERE p.attempt_id=?", (admission.key.attempt_id,),
        ).fetchone()
        return "The attempt is superseded, released, held or its session has another owner." if row is None or any(row) else None

    def _insert(
        self, con: sqlite3.Connection, record: AttemptRecord, context: RepairContext, key: AttemptKey, ref: FileRef,
    ) -> RepairResult:
        previous = record.admission.key
        row: tuple[object, ...] | None = con.execute(
            f"SELECT {ATTEMPT_ADMITTED} FROM attempt WHERE attempt_id=?", (previous.attempt_id,),
        ).fetchone()
        if row is None:
            raise StoreRefused("absent")
        values: dict[str, object] = dict(zip(ATTEMPT_ADMITTED.split(","), row, strict=True))
        values.update(attempt_id=key.attempt_id, dispatch_token=key.dispatch_token, generation=key.reservation_generation,
                      previous_attempt_id=previous.attempt_id, seq=as_int(values["seq"]) + 1,
                      input_path=ref.path, input_digest=ref.digest, repair_context=context.model_dump_json())
        insert_attempt(con, values, TaskContentStore(lambda: con).read(previous.attempt_id))
        self.repair_session(con, key, context.session)
        if not transfer(con, previous, key, record.admission.repo_id, record.admission.slot):
            raise StoreRefused("stale_reservation")
        return RepairResult(outcome=RepairOutcome.ADMITTED,
                            explanation="One answer repair retains the saved session and allowance.", key=key)
