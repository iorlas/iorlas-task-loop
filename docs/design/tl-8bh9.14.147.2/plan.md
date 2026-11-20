# Header
tl-8bh9.14.147.2 @ 74641862ca9f7cc6a2754ada170dc29b0d15459f
Depth: medium; 2 behaviours across 3 UI modules.
Owner decisions: none. Dependencies: landed. Evidence budget: 12 model calls.
Size: 8 changed files including tests/artifacts; 2 behaviours; ~60 implement model calls.

## Outcome and non-goals
Connect the existing checks endpoint and Result reader in the browser. Preserve agent feeds, scrolling, command expansion and navigation. No backend, schema, scheduler or shelf changes.

## Settled decisions
- .147.1 and all .153 predecessors landed; retain their behaviour.
- Reuse apiSource.feed; the first checks request omits the opaque cursor.
- Structured fields establish outcomes; unknown outcomes are not failures.
- Drawer owns Result selection and URL reporting; Lines receives a callback.
- Extract polling to feed.js to keep drawer.js within its source cap.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/lines.js` — `lines`, `line`, `fill`, `apply`, `show`, `setNote`: render literal check output and lifecycle summaries; carry an activation callback through initial and incremental rows; distinguish unavailable output from transport failure.
- `src/taskloop/dash/static/drawer.js` — `follow`, `pane`, `bodyTab`, `select`, `closeDrawer`, `onTaskMoved`: delegate polling, load selected checks output, retain attempt identity on Result activation, refresh cached running Result bodies and preserve URL notifications.
- `src/taskloop/dash/static/result.js` — `result`, `check`: accept the selected block/name, open and reveal its disclosure after asynchronous body loading; preserve existing disclosure choices otherwise.
- `src/taskloop/dash/static/feed.js` (new) — selected-attempt polling extracted from `drawer.follow`; integrates `apiSource.feed` with `lines.apply/show/setNote` and drawer refresh callbacks, including cancellation and stale-reply guards.
- `tests/dash/check-lines.test.js` (new) — fake-source browser contracts for output following and Result activation; integrated by `tests/dash/rail.test.js`.
- `tests/dash/rail.test.js` — browser contract imports and invocation: run the new contracts in both themes alongside existing agent-feed regressions.
- `docs/design/tl-8bh9.14.147.2/plan.md` — implementation and validation contract.
- `docs/design/tl-8bh9.14.147.2/plan-metadata.json` — preparation commit and consulted paths.
- Consult `apiSource.feed/body` in `api.js`; `app.js` callers `initDrawer`, `openDrawer`, `onTaskMoved`; navigation fixture callers of those exports in `navigation.test.js`; direct Lines/Result/drawer callers and `lines.test.js` imports in `rail.test.js`.
- Consult producer chain `dash_composition.feed` → `dash_task.build_feed/_checks_feed` → `EvidenceFiles.check_feed` → `check_feed.read`, plus `dash_task._checks/_checks_body` and `dash_model.FeedEvent/FeedPage/AttemptDetail/AttemptBody`; retain `dash_server._feed` cursor validation.

## Read list
- `src/taskloop/dash/static/lines.js:23-51` — initial rendering, cap and availability note.
- `src/taskloop/dash/static/lines.js:63-180` — check rendering, disclosures and incremental updates.
- `src/taskloop/dash/static/drawer.js:23-137` — initialization, selection, polling and stale-response guards.
- `src/taskloop/dash/static/drawer.js:292-399` — body cache, pane tabs and task-move refresh.
- `src/taskloop/dash/static/result.js:55-73` — check disclosure identity and remembered state.
- `src/taskloop/dash/static/result.js:101-124` — Result composition and check ordering.
- `src/taskloop/dash/static/api.js:13-24` — existing feed and body transport.
- `src/taskloop/dash/static/app.js:328-350` — drawer/navigation integration and task events.
- `src/taskloop/dash_model.py:128-189` — event, page and selected-attempt shapes.
- `src/taskloop/dash_model.py:203-210` — body response shape.
- `src/taskloop/dash_task.py:115-146` — checks feed routing and event producer.
- `src/taskloop/dash_task.py:211-225` — initial check summaries and Result producer.
- `src/taskloop/check_feed.py:54-69` — record/page identity and availability.
- `src/taskloop/check_feed.py:138-178` — lifecycle events, replacement and cursor progression.
- `src/taskloop/evidence_files.py:176-184` — owning check-evidence reader.
- `src/taskloop/dash_composition.py:56-67` — body and feed composition.
- `src/taskloop/dash_server.py:186-201` — distinct checks/agent cursor handling.
- `tests/dash/rail.test.js:1-22` — shared fixture and imports.
- `tests/dash/rail.test.js:625-672` — fake polling and agent-feed regressions.
- `tests/dash/rail.test.js:763-789` — browser contract registration and results.
- `tests/dash/rail.html:1-15` — offline browser entry point.
- `tests/dash/lines.test.js:1-18` — existing Lines fixture conventions.
- `tests/dash/navigation.test.js:1-65` — drawer source doubles and URL selection contract.

## Contract
Intent: show the selected checks attempt's output. Effect: request its existing feed with no initial cursor, then follow the returned cursor while running. Result: consume `FeedPage.events/cursor/replaced/available`; display `FeedEvent.text/name/block/state/passed/id` without deriving control state from text. Do not send the agent fallback `0:0` to checks.

Intent: maintain a coherent view. Effect: replace initial legacy summaries with the first checks page, use stable IDs for incremental updates, and clear obsolete output on `replaced`. Result: bounded live rows without duplicates; readable unavailable/reconnecting feedback; retry retains the successful cursor. Do not replace agent duration measurements with absent checks duration. Serialize polls; ignore replies after drawer/attempt changes or closure. Selection changes start a fresh request; terminal refresh performs a final checks read without creating an endless terminal poll.

Intent: inspect a check. Effect: a semantic row button passes block/name to the drawer, selects Result, reports navigation and refreshes the body. Result: retain the attempt and open the matching disclosure when available; otherwise show the existing running or unavailable Result. Preserve target identity through asynchronous rendering; consume the reveal once so later disclosure choices survive. Invalidate stale cached output on activation or check changes.

No new stored fields, backend types or outcomes. Browser-only state holds the selected check, cursor, availability and request ownership; existing enums/state fields retain their meanings.

## Work packages
1. Extract polling to new `feed.js`, wire `drawer.js` and add fake-source contracts in new `check-lines.test.js`. Closes A1.
2. Update `lines.js`, `drawer.js` and `result.js` for accessible check activation and asynchronous Result targeting. Register contracts in `rail.test.js`. Closes A2 and checks A1 preservation.
3. Run offline `tests/dash/rail.html` contracts in both themes and existing navigation contracts with fake sources. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
- A1: Selecting a checks attempt shows literal output from the feed, follows additions while running and reflects structured lifecycle outcomes; initial/replaced pages and repeated IDs do not duplicate rows. Empty, unavailable and failed reads remain understandable and recover; switching attempts or closing ignores pending replies. Scrolling, caps and agent command expansion remain intact.
- A2: Clicking or keyboard-activating a check row opens Result for the same task and attempt, updates existing navigation state and reveals the matching block/name when its body is available, including passed checks and repeated names in different blocks; asynchronous or stale bodies cannot navigate another selection.
