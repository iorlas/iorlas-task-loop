# Header
Task: tl-8bh9.14.145.1.1
Base: c8906e46b26e0dc092047e0e681f075e8f89fe46
Depth: medium
Reason: 3 behaviours: causes, context, projections.
Decision missing: no. Dependency unlanded: none stated.
Evidence budget: 12 model calls.
Size: 7 files, 3 behaviours, ~40 implement model calls.

## Outcome and non-goals
Add TaskEvent models/codec; existing holds have string reasons and separate attempt/cause IDs. Persistence, wiring, HoldInsert migration, snapshots and schema bump remain in the second split task.

## Settled decisions
- Persistence belongs to tl-8bh9.14.145.1.2; this part has no prerequisite.
- Use frozen pydantic v2 event/context models and enum/class cause vocabularies.
- Structured input and reason output only; no old-row reader or display-text parser.
- Preserve generic run classifications and existing answer/stop/merge meanings without importing execution/store graphs.

## Open decisions
- None.

## Change map
- `src/taskloop/task_event.py` (new): TaskEvent identities/context; integration: HoldInsert and HoldFacts.
- `src/taskloop/task_event_cause.py` (new): cause variants matching cause, end_word/judged, checks_result and round/merge refusals.
- `src/taskloop/task_event_codec.py` (new): encode/decode/reason; integration: HoldRow.reason and hold_cause.cause, without storage wiring.
- `tests/steps/test_task_event.py` (new): validation, round trips and literal reason expectations.
- `.importlinter`: refresh module coverage with tools/generate_import_contracts.py.
- `src/taskloop/hold_store.py`: consult HoldInsert/HoldRow and fences.
- `src/taskloop/hold.py`: consult hold_task, sole runtime HoldInsert producer, and _caused.
- `src/taskloop/round.py`: consult _held (hold_task caller), _settle_attempt, _advance and _publish (claim/branch refusals).
- `src/taskloop/round_land.py`: consult land_passed/HOLDING, land-refusal callback producer.
- `src/taskloop/hold_status.py`: consult cause projections.
- `src/taskloop/attempt_result.py`: consult end_word/judged projections.
- `src/taskloop/check_status.py`: consult checks_result projections.
- `src/taskloop/hold_cause.py`: consult terminal_cause/cause distinctions.
- `src/taskloop/hold_text.py`: consult HoldFacts context.
- `src/taskloop/attempt_types.py`: consult Rule and RepeatReason.
- `src/taskloop/answer_failures.py`: consult AnswerFailureData.
- `src/taskloop/merge/models.py`: consult Reason/Terminal.
- `src/taskloop/agents/stop_models.py`: consult AgentStop attribution.
- `tests/steps/test_hold.py`: consult Bench.hold and HoldInsert fixtures, including branch_moved; no caller migration.
- `tests/steps/test_hold_store.py`: consult the HoldInsert fixture; no persistence changes.
- `tests/steps/test_hold_status.py`: consult HoldInsert fixture and cause/terminal projections.
- `tests/steps/test_attempt_stop.py`: consult both stop-related HoldInsert fixtures.
- `tests/steps/test_dash_read.py`: consult agent/check HoldInsert fixtures and reason expectations.
- `tests/steps/test_wip_merge.py`: consult expired-admission HoldInsert fixture.
- `tests/steps/test_lost_entry.py`: consult lost-entry HoldInsert fixture.
- `tests/steps/test_round.py`: consult stuck-admission HoldInsert fixture.
- `tests/steps/test_discussion.py`: consult answer-failure HoldInsert fixture.
- `tests/steps/test_merge_release.py`: consult all three terminal merge HoldInsert fixtures.
- `tests/cli/test_step_status_cli.py`: consult held-status HoldInsert fixture.
- `docs/design/tl-8bh9.14.145.1.1/plan.md`: this contract.
- `docs/design/tl-8bh9.14.145.1.1/plan-metadata.json`: consulted paths.

## Read list
- `src/taskloop/hold_store.py:53-105` — existing identities, reason and row decoding.
- `src/taskloop/hold.py:93-150` — producer and cause revalidation.
- `src/taskloop/hold_status.py:21-88` — cause families and exclusions.
- `src/taskloop/hold_cause.py:17-181` — reason families and terminal semantics.
- `src/taskloop/hold_text.py:32-91` — structured explanation, checks and leftovers.
- `src/taskloop/round.py:235-270` — due-cause route; also inspect _held/_advance/_publish by targeted symbol search.
- `src/taskloop/round_land.py:27-76` — explicit land-refusal family.
- `src/taskloop/attempt_result.py:10-84` — run, answer and rejection projections.
- `src/taskloop/attempt_types.py:184-226` — execution/answer facts and verification rules; locate RepeatReason by symbol.
- `src/taskloop/answer_failures.py:8-32` — structured answer rejection.
- `src/taskloop/check_status.py:53-90` — checks failure and stuck projections.
- `src/taskloop/merge/models.py:30-60` — merge reasons; Terminal is at 135-138.
- `src/taskloop/agents/stop_models.py:70-103` — causal stop identity and validated attribution.
- `.importlinter:1-32` — existing import boundaries; refresh generated module coverage.
- `tests/steps/test_hold.py:120-134` — hold_task caller; find HoldInsert fixtures by targeted symbol search.
- `tests/steps/test_hold_store.py:50-63` — producer fixture.
- `tests/steps/test_hold_status.py:22-54` — projection examples; HoldInsert fixture at 125-134.
- `tests/steps/test_attempt_stop.py:50-65` — stop/hold association; second fixture at 100-108.
- `tests/steps/test_dash_read.py:185-210` — causal checks identity; agent fixture at 90-98.
- `tests/steps/test_wip_merge.py:35-45` — stuck event fixture.
- `tests/steps/test_lost_entry.py:103-113` — lost-entry fixture.
- `tests/steps/test_round.py:210-222` — round hold fixture.
- `tests/steps/test_discussion.py:190-200` — answer event fixture.
- `tests/steps/test_merge_release.py:55-100` — all terminal merge producers.
- `tests/cli/test_step_status_cli.py:200-210` — held reason at CLI boundary.

## Contract
Intent: TaskEvent carries held agent attempt ID, causal attempt ID/step, typed cause and context. Agent causality identifies itself; checks causality identifies a distinct checks attempt and owning implement attempt. Validate internal consistency; database ownership/currentness remain storage fences.

Effect: pure models/codec for disposition, run, answer, rejection, checks, stuck, repeat, merge, land and round claim/branch causes. Command names are data, conclusions closed values. Include main_moved and bare/qualified repeats_exhausted; exclude successful/pending/transient outcomes.

Context types cover explanation, deadline, stop/return code, failed checks, leftovers and merge/land details. Require applicable facts; reject incompatible fields/identities. Nested stop identity matches the causal attempt. Reuse fitting validated payloads; absent evidence remains optional.

Result: encode(TaskEvent) returns JSON text; decode(text) returns validated TaskEvent or raises ValueError. Reject unknown tags/reasons, extras, invalid scalar types, non-finite times and inconsistent context. One codec owns exact reason spelling, including failed prefixes, terminal distinctions and check names. No schema/SQL changes or old-reason parser.

## Work packages
1. Add task_event_cause.py/task_event.py and test_task_event.py validation cases. Closes A1/A2.
2. Add task_event_codec.py and round-trip/projection cases in test_task_event.py. Closes A1/A3.
3. Refresh .importlinter, verify size caps, then run final gates once each: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving exit status. Both must pass. No live tests. Closes A1-A3.

## Acceptance behaviours
A1: Every supported cause family round-trips through the single codec; unknown families/reasons, malformed payloads and successful/transient outcomes are rejected.
A2: Agent versus checks causality and family-specific context survive serialization; mismatched attempt/stop identities, missing required facts and contradictory or extra context are rejected without IO.
A3: Preserve exact reasons for check names, main_moved, bare/qualified repeats, merge/land and round refusals, with existing caller behaviour and schema unchanged.
