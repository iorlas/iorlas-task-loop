# Header
Task: tl-8bh9.14.153.3; base: d85192c086d24384fbd87f5192c7552e7cdf12b3
Depth: medium
Reason: 2 behaviours across 3 named modules.
Owner decision: none; unlanded dependency: none.
Evidence: 12 model calls total. Size: 9 changed files, 2 independent behaviours, about 60 implement calls.

## Outcome and non-goals
Selection and tabs already work in memory; the URL owns none of that state. Add browser restoration and correct the count without changing Lines display, focus, verification results, delivery details or tracker loading. No database, scheduling or API changes. taskview.js needs consultation only: the count belongs to drawer.renderContent.

## Settled decisions
- The fragment owns selection; the drawer owns caches, disclosure and scroll.
- Canonical attempt URLs are `#<encoded-task-id>/<step>/<n>/<tab>`; reuse step identifiers and Lines/Result/Prompt identifiers already in the UI.
- Final `task` selects Task view, retaining attempt identity. `#<id>/task` covers no attempts, `#<id>/land` delivery, `#<id>` defaults, empty hash closure.
- User opening, closing, attempt selection and tab changes create history entries. Applying a URL never pushes another entry; resolving defaults or repairing an invalid selection replaces the current entry.
- New navigation.js owns the codec, history and extracted drawer selection resolution.
- Count all non-verification attempt rows, including checks, repeats and past attempts; keep verification rows available for selection and rendering. Preserve the plain Steps label when the count is zero.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/navigation.js` (new): codec/history/selection resolver; integrate app.start and drawer notifications using existing vocabularies.
- `src/taskloop/dash/static/app.js`: start/newCard/initLogs/onTaskMoved; initialize routing, restore the fragment and share board/log opening.
- `src/taskloop/dash/static/drawer.js`: initDrawer/openDrawer/closeDrawer/select/tabOf/taskTabOpen/renderContent/pane/onTaskMoved; apply/report URL selection, filter count; extract defaults/tab vocabulary to stay within 400 lines.
- `src/taskloop/dash_server.py`: PAGES; serve navigation.js through the existing static allowlist.
- `tests/dash/navigation.test.js` (new): fake-source integration through initDrawer/openDrawer/closeDrawer/onTaskMoved and the history controller.
- `tests/dash/navigation.html` (new): fixture for navigation.test.js, following rail.html.
- `tests/dash/rail.test.js`: landSelection Steps label correction.
- Consult `src/taskloop/dash/static/logs.js`: initLogs and render's openTask callback; preserve log-originated opening.
- Consult `src/taskloop/dash/static/rail.js`: rail/groupRows/row/verificationButton/restart/causeLink/landEvent/landRow callbacks all reach drawer.select; every route must retain that shared selection path.
- Consult `src/taskloop/dash_task.py` history/_history/build_task and `src/taskloop/dash_model.py` AttemptDetail: mixed rows and step/n identity.

## Read list
- `src/taskloop/dash/static/app.js:187-196` — card opener.
- `src/taskloop/dash/static/app.js:281-355` — resync, log opening, startup and live updates.
- `src/taskloop/dash/static/drawer.js:17-98` — state, selection, async detail/tracker reads and defaults.
- `src/taskloop/dash/static/drawer.js:147-245` — closure, view tabs, count and rail integration.
- `src/taskloop/dash/static/drawer.js:293-397` — body tabs, cause navigation and live refresh.
- `src/taskloop/dash/static/taskview.js:33-45` — Task view integration and loading states.
- `src/taskloop/dash/static/logs.js:17-25` — opener registration.
- `src/taskloop/dash/static/logs.js:66-80` — log task link caller.
- `src/taskloop/dash/static/rail.js:73-155` — verification, restart, cause-link and attempt callbacks.
- `src/taskloop/dash/static/rail.js:228-284` — delivery callbacks and selected-row expansion.
- `src/taskloop/dash/static/ui.js:17-20` — step and verification identifiers.
- `src/taskloop/dash/static/accessibility.js:23-35` — tab activation behaviour.
- `src/taskloop/dash/static/accessibility.js:110-143` — dialog opening/closure and focus preservation.
- `src/taskloop/dash/static/api.js:10-23` — detail, tracker, body and feed read ports.
- `src/taskloop/dash/static/index.html:1-10` — application entry module.
- `src/taskloop/dash_server.py:28-32` — static asset allowlist.
- `src/taskloop/dash_model.py:172-188` — attempt identity and verification rows.
- `src/taskloop/dash_task.py:265-299` — verification and mixed history production.
- `src/taskloop/dash_task.py:321-343` — task detail assembly.
- `tests/dash/rail.test.js:1-30` — fake-source/browser helpers.
- `tests/dash/rail.test.js:205-242` — drawer selection regression.
- `tests/dash/rail.test.js:287-320` — delivery tab/count expectation.
- `tests/dash/rail.html:1-14` — isolated fixture integration.
- `tests/dash/test_accessibility_markup.py:77-130` — public drawer/focus/tab structural contracts.
- `tests/cli/test_dash_server.py:219-223` — complete static module serving check.

## Contract
Intent: decode a documented discriminated JS shape for closed, task-default, attempt, Task view or delivery, with closed constants and existing vocabularies. One codec validates encoding, step, positive integer n and tab. Malformed fragments close safely; absent attempts fall back to the task default; verification resolves to Result. Missing tasks retain the error drawer and close action.

Effect: app initializes one controller listening to hashchange/popstate, deduplicating locations and applying initial state without a board card. Add an optional drawer selection observer and openDrawer request argument; preserve existing fixture calls. Resolve after detail loads, before rendering selection; reuse detail for same-task changes. User actions push history; URL application cannot push; defaults use replaceState. Close button, backdrop and Escape share closeDrawer.

Result: URL and selection agree. Guard awaited reads so older work cannot render, follow or write history after navigation/closure. onTaskMoved preserves valid explicit selection; replace the fragment if refresh changes it. Body/feed/tracker replies and redraws add no history. Preserve focus, rail expansion and scroll. No server fields or API routes change.

## Work packages
1. Add navigation.js/static registration; wire app and drawer, extracting defaults to keep drawer within its cap. Add navigation.html/navigation.test.js fake-source coverage for A1–A4.
2. Filter renderContent's label with VERIFY.id; update rail.test.js's delivery expectation. Cover mixed, repeated, historical and empty rows in navigation.test.js for A5.
3. Exercise navigation and existing rail/Lines browser contracts in both themes, plus focused static-serving/accessibility checks through the allowed isolated pytest command. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; preserve exit results.

## Acceptance behaviours
A1. Card/log opening, attempt and Lines/Result/Prompt/Task selection update the fragment; reload restores it, including past attempts and verification Result.
A2. Back/Forward restore tasks, attempts, tabs and closure without adding entries; close button, backdrop and Escape share closed URL state.
A3. Direct URLs work without a board card; empty tasks and delivery restore; malformed fragments and missing tasks/attempts resolve safely as specified.
A4. Delayed reads/live refresh cannot overwrite newer selection or reopen closure; redraws preserve selection and history length.
A5. Steps counts checks, repeats and past attempts but excludes verification; zero stays plain Steps and verification remains reachable.
