# Header
Task: tl-8bh9.14.139.4; base: 28400434144adcee7c7e4728a1e6352e5f255c83.
Depth: small; one display behaviour. No missing owner decision or unlanded dependency. Evidence budget: 6 model calls. Size: 3 changed files (2 tests, plan), 1 independent behaviour, 18 implement model calls.

## Outcome and non-goals
The formatter and its consumers already supply the requested labels. Close the regression gap with exact-label and rendering assertions. Waiting, Land details and slot visibility are outside scope.

## Settled decisions
- Keep `words.js` as the display vocabulary owner; the requested mappings already exist.
- Assert the existing labels: `needs_owner` → "The agent needs your decision"; `failed:test:failed` → "Checks failed: test"; `answer:schema_invalid` → "The agent's answer was in the wrong format".
- Retain raw-code hover text and the existing fallback for unknown codes and ordinary explanation text.
- Backend codes remain structured data; label conversion happens in the page.

## Open decisions
- None.

## Change map
- `tests/cli/test_dash_words.py` — extend parametrized vocabulary assertions with the three exact code/label pairs; edit.
- `tests/dash/rail.test.js` — extend `words()` using `mount`, `result`, `say` and `wordNode` to assert actual labels and raw-code hover text; edit.
- `src/taskloop/dash/static/words.js` — consult `WORDS`, `say`, `wordNode`; mappings are already complete.
- `src/taskloop/dash/static/rail.js` — consult `changeReason`, verification `say` calls and `row`'s `wordNode`.
- `src/taskloop/dash/static/ui.js` — consult `callout` and `holdCallout`, both `say` consumers.
- `src/taskloop/dash/static/result.js` — consult `answer`'s `say` calls and `result`'s conclusion `callout`.
- `src/taskloop/dash_task.py` — consult `AttemptDetail` construction and `_agent_body`, which supply summary and answer disposition.
- `tests/dash/rail.html` — consult the existing browser-contract entry point.
- `docs/design/tl-8bh9.14.139.4/plan.md` — new plan artifact.

## Read list
- `tests/cli/test_dash_words.py:10-53` — existing required-code and exact-label assertions.
- `tests/dash/rail.test.js:1-26` — imports, attempt fixtures and rail mounting.
- `tests/dash/rail.test.js:208-213` — existing formatter and hover contracts to extend.
- `src/taskloop/dash/static/words.js:1-68` — mappings, family fallback and hover rendering.
- `src/taskloop/dash/static/rail.js:20-65` — reason and verification label consumers.
- `src/taskloop/dash/static/rail.js:115-139` — failed-attempt label rendering.
- `src/taskloop/dash/static/ui.js:56-85` — conclusion and hold callouts.
- `src/taskloop/dash/static/result.js:27-53` — answer disposition badge.
- `src/taskloop/dash/static/result.js:99-123` — result composition and conclusion.
- `src/taskloop/dash_task.py:99-110` — summary producer.
- `src/taskloop/dash_task.py:132-144` — answer and result producers.
- `tests/dash/rail.html:1-13` — local browser fixture.

## Contract
Intent: render codes through the vocabulary. Effect: show readable labels with raw-code titles. Result: readable conclusions, failed rail rows and answer dispositions. No new typed names, states, stored fields or external effects. Unknown codes and explanations pass through unchanged.

## Work packages
1. Extend the two test files with exact mapping assertions and rendered rail/conclusion cases for all three codes, plus the `needs_owner` answer badge. Include title assertions and retain existing fallback coverage. Closes A1.
2. Exercise the browser contracts through the local file fixture without a live factory. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last; confirm both commands succeed.

## Acceptance behaviours
A1. Each of the three specified codes displays its settled readable label in applicable dashboard views, preserves the raw code as hover text, and leaves unknown codes and ordinary explanations intact.
