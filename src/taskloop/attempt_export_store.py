"""The A/A and A/B comparison read: one row per agent attempt with its identity, setup, usage and latest checks conclusion.

Read-only. NULL means unknown, never zero: an attempt that did not end captured has no `ended_at` and no wall time, and
`usage_incomplete` 1 marks token counts that are a lower bound. Pool only rows with the same engine and workflow digests."""

from dataclasses import dataclass

from taskloop.attempt_reads import StoreConnection, StoreUnavailable, as_int, as_nullable_int, as_nullable_text, as_text

QUERY = """SELECT
  a.task_id, a.step, a.number, a.repeat_reason,
  a.engine_digest, a.workflow_digest, a.workflow_sha,
  a.harness, a.model, a.effort, a.compaction_token_limit, a.input_digest,
  a.admitted_at, a.ended_at, a.ended_at - a.admitted_at AS wall_seconds,
  e.disposition, e.effect, e.answer_kind, e.rc, e.timed_out, e.turns,
  e.t_in, e.t_cached, e.t_out, e.c_in, e.c_cached, e.c_out, e.usage_incomplete,
  (SELECT c.conclusion FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id ORDER BY c.number DESC LIMIT 1),
  (SELECT c.reason FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id ORDER BY c.number DESC LIMIT 1)
FROM attempt a LEFT JOIN execution e ON e.attempt_id = a.attempt_id
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


def _real(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise StoreUnavailable("Malformed attempt time")


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
    )


class ExportStore(StoreConnection):
    def attempts(self, backlog: str | None) -> tuple[ExportRow, ...]:
        """Every agent attempt (of one backlog, or of all) in task and attempt order."""
        with self._connection() as con:
            return tuple(_row(row) for row in con.execute(QUERY, (backlog, backlog)).fetchall())
