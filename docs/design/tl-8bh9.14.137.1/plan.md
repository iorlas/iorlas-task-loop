# Header
tl-8bh9.14.137.1 @ fd1be071c69c3e6eaf063d3e19ed8091a1049f3a
Depth: medium; precise failures and unfinished-path normalization.
Owner decision: none. Unlanded dependency: none. Evidence budget: 12 model calls.
Size: 15 changed files incl. plan/tests; 2 behaviours; 50 implement model calls.

## Outcome and non-goals
Invalid answers retain a specific broken rule through collection and human/JSON reporting. Decoders already enforce bounds and cross-field constraints and normalize unfinished paths; replace generic failure details.

Exclude repair invocation, continuation admission, retry policy, hold-routing changes and dashboard redesign. Later split tasks own repair and holds.

## Settled decisions
One decoder owns each step's answer contract; JSON schemas keep their current shape.
Keep the existing decoder signature and ValueError compatibility for invalid answers.
Keep result reason words and successful answer effects; report failure details separately.
Use the existing AttemptResult.explanation field and result_data JSON projection.
Store validated failure data with the answer state, independently of raw answer files.
Schema 27 becomes 28; deployment drains old attempts before replacing factory.db.

## Open decisions
- None.

## Change map
- `src/taskloop/answer_failures.py` (new): AnswerRule, AnswerFailure and stored failure codec; integrate with step decoders, Attempts._validate and attempt stores.
- `src/taskloop/plan_step.py`: decode emits specific failures for shape, disposition, plan_path, paths, message and explanation constraints; retain normalization order.
- `src/taskloop/implement_step.py`: decode emits specific failures, including forbidden plan.md, without changing accepted answers.
- `src/taskloop/attempt_types.py`: AnswerState gains failure data; consult validation producers path_allowed, listed_paths and commit_message.
- `src/taskloop/attempt.py`: Attempts._validate captures typed decoder failures and populates AnswerState.
- `src/taskloop/attempt_store.py`: AttemptStore.answer writes failure data atomically with the existing fenced answer transition.
- `src/taskloop/attempt_loads.py`: AttemptLoads._execution reconstructs validated failure data; adjust projection offsets.
- `src/taskloop/factory_schema.py`: SCHEMA and ANSWER add nullable structured failure storage and advance the schema version.
- `src/taskloop/attempt_result.py`: report projects failure explanation; preserve end_word and run-failure precedence.
- `src/taskloop/show_render.py`: _agent_lines prints the specific answer failure from the collected result.
- `src/taskloop/result_data.py`: consult _show_data's existing result.explanation projection.
- `src/taskloop/steps.py`: consult StepKind.decode and PLAN/IMPLEMENT registrations.
- `src/taskloop/answer_read.py`: consult read, the other production decoder caller; preserve valid-answer reads.
- `src/taskloop/hold_facts.py`: consult explanation, the answer_read consumer.
- `tests/steps/test_answer_contract.py`: assert specific rules and boundaries for both decoders, plus normalization precedence.
- `tests/steps/test_attempt_answers.py`: cover durable failure collection, repeat collection and unchanged unfinished-answer effects.
- `tests/steps/test_factory_schema.py`: append the new DDL version pin and verify failure storage constraints.
- `tests/cli/test_step_status_cli.py`: exercise persisted failure reporting through human and JSON CLI reads.
- `docs/design/tl-8bh9.14.137.1/plan.md`: implementation scope and acceptance.

## Read list
- `src/taskloop/plan_step.py:135-162` — plan rules and decoder integration.
- `src/taskloop/implement_step.py:89-119` — implement decoder and plan.md rejection order.
- `src/taskloop/attempt_types.py:180-204` — execution facts and AnswerState.
- `src/taskloop/attempt_types.py:311-371` — result explanation, Answer and shared validation producers.
- `src/taskloop/attempt.py:291-311` — answer decoding and persistence handoff.
- `src/taskloop/attempt_store.py:257-273` — fenced, idempotent answer write.
- `src/taskloop/attempt_loads.py:180-219` — execution projection and reconstruction.
- `src/taskloop/factory_schema.py:46-55` — schema version ownership.
- `src/taskloop/factory_schema.py:136-150` — execution storage.
- `src/taskloop/factory_schema.py:279-286` — shared projection column lists.
- `src/taskloop/attempt_result.py:8-41` — reason precedence and result collection.
- `src/taskloop/show_render.py:47-66` — human result explanation placement.
- `src/taskloop/result_data.py:46-65` — existing JSON explanation projection.
- `src/taskloop/steps.py:29-56` — decoder type and step registrations.
- `src/taskloop/answer_read.py:1-16` — second production decoder caller.
- `src/taskloop/hold_facts.py:67-74` — valid answer explanation consumer.
- `tests/steps/test_answer_contract.py:110-169` — plan contract boundaries.
- `tests/steps/test_answer_contract.py:240-310` — implement rules and unfinished normalization.
- `tests/steps/test_attempt_answers.py:21-84` — collection and normalization integration.
- `tests/steps/test_factory_schema.py:15-32` — DDL pins and version guard.
- `tests/cli/test_step_status_cli.py:18-78` — real read-only CLI fixture and assertions.

## Contract
AnswerRule is a closed enum separate from Git verification Rule. AnswerFailure is a ValueError subtype carrying a rule and bounded explanation. A pydantic v2 model and one codec validate stored failure data and its representation.

Distinguish root/keys, disposition, plan_path, paths shape/count/duplicates/location, required committed paths, forbidden plan.md, message and explanation failures. Name the requirement and applicable bound or expected value. Use deterministic validation order and the shared path/message policy; never parse error text for control.

Intent: decode. Effect: the existing strict JSON decoder receives a callback that catches only AnswerFailure and returns it as a typed value. Result: decoded Answer retains its fields; decoded AnswerFailure produces schema_invalid with detail. Invalid JSON and missing answers name their corresponding requirements. Unexpected faults propagate. No new shelf API or exception-detail fields are needed.

Intent: settle validation. Effect: the fenced answer transaction writes failure data beside answer_kind. Result: identical retries return already_same; different failures conflict. Invalid/missing states require detail; valid/pending states have none. Collection validates it without answer-file reads; malformed stored data is unavailable.

Intent: report. Effect: none. Result: AttemptResult.explanation, human output and existing JSON projection expose the stored rule and explanation. Preserve run-failure precedence and status/reason words.

## Work packages
1. Decoders (`answer_failures.py`, `attempt_types.py`, step modules, contract tests): typed rejections with preserved normalization. Closes A1/A2 at decoding.
2. Persistence (`attempt.py`, attempt stores, `factory_schema.py`, schema/attempt tests): fenced failure writes, reloads and retries. Closes A1/A2 across collection.
3. Reporting (`attempt_result.py`, `show_render.py`, CLI tests): human and JSON explanations. Closes A1 reporting. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A1. Each rejected answer identifies its violated constraint with a typed rule and useful explanation; collection after reopening storage and human/JSON reporting retain that failure, identical settlement is idempotent, conflicting settlement is refused, and invalid answers cannot authorize a commit.
A2. Incomplete and needs_owner answers still discard structurally valid unused path lists, including duplicates and out-of-scope paths; malformed answer shape, non-null message, invalid plan_path and implement plan.md remain rejected in their existing order, while valid committed and unchanged answers retain their effects.
