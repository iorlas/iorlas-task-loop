# Header
Task: tl-8bh9.14.146.1.3
Base: cd64b25ec06d8255e15670a51b0aee06d3889bc9
Depth: small; one message behaviour.
Owner decision: none missing. Unlanded dependency: none stated.
Evidence budget: 6 model calls.
Size: 17 changed files, 1 independent behaviour, 65 implement model calls.

## Outcome and non-goals
Explain situations and decisions in words; preserve operations. Admission belongs to part 1; land/hold guidance to part 2.

## Settled decisions
Keep reason-specific explanations, retry limits and process-identity safeguards.
Command labels remain identifiers; guidance contains no executable recipes.
Retain existing plain-language guides.

## Open decisions
- None.

## Change map
- `src/taskloop/step_guide.py`: STEP_ONLY/PUBLISH/HELD/ABANDON/ROUNDS/GUIDE/CHECKS_GUIDE/NEEDS_OWNER/discard; rewrite recipes; retain guide/refusal_guide routing.
- `src/taskloop/step_render.py`: _step_lines/_rows_lines/_released_lines/SLOT_COUNT_NOTE; rewrite appended instructions.
- `src/taskloop/operations.py`: UNCLAIMING/Failed; rewrite claim, database and uncertain-launch details.
- `src/taskloop/check_status.py`: HALF_DONE; explain pending claim return.
- `src/taskloop/publish.py`: publish; rewrite not_verified detail.
- `src/taskloop/rounds_lock.py`: RoundsRunning; describe scheduling ownership.
- `src/taskloop/cli.py`: STEP_ONLY caller; consult help.
- `src/taskloop/cli_step.py`: ROUNDS/STEP_ONLY callers; consult help/rendering.
- `src/taskloop/land_render.py`: refusal_guide caller; consult part 2 boundary.
- `src/taskloop/round_guide.py`: automatic_guide; retain existing explanations.
- `src/taskloop/hold_guide.py`: automatic_guide caller; consult part 2 boundary.
- `src/taskloop/step_refusal_guide.py`: REFUSALS; retain existing explanations.
- `tests/steps/test_check_operations.py`: GUIDE/CHECKS_GUIDE callers; repair assertions.
- `tests/steps/test_verifier.py`: GUIDE caller; repair assertions without expanding file.
- `tests/cli/test_step_cli.py`: rendering tests; repair affected assertions.
- `tests/cli/test_refusal_guidance.py`: refusal tests; repair affected assertions.
- `tests/steps/test_step_message_words.py` (new): exercise step_guide/step_render and mapped producers; check meaning and recipe absence.

## Read list
- `src/taskloop/step_guide.py:1-281`: text/routing.
- `src/taskloop/step_render.py:39-193`: consumers.
- `src/taskloop/operations.py:55-65`: claim-return text.
- `src/taskloop/operations.py:280-295`: database refusal.
- `src/taskloop/operations.py:490-515`: launch detail.
- `src/taskloop/check_status.py:17-21`: half-done text.
- `src/taskloop/publish.py:180-205`: publication refusal.
- `src/taskloop/rounds_lock.py:15-30`: lock refusal.
- `src/taskloop/cli.py:15-40`: guide consumer.
- `src/taskloop/cli_step.py:20-35`: guide imports.
- `src/taskloop/land_render.py:10-75`: refusal consumer.
- `src/taskloop/round_guide.py:106-140`: routing.
- `src/taskloop/hold_guide.py:1-90`: shared consumer.
- `src/taskloop/step_refusal_guide.py:1-176`: explanations.
- `tests/steps/test_check_operations.py:1-316`: expectations.
- `tests/steps/test_verifier.py:35-65`: guide integration.
- `tests/cli/test_step_cli.py:1-100`: renderer fixtures.
- `tests/cli/test_refusal_guidance.py:1-100`: refusal fixtures.

## Contract
Intent: explain existing outcomes. Effect: fixed text only. Result: situations and decisions without recipes. No new typed names, states or stored fields; retain ownership and retry boundaries.

## Work packages
1. Rewrite mapped producers and repair assertions. Close A1 with semantic and rendered coverage. Search for omitted callers.
2. Audit remaining instructions against parts 1/2. Run once each, last: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`; confirm success.

## Acceptance behaviours
A1. Guidance explains situations and decisions without recipes, including checks, launch failures, interrupted rounds, publication and pending claim return.
