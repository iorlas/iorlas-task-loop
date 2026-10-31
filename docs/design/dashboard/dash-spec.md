# task-loop dashboard: implementation spec

Status: draft, 2026-10-29, awaiting the owner's review. The owner settled every view in rounds 1–9 (phone v2: "Phone view v2 is ok. Write the full dashboard spec now"); this file consolidates those decisions and has not been approved as a whole.

Audience: the task-loop implementation session. Read this file first. Use the mocks to see the result, and use this spec as the rule.

## 0. Sources and authority

Order of authority, highest first:
1. This spec.
2. `dash-decisions.md` (owner decisions, newest first).
3. The settled mocks listed below.
4. Older mocks. These are history only and must not be copied.

| area | canonical mock | notes |
|---|---|---|
| shell, Board (Flow + Goals), Floor, drawer, Decisions, Lanes, projects → epics | `dash-round-8b.html` | desktop |
| Decisions tab layout | `dash-round-7b.html` (same in 8b) | |
| drawer (bead page) | round 3b drawer, as used in `dash-round-8b.html` | |
| one line per bead, comeback | `dash-round-6b.html` | Floor details |
| phone | `dash-round-9.html` (frames of `dash-round-9-app.html`) | below 600 px |
| UI kit, consistency fixes | `dash-kit-audit-1029.md` | 15 components + BeadLine |
| colour contract, emoji contract | `dash-review-whole-1029.md` | |
| operator model, ask lifecycle | `dash-operator-model.md` | context only: a draft the owner never decided. Its rules count only where an approved mock shows them (7, 7b, 8b showed the make-it-stick choices, ledger chips, ADR reuse, Seen, stop chips). |
| research | `dash-research-fleets-2.html`, `research-farms.md` | context only |

The mock data is invented: bead ids, lanes, numbers, ADR texts. The code must never hard-code any of it.

Orchestrator defaults: these rules have no owner decision behind them. They are marked "(default)" where they appear, and the owner may change them freely.
- Floor zoom of 2/4/8 h.
- Backlog shows 5 beads, then "+N more".
- Backlog and Done fold between 600 and 900 px.
- Stale thresholds of 30 s and 5 min.
- Stuck also fires on "no commits for N min".
- Prune is offered after 30 days with 0 reuses.
- The snapshot returns 304 by version, and the routes are named `/api/*`.

## 1. Who uses it and for what

There is one person who wears two hats, split by how often each job comes up:

| hat | job | cadence | where |
|---|---|---|---|
| operator | run the line: answer asks, approve looks, unstick, watch quota | continuous, often from the phone | Board, Decisions, drawer, Lanes |
| operator | fix: a stuck or silent bead, a tool failure, a locked lane | a few times a day to a few times a week | Floor, drawer |
| engineer | improve the factory: turn ask clusters into decisions, config and prompt fixes | weekly sitting | Decisions (learning block, Ledger) |

There is no verbosity slider and there are no per-role views. Each view answers one question:

| tab | question | altitude |
|---|---|---|
| 🗂️ Board | where is each bead, what needs me | high: Kanban (Flow) or Goals tree |
| 🏭 Floor | what is each slot doing, where is it stuck | detailed: time × slots |
| 🙋 Decisions | what waits on me, is the factory learning | asks and their outcomes |
| 🎛 Lanes | do we have capacity | quota per subscription |

Asks are a smell. Each one costs the owner time and may point to a missing decision, a weak bead text or a gap in the environment. The dashboard therefore answers fast and then offers to make the answer durable.

## 2. Global rules

### 2.1 Shell
- **Desktop.** The top bar holds the brand, the tabs (🗂️ Board · 🏭 Floor · 🙋 Decisions · 🎛 Lanes) and, on the right, the lane rings for lanes that are not fine, "N lanes ▾" (opens Lanes) and a refresh button that shows the data age in seconds inside a circle.
- **Phone, below 600 px.** It has its own shell; see §9.
- **Count badges.** Floor shows the number of unacknowledged stuck beads (red). Decisions shows the number of open asks (blue). No other tab carries a badge.
- **Browser tab title.** It carries the number of open asks plus stuck beads, e.g. "(3) task-loop".
- **Bead ids.** One format everywhere: the bd id as bd prints it (e.g. `fld.27`), prefixed with the project only when All projects is selected.
- **Selection.** Only the selected bead is marked (ink outline), once per view. Nothing else lights up with it; the owner found cascading highlights confusing (4c).
- **No "since HH:MM" banner** (4g). The morning report replaces it later (§14).
- **Drawer behaviour.** Any bead anywhere (card, tree row, bar, ledger id, lane chip) opens the bead drawer (§6). The drawer is the bead page; there is no separate bead page. A deep link reopens it after a reload.
- **Deep link format.** `#<tab>~<view option>~<bead>~<drawer tab>`, e.g. `#board~~fld.27~p1`. UI state that must survive a refresh: the tab, the Board mode, the filters, the open drawer, the drawer tab, open folds, and typed drafts.

### 2.2 Projects, epics, beads
- **Projects.** A project is one registered repo. The project chips (All first) are hidden when only one project is registered.
- **Epics.** An epic is the bd parent or epic of a bead. The epic chips appear only after one project is picked, because an epic belongs to one project. Each epic chip carries a small done-share meter.
- **Machines.** The machine chips (All first) list one chip per machine with its own name and icon. Machines are open-ended: Mac, devbox, Docker, remote.
- **One filter pattern.** All filter chips follow it: "All" first, text only, no counts. A filter with one possible value is hidden.
- **Project names in the UI.** With All projects selected, every card, tree row and drawer header names the project.
- **Universal UI.** The skill is universal. No project-specific words appear in the UI: no "rooms", no lifesim terms. The UI terms are project, epic, bead, slot, lane, pass, stage, ask, look.

### 2.3 Colour contract (one meaning per colour)
| token | meaning | never used for |
|---|---|---|
| teal `--run` | live: running now | selection |
| red `--red` | trouble: stuck, worker exited, tokens ≥ 4× usual | needs-you, lane bars |
| amber `--amb` | watch: tokens ≥ 2×, send-backs, lane running out | |
| blue `--you` | needs you: open ask, your look | selection, primary buttons |
| ink `--ink` | selection, primary buttons, active tab underline | |
| green `--ok` | done, good trend | "ready" (ready is grey ▷) |
| violet | tokens (cell tint by absolute token bands) | |

- **Palette.** Light = "Current" cream; dark = "Current" dark. The tokens are in `dash-round-8b.html :root`, with AA contrast fixed. Every colour comes from a token; no hard-coded hex or rgba appears in components.
- **Meters.** Meters are neutral ink. State is shown by a Tag or a marker, never by bar colour, except for the lane bars (§8), which use the status colours by design.
- **Data freshness.** It is shown as text or as the refresh circle, never as a green dot.

### 2.4 Markers (emoji contract)
| marker | meaning |
|---|---|
| ▶ | running (plus a teal dot on the current pass) |
| 🙋 | asks you (blocking) / your look |
| ⏩ | asked, not blocking: went on with a default |
| ⏸️ | parked: by an ask, by the owner, or by a lane running out. The parked line says which. |
| ▷ | ready (grey) |
| ⏳ | blocked by another bead |
| ✅ | bead done |
| 🚀 | land stage only |
| 🛑 | stuck: silent past the stage limit, or the same check failed 3× |
| 💀 | worker exited unexpectedly |
| 🔁 | replan / send-back pass ending |
| ↩️ | test failed: back to write |
| ✉️ | note to the worker |
| 💬 | ask back |
| 📝 | Edit tool (tool icons never reuse stage emoji) |
| 🎯 | goal (a bead other beads exist to serve) |

### 2.5 Type, boxes, motion
- **Type.** Cards and rows use one font weight. Bold is kept for headings and a tag's dynamic value. The owner rejected "all text is bold".
- **Boxes.** Use few: cards on the Board, ask, look and stuck boxes in the drawer, and the learning panel. Everything else uses rules (lines) and spacing.
- **Motion.** Motion carries meaning only:
  - a pulse on the live segment, the live dot and the current stage cell;
  - new terminal lines fade in;
  - the drawer slides in;
  - a card collapses out when it is answered or approved.
  `prefers-reduced-motion` turns all of it off.
- **Text size.** The minimum is 12 px on the phone and 11 px on desktop, except for axis labels.

### 2.6 Tokens and time
- **Tokens only.** Dollars are never shown.
- **Fresh tokens.** "Fresh" = input − cached + output, as in today's cockpit layer.
- **Usual.** "Usual" is the median per model lane, with its sample size shown. It is advisory (grey) until the lane has 5 landed beads.
- **Warnings.** At ≥ 2× usual tokens the bead total turns amber; at ≥ 4× it turns red.
- **Cell tint.** The violet cell tint uses fixed absolute token bands, never a share of the bead (a share would recolour old cells when a new pass arrives).
- **Silence limits.** These are fixed per stage. A stage silent past its limit makes the bead 🛑 stuck. The default limits live in one place in config.

## 3. Board: Flow (Kanban)

- **Columns**, in the order work moves: Backlog · Working · Has questions · AI review · Your look · Landing · Done.
- **Columns are derived** from engine state and never dragged. The derivation:

| column | engine state |
|---|---|
| Backlog | open bead, not claimed by a slot. Ready (▷) or blocked (⏳ waits for an open bead). |
| Working | claimed; current step reset / plan / replan / write / checks / fix round; also 🛑 stuck, and 💀 exited while still claimed (an exited run that is not claimed shows 💀 in Backlog) |
| Has questions | open ask on the bead (blocking or not). A blocking ask has parked the bead and freed the slot. |
| AI review | current step review or verify |
| Your look | owner look pending (screens ready) |
| Landing | land step: lock, rebase, gate, push |
| Done | closed today (landed or closed) |

- **Card anatomy:**
  - a meta line: project (with All projects only) · bead id · slot · age;
  - the title;
  - one status line. For a running bead it is the last action (the newest message or tool call), with the time running shown as the age. It is blue for needs-you and red for trouble, starts with ⏩ for a non-blocking ask, and for a stuck bead says "why? ?" until a cause is picked;
  - stage dots: one per stage (plan, write, test, review, look, land), grey when done, teal pulsing when current, blue when waiting on you, red when stuck;
  - ↻N loops, amber, and red at > 2.
  A left rule is blue for needs-you and red for trouble.
- **Backlog column.** It shows the first 5 beads, then "+N more" (default). Done shows compact rows. A ready bead that no slot has picked up shows why it waits: lane out until HH:MM, its area is busy, it is held, or no slot fits. Today's Roadmap "Held back" logic supplies this.
- **Wide screens.** All columns are visible; they shrink, and none scrolls sideways. Between 600 and 900 px, Backlog and Done fold to their headers (default).

### 3.1 Board: Goals (tree)
- **Toggle.** A Flow · Goals segmented toggle sits at the left of the filter bar. The same filters apply to both.
- **Tree shape.** Roots are beads that no open bead waits on. Under each root is what it needs (bd `blocks` / needs dependencies), recursively. The bottom of each branch is what runs now.
- **Row:**
  - fold ▸/▾ on parents;
  - a marker;
  - the bead id;
  - the title;
  - the slot or status;
  - on a collapsed branch only, a roll-up right after the title: ▶n 🙋n 🛑n ✅n.
- **Shared children.** A bead needed by two parents is shown once in full; other places show a ⤴ stub that links to it.
- **Sort.** Within a level the order is stuck, ask, you, run, blocked, ready, done.

## 4. Floor: slot tracks

- **Rows.** One row per slot, grouped by machine. Each group header carries its icon and name; each row label shows the slot name and lane.
- **The bead line.** Each bead on a slot is one continuous line, cut into stage segments by 1 px inner rules, never by rounded corners between parts. The line has radius 6 at its outer ends only. Above the line sit the bead id and title, plus ↻N. When the line starts before the visible area, the name sticks to the left edge, so it stays on screen while the bar runs past the edge (decision 5).
- **Segment kinds:**

| kind | look |
|---|---|
| stage | neutral fill, label when it fits |
| failed test | red tint |
| live | teal tint, pulsing, teal outline on the whole line |
| asking you | blue hatch, blue outline |
| answered / parked by a lane | grey hatch |
| your look | blue tint |
| stuck | red tint, red outline; label "🛑 stuck · <cause or ?>" |
| projected | white with a border, on the hatched future side |
| waiting for a slot | dotted stretch, in the drawer trace only (the Floor shows the comeback instead) |

- **Comeback.** A parked bead resumed in another slot shows as two pieces, one per slot. A dashed curve joins the end of the first piece to the start of the second. The first piece ends with "→ <new slot>"; the second starts with "↪ … from <old slot>".
- **Time axis.** Hours back, "now" as a vertical line, and the future hatched. A lane wall (e.g. "⛔ codex quota ends") is labelled on the axis row and never over names. Zoom offers 2 h, 4 h and 8 h (default); the view opens scrolled to now.
- **Idle slot.** It shows a dotted "idle · no <lane> work ready" span after now. It shows no "next" (decision 1e).
- **Stuck.** The line keeps a red outline until a cause is picked or 👁 Seen is pressed. Seen fades the outline and mutes the alert until something changes.
- **Legend.** One line above the tracks.

## 5. Asks

**Owner ruling, 2026-10-26 (bead tl-7y6.4.11):** agents assume rather than ask. An ask is allowed only when the step cannot be undone. Agents record each assumption instead, as a typed record. The dashboard shows a count of assumptions per bead (drawer header, next to ⚠N) and in total, and never shows a text list. Everything below applies to the asks that remain.

### 5.1 The ask card (in the drawer and in Decisions › Waiting)
- **Header:**
  - 🙋 "Blocking · bead parked, slot freed", or ⏩ "Not blocking · went on with <default>";
  - on the right, the cause declared by the agent: requirement gap / decision / environment / process / unknown. The owner can correct it (✎).
- **Body.** It is a decision card, not a chat:
  - a one-line question;
  - 1–3 "why" bullets, with file references;
  - 2–4 options, each with a one-line consequence and exactly one marked recommended (or the running default for a non-blocking ask);
  - pictures for looks;
  - an optional ASCII diagram of 8 lines or fewer.
- **Validation.** `tl ask` rejects an ask that lacks any of these.
- **Answer bar.** Tapping an option sends it at once, with a 5 s Undo. A free-text field is always there: "Ask back, or answer in your own words…". Free text that asks a question is an ask back (💬) and keeps the ask open. A read-only helper answers ask-backs with citations, in structured markdown (the owner called this critical). After 3 ask-backs the card says "decide or defer" (owner decision 2b). Review 1029 proposed dropping the cap; the owner did not pick that, so the cap stays.
- **Similar.** Before an ask is sent, `tl ask` searches past asks and decisions. A match shows inside the card as "🔁 Similar: <bead> asked "<q>" N days ago → "<answer>". [Same rule]". The agent must cite the match or explain why it does not apply.
- **Looks.** The buttons are ✅ Looks right · ↩️ Send back (typed text required, never one tap) · 💬 Ask back. A gallery shows all pictures of the look.
- **Blocking asks.** A blocking ask parks the bead and frees the slot. The answer queues the bead first and reruns the stage. If beads landed since the ask was made, a stale warning shows.

### 5.2 One cause list (asks and stops)
Asks and stops share one list, so they can feed one chart:

| cause | set by | used for |
|---|---|---|
| requirement gap | agent on an ask; owner on a stop ("requirement unclear") | both |
| decision | agent on an ask | asks |
| environment | agent on an ask; owner on a stop | both |
| process | agent on an ask | asks |
| flaky test | owner on a stop | stops |
| wrong plan | owner on a stop | stops |
| other | owner on a stop | stops |
| ? no cause | default until set | both, amber |

The stop chips in the drawer show the stop subset: flaky test · wrong plan · environment · requirement unclear (= requirement gap) · other.

### 5.3 After the answer: make it stick (optional, never blocks)
After sending, the card shows "✓ Sent. <bead> resumes in its slot. Undo · Make it stick?" with five choices:

| choice | effect |
|---|---|
| 📜 Record a decision | drafts an ADR from the card (question, chosen option, why). Agents read decisions at plan; `tl ask` checks them before asking. |
| 🛠 Factory bead | files a bead against the template, config or prompt, e.g. "bead template: state the period for every money rule". The current bead does not wait for it. |
| ✏️ Fix the bead text | rewrites the bead title or text; plan runs again |
| ⬇ Next time don't block | asks of this kind become non-blocking: the agent goes on with its best guess and says so at review |
| Just this once | nothing recorded |

The chosen outcome is stored on the ask and feeds the Ledger and the learning stats.

## 6. Bead drawer (the bead page)

The drawer opens from the right, 640 px wide, with a ⤢ toggle for full width (review 1029 item 8). It is full width below 900 px and full screen on the phone (§9). It closes with ×, Esc or a click outside.

- **Header:**
  - project · epic · bead id · slot · lane;
  - on the right, the totals: ⏱ elapsed across all passes (replans included) · tokens (amber or red per §2.6) · ⚠N, which opens the problem list (popover on desktop, sheet on phone);
  - the full title.
- **Trace.** The whole bead as one line, as on the Floor, fitted to the drawer width, with ticks at start, middle and now.
- **Tabs:**
  - 📄 Bead;
  - then one tab per pass: ①②③… Each is followed by its ending marker (↩️ 🔁 🙋 ⏸ ✅), or "now" with a teal dot for the live pass.
  A blocking ask, a look or a stuck bead opens on the live pass; otherwise the drawer opens on the last pass.
- **Pass tab:**
  - **Stage cells.** One cell per stage (plan · write · test · review · look · land) showing minutes over tokens, following the slot-card rules settled in 1k:
    - a visited cell is a grey tile;
    - a small cell (under 10 min and under 100k) is an empty tile, and hovering still gives the exact time and tokens;
    - a skipped stage is "—"; a stage not reached yet is white;
    - the current cell has a pulsing outline; failed cells are red; cells waiting on you are blue.
    - **Units.** Minutes read "12m" and tokens read "114k" or "1.2M", rounded. A bare number never stands for tokens, so "M" cannot read as minutes.
    - **Weights.** Numbers come in 3 weights by size: under 20m and 300k they recede, 20m+ or 300k+ stand out, 500k+ is the strongest.
    - **Violet tint.** 4 fixed bands by absolute tokens: none under 150k, then 150k, 300k, 500k and 1M.
    - **Thumbnails.** Screenshot thumbs sit under the stage that produced them; on the live pass they sit under the running stage (layout D). Hovering a cell gives its final status and last comment; clicking it scrolls the messages to that stage.
  - **Resumed note.** A resumed pass says "↪ Resumed on <slot> from branch bd/<id> after Nm waiting for a slot".
  - **Pass ending.** One line with its emoji and reason.
  - **Live box**, one of:
    - **Running:** the stage and pass, a timer, the command, tokens for this stage, and a terminal tail of the last 5–6 lines, new lines fading in, and the subtask list when the harness gives one (decision 1b). No burn rate (cut for v1, review 1029). Test counts appear only when the stage wrote a typed results file, never from regex on logs (decision 3); without one there is no test row. Behind it is a tool-call count ("14 calls · 1 failed"); clicking it lists one line per call with a type icon (read, 📝 edit, bash, search) and the tool name in bold.
    - **Ask:** the §5.1 card.
    - **Look:** the gallery, ✅ Approve → land, ↩️ Send back (says why).
    - **Stuck:** the reason ("same test failed 3×, then 22m with no tool calls") and the time it started; the last command and the watcher line; a terminal tail; "Why did it stop?" chips (flaky test · wrong plan · environment · requirement unclear · other), one tap, which feed the cause chart. The actions are ⏸ Park it and 👁 Seen ("stop alerting until something changes"). The mock's 🔁 Re-plan from the failing test and 📝 Add a note and restart write are not built: the owner cut restart-with-note (review 1029); they wait for the restart verb (§14).
  - **Messages, newest first.** These are the comments, AI notes and loop events of this pass only. Older lines fade when more than about 10 show.
- **Bead tab:**
  - screenshots and files: a gallery with the newest big; clicking opens a full gallery;
  - the description and acceptance criteria;
  - all comments across passes;
  - "Waits for" and "Unblocks", as BeadRows.
- **Bottom controls:**
  - ⏸ Park parks at the next safe point; the slot takes other work.
  - ⏹ Stop asks to confirm; the branch is kept.
  - ✉️ Note for the worker is saved as a bead comment that every later stage reads. The label says so, with an ETA to the next stage.
  - Send.
  A done bead shows Comment only.

## 7. Decisions tab

### 7.1 "Is the factory learning?" (always on top)
- **Scope.** The last 8 weeks, this week against last week.
- **Four stats**, each a number, a delta with a direction, an 8-point sparkline and a one-line meaning:

| stat | definition | good direction |
|---|---|---|
| asks per landed bead | asks raised ÷ beads landed, per week | down |
| repeat asks | asks whose question matched an existing answer or decision | down |
| send-backs per bead | look send-backs plus review send-backs ÷ landed. A guard: fewer asks must not mean more wrong guesses. | down or flat |
| asks made durable | share of answered asks whose outcome is decision, factory bead, bead fixed or demoted | up |

- **Causes.** "Why agents asked or stopped": a Pareto over asks plus stuck stops, using the one cause list in §5.2. Each cause has a count and a ↑↓ change against last week. "? no cause" is amber and sorts by its count.

### 7.2 Tabs: Waiting on you · Ledger · Decisions in force
The tab opens on Waiting when something waits, otherwise on Ledger.

- **Waiting on you.** Open ask cards in full (§5.1), each headed by bead · title · waited N, with an "open bead →" link. Cards sit in a grid of 420 px or wider.
- **Ledger.** Every ask, one line per row: date · bead · question → answer · outcome (or "waiting on you", or a "make it stick" button) · cause.
  - Filter chips: All · 📜 Decision · 🛠 Factory bead · ✏️ Bead fixed · ⬇ No longer blocks · Once · Open · ? No cause.
- **Decisions in force.**
  - Each ADR shows its id, text, reuse count and age. Reuse = how many plans cited it.
  - A decision with 0 reuses in 30 days shows amber and offers prune.
  - A one-line note: agents read these at plan, and `tl ask` checks them first.

## 8. Lanes tab

- **Rows.** One row per subscription lane. A lane is a license (e.g. "claude Max", "codex Pro", "OC Go" for OpenCode Go), not a harness. There is no "opencode" lane.
- **Columns:**
  - lane: a ring and its name; under it, the plan and model;
  - 5 h window: a used bar, then a hatched forecast to the reset at the current burn rate, the percentage, and "resets HH:MM";
  - week: a bar;
  - forecast: plain text, e.g. "runs out in ~45m at this burn; q1 then waits until 21:10";
  - slots;
  - running: bead chips with markers;
  - waiting for it.
- **Sort.** Locked first, then running out, then fine.
- **Rings.** The number sits inside the ring: a percentage, or the time to unlock rounded to one unit (3d, 5h, 42m). The ring is larger than in the 4-series mocks.
- **Stale.** A lane whose status is older than 1 h shows greyed, with its age and "run tl lanes".
- **Top bar.** The top bar shows only lanes that are not fine. "N lanes ▾" opens this tab.
- **Data source.** Delegate's usage feed. The loop refreshes it every 20 min; the dashboard never calls a vendor.

## 9. Phone (below 600 px)

This is its own layout over the same data and content renderers. The desktop is unchanged. The mock is `dash-round-9.html`.

- **Rules:**
  - no sideways scrolling anywhere;
  - tap targets 40 px or larger;
  - text 12 px or larger;
  - inputs 16 px (no iOS zoom);
  - primary actions in the bottom third;
  - `env(safe-area-inset-*)` respected;
  - system back closes the top layer, in the order sheet → bead page → goal level (history states).
- **Header.** The tab title (large) and one pill listing only the lanes in trouble, e.g. "● gemini ● codex 91%"; tapping it opens Lanes.
- **Bottom tab bar.** Board · Floor · Decisions · Lanes, with badges: Floor stuck (red), Decisions open asks (blue).
- **Board:**
  - **Controls.** A segmented Flow · Goals and a Filter button. The Filter button opens a bottom sheet with project, epic (after a project is picked) and machine chips, which wrap at 40 px, plus Clear and "Show N beads". An active filter shows a summary line with Clear.
  - **Flow sections:** 🛑 Stuck · 🙋 Needs you (has questions plus your look) · ▶ Working · 👀 AI review · 🚀 Landing · ▷ Backlog (folded) · ✅ Done today (folded).
  - **Quick actions on cards.** An ask card carries its recommended answer as a button (✅ <option> + consequence) and More. A look card carries ✅ Approve → land and 📸 N (opens the Bead tab). A stuck card carries "Why did it stop? Pick a reason", which opens the bead.
  - **After an answer.** A sheet shows ✓ Sent · <bead> resumes · Undo, plus the five make-it-stick rows. The card collapses out of the list.
  - **Goals.** Drill down one level at a time: a list, then the goal, then what it needs. Each row shows a roll-up; "‹ <parent>" goes back.
- **Bead page.** Pushed from the right, with ‹ Back and a swipe from the left edge to go back.
  - It shows the title, meta lines, the trace fitted to the width with no labels in segments, sticky pass tabs at 46 px, and the pass content per §6. The terminal wraps.
  - The bottom bar holds ⏸ Park · ⏹ Stop · ✉️ Note. A look shows ✅ Approve → land · Note instead.
  - Stop opens a confirm sheet, never one tap. Note opens a sheet with a 16 px textarea.
- **Floor.** It opens with counts: running · stuck · your look · free. Under them is one card per slot holding:
  - the machine icon, slot name and lane, with a state pill (running, stuck Nm, your look, free);
  - the current bead's title;
  - the stage and its minutes, ↻N, "↪ from <slot>", and "next: <bead>" on a busy slot only (an empty slot shows no next, 1e);
  - a 2 h strip in segment colours, with "2 h ago · 1 h · now".
  A slot whose bead parked on an ask reads "Free · <bead> parked here · waits on your answer".
- **Decisions.** The same content as desktop: the learning panel (2×2 stats, causes), sticky three-way tabs (Waiting · Ledger · In force), the ledger as stacked rows, and ADR reuse under its text.
- **Lanes.** One card per lane, worst first: a 46 px ring, the name and plan, reset and slots, a bar with the forecast hatch, the forecast text, and bead chips.

## 10. States

| state | rule |
|---|---|
| first run, no beads | EmptyState: what the loop needs (`tl` command to register a repo, to start the loop) |
| empty column / section | "Nothing here." in muted text, one line |
| loop not running | header banner in amber: "loop not running on <project> · last activity <age>" with the start command |
| data stale (no refresh > 30 s) | refresh circle turns amber with the age; > 5 min: banner |
| server unreachable | full-width red line under the header, retry with backoff; keep last data greyed |
| worker exited | 💀 on the bead, red; drawer shows exit code and last 20 lines |
| no baseline yet | token totals grey with "usual: n=3 of 5" |
| lane status stale > 1 h | greyed lane row with age and "run tl lanes" |
| error in one panel | that panel shows the error line; other panels keep working |

## 11. Data and API

(See §11.1 for what origin/main has today and the gaps.)

### 11.1 Backend today and gaps
The dashboard backend needs were sent to the refactor session as a heads-up on 2026-10-29 (decision 7); this table supersedes that note. It records what origin/main 0.23.130 has, as read on 2026-10-29 in one pass and not cross-checked. Verify each row before building on it.

| need | today | gap to close |
|---|---|---|
| passes (stage, slot, start, end, outcome) | engine log per run: `RunStart.slot`, `StepStart`/`StepEnd` (`step`, `stage`, `outcome`, `secs`), `node`/`end`/`transition` records; `views/timeline.py` builds runs → blocks | a pure builder that joins runs + steps into pieces per slot; a resume in another slot is a new run, so it becomes a new piece. Stage cells map steps: plan/replan → plan, write → write, checks → test, review + verify → review, look → look, gate + land → land. |
| Kanban column | `/api/tasks` states (running, asks, waiting, paused, blocked_by, failed); queue from `loop.queue()`; `AskStore`; look = label `owner-look` (`api/looks.py`) | one pure `column(bead)` in `views/` composing these; tests per column |
| asks | `contracts/ask.py` `Ask`, `AskOption` (`label`, `consequence`, `recommended`), `AskStatus`; `tried[]` is the nearest thing to the "why" bullets | add `blocking: bool`; add `cause` from the agent (requirement, decision, env, process, unknown), owner-correctable, separate from the engine's `AskClass`; add `outcome` (adr, factory, fix, demote, once); add an answered-ask history (the ledger) and an API for it; extend `tl ask` validation to §5.1 |
| repeat detection | none | `tl ask` searches past asks + decisions before raising; the agent cites or explains; store the match on the ask |
| decisions in force (ADRs) | none (`intake.py` has a `decision` verb that leaves a bead comment) | a decision store (one file per ADR in the repo, e.g. `docs/decisions/`), read at plan, cited by id; a reuse counter from plan citations |
| stuck | `views/live_state.py` `silent` (fixed 60 s, worker lines), `hung`; `signals.py` churn | stuck = silent past a per-stage limit, or the same check red 3×; also "no commits for N min" (default); stuck `cause` and `ack` stored per bead run |
| controls | CLI `tl stop`, `tl hold`, `tl hint` (owner_hint, read on the next run), `tl slot hold/release`; dash POSTs only answer, withdraw, look | `tl` verbs + POSTs for park (bead, at the next safe point), stop (one bead), note (a comment read at the next stage start, not only the next run), ack, cause, stick; restart-stage later |
| lanes | `api/lanes.py` card (`usage[{window, used_pct, resets_at}]`, `out_until`), via the `tl lanes` snapshot | forecast (burn rate from the last hour of `AiCall` tokens per lane); a lane → slots map; "waits for it" from queue rows that need the lane |
| slots | `tl slot list` (name, bead, status, holder); `LoopState`; slot beads per host | the slot's lane or harness recorded on the slot; a machine field; one dashboard per machine |
| projects | `~/.config/task-loop/repos.json` (`tl register`) | none |
| epics, needs | `/api/graph`, `views/graph.py`, `api/beads.py` deps | parent/epic on each bead in the snapshot; the goal-roots builder |
| tokens, time, artifacts | `AiCall.tokens`, fresh formula in roadmap briefs, `/api/artifact`, `/api/look-shot` | tokens per stage per pass in the bead endpoint; usual per model lane with n |
| live tail, tool calls | `/api/live` (paged events, `tool_start`/`tool_end`, long-poll `wait=`), byte-offset tails | a tool-call list shaped for the drawer (kind, name, ok/failed) |
| learning | `tl report` card, `reflect` cause digest (`/api/reflections`), `traces.jsonl` fingerprint | weekly series for the four stats; send-backs per bead stored; durable share from ask outcomes |
| auth | GETs open; a POST needs no token from loopback or Tailscale, else a Bearer token (`bind.post_allowed`) | keep as is |
| data path | per-request reads with a TTL cache; live runs tail by offset (`tails.py`) | data path A for the snapshot (§11.2); measure before adding a persisted cache |

### 11.2 Snapshot and live updates
- **Process.** One dashboard per machine. It keeps running after every Claude session closes (it is a detached process and exits after its idle limit). `tl dash ensure` is idempotent: running it again, from any number of sessions, never starts a second server (decision 1b).
- **Data path A.** The server keeps what it has read in process memory and reads only new bytes, using an offset and size per file. A restart reads everything once. Measure warm refresh and cold start before adding any persisted cache.
- **Snapshot.** `GET /api/snapshot` returns one JSON document holding everything the four tabs need. Filters are applied on the client.
  - `projects[]`, `machines[]`, `slots[]` (machine, name, lane, current bead, state);
  - `beads[]` (id, project, epic, title, column, marker, status line, age, loops, needs[], cause, ack, totals);
  - `passes[bead]` (pieces: stage, slot, start, end, kind, outcome);
  - `asks.open[]` (the full card), `asks.ledger[]`;
  - `decisions[]` (ADR id, text, reuses, age), `learning` (the four weekly series plus causes this week and last week);
  - `lanes[]` (window %, forecast %, reset, week %, locked until, slots, running, waiting, status age);
  - `server` (version, data age, loop state per project).
- **Per bead.** `GET /api/bead?project&id` returns the full drawer: passes with stage cells, messages per pass, tool calls per stage, artifacts, description, acceptance, comments, waits for, unblocks.
- **Live.** The live tail of the running worker (terminal lines, tool calls) reuses the run's long-poll, `GET /api/live?project&id&since&wait`. No SSE is added. Everything else polls the snapshot every 2.5 s while the page is visible, and at once when the page regains focus. Polls are keyed by version, so an unchanged snapshot returns 304.
- **Writes.** Every write is a POST under today's auth rule (§11.1) and goes through `tl` verbs, never through direct bd calls:

| POST | does | `tl` verb |
|---|---|---|
| `/api/answer` | answer, ask back, undo within 5 s | existing answer path, extended |
| `/api/look` | approve or send back (text required) | existing look path |
| `/api/stick` | outcome of an answered ask: adr, factory, fix, demote, once | new |
| `/api/cause` | set or correct the cause of an ask or a stop | new |
| `/api/ack` | 👁 Seen on a stuck bead | new |
| `/api/park` | park at the next safe point | new |
| `/api/stop` | stop the run, keep the branch | new |
| `/api/note` | note to the worker (bead comment) | new |

### 11.3 Derived in Python (pure, tested)
These live in pure Python functions under `taskloop_dash/views/`, each with fixture tests:
- the Kanban column;
- the marker;
- the status line;
- stuck detection;
- passes and pieces from the engine log;
- comeback joins;
- the roll-up;
- the goal roots;
- the lane forecast;
- the learning series;
- the cause Pareto.
The client only lays out.

## 12. Frontend build

- **Runtime.** Preact + HTM, vendored as one checked-in file, pinned by hash, with no build step. Components are keyed by bead, run and event id. UI state (open ids, drafts, selection, scroll) is kept apart from server snapshots, so a refresh never loses a draft, an open fold, focus or scroll. The terminal tail stays imperative.
- **Files.** `static/css/{tokens,kit,layout,phone}.css`, `static/js/{app,api,state,format}.js`, `static/js/ui/` (kit components), `static/js/views/{board,goals,floor,drawer,decisions,lanes,phone}.js`, `static/vendor/ui-runtime.js`. `http.py` serves an asset allowlist.
- **Kit (the audit's 15 components plus BeadLine; one look each):**
  - Tokens, Button, FilterChips (with All), Tag, CountBadge, Totals (the one home of the token and time thresholds of §2.6);
  - Tabs: one look, a 2 px ink underline;
  - Panel + SectionHeader, Marker;
  - Meter: one size;
  - BeadRow, StageCard (Totals + StageCells + messages, the 1k slot card living on in the drawer);
  - BeadLine: the one-line bead, used by the Floor, the trace and the phone strip;
  - AskCard, Drawer/Sheet;
  - Message line;
  - Overlays: Popover, Toast, EmptyState.
  Pill shapes are for filter chips only. Answers are small buttons; statuses are Tags (radius 4, tinted, no border).
- **Phone.** It is the same components with a phone shell (`views/phone.js`) chosen by `matchMedia('(max-width:600px)')`. It is not a CSS squeeze of the desktop: the v1 attempt at that was rejected.
- **`components.html`.** This sheet renders every kit component with fixtures, in light, dark and phone.
- **Budget.** JS and CSS together stay at 100 KB gzip or less.
- **Retired.** The old pages and their API are removed. There is no backward compatibility.

## 13. Build slices (in order, each lands on its own)

| # | slice | done when |
|---|---|---|
| 1 | kit + shell + snapshot endpoint (read-only): tabs, header, filters, projects → epics → machines, deep links, states (§10) | `components.html` renders every kit component; snapshot fixture test; shell on desktop and phone |
| 2 | Board Flow + drawer read-only (passes, stage cells, messages, Bead tab, live tail via long-poll) | column derivation tests over recorded engine logs; drawer of a 3-pass bead matches the mock |
| 3 | asks: card, answer + undo, ask back + helper, looks, Decisions › Waiting; `tl ask` validation + similar search | answering from the card and the drawer; invalid ask rejected; similar ask cited |
| 4 | Floor slot tracks + comeback; stuck detection + cause + ack; Floor badge | a recorded comeback renders as two pieces with a curve; stuck fires at the stage limit |
| 5 | Decisions › learning block, Ledger, In force; make it stick (5 outcomes); ADR reuse counts | stats recomputed from a fixture ledger; prune offered at 30 days 0 reuse |
| 6 | controls: park, stop, note, ack, cause | each verb round-trips through `tl` and shows in messages |
| 7 | Goals tree (desktop) + drill-down (phone) | roots/children from bd deps; shared child stub |
| 8 | Lanes tab + header pill + forecast | sort order; stale lane greyed |
| 9 | phone shell complete (§9) | phone checks below pass on 390×844 |

**Checks for every slice:**
- unit tests for the pure builders;
- one browser scenario. It extends `tests/cockpit_scenario.py`: the real page, mocked data, assertions, and desktop plus phone screenshots saved as evidence;
- on the phone: no element wider than the viewport, no horizontal scroll container, no tap target under 40 px, no text under 12 px, inputs at 16 px. Assert these in the scenario;
- that state survives a refresh: an open drawer, a draft, a fold and the scroll position.

## 14. Out of scope (later beads)

- ⌘K command palette and keyboard shortcuts (file as a bead).
- Morning report: "while you were away" grown into a daily report (file as a bead).
- "What an answer unlocks": a brainstorm, low priority (file as a bead).
- Owner attachments on answers: the lowest priority.
- Affinity tags on beads, with Up next showing only beads that fit the slots in view.
- One central dashboard across machines. It runs one per machine and lists its projects.
- Push notifications on an ask or a stuck bead.
- Per-stage token baselines and the corner triangle.
- Restart controls: 🔁 Re-plan from the failing test, 📝 Add a note and restart a stage (a `restart` verb and POST). Cut from v1 by the owner.
- Machine online and offline lamps, for remote machines only.
