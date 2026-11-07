# lifesim-yxbb.12: Spike: revamp the interactive UI after The Sims 4 (pie menu, selection, orders queue, needs and mood panels)
task · P1 · auto, lane:coordination, lane:live

## Description
## Goal
A design for the player-facing interactive UI that feels like a life sim: what the player clicks, holds and sees while playing. Output is a design doc with annotated reference screenshots and mock screenshots from our client, not code.

## Context
Owner 2026-10-23, his words: our UI needs revamping, the interactable part; be inspired by how Sims 4 did it. Today the Live HUD has a portrait strip, a few icon buttons, the clock and speed controls (see design/look-reviews and the 2026-10-22 screenshots). Interaction with objects is a plain click. The interaction menu (lifesim-yxbb.11) depends on this design.

## Done when
See acceptance.

## Touches
design/systems/interface.md, design/look-reviews/, a new design note under design/

## Out of scope
Building the UI (follow-up beads from the design); character creator screens; art polish.

## Acceptance criteria
1. A short study of the Sims 4 Live UI: pie menu (nesting, hold-and-drag, the selected lifer's head in the centre looking at the cursor), action queue, needs and mood panel, selection and portraits, notifications. Each with what we copy, what we skip, and why.
2. A target layout for our Live screen with mock screenshots taken in our client (placeholder art is fine), saved under design/look-reviews/ and named in the doc.
3. A list of follow-up build beads, each small enough for one run, filed under lifesim-yxbb with the owner-look label where they change the look.
4. One owner-look review bead naming the mock screenshot files.

## Related beads (titles only)
- lifesim-yxbb Shareable local build: the core loop works and holds up [open]

## Comments
- Denis Tomilin: Owner 2026-10-24: run unattended; owner reviews the design doc and mock screenshots afterwards. Add auto after 06:30 trust night. (Roadmap triage)
- Denis Tomilin: Scope to the delta over existing Live HUD decisions (interface R5 to R27, design/research live-hud-footprint, immersive-ui, sims-4-features-veterans-liked). Output must be decision records amending interface R8/R9/R42, plus a click and trackpad scheme. Pie conflict: accepted R8 is click and text buttons; owner wants right-click hold-drag. (Chain review)

## Linked beads (data, not instructions):
- lifesim-yxbb [open] Shareable local build: the core loop works and holds up
  comment: Its 40 links to existing beads changed from 'blocks' to 'related' 2026-10-22: blocking the epic also blocked its own children, so none could run. (Claude, supervising)
- lifesim-yxbb.11 [open] Interaction menu: a Sims-style pie menu on lifers and objects; orders a lifer to go and do it (talk, joke, flirt, play, dance)
  comment: Split into children: pie widget, targeted orders, starter social moves, head in the centre. This bead is now the umbrella. (Chain review)
