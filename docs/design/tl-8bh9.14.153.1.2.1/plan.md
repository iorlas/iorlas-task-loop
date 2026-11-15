# Header
Task: tl-8bh9.14.153.1.2.1
Base: b0d1f292baca305bb8a5e00926a5d24250c58782
Depth: medium; two feed display behaviours.
Decisions: settled. Unlanded dependencies: none.
Evidence budget: 12 model calls.
Size: 4 changed files including tests/artifacts; 2 behaviours; 35 implement model calls.

## Outcome and non-goals
Make the Lines view use the attempt state consistently for initial rendering, updates and its feed note. The backend already provides complete finished feeds; the remaining work is page presentation and regression coverage. Folding and jump-to-latest interactions belong to the sibling task. No backend, schema, polling protocol or styling changes are needed.

## Settled decisions
- Use the existing attempt state: only `running` receives the display cap.
- The live cap includes the synthetic step row; the note is outside the event list.
- Keep every supplied finished event in its existing order, including the step marker.
- Preserve replacement by event ID, pause information, empty feeds, reconnect errors and scroll following.
- Use the existing page fixture; no browser installation or new test runner.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/lines.js` — `lines`, `setNote`, `apply`, `show`: make initial selection, note wording and incremental retention depend on attempt state; limit live DOM rows even when initial detail contains a step marker plus 20 events.
- `src/taskloop/dash/static/drawer.js` — consult `pane`, `follow`, `onTaskMoved`, `openDrawer`: production callers render initial detail, apply/show batches, and reload full detail when an attempt ends; retain this integration.
- `src/taskloop/dash/static/ui.js` — consult `FEED_LIMIT`, `el`, `$`: reuse the existing limit and DOM helpers.
- `src/taskloop/dash/static/api.js` — consult `apiSource.detail` and `apiSource.feed`: retain the detail and cursor boundaries.
- `src/taskloop/dash_task.py` — consult `_agent`, `build_feed`: complete finished reads and bounded live reads are delivered; `_agent` prepends the step marker.
- `tests/dash/rail.test.js` — extend existing `vocabulary` and `liveDurations` page checks and their registered execution: assert row identities/counts, notes, update replacement and finished-detail refresh through the existing drawer fixture.
- `tests/dash/rail.html` — consult the existing DOM fixture and module entry point.
- `tests/steps/test_dash_read.py` — consult the existing complete-versus-bounded feed regression; preserve its contract.
- `docs/design/tl-8bh9.14.153.1.2.1/plan.md` — new implementation plan.
- `docs/design/tl-8bh9.14.153.1.2.1/plan-metadata.json` — new preparation commit and consulted-path record.

## Read list
- `src/taskloop/dash/static/lines.js:23-45` — initial rows and feed note.
- `src/taskloop/dash/static/lines.js:110-140` — event replacement, retention and DOM updates.
- `src/taskloop/dash/static/drawer.js:57-76` — initial detail and selection.
- `src/taskloop/dash/static/drawer.js:103-131` — follow batches and replacement rendering.
- `src/taskloop/dash/static/drawer.js:331-399` — Lines caller and terminal-detail refresh.
- `src/taskloop/dash/static/ui.js:38-45` — shared cap and DOM helpers.
- `src/taskloop/dash/static/api.js:13-24` — detail and follow producers.
- `src/taskloop/dash_task.py:87-107` — feed endpoint selection.
- `src/taskloop/dash_task.py:126-143` — detail state, complete feed and step marker.
- `tests/dash/rail.test.js:16-28` — fixture and attempt builders.
- `tests/dash/rail.test.js:368-380` — existing feed vocabulary assertions.
- `tests/dash/rail.test.js:491-577` — controlled polling and finished-attempt fixtures.
- `tests/dash/rail.test.js:579-588` — page-check registration.
- `tests/dash/rail.html:7-11` — fixture elements and module integration.
- `tests/steps/test_dash_read.py:387-418` — delivered backend boundary regression.

## Contract
Intent: render one attempt's supplied feed using its existing `state`, `feed` and event IDs. Effect: select the last `FEED_LIMIT` rows only while running; render all supplied rows otherwise. Apply the same state condition when retaining model events and pruning incremental DOM rows. Result: the DOM and feed note describe the same retention policy. Finished wording describes retained lines without promising events absent from the supplied feed.

Intent: replace a running command's row with its matching completed event. Effect: preserve ID replacement before enforcing the live cap; preserve the existing scroll adjustment and pause calculation using the preceding event where available. Result: updates do not duplicate rows or exceed the live cap.

Intent: observe attempt completion. Effect: use the existing drawer detail refresh, which supplies the complete finished feed, rather than reconstructing omitted events from the live tail. Result: historical rows reappear when the attempt ends. No new typed names, stored fields, states or external effects.

## Work packages
1. Update `lines.js` initial selection, feed note and incremental paths together. Close A1 and A2 without changing the drawer/backend contracts.
2. Extend existing checks in `rail.test.js` with more than 20 identifiable events, a step marker, successful and failed terminal states, live batch updates, matching-ID replacement, and completion refresh. Assert earliest/latest row identities as well as counts and truthful notes; close A1 and A2. Include zero and exactly-20 boundary cases.
3. Validate the focused existing page contracts and backend regression. The HTML fixture requires a browser, unavailable on this devbox: retain its executable assertions and explicitly report that runtime limitation, without claiming browser execution. Run the available focused Python page checks and `tests/steps/test_dash_read.py` through the permitted focused pytest command after installation. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
- A1: Opening or refreshing a finished attempt displays every retained supplied event in order, including events older than the live tail; its note does not claim a 20-row limit.
- A2: A running attempt displays at most the latest 20 event rows on initial render, replacement render and incremental updates, including any step marker in that count; updating an existing event preserves one row, and finishing restores the complete supplied history.
