"""Fenced reads of an admitted attempt's record and stored execution; the writers inherit them, no write lives here."""

import sqlite3
from abc import ABC, abstractmethod

from any_agent.procs import Worker
from pydantic import BaseModel, ConfigDict

from taskloop import answer_failures
from taskloop.agents.settings import AgentSetting
from taskloop.answer_repair_models import RepairContext
from taskloop.attempt_reads import (
    StoreConnection,
    StoreRefused,
    StoreUnavailable,
    as_int,
    as_listed,
    as_nullable_int,
    as_nullable_text,
    as_text,
    stored_effect,
    stored_setting,
)
from taskloop.attempt_types import (
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    Committed,
    Evidence,
    ExecutionFacts,
    FileRef,
    Rejected,
    StoredExecution,
    Verdict,
)
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.state_store import fence
from taskloop.repo import RepoId
from taskloop.step import decode_step
from taskloop.steps import RULES
from taskloop.task import TaskReference, TaskScope


class RetainedInputs(BaseModel):
    """The implement attempt's original inputs, independent of its released slot."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: AttemptKey
    repo_id: str
    backlog: str
    task_id: str
    tracker_root: str
    checked: str
    input_ref: FileRef
    setting: AgentSetting


class PlanEvidence(BaseModel):
    """The latest plan's artifact accepted by factory commit, scoped to one repository and tracker task."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    key: AttemptKey
    revision: int
    end_commit: str
    blob: str


def _counts(row: tuple[object, ...]) -> tuple[int | None, int | None, int | None] | None:
    """Stored token counts (in, cached, out): known when any is stored, else None; an unknown count is NULL, never 0."""
    counts = (as_nullable_int(row[0]), as_nullable_int(row[1]), as_nullable_int(row[2]))
    return None if counts == (None, None, None) else counts


def verdict_of(row: tuple[object, ...]) -> Verdict | None:
    """The stored verdict of a factory_commit row; None for the all-NULL row of a LEFT JOIN without one."""
    kind, reason, blob, reused = row
    if kind is None:
        return None
    if kind == "committed":
        return Committed(as_nullable_text(blob), bool(as_int(reused)))  # a kind without an artifact stores no blob
    rule = next((rule for rule in RULES if rule == reason), None)
    if kind != "rejected" or rule is None:
        raise StoreUnavailable("Invalid stored verdict")
    return Rejected(rule)


class AttemptLoads(StoreConnection, ABC):
    """The fenced reads an attempt's writers need."""

    @abstractmethod
    def _retained(self, con: sqlite3.Connection, key: AttemptKey) -> RetainedInputs | None: ...

    @abstractmethod
    def _plan_row(self, con: sqlite3.Connection, repo_id: str, backlog: str, task_id: str,
                  tracker_root: str) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _earlier_row(self, con: sqlite3.Connection, repo_id: str, backlog: str, task_id: str,
                     tracker_root: str) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _scope_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _attempt_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _reservation_row(self, con: sqlite3.Connection, slot: object, repo_id: object) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _repair_row(self, con: sqlite3.Connection, previous: str) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _slot_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _execution_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[object, ...] | None: ...

    @abstractmethod
    def _callback_row(self, con: sqlite3.Connection, key: AttemptKey) -> tuple[str | bytes | None] | None: ...

    def retained(self, key: AttemptKey) -> RetainedInputs | None:
        with self._connection() as con:
            return self._retained(con, key)

    def latest_plan(self, repo_id: str, backlog: str, task_id: str, tracker_root: str) -> PlanEvidence | None:
        """Never fall back past a newer unsuccessful plan; later implementation attempts do not hide this plan."""
        with self._connection() as con:
            row = self._plan_row(con, repo_id, backlog, task_id, tracker_root)
        if row is None or row[6] != "committed" or row[4] is None or row[5] is None:
            return None
        return PlanEvidence(key=AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), revision=as_int(row[3]),
                            end_commit=as_text(row[4]), blob=as_text(row[5]))

    def earlier(self, repo_id: str, backlog: str, task_id: str, tracker_root: str) -> EarlierAttempt | None:
        """Latest agent attempt for exactly this registered repo and tracker task; checks have their own table."""
        with self._connection() as con:
            row = self._earlier_row(con, repo_id, backlog, task_id, tracker_root)
        if row is None:
            return None
        return EarlierAttempt.model_validate({
            "key": AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), "revision": as_int(row[3]),
            "repo_id": repo_id, "backlog": backlog, "task_id": task_id, "tracker_root": tracker_root,
            "slot": as_text(row[4]), "step": decode_step(as_text(row[5])), "end_commit": as_nullable_text(row[6]),
        })

    def earlier_for(self, key: AttemptKey) -> EarlierAttempt | None:
        """Look up the predecessor's fenced identity, independently of its released reservation."""
        with self._connection() as con:
            row = self._scope_row(con, key)
        return None if row is None else self.earlier(*(as_text(value) for value in row))

    def _load(self, con: sqlite3.Connection, key: AttemptKey) -> AttemptRecord | None:
        """The fenced read; `start` (E) is the previous attempt's X, else its B, frozen since this attempt took over."""
        row = self._attempt_row(con, key)
        if row is None:
            return None
        if any(value is None for value in row[10:13]):
            raise StoreRefused("unregistered_entry")
        held = self._reservation_row(con, row[3], row[2])
        if held != (row[2], key.reservation_generation, key.attempt_id) or row[31] is None:
            raise StoreRefused("stale_reservation")
        if not isinstance(row[9], (int, float)):
            raise StoreUnavailable("Malformed deadline")
        start = as_nullable_text(row[32])
        if (row[24] is None) != (start is None):  # a later attempt always starts where a captured one ended
            raise StoreUnavailable("Malformed previous attempt")
        admission = Admission(
            key,
            TaskReference(TaskScope(as_text(row[0])), as_text(row[1])),
            RepoId(as_text(row[2])),
            as_text(row[3]),
            as_text(row[31]),
            FileRef(as_text(row[4]), as_text(row[5])),
            stored_setting(row[27], row[29], row[6], row[7], row[8], row[30]),
            float(row[9]),
            (as_int(row[10]), as_text(row[11]), as_text(row[12])),
            as_int(row[23]),
            decode_step(as_text(row[25])),
            as_nullable_text(row[26]),
            as_nullable_text(row[28]),
            None if row[33] is None else RepairContext.model_validate_json(as_text(row[33])),
            bool(as_int(row[34])),
        )
        pid, pgid, began, boot = row[15:19]
        worker = None if pid is None else Worker(pid=as_int(pid), pgid=as_int(pgid), start=as_text(began), boot=as_text(boot))
        session, conflict = as_nullable_text(row[19]), bool(as_int(row[20]))
        if admission.repair is not None and (session != admission.repair.session or
                                             (row[21] is not None and row[21] != admission.repair.base_commit)):
            raise StoreUnavailable("Malformed repair context")
        if admission.repair is not None:
            self._repair_source(con, as_text(row[24]), admission)
        base, end = as_nullable_text(row[21]), as_nullable_text(row[22])
        return AttemptRecord(admission, as_text(row[13]), as_int(row[14]), worker, session, conflict, base, end, start)

    def _repair_source(self, con: sqlite3.Connection, previous: str, admission: Admission) -> None:
        row = self._repair_row(con, previous)
        context = admission.repair
        if (row is None or context is None or row[10] is not None or row[:4] !=
                (context.session, context.base_commit, admission.number, admission.deadline)
                or stored_setting(*row[4:10]) != admission.setting
                or row[11] is None or answer_failures.AnswerFailureData.model_validate_json(as_text(row[11])) != context.failure):
            raise StoreUnavailable("Repair context disagrees with its failed attempt")

    def load(self, key: AttemptKey) -> AttemptRecord | None:
        with self._connection() as con:
            return self._load(con, key)

    def _fence(self, con: sqlite3.Connection, admission: Admission) -> AttemptRecord:
        record = self._load(con, admission.key)
        if record is None or record.admission != admission:
            raise StoreRefused("changed_admission")
        return record

    def _owned(self, con: sqlite3.Connection, admission: Admission, callback: Callback | None) -> AttemptRecord:
        fence(con, admission.key, callback)
        current = self._fence(con, admission)
        worker = current.worker
        if callback is not None and (worker is None or
                (worker.pid, worker.pgid, worker.start, worker.boot) !=
                (callback.worker.pid, callback.worker.pgid, callback.worker.start, callback.worker.boot)):
            raise StoreRefused("worker_mismatch")
        return current

    def slot_base(self, key: AttemptKey) -> str:
        """The reservation's original park point D, independent of the branch source and prepared B."""
        with self._connection() as con:
            row = self._slot_row(con, key)
        if row is None:
            raise StoreRefused("absent")
        return as_text(row[0])

    def _execution(self, con: sqlite3.Connection, key: AttemptKey) -> StoredExecution | None:
        row = self._execution_row(con, key)
        if row is None:
            return None
        tokens, cumulative = _counts(row[9:12]), _counts(row[12:15])
        self._callback(con, key)
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
            tokens,
            cumulative,
            as_nullable_int(row[15]),
            as_nullable_text(row[16]),
            None if row[17] is None else bool(row[17]),
        )
        evidence = Evidence(*(FileRef(as_text(row[i]), as_text(row[i + 1])) for i in (18, 20, 22, 24)))
        kind, session_state = as_text(row[26]), as_text(row[32])
        if kind not in ("validation_pending", "valid", "missing", "json_invalid", "schema_invalid"):
            raise StoreUnavailable("Invalid answer phase")
        if session_state not in ("complete", "pending", "conflict", "fault"):
            raise StoreUnavailable("Invalid session state")
        answer = AnswerState(
            kind, as_nullable_text(row[27]), stored_effect(row[28]), as_listed(row[29]), as_nullable_text(row[30]),
            answer_failures.decode(row[31], kind),
        )
        return StoredExecution(key, facts, evidence, answer, session_state, verdict_of(row[33:37]))

    def collect(self, key: AttemptKey) -> StoredExecution | None:
        with self._connection() as con:
            return self._execution(con, key)

    def _callback(self, con: sqlite3.Connection, key: AttemptKey) -> Callback | None:
        row = self._callback_row(con, key)
        identity = None if row is None or row[0] is None else Callback.model_validate_json(row[0])
        if identity is not None and identity.key != key:
            raise StoreUnavailable("Captured recovery identity does not match the execution")
        if row is not None:
            try:
                fence(con, key, identity)
            except StoreRefused as error:
                raise StoreUnavailable("Captured recovery association does not match its authorization") from error
        return identity

    def callback(self, key: AttemptKey) -> Callback | None:
        """Trusted completion reads the identity from captured execution, never the latest recovery owner."""
        with self._connection() as con:
            return self._callback(con, key)
