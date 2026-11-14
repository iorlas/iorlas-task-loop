# Header
Task: tl-8bh9.14.188; base: 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: medium; retain usage and explain coverage.
Owner decisions: settled; unlanded dependencies: none.
Evidence budget: 12 model calls.
Size: 11 changed files; 2 behaviours (A1, A2); 65 implement model calls.

## Outcome and non-goals
Expose interrupted usage and its coverage. Projection already extracts counts regardless of return code, and capture precedes answer validation. Add the missing completeness flag and explanation. No backfill, transcript reader, stream parser, shelf change or scheduling change.

## Settled decisions
- `RunOutcome.summary.res` supplies interrupted-run counts and `usage_incomplete`; true means the in-flight request is missing.
- Preserve unknown counts and reported zeroes regardless of outcome or answer validity.
- Store `usage_incomplete` as a nullable boolean: absent or invalid flag remains unknown; false and true remain distinct.
- Dashboard totals retain known counts from incomplete attempts, with incomplete coverage.
- The new execution column requires schema 29, draining active attempts before upgrade and discarding the old database through the owning operation.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_types.py` — add validated `usage_incomplete` to `ExecutionFacts` and `execution_facts`.
- `src/taskloop/factory_schema.py` — extend execution DDL and `FACTS`, increment `SCHEMA.version` to 29 and constrain the nullable boolean.
- `src/taskloop/attempt_store.py` — extend `_facts_values`; `AttemptStore.capture` stores the flag in its existing idempotent result transaction.
- `src/taskloop/attempt_loads.py` — extend `AttemptLoads._execution`; adjust evidence, answer and verdict offsets.
- `src/taskloop/attempt_result.py` — add `usage_explanation` and compose it in `report` without losing outcome or answer-failure explanations; `collect` consumes the same report.
- `src/taskloop/show_render.py` — `_agent_lines` displays the shared usage explanation from stored facts, including successful answer-stopped attempts.
- `src/taskloop/dash_usage.py` — `project` excludes incomplete reports from complete coverage; retain `total` semantics.
- `tests/steps/test_attempt_usage.py` (new) — use `test_attempt` helpers, `Attempts.execute`/`collect`, `show_attempt` and rendering for A1–A2.
- `tests/steps/test_factory_schema.py` — append schema 29's DDL pin and verify nullable boolean validation.
- `tests/steps/test_dash_usage.py` — extend `report` fixture and coverage/explanation assertions.
- `docs/design/tl-8bh9.14.188/plan.md` — implementation contract and bounded verification scope.
- `src/taskloop/attempt.py` — consult `_capture`, `_resume`, `_answered`, `capture`: projection, store and report callers.
- `src/taskloop/recovery/callbacks.py` — consult `Callbacks.returned`/`capture`, the other `PendingResult` producer and capture caller.
- `src/taskloop/dash_task.py` — consult `_agent`/`_agent_body`, report-explanation consumers and `project` caller.
- `src/taskloop/dash_model.py` — consult `Usage`/`AttemptDetail`; reuse existing counts and coverage shape.
- `src/taskloop/dash/static/usage.js` — consult `usageText`, the existing absent-report and aggregate-coverage rendering.
- `tests/steps/test_attempt.py` — consult fixtures, unknown-count checks and `report` callers; near its size cap.
- `tests/steps/test_attempt_stop.py` — consult stop hooks and CLI/dashboard integration fixtures.
- `tests/steps/test_recovery_callbacks.py` — consult the direct `execution_facts`/capture caller and reopen-without-rerun contract.

## Read list
- `src/taskloop/attempt_types.py:180-194` — execution facts shape.
- `src/taskloop/attempt_types.py:359-397` — normalized usage projection.
- `src/taskloop/factory_schema.py:46-51` — schema version.
- `src/taskloop/factory_schema.py:135-151` — execution DDL.
- `src/taskloop/factory_schema.py:282-285` — ordered facts columns.
- `src/taskloop/attempt_store.py:43-58` — facts encoder.
- `src/taskloop/attempt_store.py:219-256` — capture transaction and replay fences.
- `src/taskloop/attempt_loads.py:182-219` — decoding offsets and stored result.
- `src/taskloop/attempt.py:105-129` — capture retry and report callers.
- `src/taskloop/attempt.py:246-300` — returned outcome, projection, persistence and report caller.
- `src/taskloop/attempt_result.py:8-70` — outcome and explanation composition, collection.
- `src/taskloop/show_render.py:47-68` — attempt display integration.
- `src/taskloop/dash_usage.py:11-39` — completeness and totals.
- `src/taskloop/dash_task.py:97-142` — usage and explanation consumers.
- `src/taskloop/dash_model.py:154-182` — public usage model.
- `src/taskloop/dash/static/usage.js:1-21` — existing usage wording.
- `src/taskloop/recovery/callbacks.py:39-49` — returned execution producer and capture caller.
- `tests/steps/test_attempt.py:70-157` — fixture integration for new tests.
- `tests/steps/test_attempt.py:394-400` — unknown usage and answer stop.
- `tests/steps/test_attempt.py:770-789` — direct report consumers.
- `tests/steps/test_attempt_stop.py:35-76` — semantic stop and display fixture.
- `tests/steps/test_recovery_callbacks.py:114-137` — capture replay and reopen.
- `tests/steps/test_factory_schema.py:14-54` — schema pin and validation pattern.
- `tests/steps/test_dash_usage.py:17-58` — dashboard fixture and public count assertions.
- `tests/steps/test_dash_usage.py:70-105` — totals and partial coverage assertions.

## Contract
Intent: project `RunOutcome` independently of exit classification and answer decoding. Add `ExecutionFacts.usage_incomplete: bool | None`, accepting only booleans from `summary.res`. Retain existing count meanings. No additional harness API is required.

Effect: `AttemptStore.capture` writes counts and `execution.usage_incomplete` together after execution. The column accepts NULL, 0 or 1. Extend `FACTS` in writer and reader; replay compares the full facts. Update evidence and answer offsets. Retry and recovery use the same boundary.

Result: collection retains counts and flag without rerunning. Add `usage_explanation(facts: ExecutionFacts) -> str`: absent counts say usage was not reported; true flag explains the missing in-flight request; partial reports identify missing counts. Zeroes are known. Preserve outcome and parse explanation in result text. CLI shares this explanation; dashboard consumes result explanations.

`dash_usage.project` retains known values but marks true-flag reports incomplete even with all counts present. Existing aggregate rendering describes reported values only. Unknown flag alone does not invalidate a complete report.

## Work packages
1. Persistence (A1): change `attempt_types.py`, `factory_schema.py`, `attempt_store.py`, `attempt_loads.py`, schema tests and new execution tests; cover all endings and replay.
2. Coverage (A2): change `attempt_result.py`, `show_render.py`, `dash_usage.py`, new execution tests and dashboard tests; verify public words and totals.
3. Verification (A1–A2): run focused new/schema/dashboard tests if needed; run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. Kill, timeout, answer stop and answer-parse failure retain all reported token, cumulative and turn counts plus the completeness flag in the captured result; repeated capture and later collection preserve them without rerunning execution, including a killed-attempt case.
A2. Missing counts remain unknown and are explained in attempt views; reported zeroes remain known; an explicitly incomplete report explains the missing in-flight request and contributes known counts to dashboard totals without being counted as complete. Existing outcome and parse explanations remain visible.
