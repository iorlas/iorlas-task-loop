# Depth
Medium: three independent behaviours—an owner-attention count, agent asks placed above other Held cards, and their questions visible on the cards. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total.

## Size
Estimated changed files: 8, including this plan, two Python source files, one JavaScript source file, two existing Python test files and two new browser-fixture files. Independent behaviours: 3. Estimated model calls for one implement attempt: 45, including focused verification and the required gates.

1. Count: a mixed board containing two agent asks, ordinary Held cards and running tasks says `2 need you`; zero asks says `0 need you`. Ordinary holds do not increase this count.
2. Placement: in both Steps and By slot layouts, agent asks precede every other Held card in their cell, even when the other holds are newer. Existing recency ordering applies within each group.
3. Question text: each ask card visibly shows its own stored explanation, including multiline question text, without opening the drawer. Ordinary Held cards retain their cause. Text containing HTML renders as text.

## Implementation
The supplied glossary defines an ask as a question requiring the owner's answer before the task can proceed. Keep asks in the existing Held column; use placement within that column to distinguish them. This task is the first ordered dashboard part and has no prerequisite on the sibling parts. Factory-fault wording, health freshness and land-card round status belong to the other parts.

Extend `dash_model.Card` with defaulted display fields for whether the current hold is an ask and its optional question text. A boolean and optional string suffice; introduce no new status vocabulary or database state. Populate these in `dash_board.card_of`, the operation already used by both the board and task detail. Identify the current agent `needs_owner` outcome through the existing owning result/disposition constant and hold facts, rather than searching display wording. Respect the effective hold's cause identity and precedence: a checks, stop or other factory hold must not acquire ask status merely because an older agent explanation exists.

For an ask, read its stored answer through `answer_read.read` and use `Answer.explanation` as the complete question text. There is no separate structured questions field in the current answer contract. Follow the existing missing/invalid/unreadable-evidence handling demonstrated by `hold_facts.explanation`; a damaged answer must not fail the board or suppress an ask identified by its current outcome. In that case show a clear question-unavailable note on the card. Read only the relevant ask answers, without transcripts, tracker discussion parsing, log parsing or new state storage. Use the same projection for the board and drawer's task card. The server already serializes Card and compares complete cards for event updates, so these fields travel through existing snapshot and stream paths.

In `app.js`, derive the `N need you` summary from current ask cards; retain the total Held count as a separate fact. Sort asks ahead of ordinary Held cards within each cell, retaining descending activity order inside each group. Use the same predicate for count, placement and card treatment. Render an ask callout with the question text through DOM text nodes, preserving line breaks and allowing wrapping without clamping away the question. Reuse existing compiled utility classes and DOM helpers; ordinary hold callouts keep their current rendering. Ensure resync, task events, removals and layout switches recompute the count and placement. Avoid adding a second scheduler, status owner or fetch path.

No rounds state is needed for owner attention. If later sibling work needs it, the supplied decision requires the owning rounds.log reader. This task introduces no rounds-state reader.

## Read list
- `src/taskloop/dash_model.py:10-47` — existing column, Card and Board contracts; add defaulted ask presentation fields.
- `src/taskloop/dash_board.py:19-62` — status-to-column mapping and existing hold timestamps.
- `src/taskloop/dash_board.py:82-126` — shared card producer and board caller; populate ask fields here.
- `src/taskloop/dash_task.py:271-289` — task-detail caller of the shared card producer and hold enrichment.
- `src/taskloop/attempt_status.py:65-105` — current view fields and the existing needs-owner constant.
- `src/taskloop/attempt_status.py:215-241` — collected execution and reason producer, including retained execution during refusal.
- `src/taskloop/attempt_status.py:380-405` — hold cause identity, stop enrichment and effective hold precedence.
- `src/taskloop/hold_status.py:48-79` — owning hold-cause derivation and completed-hold behaviour.
- `src/taskloop/answer_read.py:1-16` — owning validated stored-answer reader.
- `src/taskloop/attempt_types.py:316-335` — AttemptResult and Answer explanation contracts.
- `src/taskloop/hold_facts.py:67-74` — existing explanation reader's evidence-error handling.
- `src/taskloop/dash/static/app.js:18-128` — board cells, card rendering, ordering and summary; implement presentation here.
- `src/taskloop/dash/static/app.js:132-228` — layout switching, failures, snapshots and stream updates that must refresh attention.
- `src/taskloop/dash/static/ui.js:5-16` — shared Held column and step definitions; preserve existing columns.
- `src/taskloop/dash/static/ui.js:37-69` — safe DOM helpers and existing callout rendering.
- `src/taskloop/dash/static/index.html:19-34` — summary, layout controls and board integration points for the browser fixture.
- `src/taskloop/dash/static/api.js:13-37` — snapshot and stream boundary for browser fixture fakes.
- `src/taskloop/dash_server.py:117-128` — complete-card comparison and task event serialization.
- `src/taskloop/dash_server.py:156-159` — snapshot JSON serialization of the extended card.
- `tests/steps/test_dash_read.py:1-136` — existing semantic board/task fixtures and tests; add ask projection cases.
- `tests/cli/test_dash_server.py:17-71` — fake board/server ports; add snapshot and Hub event coverage for ask fields.
- `tests/steps/conftest.py:200-222` — existing captured-execution fixture format for evidence-backed test setup.
- `tests/dash/rail.html:1-13` — existing standalone browser-fixture integration pattern.
- `tests/dash/rail.test.js:1-24` — existing DOM assertion pattern and fixture setup.

## Verification
Extend `test_dash_read.py` with valid plan and implement needs-owner answers, effective ordinary holds, held asks after release, and missing/corrupt answer evidence. Assert the board and task-detail card agree, the question belongs to the current cause, and non-ask cards carry no question. Use semantic fixtures and the existing evidence writer; do not import old application bootstraps or add source SQL.

Extend `test_dash_server.py` to verify snapshot fields and that a question-only card change emits an updated task event. The existing `Ports` fake and Hub support this without a live factory or task tracker.

Add new `tests/dash/owner-attention.html` and `tests/dash/owner-attention.test.js`. Their existing integration points are the page's summary/board/layout elements, `app.js` startup and `api.js` fetch/EventSource boundary. Load the actual app with browser-local fake snapshot and stream responses. Exercise mixed Held cards with two asks and a newer ordinary hold, multiline and HTML-shaped question text, zero asks, both layouts, an ask moving out of Held, removal, and resync. Assert visible summary, DOM order, text safety and the question-unavailable note. Keep this fixture standalone like the existing rail fixture; introduce no browser dependency into factory runtime.

Run focused Python tests for dashboard projection and server contracts, and run the standalone browser fixture using available local browser tooling with fake data. Then run `just check` and `just test` as the supplied required gates. Do not run live/whole-suite commands beyond those supplied gates. Keep source files below 400 lines, functions below 80 lines and test files below 800 lines. A plan attempt does not execute implementation checks.
