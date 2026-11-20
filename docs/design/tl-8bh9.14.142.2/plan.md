# Header
Task: tl-8bh9.14.142.2; base: ca861999263bd031d4f59007c60cdcf726a50fea
Depth: medium; schema, decoding, prompts.
Owner decision: none; unlanded dependency: none. Evidence budget: 12 calls.
Size: 16 files including tests/artifacts; 3 independent behaviours; ~60 implement model calls.

## Outcome and non-goals
Close the schema, decoding, wording and fixture gap around existing slot-derived commit selection. Preserve plan answers, slot safety and structured shelf requests. No database upgrade, compatibility decoder or shelf change.

## Settled decisions
- Implement's external keys are disposition, message and explanation; an extra paths key is invalid for every disposition.
- Preserve the shared internal Answer representation for planning; implement decoding supplies an empty paths tuple.
- Keep answer_decode.paths for plan_step.decode. Implement path safety and nonempty-commit enforcement belong to slot settlement, which already owns them.
- Keep message validation and the existing string/structured-shelf-request explanation rules.
- Initial, repeat, failed-check and shelf-refusal instructions must describe answers without requesting or showing a paths list.

## Open decisions
- None.

## Change map
- `src/taskloop/implement_step.py` — ANSWER_KEYS, ANSWER_SCHEMA, decode: drop external paths; update constants and all prompt functions.
- `src/taskloop/answer_decode.py` — fields, paths: consult shared validation retained for planning.
- `src/taskloop/answer_read.py` — read: consult stored-answer dispatch; test three-field evidence.
- `src/taskloop/step_text.py` — feedback, SAVED_WORK: consult shared framing and filename evidence.
- `src/taskloop/attempt_types.py` — Answer: clarify plan-path versus slot-path ownership.
- `src/taskloop/steps.py` — IMPLEMENT, failed_check_feedback: consult contract/prompt dispatch.
- `src/taskloop/plan_step.py` — decode: consult caller retaining answer_decode.paths.
- `src/taskloop/factory_commit.py` — _review: consult slot selection, caps and plan.md protection.
- `src/taskloop/verdict.py` — _changes: consult plan-only answer membership check.
- `src/taskloop/earlier_input.py` — EarlierInput.attach: consult read_answer caller and commit-derived names.
- `src/taskloop/hold_facts.py` — explanation: consult read_answer caller.
- `src/taskloop/dash_board.py` — _ask: consult read_answer caller.
- `tests/steps/test_answer_contract.py` — IMPLEMENTED/shared cases: test strict keys, effects and stored reads; separate plan-path tests.
- `tests/steps/test_agent_launch.py` — assert_disposition_guidance/schema assertions: update implement expectations.
- `tests/steps/test_steps.py` — initial/repeat/failed-check assertions: cover consistent three-field guidance.
- `tests/steps/test_check_repeat.py` — repair_agent/scripted producers: migrate payloads, preserve safety coverage.
- `tests/steps/round_bench.py` — Factory: migrate shared implement producer.
- `tests/steps/test_conflict_recovery.py` — scripted producers: migrate recovery payloads.
- `tests/steps/test_environment.py` — UNCHANGED: migrate implement fixture.
- `tests/steps/test_answer_repair.py` — implement repair case: migrate payload.
- `tests/steps/test_admit_chain.py` — implement producers: migrate chain fixtures.
- `tests/steps/test_merge_advance.py` — implementation/scripted producers: migrate payloads.
- `tests/steps/test_input_context.py` — implement producers: migrate payloads, retain internal AnswerState fixtures.
- `tests/steps/test_implement_feedback.py` — unsafe/failed-check cases: consult framing coverage.

## Read list
- `src/taskloop/implement_step.py:30-243` — contract, decoder and every implement prompt variant.
- `src/taskloop/answer_decode.py:7-51` — shared validation used by both agent steps.
- `src/taskloop/answer_read.py:3-16` — stored-evidence decoder dispatch.
- `src/taskloop/step_text.py:11-46` — shared prompt frame and saved-work guidance.
- `src/taskloop/attempt_types.py:332-343` — shared Answer fields and ownership wording.
- `src/taskloop/steps.py:30-63` — schema, decoder and feedback consumers.
- `src/taskloop/plan_step.py:140-157` — retained planning path decoder caller.
- `src/taskloop/factory_commit.py:171-207` — slot selection and safety ownership.
- `src/taskloop/verdict.py:67-85` — plan-only path membership verification.
- `src/taskloop/earlier_input.py:70-90` — stored-answer consumer and commit-derived names.
- `src/taskloop/hold_facts.py:71-80` — stored-answer explanation consumer.
- `src/taskloop/dash_board.py:93-104` — dashboard stored-answer consumer.
- `tests/steps/test_answer_contract.py:230-405` — implement contract and shared path-rule tests to separate.
- `tests/steps/test_agent_launch.py:75-153` — guidance helper and schema forwarding assertions.
- `tests/steps/test_steps.py:300-373` — initial/repeat/failed-check prompt assertions.
- `tests/steps/test_check_repeat.py:85-115` — repair answer producers.
- `tests/steps/test_check_repeat.py:393-445` — unchanged and unsafe-slot producers/coverage.
- `tests/steps/round_bench.py:320-335` — shared implement answer producer.
- `tests/steps/test_conflict_recovery.py:130-162` — implement recovery answer producers.
- `tests/steps/test_environment.py:24-38` — implement unchanged fixture.
- `tests/steps/test_answer_repair.py:315-329` — implement repaired-answer fixture.
- `tests/steps/test_admit_chain.py:275-361` — implement admission/chain producers.
- `tests/steps/test_merge_advance.py:45-91` — retained-plan implementation producers.
- `tests/steps/test_input_context.py:250-289` — digest/repeat answer producers.
- `tests/steps/test_implement_feedback.py:1-91` — evidence framing regression coverage.

## Contract
Intent: request an implement commit or report another disposition. Effect: strictly decode three keys with existing message/explanation rules. Result: Answer carries the existing effect and paths=(); external paths fails shape validation for every disposition.

Intent: launch or repeat. Effect: remove answer-path requirements from every implement prompt variant. Result: consistent instructions retaining cleanup, restoration, plan.md protection and slot-status filename evidence.

Intent: collect, settle or read an answer. Effect: dispatch through steps and answer_read. Result: explanations remain readable; slot review selects safe changes and rejects forbidden changes or empty commits. Planning retains listed-path validation. No stored field or state changes.

## Work packages
1. Change implement_step's external contract and decoder; clarify Answer ownership, separate implement cases from planning path tests, and cover stored reads in test_answer_contract. Closes acceptance 1.
2. Update all implement prompt constants/functions and the test_steps/test_agent_launch assertions, including repeats and failed-check feedback. Closes acceptance 2.
3. Migrate affected fixtures, retaining plan payloads/internal AnswerState. Exercise collection, repair and settlement with focused tests. Finish with pipefail and `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`, once each as final validation. Closes acceptance 3.

## Acceptance behaviours
1. Every implement disposition decodes with exactly three external fields and its existing effect/message/explanation rules; paths is rejected as an extra field, stored implement evidence is readable, and plan answers retain their path rules.
2. Initial, repeated and failed-check implement prompts, including shelf-request examples, never ask for an answer path list; commit-message, cleanup, saved-work and plan-protection instructions remain consistent.
3. A three-field implement answer flows through launch, collection, repair and settlement: safe slot changes are committed and verified, unsafe changes remain refused, and unchanged answers retain their existing treatment of leftover work.
