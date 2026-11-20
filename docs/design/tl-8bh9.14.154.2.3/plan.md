# Header
Task: tl-8bh9.14.154.2.3
Base: 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: small; one layout behaviour, stylesheet owner.
Owner decisions: none missing. Dependency: landed.
Evidence budget: 6 model calls.
Size: 13 changed files, 1 behaviour, about 30 implement model calls.

## Outcome and non-goals
Fit the dashboard and drawer to narrow screens, retaining access to columns and details. Preserve delivered reduced-motion rules and indicator words. No browser visual check or backend change.

## Settled decisions
- Test 320 CSS px, 375px and desktop width.
- Scroll the board canvas inside its viewport in both layouts.
- Stack drawer rails/content below a breakpoint; retain desktop rail widths.
- Test source and regenerated shipped CSS without a browser.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/index.html`: board panel/canvas and shell sizing; retain panel IDs.
- `src/taskloop/dash/static/app.js`: `buildBoard` and layout/update/startup callers; target inner canvas.
- `src/taskloop/dash/static/drawer.js`: `render`, `pane`, `deliveryPane`; responsive body hooks.
- `src/taskloop/dash/static/rail.js`: `rail`; bound the step navigation width.
- `src/taskloop/dash/static/taskview.js`: `taskView`, `trackerView`; stack properties sidebar.
- `src/taskloop/dash/static/accessibility.js`: `tabBar`, `tabPanel`; wrap tabs, shrink panels, preserve focus.
- `src/taskloop/dash/static/logs.js`: `render`; wrap toolbar and row tracks within available width.
- `src/taskloop/dash/static/lines.js`: `line`, `lines`; constrain event tracks and long content.
- `src/taskloop/dash/static/dash.input.css`: responsive rules/hooks.
- `src/taskloop/dash/static/dash.css`: regenerate for `index.html` and `dash_server.PAGES`.
- `tests/dash/test_narrow_width.py` (new): CSS/markup contracts using the existing dashboard pytest pattern.
- `docs/design/tl-8bh9.14.154.2.3/plan.md` (new): plan.
- `docs/design/tl-8bh9.14.154.2.3/plan-metadata.json` (new): inputs.

## Read list
- `src/taskloop/dash/static/index.html:11-40` — shell, panel and drawer.
- `src/taskloop/dash/static/dash.input.css:1-43` — stylesheet inputs and overrides.
- `src/taskloop/dash/static/dash.css:1-2` — generated artifact.
- `src/taskloop/dash/static/app.js:105-142` — canvas producer.
- `src/taskloop/dash/static/app.js:238-329` — layout/update/startup callers.
- `src/taskloop/dash/static/drawer.js:190-242` — rail and task-view callers.
- `src/taskloop/dash/static/drawer.js:259-362` — selected panes and tabs.
- `src/taskloop/dash/static/rail.js:226-242` — fixed step rail.
- `src/taskloop/dash/static/taskview.js:32-73` — properties rail producer.
- `src/taskloop/dash/static/accessibility.js:42-82` — shared tab producers.
- `src/taskloop/dash/static/logs.js:45-83` — toolbar and rows.
- `src/taskloop/dash/static/lines.js:24-98` — event pane and tracks.
- `src/taskloop/dash/static/result.js:7-105` — result pane sizing.
- `src/taskloop/dash_server.py:29-33` — stylesheet serving integration.
- `tests/dash/test_reduced_motion.py:1-39` — source/shipped CSS test pattern.
- `tests/dash/test_accessibility_markup.py:1-199` — existing markup contracts.

## Contract
Intent: open either layout/view at narrow width. Effect: constrain outer boxes, reflow rails and wrap content; contain board scrolling. Result: navigation/details remain reachable. No new typed names, states, stored fields or external effects. Preserve focus, selection and live updates.

## Work packages
1. Implement the mapped layout hooks/rules and regenerate CSS; closes A1.
2. Test source/shipped CSS for shell, both layouts, rails and tracks. Run focused isolated pytest, then `just check` and `just test` once each, last, using required tails; closes A1 verification.

## Acceptance behaviours
A1: At 320px/375px, shell/drawer fit, rails stack, controls/content wrap and both board layouts scroll inside their panel; desktop retains side-by-side rails and usable columns.
