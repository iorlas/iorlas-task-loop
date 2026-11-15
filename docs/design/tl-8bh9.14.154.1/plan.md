# Header
Task: tl-8bh9.14.154.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; three behaviours.
Owner decision missing: no. Explicitly unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 8 changed files incl. tests/artifacts; 3 behaviours; ~60 implement calls.

## Outcome and non-goals
Keyboard users can open cards, use the drawer without losing focus, and identify/select tabs. Verify markup and event wiring without a browser. Exclude rendering, reduced motion, narrow layouts and labels beside dots. Leave lines.js and ui.js untouched.

## Settled decisions
- app.js owns card creation and needs a focused edit.
- Annotate Steps/Task, Lines/Result/Prompt and Board/Logs as tabs; retain the layout button group.
- Share DOM focus/tab helpers in accessibility.js: drawer.js already has 398 lines.
- Attach panel semantics around taskView output, covering every tracker state.
- Use pytest markup contracts under tests/dash without new dependencies.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/index.html` — drawer and screen controls: dialog name, closed focus exclusion and tab/panel relationships.
- `src/taskloop/dash/static/app.js` — newCard: keyboard activation; renderBoard calls/reuses it. showScreen/start: screen tabs; start calls initDrawer and passes openDrawer to initLogs.
- `src/taskloop/dash/static/drawer.js` — initDrawer/openDrawer/reveal/closeDrawer/showError/head/render/pane: delegate focus and tab markup. Consult redraw callers loadTracker, select, bodyTab, loadDelivery, follow and onTaskMoved.
- `src/taskloop/dash/static/accessibility.js` (new) — DOM activation, dialog focus and tab helpers; callers app.js/drawer.js, served by PAGES.
- `src/taskloop/dash_server.py` — PAGES: register the new module.
- `tests/dash/test_accessibility_markup.py` (new) — markup/event-wiring contracts integrated with index.html, app.js, drawer.js, accessibility.js and asset completeness.
- `src/taskloop/dash/static/taskview.js` — taskView/trackerView: consult tracker-state panel content; no edit required.
- `src/taskloop/dash/static/logs.js` — initLogs/render: consult task-link callback, another openDrawer caller.
- `tests/dash/rail.test.js` — consult initDrawer/openDrawer/closeDrawer/onTaskMoved/taskView callers and redraw/race contracts.
- `tests/dash/owner-attention.test.js` — consult app/card/backdrop integration.
- `tests/dash/owner-attention.html` — consult fixture roots.
- `tests/cli/test_dash_server.py` — consult asset completeness and safe text rendering.
- `docs/design/tl-8bh9.14.154.1/plan.md` — retain this bounded plan.
- `docs/design/tl-8bh9.14.154.1/plan-metadata.json` — retain preparation commit and consulted paths.

## Read list
- `src/taskloop/dash/static/index.html:15-34` — screen controls, content roots and drawer shell.
- `src/taskloop/dash/static/app.js:145-235` — card content, activation producer and reuse/movement during redraw.
- `src/taskloop/dash/static/app.js:237-256` — layout group and screen switch.
- `src/taskloop/dash/static/app.js:310-343` — startup, log opener and stream redraw callers.
- `src/taskloop/dash/static/drawer.js:16-95` — initialization, opening and tracker races.
- `src/taskloop/dash/static/drawer.js:100-149` — feed redraw, error content and dismissal.
- `src/taskloop/dash/static/drawer.js:161-240` — header and outer tabs, early returns and preserved scroll.
- `src/taskloop/dash/static/drawer.js:244-270` — delivery loading and retry redraw.
- `src/taskloop/dash/static/drawer.js:291-308` — asynchronous body-tab completion.
- `src/taskloop/dash/static/drawer.js:326-398` — attempt tabs and streamed task refresh.
- `src/taskloop/dash/static/taskview.js:22-70` — retry button, taskView root and tracker-state content.
- `src/taskloop/dash/static/logs.js:15-21` — callback injection from app.start.
- `src/taskloop/dash/static/logs.js:70-78` — task-link opener with a button focus target.
- `src/taskloop/dash_server.py:27-30` — static module registration.
- `src/taskloop/dash_server.py:210-220` — static serving boundary.
- `tests/cli/test_dash_server.py:205-229` — completeness and safe DOM construction checks.
- `tests/dash/rail.test.js:190-320` — drawer callers, selections, dismissal and stale delivery responses.
- `tests/dash/rail.test.js:385-393` — taskView retry caller.
- `tests/dash/rail.test.js:430-488` — drawer and taskView usage callers.
- `tests/dash/rail.test.js:500-573` — live drawer redraw callers.
- `tests/dash/owner-attention.test.js:1-65` — existing app fixture and fake source boundaries.
- `tests/dash/owner-attention.html:8-14` — existing drawer and board fixture roots.
- `pyproject.toml:41-50` — size limits and default pytest collection roots.

## Contract
Intent: activate a card. Effect: button role, tabIndex 0 and task identity/title name; Enter/Space share the click opener, prevent Space scrolling and ignore nested controls. Result: one opening with its invoker retained.

Intent: open from a card/log button. Effect: reveal the named modal dialog, clear closed inert/aria-hidden state, exclude background focus and focus inside before detail arrives. Result: Tab/Shift+Tab stay inside; Escape/backdrop/Close use closeDrawer. Restore background access and the connected invoker's focus on close, falling back to a visible screen control. Closed descendants cannot receive focus.

Intent: redraw. Effect: restore the focused control by stable DOM identity, falling back inside the dialog. Result: tracker/body/feed/delivery/task refresh never loses focus to the body or reopens a closed dialog; preserve abort/stale-response guards.

Intent: select a tab. Effect: labelled tablist; tab buttons with stable ids, aria-controls, aria-selected and roving tabindex; active tabpanel with aria-labelledby. ArrowLeft/Right and Home/End change selection/focus within the bar; clicks agree. Result: one selection through defaults, tracker states and redraws; verification's result-only view has no dangling tab reference. Preserve screen hidden states.

Only ephemeral DOM state changes; no stored fields, backend states or external effects. Move duplicated tab construction into helpers to keep drawer.js within 400 lines.

## Work packages
1. Cards: add accessibility.js/PAGES registration, wire app.newCard and preserve renderBoard reuse; add card contracts in the new test file. Closes A1.
2. Dialog: update index.html and drawer lifecycle/redraw paths via helpers; add loading/error/refresh and dismissal contracts in that test file. Closes A2.
3. Tabs: replace drawer builders and annotate screen navigation/panels in app.js/index.html; wrap taskView content. Add selection/panel contracts, including verification/empty output. Closes A3.
4. After `just install`, run `uv run --frozen --no-sync python -I -m pytest -q tests/dash/test_accessibility_markup.py --tb=short | tail -40`. Complete edits/focused checks, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Gates exclude tests/dash. Contracts verify markup/wiring, not browser focus/rendering measurements.

## Acceptance behaviours
A1. Cards in both layouts expose focusable activation markup and Enter/Space wiring to the click opener without duplicate activation or nested-control interception.
A2. The named drawer exposes open/closed accessibility states, initial/bounded focus, redraw focus preservation and dismissal focus return, including a removed invoker.
A3. Screen/drawer tabs expose one selection, keyboard wiring and valid panels through defaults/clicks/redraw; verification has no absent-tab reference.
