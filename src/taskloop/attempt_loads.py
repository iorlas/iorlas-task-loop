"""Fenced reads of an admitted attempt's record and stored execution; the writers inherit them, no write lives here."""

import sqlite3
from dataclasses import astuple

from any_agent.procs import Worker
from pydantic import BaseModel, ConfigDict

from taskloop import answer_failures
from taskloop.agents.settings import AgentSetting
from taskloop.attempt_reads import (
    AttemptReads,
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
    Evidence,
    ExecutionFacts,
    FileRef,
    Rejected,
    StoredExecution,
    Verdict,
    Verified,
)
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.factory_schema import ANSWER, ATTEMPT_LOADED, EVIDENCE, FACTS, VERDICT, prefixed
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.state_store import fence
from taskloop.repo import RepoId
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


def retained_on(con: sqlite3.Connection, key: AttemptKey) -> RetainedInputs | None:
    row = con.execute(
        "SELECT repo_id,backlog,task_id,tracker_root,end_commit,input_path,input_digest,harness,provider,model,effort,access_policy,"
        "compaction_token_limit "
        "FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=? AND step='implement'",
        astuple(key),
    ).fetchone()
    if row is None:
        return None
    return RetainedInputs(key=key, repo_id=as_text(row[0]), backlog=as_text(row[1]), task_id=as_text(row[2]),
                          tracker_root=as_text(row[3]), checked=as_text(row[4]),
                          input_ref=FileRef(as_text(row[5]), as_text(row[6])),
                          setting=stored_setting(*row[7:13]))


def _counts(row: tuple[object, ...]) -> tuple[int | None, int | None, int | None] | None:
    """Stored token counts (in, cached, out): known when any is stored, else None; an unknown count is NULL, never 0."""
    counts = (as_nullable_int(row[0]), as_nullable_int(row[1]), as_nullable_int(row[2]))
    return None if counts == (None, None, None) else counts


def verdict_of(row: tuple[object, ...]) -> Verdict | None:
    """The stored verdict of a verification row; None for the all-NULL row of a LEFT JOIN without one."""
    kind, reason, blob, reused = row
    if kind is None:
        return None
    if kind == "verified":
        return Verified(as_nullable_text(blob), bool(as_int(reused)))  # a kind without an artifact stores no blob
    rule = next((rule for rule in RULES if rule == reason), None)
    if kind != "rejected" or rule is None:
        raise StoreUnavailable("Invalid stored verdict")
    return Rejected(rule)


class AttemptLoads(AttemptReads):
    """The fenced reads an attempt's writers need; the status reads are `AttemptReads`'."""

    def retained(self, key: AttemptKey) -> RetainedInputs | None:
        with self._connection() as con:
            return retained_on(con, key)

    def earlier(self, repo_id: str, backlog: str, task_id: str, tracker_root: str) -> EarlierAttempt | None:
        """Latest agent attempt for exactly this registered repo and tracker task; checks have their own table."""
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                """SELECT attempt_id,dispatch_token,generation,rev,slot,step,end_commit FROM attempt
                WHERE repo_id=? AND adapter='beads' AND backlog=? AND task_id=? AND tracker_root=?
                ORDER BY seq DESC LIMIT 1""", (repo_id, backlog, task_id, tracker_root),
            ).fetchone()
        if row is None:
            return None
        return EarlierAttempt.model_validate({
            "key": AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), "revision": as_int(row[3]),
            "repo_id": repo_id, "backlog": backlog, "task_id": task_id, "tracker_root": tracker_root,
            "slot": as_text(row[4]), "step": as_text(row[5]), "end_commit": as_nullable_text(row[6]),
        })

    def earlier_for(self, key: AttemptKey) -> EarlierAttempt | None:
        """Select by the predecessor's fenced identity, independently of its released reservation."""
        with self._connection() as con:
            row = con.execute(
                "SELECT repo_id,backlog,task_id,tracker_root FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                astuple(key),
            ).fetchone()
        return None if row is None else self.earlier(*(as_text(value) for value in row))

    def _load(self, con: sqlite3.Connection, key: AttemptKey) -> AttemptRecord | None:
        """The fenced read; `start` (E) is the previous attempt's X, else its B, frozen since this attempt took over."""
        row: tuple[object, ...] | None = con.execute(
            f"""SELECT {prefixed("p", ATTEMPT_LOADED)},
            (SELECT path FROM slot WHERE name=p.slot AND repo_id=p.repo_id),
            (SELECT coalesce(q.end_commit, q.base_commit) FROM attempt q WHERE q.attempt_id=p.previous_attempt_id)
            FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
            astuple(key),
        ).fetchone()
        if row is None:
            return None
        if any(value is None for value in row[10:13]):
            raise StoreRefused("unregistered_entry")
        held = con.execute(
            "SELECT repo_id,generation,attempt_id FROM reservation WHERE slot=? AND repo_id=?", (row[3], row[2])
        ).fetchone()
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
            as_text(row[25]),
            as_nullable_text(row[26]),
            as_nullable_text(row[28]),
        )
        pid, pgid, began, boot = row[15:19]
        worker = None if pid is None else Worker(pid=as_int(pid), pgid=as_int(pgid), start=as_text(began), boot=as_text(boot))
        session, conflict = as_nullable_text(row[19]), bool(as_int(row[20]))
        base, end = as_nullable_text(row[21]), as_nullable_text(row[22])
        return AttemptRecord(admission, as_text(row[13]), as_int(row[14]), worker, session, conflict, base, end, start)

    def load(self, key: AttemptKey) -> AttemptRecord | None:
        with self._connection() as con:
            return self._load(con, key)

    def slot_base(self, key: AttemptKey) -> str:
        """The reservation's original park point D, independent of the branch source and prepared B."""
        with self._connection() as con:
            row = con.execute("SELECT slot_head FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                              astuple(key)).fetchone()
        if row is None:
            raise StoreRefused("absent")
        return as_text(row[0])

    def _execution(self, con: sqlite3.Connection, key: AttemptKey) -> StoredExecution | None:
        row: tuple[object, ...] | None = con.execute(
            f"""SELECT {prefixed("e", FACTS)},{prefixed("e", EVIDENCE)},{prefixed("e", ANSWER)},{prefixed("v", VERDICT)}
            FROM execution e LEFT JOIN verification v
            ON v.attempt_id=e.attempt_id AND v.dispatch_token=e.dispatch_token AND v.generation=e.generation
            WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=?""",
            astuple(key),
        ).fetchone()
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
        )
        evidence = Evidence(*(FileRef(as_text(row[i]), as_text(row[i + 1])) for i in (17, 19, 21, 23)))
        kind, session_state = as_text(row[25]), as_text(row[31])
        if kind not in ("validation_pending", "valid", "missing", "json_invalid", "schema_invalid"):
            raise StoreUnavailable("Invalid answer phase")
        if session_state not in ("complete", "pending", "conflict", "fault"):
            raise StoreUnavailable("Invalid session state")
        answer = AnswerState(
            kind, as_nullable_text(row[26]), stored_effect(row[27]), as_listed(row[28]), as_nullable_text(row[29]),
            answer_failures.decode(row[30], kind),
        )
        return StoredExecution(key, facts, evidence, answer, session_state, verdict_of(row[32:36]))

    def collect(self, key: AttemptKey) -> StoredExecution | None:
        with self._connection() as con:
            return self._execution(con, key)

    def _callback(self, con: sqlite3.Connection, key: AttemptKey) -> Callback | None:
        row = con.execute("SELECT recovery_callback FROM execution WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                          astuple(key)).fetchone()
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
