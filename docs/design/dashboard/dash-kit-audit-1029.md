# UX consistency and UI kit audit, 2026-10-29

Reviewers: Fable (UX consistency across 1k, 2b, 3b, 4c), ChatGPT/Codex (frontend architecture), Sonnet (inventory of installed taskloop_dash 0.23.127). Merged by Opus.

## Rule of authority
Colour/emoji contract (review 1029) > 4c > older settled mocks. 1k/2b/3b predate the contract and drift from it.

## Today's code (0.23.127, Sonnet)
- `static/index.html` 960 lines, ~500 CSS rules inline, JS inline; `live.html` 225 lines, own dark-only palette, shares nothing.
- Render: string templates, `paint()` swaps a subtree when its HTML changes; polling 2.5 s; live page long-polls.
- Duplicates: `.chip` x3, `.tag` x3, `.btn` x3, `.badge` x2, `.drawer` x2, `.lane` x7, `.askbox` x25 rules; two side panels (`#drawer`, `#bpanel`); dark token block copy-pasted twice.
- Python: JSON endpoints only (13 GET, 3 POST); views/ builders are pure. Hotspots: `poll()`, `renderTask`, `lkSend`; `views/timeline.py`, `views/roadmap.py`.

## Inconsistencies to fix (Fable)
- Blue meant selection/primary in 1k/2b/3b and "needs you" in 4c. Fix: blue = needs you only; selection and primary = ink.
- Decisions count badge red in 2b, blue in 4c. Fix: blue always.
- Four tab looks. Fix: one, 2px ink underline.
- Pill shape used for filters, answers, statuses, tags. Fix: pill = filter chip only; answers = small buttons; statuses = Tag (r4, tinted, no border).
- Green "ready" vs green "done". Fix: ready is grey ▷.
- Done marked 🚀 in strips, ✅ in tree. Fix: ✅ = bead done; 🚀 = land stage only.
- Current pass: 🔄 / ▶ / "now" + red blink. Fix: ▶ + teal dot.
- 1k replan 🧭; 3b ✏️ edit tool, 💬 note, ⚙️. Fix: 🔁, 📝, ✉️; ⚙️ dropped.
- Token warning thresholds differ per mock. Fix: one Totals component, thresholds in one place.
- Green dot = data fresh (1k/2b) and machine online (4c). Fix: freshness as text only.
- Lane bars green/amber/red, epic bar green. Fix: meters neutral ink; state shown by Tag or emoji.
- Four meter sizes, four row styles, six section header sizes, three drawer shells, button radii 6/8/99. Fix: one each.
- Hardcoded colours (ring rgba, #2563eb) break dark mode. Fix: tokens only.
- Empty states differ; no first-run state. Fix: one EmptyState.
- 4c dock shows a one-tap "↩️ Send back", which would send an empty send-back. Fix: Send back opens the ask (text required).
- First daily hit: blue everywhere in the drawer would read as "needs you".

## Roll-up placement (Fable)
Cause: the title does not stretch, so `margin-left:auto` throws the roll-up to the far edge. Also, on an open branch the roll-up repeats the rows under it. Fix: roll-up right after the title, shown only on a collapsed branch; parents get ▸/▾.

## Component set (Fable + Codex merged, 15)
Tokens · Button · FilterChips (with All) · Tag · CountBadge · Tabs · Panel + SectionHeader · Marker · Meter · BeadRow · SlotCard (= Totals + StageGrid + Feed) · AskCard · Drawer · Message line · Overlays (Popover, Toast, EmptyState).
- Machines and epics both use FilterChips: All first, text only, no count.
- Tree, ranked list, drawer "Waits for / Unblocks" and Home lists all use BeadRow.

## Frontend approach (Codex)
- ❌ vanilla template strings: re-render loses open lists, drafts, focus, scroll (seen in today's `paint()` and in mock 3b).
- ❌ native Web Components: lifecycle plumbing, still no reconciliation.
- ✅ Preact + HTM vendored as one checked-in file, pinned with hash, no build step; keyed by bead/run/event id; UI state (open ids, drafts, selection) kept apart from server snapshots.
- Runner-up lit-html. ❌ Alpine. Terminal tail stays imperative.
- Layout: `static/css/{tokens,kit,layout}.css`, `static/js/{app,api,state,format,ui,domain}.js` + `views/`, `vendor/ui-runtime.js`; `http.py` gets an asset allowlist.
- Keep honest: `components.html` sheet rendering the real components with fixtures; browser tests that open state, drafts, focus and scroll survive updates; budget 100 KB gzip JS+CSS.
- Biggest risk: putting engine meaning into components. Park/stop/restart/ask-back need server contracts first; today `http.py` only has answer/withdraw/look writes.
