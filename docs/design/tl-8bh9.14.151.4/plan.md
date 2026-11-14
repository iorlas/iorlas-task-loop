# Header
Task: tl-8bh9.14.151.4
Base: ddd02a30f27d46341168b567777fcb23529b6860
Depth: medium; two display behaviours.
Owner decisions: none missing. Dependencies: none unlanded.
Evidence budget: 12 model calls.
Size: 1 changed file (plan artifact), 2 behaviours, 8 implement model calls.

## Outcome and non-goals
Both requested descriptions are already present in WORDS, their rendering paths use the table, and the matching dashboard tests assert their wording. No remaining runtime or test gap was found. Confirm this delivered behaviour with the existing checks; retain the implementation. This task does not change codes, stored data, schema, scheduling, timers, restart wording or attempt end times.

## Settled decisions
The summary label is "The factory's check of the answer failed".
The cause label is "A listed path is unsafe"; the unsettled form adds "Not committed: ". These are descriptions, rather than bare codes.
WORDS remains the single presentation mapping; raw codes remain available in diagnostic hover text.
Existing exact-description tests cover both acceptance behaviours; no duplicate tests or runtime edits are proposed.

## Open decisions
- None.

## Change map
- `docs/design/tl-8bh9.14.151.4/plan.md` (new): record the bounded confirmation work; integration points are the existing WORDS mappings and dashboard wording tests.
- `src/taskloop/dash/static/words.js` — retain `WORDS`, `say`, `wordNode` and their summary/cause descriptions.
- `src/taskloop/dash/static/ui.js` — consult and retain `callout` and `holdCallout`, which translate summary bodies and hold headings.
- `src/taskloop/dash/static/rail.js` — consult and retain `changeReason`, `verdict`, `verificationButtons`, `row`: reasons and summaries use `say`/`wordNode`.
- `src/taskloop/dash/static/result.js` — consult and retain `answer` and `result`: dispositions use `say`; result summaries reach `ui.callout`.
- `src/taskloop/attempt_result.py` — consult `_report`, the producer of the pending verification summary; retain serialized codes.
- `src/taskloop/dash_verify.py` — consult `CHECKS`, `verification` and failed-result construction; retain the unsafe check code.
- `src/taskloop/dash_model.py` — consult `Verification` and `Outcome`; retain the dashboard interchange shapes.
- `src/taskloop/dash_task.py` — consult `_verification`, `build_body` and `build_task`, which assemble the result consumed by the page; retain their data flow.
- `tests/cli/test_dash_words.py` — retain `test_outcomes_repeat_causes_and_verification_failures_have_readable_words` and mapping/caller coverage; run the matching tests.

## Read list
- `src/taskloop/dash/static/words.js:5-69` — mappings, fallback and diagnostic title boundary.
- `src/taskloop/dash/static/ui.js:63-85` — summary and hold-cause rendering.
- `src/taskloop/dash/static/rail.js:29-88` — repeat reasons and result descriptions.
- `src/taskloop/dash/static/rail.js:119-156` — failed-summary rendering and attached result.
- `src/taskloop/dash/static/result.js:24-32` — disposition caller of say.
- `src/taskloop/dash/static/result.js:101-110` — conclusion delegates to callout.
- `src/taskloop/attempt_result.py:55-75` — summary producer and stored result boundary.
- `src/taskloop/dash_verify.py:13-58` — check codes and result producer.
- `src/taskloop/dash_model.py:97-124` — result payload models.
- `src/taskloop/dash_task.py:214-278` — producer integration and detail assembly.
- `tests/cli/test_dash_words.py:8-55` — existing coverage of the two descriptions and their presentation table.

## Contract
Intent: present typed summary/cause codes as readable descriptions. Effect: say resolves WORDS, wordNode and callout use those descriptions as visible text, and holdCallout resolves the heading cause. Result: the summary and cause are explanatory text while the underlying codes and hover diagnostics remain intact. No new typed names, states, stored fields, IO or external effects are needed. Unknown codes retain the existing fallback.

## Work packages
1. Confirm the retained mappings and consumers using the read list. Existing exact-wording tests in `tests/cli/test_dash_words.py` close acceptance behaviours 1 and 2; no implementation change is currently needed.
2. After `just install`, run `uv run --frozen --no-sync python -I -m pytest -q tests/cli/test_dash_words.py --tb=short | tail -40`. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each. Report their results and the absence of a remaining implementation gap.

## Acceptance behaviours
1. A verification summary resolves to the factory's answer-check failure description in summary rendering, rather than a bare code.
2. An unsafe cause, including its unsettled form, resolves to a listed-path description in cause rendering, rather than a bare code.
