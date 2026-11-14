# Header
Task: tl-8bh9.14.187; base: 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: medium; count and display are two linked behaviours.
Decision settled; no unlanded dependency; evidence budget: 12 model calls.
Size: 8 changed files, 2 behaviours, 40 model calls per implement attempt.

## Outcome and non-goals
New attempts persist the model-request count in execution.turns and show it beside tokens. The pinned release supplies requests; persistence and dashboard usage are delivered. Remaining work is the input projection, wording and regression coverage. No schema upgrade, historical rewrite, transcript reader or new usage metric is included.

## Settled decisions
- The owner's 2026-11-14 decision retains execution.turns and defines a turn as one model request and reply; document Codex's different whole-invocation usage.
- The re-queue decision supplies summary.res['requests'] from any-agent 0.15.0; consume that normalized fact without reproducing its rollout processing.
- Existing rows retain their values. No schema change or drain is required; stop and explain if implementation discovers a schema change is necessary.
- Keep the existing dashboard usage shape and shared renderer. Explain the released adapter's completion fallback when request evidence is unavailable; do not claim all historical counts have the new meaning.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_types.py`: `execution_facts`, `ExecutionFacts.turns` — project validated requests into turns; preserve other facts.
- `src/taskloop/attempt.py`: `Attempts._capture` — consult the sole production projection caller and retry boundary.
- `src/taskloop/attempt_store.py`: `_facts_values`, `AttemptStore.capture` — consult unchanged persistence and idempotency.
- `src/taskloop/attempt_loads.py`: `AttemptLoads._execution`, `collect` — consult unchanged persisted-fact reads.
- `src/taskloop/factory_schema.py`: `FACTS` — consult the existing field order; no edit expected.
- `src/taskloop/dash_usage.py`: `project`, `total`, `totals` — consult unchanged count projection and aggregation.
- `src/taskloop/dash_model.py`: `Usage` — consult unchanged public usage shape.
- `src/taskloop/dash_task.py`: `_agent`, `build_task` — consult consumers of projected facts and totals.
- `src/taskloop/dash/static/usage.js`: `fields`, `explanation`, `usageText`, `usageNode` — describe model-request turns and reporting limitations.
- `src/taskloop/dash/static/rail.js`: usage calls — consult attempt tooltip and step total consumers.
- `src/taskloop/dash/static/drawer.js`: usage calls — consult task total and attempt header consumers.
- `src/taskloop/dash/static/taskview.js`: `taskView` — consult task total consumer.
- `docs/glossary.md`: harness entry and usage labels — define the owner-approved turn meaning and Codex distinction.
- `tests/steps/test_execution_turns.py` (new): fake stream/result regression — integrate with `test_attempt.database`, `app`, `KEY`, `ENTRY`, `WORKER` and the existing surroundings fixture.
- `tests/steps/test_attempt.py`: `fake`, `app`, execution/collection assertions — consult existing fake-agent integration helpers; no edit expected.
- `tests/steps/test_dash_usage.py`: persisted usage cases — cover a count greater than one beside the existing token values.
- `tests/dash/rail.test.js`: `usage` — verify multi-request counts and the updated explanation through shared rendering.
- `docs/design/tl-8bh9.14.187/plan.md`: implementation scope and acceptance artifact.

## Read list
- `src/taskloop/attempt_types.py:356-397` — count validation and normalized result projection.
- `src/taskloop/attempt.py:268-291` — production caller and capture retries.
- `src/taskloop/attempt_store.py:43-58` — stored fact order.
- `src/taskloop/attempt_store.py:219-250` — capture ownership and duplicate handling.
- `src/taskloop/attempt_loads.py:182-224` — stored fact reconstruction and collection.
- `src/taskloop/factory_schema.py:282-285` — existing turns column mapping.
- `src/taskloop/dash_usage.py:7-39` — attempt counts and totals.
- `src/taskloop/dash_model.py:155-163` — existing Usage fields.
- `src/taskloop/dash_task.py:94-110` — attempt usage consumer.
- `src/taskloop/dash_task.py:280-289` — step/task total consumer.
- `src/taskloop/dash/static/usage.js:1-22` — shared text and tooltip.
- `src/taskloop/dash/static/rail.js:140-145` — renderer callers.
- `src/taskloop/dash/static/drawer.js:181-188` — task total renderer caller.
- `src/taskloop/dash/static/drawer.js:320-328` — attempt renderer caller.
- `src/taskloop/dash/static/taskview.js:33-40` — task total renderer caller.
- `docs/glossary.md:46-74` — usage wording and harness definition integration point.
- `tests/steps/test_attempt.py:122-165` — fake execution, app composition and collection pattern for the new test file.
- `tests/steps/test_dash_usage.py:17-59` — persisted usage fixture and serialized dashboard assertions.
- `tests/dash/rail.test.js:404-440` — usage counts, rail, drawer and task view assertions.

## Contract
Intent: record requests made during this agent invocation. Effect: `execution_facts(RunOutcome)` validates `summary.res['requests']` with the existing nonnegative-integer codec and puts it into `ExecutionFacts.turns`. Result: the existing capture transaction writes execution.turns, and collection returns the same count. No new type, state, column or side effect is introduced.

Absent, boolean, negative or otherwise invalid requests remain unknown; zero is valid. Do not substitute summary.res['turns'] in the factory. Any fallback belongs to the released adapter, which already supplies requests. Tool events, answer completion and repeated capture do not increment the stored count. Token totals and session/completion handling retain their current contracts. The factory consumes stream-derived normalized facts and never opens the adapter's rollout or transcript files to compute usage.

Dashboard intent: show the persisted count next to tokens. Effect: keep Usage.turns and the shared usage renderer; update its description to model requests, with historical-value and adapter-fallback limitations. Result: attempt displays and step/task totals keep their current count, unknown-value and coverage semantics. The available usage_incomplete fact does not require a new persisted field in this task.

## Work packages
1. Change `attempt_types.py`; add `test_execution_turns.py` using the existing fake-agent boundary. Feed a multi-call fake stream/result whose normalized summary reports requests=3 and turns=1, then exercise execution, persistence and independent collection. Include invalid/missing/zero request cases and capture reuse. Closes A1–A2.
2. Update `usage.js`, `glossary.md`, `test_dash_usage.py` and `rail.test.js`. Retain existing display integration and verify the count and explanation beside tokens. Closes A3.
3. Run the new execution and dashboard usage tests with the permitted isolated pytest command. Exercise the static usage fixture with an available non-live runner and report its execution status. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Include this plan among the eight changed files.

## Acceptance behaviours
A1. A fake agent stream reporting three model requests and one harness completion produces execution.turns=3 after capture and independent collection; tool events and repeated capture do not inflate it, and completion/session/token facts remain correct.
A2. A valid zero request count persists as zero; missing or invalid requests persist as unknown even if a completion count is present; prior stored rows are unchanged.
A3. The dashboard shows the persisted multi-request count beside tokens and retains it in step/task totals, with wording defining model-request turns and acknowledging historical values and adapter fallback; missing counts remain explicit.
