# Header
Task: tl-8bh9.14.153.1.2.2
Base: 552de071cd65da4b6be5425104c2458e5fc83091
Depth: medium; 2 behaviours: folding/expansion, jump.
Owner decisions: none. Unlanded dependencies: none.
Evidence budget: 12 model calls.
Size: 7 files incl. tests/artifacts, 2 behaviours, ~35 implement calls.

## Outcome and non-goals
Make long messages readable in the Lines tab without losing access to their full text, and let the person reach the newest displayed event from any scroll position. Existing complete finished feeds, live retention, event ordering and scroll-position preservation remain the surrounding contract. No feed API, persistence, tracker, harness or other tab changes.

## Settled decisions
- Fold message content to eight rendered lines; preserve whitespace and wrap long words. Expansion reveals the complete original text.
- Use a native button with an accessible name and expansion state for message disclosure.
- Keep Jump to latest reachable outside the scrolling event content; it targets the current displayed list, including finished attempts.
- Reuse the existing Lines scroll container and bottom-following behaviour; jumping uses an immediate scroll.
- Add interaction coverage through the existing page-test entry point. A real browser on the devbox is not a prerequisite.
- Keep new page cases in a separate module because rail.test.js is already 736 lines.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/lines.js` — `lines`, `fill`, `show`, `atBottom`: render message disclosure and a reachable jump button; retain `#tail`, `#lines`, row identities and live update semantics.
- `src/taskloop/dash/static/dash.input.css` — message styles: eight-line folded presentation and expanded presentation, with literal classes discoverable by the existing stylesheet build.
- `src/taskloop/dash/static/dash.css` — regenerate the shipped stylesheet used by the page and test fixture.
- `tests/dash/lines.test.js` (new) — exported interaction cases, integrated into the existing `rail.test.js` runner; mount the real `lines` renderer and exercise `apply`/`show` updates.
- `tests/dash/rail.test.js` — module imports and test loop: invoke the new cases and keep the displayed contract count accurate; existing Lines callers are `eventIndicators`, `vocabulary`, `feedDisplay` and `liveFeedDisplay`.
- `src/taskloop/dash/static/drawer.js` (consult) — `follow`, `renderContent`, `pane`: callers of `apply`, `show`, `setNote`, `touchQuiet`, `atBottom` and `lines`; preserve replacement redraw and scroll restoration.
- `src/taskloop/dash/static/api.js` (consult) — `apiSource.feed`: page feed source; no interchange change.
- `src/taskloop/dash_model.py` (consult) — `FeedEvent`, `FeedPage`: message text, identity and feed replacement producer contract.
- `src/taskloop/dash/static/ui.js` (consult) — `el`, `$`, `FEED_LIMIT`: existing DOM helpers and retention constant.
- `tests/dash/rail.html` (consult) — existing fixture loads the shipped CSS and page-test runner.
- `tests/dash/test_reduced_motion.py` (consult) — existing source/shipped stylesheet motion contract.
- `docs/design/tl-8bh9.14.153.1.2.2/plan.md` (new) — bounded implementation scope.
- `docs/design/tl-8bh9.14.153.1.2.2/plan-metadata.json` (new) — consulted-path metadata.

## Read list
- `src/taskloop/dash/static/lines.js:21-45` — initial view, scroll container and feed note.
- `src/taskloop/dash/static/lines.js:56-108` — row construction and message content branch.
- `src/taskloop/dash/static/lines.js:110-140` — model updates, row replacement, retention and following.
- `src/taskloop/dash/static/drawer.js:105-131` — feed producer integration and redraw conditions.
- `src/taskloop/dash/static/drawer.js:182-200` — snapshot of scroll position before redraw.
- `src/taskloop/dash/static/drawer.js:237-245` — restoration after mounting the Lines view.
- `src/taskloop/dash/static/drawer.js:331-364` — selected attempt pane and Lines caller.
- `src/taskloop/dash/static/ui.js:38-45` — feed cap and DOM construction helpers.
- `src/taskloop/dash/static/api.js:14-24` — feed request boundary.
- `src/taskloop/dash_model.py:127-155` — message and feed-page producer fields.
- `src/taskloop/dash/static/dash.input.css:1-43` — scan sources, theme and motion styles.
- `src/taskloop/dash/static/dash.css:1-2` — generated stylesheet consumed by the page fixture.
- `tests/dash/rail.html:1-13` — shipped stylesheet and runner integration.
- `tests/dash/rail.test.js:1-35` — imports, DOM fixture and assertion pattern.
- `tests/dash/rail.test.js:543-579` — existing feed display regression coverage.
- `tests/dash/rail.test.js:581-624` — live polling and finished-feed restoration coverage.
- `tests/dash/rail.test.js:717-736` — case registration and pass/fail reporting.
- `tests/dash/test_reduced_motion.py:1-20` — stylesheet motion contract.

## Contract
Message intent: read a long message, then expand it. Effect: change only its presentation and disclosure state; retain the complete text as text content, never interpreted markup. Result: the folded content shows at most eight rendered lines, while expansion exposes every line. Short messages remain fully readable. Initial rendering and incremental insertion use the same message presentation.

Jump intent: activate Jump to latest. Effect: set the current `#tail` scroll position to its end without changing the selected attempt, feed contents or cursor. Result: the newest displayed event is visible, and subsequent arrivals follow the end through the existing `atBottom` logic. Empty lists permit a harmless activation.

No new typed API names, stored fields or workflow states. Disclosure is local view state; feed events retain the `FeedEvent` shape. The Lines view may gain a flex wrapper holding the jump control and existing `#tail`; drawer scroll restoration continues to address `#tail` directly. Appending another event must not replace unrelated expanded rows.

## Work packages
1. `lines.js`, `dash.input.css`, `dash.css`: add message folding and disclosure; regenerate shipped CSS. Close A1 using short, eight-line, nine-line, wrapped and whitespace-preserving content, including incremental messages.
2. `lines.js`: place the jump control above the scrolling list, targeting the existing scroll container. Close A2 for finished and running attempts while preserving automatic following and the person's position before activation.
3. New `tests/dash/lines.test.js`, integrated in `rail.test.js`: exercise A1 and A2 through the real page components; give fixtures a bounded height for overflow and assert rendered height/visibility as well as button state. Reuse existing feed regressions for retention and replacement. Keep the shared runner below its cap. Run the focused page cases through the existing page-test mechanism; report any execution limitation accurately. At the end of the implement attempt run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each.

## Acceptance behaviours
- A1: Messages exceeding eight rendered lines initially show eight lines; activating expansion reveals all text. Messages of eight lines or fewer remain readable in full. This holds for initial and newly arriving messages, including wrapped text and preserved whitespace.
- A2: From an earlier scroll position, Jump to latest makes the newest displayed event visible in running and finished feeds. Empty feeds remain usable; a subsequent live event follows the end after jumping, while arrivals before activation preserve the person's earlier position.
