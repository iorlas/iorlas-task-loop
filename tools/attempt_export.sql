-- One row per agent attempt, for A/A and A/B comparison. Read-only; run against a copy or with -readonly:
--   sqlite3 -readonly -header -csv <factory.db> < tools/attempt_export.sql
-- Pool only rows with the same engine_digest and workflow_digest. NULL means unknown, never zero: an attempt that did not
-- end captured has no ended_at and no wall time; usage_incomplete = 1 marks token counts that are a lower bound.
SELECT
  a.task_id, a.step, a.number, a.repeat_reason,
  a.engine_digest, a.workflow_digest, a.workflow_sha,
  a.harness, a.model, a.effort, a.compaction_token_limit, a.input_digest,
  a.admitted_at, a.ended_at, a.ended_at - a.admitted_at AS wall_seconds,
  e.disposition, e.effect, e.answer_kind, e.rc, e.timed_out, e.turns,
  e.t_in, e.t_cached, e.t_out, e.c_in, e.c_cached, e.c_out, e.usage_incomplete,
  (SELECT c.conclusion FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id
     ORDER BY c.number DESC LIMIT 1) AS latest_checks_conclusion,
  (SELECT c.reason FROM checks_attempt c WHERE c.after_attempt_id = a.attempt_id
     ORDER BY c.number DESC LIMIT 1) AS latest_checks_reason
FROM attempt a
LEFT JOIN execution e ON e.attempt_id = a.attempt_id
ORDER BY a.backlog, a.task_id, a.seq;
