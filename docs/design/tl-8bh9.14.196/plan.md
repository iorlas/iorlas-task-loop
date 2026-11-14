# Header
tl-8bh9.14.196; base 61cc8e66744c2e70bbddcd5431dd7933b7421f4c.
Depth: medium; two behaviours across two owning modules.
Owner decision: none missing. Unlanded dependency: none stated.
Evidence budget: 12 model calls. Size: 6 changed files, 2 behaviours, 25 implement model calls.

## Outcome and non-goals
Make the plan prompt and depth refusal describe the standalone declaration the validator already recognizes. An agent can repair an inline declaration by moving it onto its own line. Preserve the existing validation boundary, byte caps and other content rules. No free-prose depth extraction, scheduler changes or automatic repair.

## Settled decisions
- Require exactly one standalone `Depth: small`, `Depth: medium` or `Depth: large` line in Header, outside fenced code; reject a declaration embedded in a header sentence.
- Retain the existing optional `; explanation` suffix and state it explicitly; nothing precedes `Depth:` except the indentation already accepted by the validator.
- Keep `PlanDepth`, `PlanHeader`, `PlanContentRule.DEPTH` and the current parser; change the instructions and refusal wording rather than accepting inline prose.
- Use literal header examples to verify both shapes through the artifact boundary, including completion by new content and reuse.

## Open decisions
- None.

## Change map
- `src/taskloop/plan_step.py` — `TEMPLATE`, `DEPTH_ASSESSMENT`: require the standalone line, give a valid example and warn against embedding it after task/base prose; consult `input_text`, `_closing_words`, `feedback`, `artifact` and `_content` for initial/repeated instructions and validation integration.
- `src/taskloop/hold_cause.py` — `RULES[PlanContentRule.DEPTH]`: name the standalone form and a concrete repair; `_rejected` remains its explanation producer.
- `tests/steps/test_steps.py` — `test_plan_requests_fixed_lean_template_and_immutable_handoff`, `plan_input`: assert the unambiguous form reaches initial and repeated inputs.
- `tests/steps/test_plan_content.py` — `artifact`, depth/content tests: add paired standalone/inline cases and concrete repair guidance assertions; exercise both new completion and reuse through the existing verifier helpers.
- `tests/steps/test_hold_text.py` — `test_each_cause_class_names_its_cause_and_the_one_right_next_step`: update the depth case to require actionable standalone-line guidance in the rendered hold comment.
- `src/taskloop/plan_content.py` — consult `validate`, `_lines`, `PlanDepth`, `PlanHeader`; preserve recognition, suffix handling and rejection rules.
- `src/taskloop/steps.py` — consult `PLAN`, the registered caller of `plan_step.input_text`, `artifact` and `feedback`; no wiring change.
- `tests/steps/plan_fixtures.py` — consult `HEADER`, `PLAN_TEXT`; keep valid shared fixtures and make the inline regression explicit in its own test.
- `docs/design/tl-8bh9.14.196/plan.md` — new planning artifact; implementation consumes this plan through the existing plan/implement handoff.

## Read list
- `src/taskloop/plan_step.py:37-107` — assessment wording and emitted template.
- `src/taskloop/plan_step.py:162-188` — prompt producer and template integration.
- `src/taskloop/plan_step.py:235-274` — repeated input and artifact-to-validator boundary.
- `src/taskloop/hold_cause.py:17-27` — depth refusal and repair vocabulary.
- `src/taskloop/hold_cause.py:75-86` — explanation production from stored rules.
- `src/taskloop/plan_content.py:12-43` — typed depth values and fenced-code exclusion.
- `src/taskloop/plan_content.py:70-86` — exact declaration parser and content precedence.
- `src/taskloop/steps.py:28-49` — registered prompt, artifact and feedback callers.
- `tests/steps/test_steps.py:22-27` — initial/repeated input fixture.
- `tests/steps/test_steps.py:333-350` — template contract assertions to extend.
- `tests/steps/test_plan_content.py:1-52` — artifact helper and current depth cases.
- `tests/steps/test_plan_content.py:101-136` — new/reused artifact checks and refusal advice.
- `tests/steps/test_hold_text.py:158-176` — rendered depth refusal expectation.
- `tests/steps/plan_fixtures.py:1-6` — existing valid declaration shape.

## Contract
Intent: an initial or repeated plan input prescribes exactly one standalone depth declaration in Header. Effect: prompt text names all three allowed values, shows a valid line and permits the existing semicolon explanation. Result: the author has an exact format to follow.

Intent: validate plan content on new completion or reuse. Effect: the current line-only parser reads a valid declaration and rejects an inline-only one. Result: the existing typed depth refusal is rendered with the required standalone form and instruction to move an embedded declaration to its own line. No new typed names, states, stored fields or external effects.

## Work packages
1. Clarify `plan_step.py` and extend `test_steps.py` for initial and repeated inputs; closes A1.
2. Clarify `hold_cause.py`, extend `test_plan_content.py` with both header shapes and the repair wording, and update the rendered expectation in `test_hold_text.py`; closes A2. Retain parser code. After focused verification, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, with pipeline failure propagation.

## Acceptance behaviours
A1. Initial and repeated plan inputs explicitly require one standalone depth line in Header, show the valid form, name all allowed values and explain the optional semicolon suffix and rejection of inline-only declarations.
A2. For each allowed depth, standalone declarations pass and inline-only declarations fail on both new completion and reuse; the depth refusal and rendered hold guidance name the standalone form and a concrete repair. Existing duplicate, invalid and fenced declarations remain rejected.
