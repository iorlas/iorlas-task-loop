# Dashboard drawer and status redesign: Opus UX review (2026-11-13)

Status: proposal from a read-only consultant review of the live dashboard data and page code (no browser was opened, so nothing
about looks or layout is verified). Nothing here is implemented; the owner decides. Real run 2 reflection:
`self-hosting-real-run-2.md`.

## What the live data showed

- `tl-8bh9.14.111`: the card of a restarted task has no stored cause; the default word is `restarted at plan`
  (`dash_board._repeat`). Plan 1 and plan 2 prompts are byte-identical, yet the second plan agent found no plan at the path: the
  base moved and nothing shows it.
- `tl-8bh9.14.112`: two causes for one hold (`failed:answer:schema_invalid` on the card, `held:slot_dirty` in the log); two earlier
  holds appear only in tracker comments, not in the rail.
- `tl-8bh9.14.132`: 33 minutes of land waiting (`stopped=slot_for_land`, `skip attempted`) that the history does not show.
- An abandoned card falls back to the Implement column (`column_of`); quiet comes from `last_command` after an abandon; a card
  shows a slot only while `row.held and release is None`.

## Drawer layout

Header: task facts, one status pill, and one "Needs you" panel only when a person must act. Rail: one row per attempt and one
row per event between attempts, grouped into runs ("Run 2 (current)" open, "Run 1 abandoned 17:34" folded). Right pane: an attempt
(Lines, Result, Prompt) or an event's detail panel. Never above the tabs: jump reasons, hold cause, land text, CLI commands; the
attempt header keeps one line "Began after Restart at plan, why" that selects the event.

## Events between attempts

Kinds: restart, repeat, abandon, hold, hold cleared, factory verification and commit, land try, landed. Each is a clickable rail row
with a glyph, a plain title and a time. One detail panel with five fields: What happened (plain sentence, raw code in mono), Decided
by (factory, you by label or edit, main moved or conflict, the agent's answer), When (time and link to the log lines), What changed
(prompt lines added, base commit old to new, branch reset, task text edited), What happens next. This needs a stored typed cause
(`TaskEvent` list in `TaskDetail`, recorded once by the deciding operation, like `repeat_listing`): a factory.db schema bump.

## Status vocabulary (one word per state)

Ready (not started), Agent running (quiet indicator only here, only while that attempt's agent is alive), Factory work (committing,
publishing; elapsed), Checking (current check and slot), Queued (why), Abandoned (why), Ready to land (factory lands next round),
Landing, Landed, Needs you (kind: needs info, review requested, blocked). Quiet never shows on held, queued, land or checks cards.

## Land

Land is a run of events ("ready 17:01, tried 17:29 (no slot), landed 17:34"). Remove every `tl step land` string
(`app.js`, `rail.js`, `drawer.js`, `ui.js`). With automatic landing the card says Ready to land or Review ready. Conflict to decide:
Accept/Reject buttons break the recorded "read-only, no buttons" decision; if it is lifted, a button must call the same application
operation as the CLI.

## Readable labels (raw code kept as hover text; an unknown code shows raw)

| raw | shown |
|---|---|
| needs_owner, failed:needs_owner | The agent needs your decision |
| answer:schema_invalid | The agent's answer was in the wrong format |
| failed:test:failed | Checks failed: test |
| held:slot_dirty | Slot has leftover files |
| verified | Checked and committed |
| reused | Nothing new; earlier commit kept |
| rejected:RULE | Commit refused: RULE |
| unsettled:unsafe | Not committed: a listed path is unsafe |
| pending, registered, passed | Not checked yet, Starting, All checks passed |

Verification title: "Factory checked the answer of Implement try 1" (no task-wide try number); the gap between steps is "factory work
30s (commit, publish, start checks)", never "idle".

## Ranked changes

1. Readable labels (new `words.js`; `rail.js`, `result.js`, `app.js`, `drawer.js`). Low.
2. Move the restart/jump banner out of the drawer pane above the tabs; the attempt header links to its event (`drawer.js`). Low.
3. Quiet only for a live agent; slot shown during checks (`dash_board.card_of`, `app.js`). Low.
4. Queued and abandoned states (`column_of`, `dash_model`, `app.js`). Medium (bead `tl-8bh9.14.143`).
5. Event rows and the uniform event panel (`dash_model`, `dash_task.py`, `rail.js`, `drawer.js`, new `event.js`). Medium.
6. Store restart, abandon and hold-clear causes and the base change (engine writers, schema bump). High; unlocks 5.
7. Land as events, no CLI text, runs folded. Medium; after auto-land (`tl-8bh9.14.136`).
8. Live check lines in Lines; a click opens that check in Result (checks feed endpoint, `lines.js`, `result.js`). Medium.
