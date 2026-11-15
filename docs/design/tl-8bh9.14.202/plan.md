# Header
tl-8bh9.14.202 @ 6a0bd3db681dec4fe29ab4b8abbfa4583a67c526
Depth: small; one template behaviour in one owning module.
Owner decision missing: no. Unlanded dependency: none stated. Evidence budget: 6 calls.
Size: 2 implementation files including tests; 1 behaviour; 20 implement calls.

## Outcome and non-goals
Align the agent's Change map instructions with the existing first-content-line validation. The shared template already requests bullets, but omits their required position. Add explicit placement guidance and pin its delivery through initial and repeated plan input. Keep validation semantics and plan structure intact.

## Settled decisions
- Use the wording: "the first line under ## Change map must be a bullet; put any explanation inside a bullet" in TEMPLATE's Change map guidance.
- Exercise the public PLAN input with the existing plan_input fixture beside the template tests.
- No new types, vocabulary, dependencies or files are needed for implementation.

## Open decisions
- None.

## Change map
- `src/taskloop/plan_step.py` — amend `TEMPLATE`; consult `input_text`, `_closing_words`, `feedback` and `repeat_instructions` for delivery through initial and repeated input.
- `tests/steps/test_steps.py` — add a contract test beside `test_plan_requests_fixed_lean_template_and_immutable_handoff`, using `plan_input` to assert both clauses within the Change map guidance.
- `src/taskloop/plan_content.py` — consult `_change_map`; preserve its first-nonempty-line check.
- `src/taskloop/steps.py` — consult `PLAN`/`StepKind` wiring; no change.
- `tests/steps/test_commit_paths.py` — consult the `plan_step.feedback` caller; no change to repair framing.
- `tests/steps/refusal_inventory.py` — consult the `plan_step.py`/`Rejected` inventory entry; no change.
- `tests/rules/test_enum_values.py` — consult the existing `plan_step.py` depth exemption; no change.
- `tests/rules/repeated_string_exceptions.json` — consult the `plan_step.py` entry; no exemption changes expected.

## Read list
- `src/taskloop/plan_step.py:77-92` — template and Change map guidance to edit.
- `src/taskloop/plan_step.py:166-170` — initial input producer.
- `src/taskloop/plan_step.py:184-208` — shared closing text and TEMPLATE interpolation.
- `src/taskloop/plan_step.py:232-260` — repeated input producer and feedback.
- `tests/steps/test_steps.py:17-39` — shared initial/repeated input fixture.
- `tests/steps/test_steps.py:408-425` — adjacent template contract tests.
- `src/taskloop/plan_content.py:57-67` — validator boundary to retain.
- `src/taskloop/steps.py:37-50` — public PLAN wiring.
- `tests/steps/test_commit_paths.py:184-193` — direct feedback consumer.
- `tests/steps/refusal_inventory.py:119-119` — rejection inventory reference.
- `tests/rules/test_enum_values.py:52-52` — existing depth reference.
- `tests/rules/repeated_string_exceptions.json:444-451` — existing string counts.

## Contract
Intent: an agent receives the positional constraint with the Change map instructions. Effect: TEMPLATE text flows through existing PLAN producers. Result: initial and repeated input explicitly require the first line to be a bullet and explanations to remain inside bullets. No typed, stored or external-effect contract changes.

## Work packages
1. Edit `src/taskloop/plan_step.py` and add the neighbouring contract test in `tests/steps/test_steps.py`; close A1. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, and require both to pass.

## Acceptance behaviours
- A1: Initial and repeated plan instructions place the first-line bullet requirement and explanation-inside-a-bullet requirement in the Change map guidance.
