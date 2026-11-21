"""The A/A and A/B comparison read: one row per agent attempt with its identity, setup, usage and latest checks conclusion.

Read-only. NULL means unknown, never zero: an attempt that did not end captured has no `ended_at` and no wall time, and
`usage_incomplete` 1 marks token counts that are a lower bound. `harness`, `model` and `effort` are what the attempt
asked for; `ran_model`, `ran_effort` and `harness_version` what the harness reported (NULL: it could not tell);
`ran_model_differs` is 1 where the reported model is not the one asked for, 0 where it is, NULL where either is unknown;
`max_attempts` is the attempt's pinned workflow's cap of its step (NULL: the stored workflow cannot be read).
Pool only rows with the same engine and workflow digests."""

from dataclasses import dataclass, replace

from taskloop.attempt_reads import StoreConnection, StoreUnavailable, as_int, as_nullable_int, as_nullable_text, as_text
from taskloop.attempt_result import report
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import CheckStore
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.hold_store import HoldStore
from taskloop.step import decode_step
from taskloop.workflow_read import WorkflowRefusal, pinned

QUERY = f"""WITH RECURSIVE chain(attempt_id,ancestor_id) AS (
 SELECT attempt_id,attempt_id FROM attempt
 UNION ALL SELECT chain.attempt_id,p.previous_attempt_id FROM chain
 JOIN attempt p ON p.attempt_id=chain.ancestor_id WHERE p.previous_attempt_id IS NOT NULL
)
SELECT
  a.task_id, a.step, a.number, a.repeat_reason,
  a.engine_digest, a.workflow_digest, a.workflow_sha,
  a.harness, a.model, a.effort, a.compaction_token_limit, a.input_digest,
  a.admitted_at, a.ended_at, a.ended_at - a.admitted_at AS wall_seconds,
  e.disposition, e.effect, e.answer_kind, e.rc, e.timed_out, e.turns,
  e.t_in, e.t_cached, e.t_out, e.c_in, e.c_cached, e.c_out, e.usage_incomplete,
  (SELECT c.conclusion FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id ORDER BY c.number DESC LIMIT 1),
  (SELECT c.reason FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id ORDER BY c.number DESC LIMIT 1),
  e.model, e.effort, e.harness_version,
  (SELECT w.content FROM workflow_file w WHERE w.digest = a.workflow_digest),
  a.attempt_id,a.backlog,a.previous_attempt_id,a.seq,a.base_commit,f.verdict,
  (SELECT p.attempt_id FROM chain k JOIN attempt p ON p.attempt_id=k.ancestor_id
   WHERE k.attempt_id=a.attempt_id AND p.previous_attempt_id IS NULL),
  (SELECT s.ended_at-s.started_at FROM setup_run s WHERE s.attempt_id=a.attempt_id ORDER BY s.run DESC LIMIT 1),
  c.attempt_id,
  (SELECT count(*) FROM chain k JOIN attempt p ON p.attempt_id=k.ancestor_id
   WHERE k.attempt_id=a.attempt_id AND p.repeat_reason IS NOT NULL AND p.repair_context IS NULL),
  CASE WHEN c.conclusion='{encode(CommandConclusion.PASSED)}' THEN c.concluded_at-
   (SELECT p.admitted_at FROM chain k JOIN attempt p ON p.attempt_id=k.ancestor_id
    WHERE k.attempt_id=a.attempt_id AND p.previous_attempt_id IS NULL) END,
  a.dispatch_token,a.generation,c.dispatch_token,c.generation
FROM attempt a LEFT JOIN execution e ON e.attempt_id = a.attempt_id
LEFT JOIN factory_commit f ON f.attempt_id=a.attempt_id
LEFT JOIN checks_attempt c ON c.attempt_id=(SELECT latest.attempt_id FROM checks_attempt latest
 WHERE latest.after_attempt_id=a.attempt_id ORDER BY latest.number DESC LIMIT 1)
WHERE (? IS NULL OR a.backlog = ?)
ORDER BY a.backlog, a.task_id, a.seq"""


@dataclass(frozen=True)
class ExportRow:
    """One agent attempt; the field order is the CSV column order."""

    task_id: str
    step: str
    number: int
    repeat_reason: str | None
    engine_digest: str | None
    workflow_digest: str | None
    workflow_sha: str | None
    harness: str | None
    model: str | None
    effort: str | None
    compaction_token_limit: int | None
    input_digest: str | None
    admitted_at: float
    ended_at: float | None
    wall_seconds: float | None
    disposition: str | None
    effect: str | None
    answer_kind: str | None
    rc: int | None
    timed_out: int | None
    turns: int | None
    t_in: int | None
    t_cached: int | None
    t_out: int | None
    c_in: int | None
    c_cached: int | None
    c_out: int | None
    usage_incomplete: int | None
    latest_checks_conclusion: str | None
    latest_checks_reason: str | None
    ran_model: str | None  # the model the agent harness reported answering (the resolved id), against `model`, the one asked for
    ran_effort: str | None
    harness_version: str | None
    ran_model_differs: int | None
    max_attempts: int | None
    attempt_id: str
    backlog: str
    previous_attempt_id: str | None
    seq: int
    base_commit: str | None
    factory_commit_verdict: str | None
    chain_id: str
    setup_seconds: float | None
    check_seconds: dict[str, float | None]
    rework_count: int
    time_to_green_seconds: float | None
    hold_cause: str | None
    terminal_result: str | None


def _real(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise StoreUnavailable("Malformed attempt time")


def _cap(step: str, content: object, sha: object) -> int | None:
    """The step's cap in the attempt's stored workflow; None when the file is absent or no longer loads."""
    if not isinstance(content, bytes) or not isinstance(sha, str):
        return None
    try:
        return pinned(content, sha).workflow.cap(decode_step(step))
    except WorkflowRefusal:
        return None


def _row(r: tuple[object, ...]) -> ExportRow:
    text, whole, admitted = as_nullable_text, as_nullable_int, _real(r[12])
    if admitted is None:
        raise StoreUnavailable("Malformed attempt time")
    return ExportRow(
        as_text(r[0]),
        as_text(r[1]),
        as_int(r[2]),
        text(r[3]),
        text(r[4]),
        text(r[5]),
        text(r[6]),
        text(r[7]),
        text(r[8]),
        text(r[9]),
        whole(r[10]),
        text(r[11]),
        admitted,
        _real(r[13]),
        _real(r[14]),
        text(r[15]),
        text(r[16]),
        text(r[17]),
        whole(r[18]),
        whole(r[19]),
        whole(r[20]),
        whole(r[21]),
        whole(r[22]),
        whole(r[23]),
        whole(r[24]),
        whole(r[25]),
        whole(r[26]),
        whole(r[27]),
        text(r[28]),
        text(r[29]),
        text(r[30]),
        text(r[31]),
        text(r[32]),
        None if r[30] is None or r[8] is None else int(r[30] != r[8]),
        _cap(as_text(r[1]), r[33], r[6]),
        as_text(r[34]),
        as_text(r[35]),
        text(r[36]),
        as_int(r[37]),
        text(r[38]),
        text(r[39]),
        as_text(r[40]),
        _real(r[41]),
        {},
        as_int(r[43]),
        _real(r[44]),
        None,
        None,
    )


class ExportStore(StoreConnection):
    def check_seconds(self, raw: tuple[object, ...]) -> dict[str, float | None]:
        """Durations of the latest block, through the owning check-result reader and codec."""
        if raw[42] is None:
            return {}
        results = CheckStore(self.connect, self.begin).results(AttemptKey(as_text(raw[42]), as_text(raw[47]), as_int(raw[48])))
        latest = max((each.block for each in results), default=0)
        return {
            each.name: None if each.ended_at is None or each.conclusion is CommandConclusion.UNDEFINED else each.ended_at - each.started_at
            for each in results
            if each.block == latest
        }

    def attempts(self, backlog: str | None) -> tuple[ExportRow, ...]:
        """Every agent attempt (of one backlog, or of all) in task and attempt order."""
        with self._connection() as con:
            found = con.execute(QUERY, (backlog, backlog)).fetchall()
            holds = HoldStore(self.connect, self.begin).of_attempts(tuple(as_text(row[34]) for row in found))
            reader = AttemptStore(self.connect, self.begin)
            rows = []
            for raw in found:
                row = _row(raw)
                stored = reader.collect(AttemptKey(row.attempt_id, as_text(raw[45]), as_int(raw[46])))
                result = None if stored is None else report(stored)
                hold = holds.get(row.attempt_id)
                rows.append(
                    replace(
                        row,
                        check_seconds=self.check_seconds(raw),
                        hold_cause=None if hold is None else hold.reason,
                        terminal_result=result.reason if result is not None and result.status == "collected" else None,
                    )
                )
            return tuple(rows)
