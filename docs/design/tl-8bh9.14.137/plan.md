# Header
Task: tl-8bh9.14.137; base: aa0ef0aeecdce4c4e11772afad308f072746cb59.
Depth: medium
Reason: three behaviours. No missing decision; resume dependency landed.
Evidence budget: 12 model calls.
Size: 32 files including tests and plan; 3 behaviours; 90 implement model calls.

## Outcome and non-goals
Repair invalid answers once in the existing session, preserving work and original failure; hold with the broken rule after failure. Preserve delivered unfinished-path normalization. No fresh-session fallback or general retry framework.

## Settled decisions
- One repair, through landed AgentLaunch.build resume and existing recovery.
- contract_invalid replaces schema_invalid; retain missing/json_invalid.
- One typed vocabulary for errors, prompts and holds.
- Separate repair attempt/evidence; immutable source.
- Keep slot, settings, session, deadline and base.
- Separate durable repair and leftovers allowances.

## Open decisions
- None.

## Change map
- `src/taskloop/answer_contract.py` (new): typed failures and codec for decoders, Attempts and holds.
- `src/taskloop/attempt_types.py`: AnswerState carries typed failure.
- `src/taskloop/implement_step.py`: decode explains rules; expose complete repair contract.
- `src/taskloop/plan_step.py`: plan-specific failures and contract.
- `src/taskloop/steps.py`: StepKind exposes contract beside schema/decode; sole step-module importer.
- `src/taskloop/attempt.py`: _validate retains failure; _start supplies admitted resume reference.
- `src/taskloop/answer_read.py`: read remains a pure decoder caller with typed failure handling.
- `src/taskloop/attempt_store.py`: answer stores failure once; repair-admission support.
- `src/taskloop/attempt_loads.py`: _execution reads failure.
- `src/taskloop/factory_schema.py`: failure fields, repair relation and incompatible version 28.
- `src/taskloop/attempt_result.py`: end_word uses rule-bearing codec.
- `src/taskloop/answer_repair/models.py` (new): validated intent/results for admission and Attempts.
- `src/taskloop/answer_repair/store.py` (new): repair-table owner; unique successor via owning admission APIs.
- `src/taskloop/answer_repair/repair.py` (new): prompt, admission and dispatch before StepRepeat's leftovers path.
- `src/taskloop/admit_chain.py`: ChainAdmission repair support and separate repeat accounting.
- `src/taskloop/repeat.py`: StepRepeat delegates repair first; repairs do not spend leftovers cap.
- `src/taskloop/attempt_status.py`: eligible repair selects existing repeat action before hold.
- `src/taskloop/hold_status.py`: cause preserves pending repair and explicit holds.
- `src/taskloop/composition.py`: open_attempts injects repair reads; retain open_continuation wiring.
- `src/taskloop/cli_composition.py`: _starting wires repair into StepRepeat.
- `src/taskloop/operations.py`: consult start's captured-attempt caller through ports.repeat.
- `src/taskloop/round.py`: consult round's ports.repeat caller; same operation.
- `src/taskloop/agents/launch.py`: consult build's resume and capability-refusal boundary.
- `src/taskloop/hold_cause.py`: _answer renders rule and repair result through shared codec.
- `src/taskloop/step_refusal_guide.py`: replace schema wording.
- `src/taskloop/dash/static/words.js`: contract classification and specific rule wording.
- `tests/steps/test_answer_contract.py`: typed failures and preserved normalization.
- `tests/steps/test_attempt_answers.py`: failure persistence/collection.
- `tests/steps/test_answer_repair.py` (new): success, exhaustion, restart and races with semantic fakes.
- `tests/cli/test_dash_words.py`: public rule wording.

## Read list
- `src/taskloop/attempt_types.py:108-205` — admission and answer models.
- `src/taskloop/implement_step.py:88-122` — decoder and unfinished paths.
- `src/taskloop/plan_step.py:135-161` — plan decoder.
- `src/taskloop/steps.py:20-61` — StepKind and decoder producers.
- `src/taskloop/attempt.py:151-311` — launch, capture and failure production.
- `src/taskloop/attempt_store.py:257-277` — write-once answer.
- `src/taskloop/attempt_loads.py:190-235` — stored projection.
- `src/taskloop/factory_schema.py:49-165` — version and execution DDL.
- `src/taskloop/attempt_result.py:8-42` — collection words.
- `src/taskloop/answer_read.py:1-16` — other decoder caller.
- `src/taskloop/agents/launch.py:86-138` — native resume.
- `src/taskloop/admit_chain.py:55-165` — fenced takeover.
- `src/taskloop/repeat.py:55-115` — repeat admission and cap.
- `src/taskloop/attempt_status.py:215-242` — action selection.
- `src/taskloop/hold_status.py:46-73` — hold decision.
- `src/taskloop/composition.py:93-143` — continuation/Attempts wiring.
- `src/taskloop/cli_composition.py:139-156` — StartPorts wiring.
- `src/taskloop/operations.py:345-371` — CLI dispatch caller.
- `src/taskloop/round.py:264-285` — round dispatch caller.
- `src/taskloop/hold_cause.py:80-101` — answer wording.
- `src/taskloop/step_refusal_guide.py:145-164` — refusal guidance.
- `src/taskloop/dash/static/words.js:1-35` — dashboard labels.
- `tests/steps/test_answer_contract.py:230-306` — decoder regressions.
- `tests/steps/test_attempt_answers.py:1-84` — stored classification.
- `tests/cli/test_dash_words.py:1-65` — wording expectations.

## Contract
AnswerFailure validates enum classification/rule, field location and explanation. Cover shape, disposition, paths, message, explanation, bounds and plan constraints. Preserve exact error and JSON parse detail; missing output is distinct. Report the first violation deterministically; unexpected faults propagate.

Persist failure with execution. One codec owns answer:contract_invalid:<rule> and human wording. Remove old vocabulary without aliases. Version 28 rejects older databases; drain entries before authorized discard.

Intent: under custody and a short transaction, recheck reservation, claim, session, deadline, hold/drain fences and absent successor. Store source/successor, saved session, prompt reference and dispatch state. Retain original evidence/failure, base and valid commit chain; link invalid source separately. Keep ordered attempt numbering; exclude repair from leftovers cap.

Effect: outside the transaction, dispatch with exact failure, rule in words, complete current step contract and schema through build(resume=...). Ask only for a corrected final answer. Record registration/result under existing fences. Existing recovery reconciles ambiguous launches; missing output never authorizes another launch. Unsupported continuation refuses without a fresh session.

Result: valid repair follows normal handling; invalid repair holds with its latest failure. Durable linkage prevents another repair after restart or concurrent starts. Reads launch nothing.

## Work packages
1. Add typed failures/contracts and persistence in answer_contract, step modules and attempt models/stores/result/schema. Closes acceptance 1.
2. Add repair slice and admitted resume input; integrate Attempts, admission, StepRepeat and composition. Closes acceptance 2.
3. Route status before hold, update wording and tests. Closes acceptance 3; checks 1–2. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, with pipeline failure propagation.

## Acceptance behaviours
1. Invalid plan/implement answers report the actual typed rule and explanation, including malformed JSON. Unfinished string paths still normalize to no commit request and trigger no repair.
2. Invalid then valid uses original session/slot, retains work/settings and reaches normal handling. Restart, concurrent callers and lost acknowledgement yield one successor. Valid answers and failed executions receive no repair.
3. Invalid again holds with the latest rule in words in collection, refusal guidance and dashboard. Later rounds cannot add a third invocation; explicit holds and unsupported, unsafe or unobservable continuation cannot start a fresh or competing session.
