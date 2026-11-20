# Header
Task: tl-8bh9.14.145.3
Base: 1c357b0a7d9c2436f8ff2406a853b92b9b9805d3
Depth: medium
Reason: two behaviours in Python and JS.
Owner decision: none missing. Unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 9 changed files; 2 behaviours; about 60 implement model calls.

## Outcome and non-goals
Add What changed to the selected attempt's existing panel. Keep the full prompt, event selection, cause snapshots, history and output tabs. Exclude rail redesign, new storage, schema changes and live Git comparisons.

## Settled decisions
- Compare against `previous_attempt_id`; an unlinked restart has no baseline.
- Reuse delivered `added_lines` and `AttemptBody.added`, zero-based half-open ranges for insertions/replacements.
- Compare recorded bases, never end commits or today's main ref.
- Use historical listings: `AttemptStore.load` requires a live reservation.
- Extend the delivered rail/shared panel content.
- Use the supplied glossary meanings; introduce no terminology.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_reads.py`: extend `AttemptRow` with nullable `base_commit`; extend `attempt_row` decoding without disturbing existing positional fields.
- `src/taskloop/attempt_status_store.py`: append the existing stored base column to `AttemptReads._attempts`; retain its read-only historical semantics.
- `src/taskloop/dash_model.py`: add a frozen Pydantic v2 `AttemptChange` payload with nullable `base_before` and `base_after`; attach it optionally to `AttemptBody` for agent repeats.
- `src/taskloop/dash_task.py`: `_agent_body` adds bases beside `added`; callers `build_body`, `history`, `_history`, `build_task` preserve event semantics.
- `src/taskloop/dash/static/drawer.js`: share the existing attempt-body request/cache between `pane` and `bodyTab`; render What changed above tabs, with loading/error handling and selection guards.
- `tests/dash/test_task_events.py`: add read-only projection and serialization coverage for prompt additions and base pairs, including released history.
- `tests/dash/task-events.test.js`: extend `taskEvents` with visible additions/base comparison, tab navigation, escaping and delayed-response cases.
- `src/taskloop/dash/static/result.js`: consult `prompt`; retain its complete-input view and highlighted additions.
- `src/taskloop/dash/static/event-detail.js`: consult `attemptPanel`, the shared panel integration point; preserve cause content.
- `src/taskloop/dash_composition.py`: callers `_ports.task` and `_ports.body` retain existing endpoint wiring.
- `src/taskloop/dash/static/app.js`: callers `newCard`, `start` and task-update handlers retain navigation/refresh integration.
- `tests/dash/rail.test.js`: drawer callers and the `taskEvents` runner exercise the existing panel; `tests/dash/rail.html` hosts that runner.
- `tests/dash/navigation.test.js`: consult drawer route/stale-response callers.
- `tests/dash/check-lines.test.js`: consult drawer check-activation/stale-response callers.
- `src/taskloop/prepare.py`, `src/taskloop/attempt_types.py`, `src/taskloop/attempt_store.py`, `src/taskloop/attempt_loads.py`: consult the base producer, record meaning and fenced-load restriction.
- `src/taskloop/evidence_files.py`, `tests/steps/test_dash_read.py`: consult prompt evidence ownership and the existing repeat-additions contract.

## Read list
- `src/taskloop/attempt_reads.py:50-88` — historical projection fields.
- `src/taskloop/attempt_reads.py:206-222` — row decoding.
- `src/taskloop/attempt_status_store.py:90-125` — historical listing query and caller of decoding.
- `src/taskloop/attempt_status_store.py:171-178` — immutable prompt reference.
- `src/taskloop/dash_model.py:183-224` — attempt and body response shapes.
- `src/taskloop/dash_task.py:153-202` — repeat relationship, diff and body construction.
- `src/taskloop/dash_task.py:276-366` — history and endpoint callers.
- `src/taskloop/dash/static/drawer.js:289-332` — cached body loading and selected panel.
- `src/taskloop/dash/static/result.js:137-150` — existing prompt renderer.
- `src/taskloop/dash/static/event-detail.js:57-90` — shared attempt panel and recorded cause.
- `tests/dash/test_task_events.py:1-76` — projection fixtures and read-only assertions.
- `tests/dash/task-events.test.js:1-73` — panel, selection and refresh contracts.
- `src/taskloop/dash_composition.py:39-60` — endpoint consumers.
- `src/taskloop/dash/static/app.js:328-349` — initialization/refresh callers; card caller is `newCard`.
- `tests/dash/rail.test.js:768-784` — existing browser test registration.
- `tests/dash/rail.html:1-12` — browser fixture integration.
- `tests/dash/navigation.test.js:169-200` — delayed drawer responses and refresh.
- `tests/dash/check-lines.test.js:136-155` — attempt selection while body requests run.
- `src/taskloop/prepare.py:325-336` — base selected immediately before dispatch.
- `src/taskloop/attempt_types.py:151-160` — recorded base versus predecessor end.
- `src/taskloop/attempt_store.py:69-80` — fenced-load query.
- `src/taskloop/attempt_loads.py:154-174` — live-reservation requirement.
- `src/taskloop/evidence_files.py:359-367` — retained input ownership.
- `tests/steps/test_dash_read.py:790-800` — existing prompt addition comparison.

## Contract
Intent: inspect an agent repeat. Effect: read historical rows and prompt references through their owners. Result: existing ranges plus optional `AttemptChange(base_before, base_after)` in the body response. Checks/factory commits have no change payload. No writes or Git reads.

The payload is frozen, strict and rejects extra fields. Nullable bases allow undispatched attempts. Absent payload means no repeat baseline; a null base means unavailable. Render full hashes and label equal bases unchanged.

Render the added-line count and text using existing ranges and text nodes. Empty ranges with a baseline mean zero additions; unlinked attempts have no comparison. Evidence failures retain the endpoint's unavailable result.

Use one body request per cache entry and existing refresh invalidation. Show What changed above tabs, including Lines. Late responses update only their owning cache entry and redraw only the same selection. Loading/errors preserve causes and tabs.

## Work packages
1. Extend historical base reads and body projection in `attempt_reads.py`, `attempt_status_store.py`, `dash_model.py`, `dash_task.py`; add focused assertions in `test_task_events.py`. Closes acceptance B and server-side A, including released predecessors and unchanged/null bases.
2. Extend body caching and What changed rendering in `drawer.js`; add browser assertions in `task-events.test.js` through the existing rail runner. Closes A and B at the panel, including tab changes and out-of-order responses. Keep the existing full-prompt renderer.
3. After focused dashboard verification, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Use the existing browser fixture for the JS contract; no live factory tests.

## Acceptance behaviours
- A: Selecting a repeat shows the count and text of added/replaced prompt lines relative to its linked predecessor, including historical repeats; full prompt highlighting agrees. Identical prompts show zero additions; an unlinked attempt has no comparison.
- B: Selecting a repeat shows its predecessor base followed by its own base in old-to-new order, even after release; unchanged and unavailable bases are explicit and are never replaced by end commits or current Git state.
- Both: The block remains visible across output tabs, preserves the recorded cause and single panel, escapes external text, and never displays a late response for a different selection. Non-agent panels retain their existing output.
