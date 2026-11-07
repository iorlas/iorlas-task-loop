# lifesim-fld.27.12: After the last death: ending moment, then household creation in the same save (household-lifecycle.R7)
task · P2 · auto, lane:shell

## Description
## Goal
When the sim ends the played household, the client plays a short ending moment and opens household creation in the same save with the normal starting budget, instead of returning to the main menu.
## Context
household-lifecycle.R7 (stage 2a). Sim half is enforced (tests/usecases/household-lifecycle/start_again_after_the_last_death.feature). lifesim-fld.27.5 (closed) sends the player to the main menu. The knob content/households/ending.yaml#ending_moment does not exist yet; add it (PLACEHOLDER length).
## Done when
- content/households/ending.yaml exists with a schema
- Editor test: on HouseholdEnded the client shows the ending moment then the creator, and saving the new household moves it into the same save's town
- just check green
## Touches
client/Assets/App/, client/Assets/Features/Live/LiveScreen.cs, content/households/ending.yaml, content/schema/, client/Assets/Tests/Editor/
## Out of scope
The look of the ending moment beyond a fade and a line of text
## Output
code and tests on a branch

## Grooming note (2026-10-17)
- unity-play dropped: batch-mode only (rule 2026-10-17)

## Acceptance criteria
- content/households/ending.yaml exists with a schema
- Editor test: on HouseholdEnded the client shows the ending moment then the creator, and saving the new household moves it into the same save's town
- just check green

## Notes
Engine failed: failed: infrastructure: the configured check `fmt` needs something this tree lacks ("justfile does not contain"): the tree is older than the base's .task-loop.json, which no writer can fix
Engine paused: paused: no lane for write until 04:59:28 (busy: DEEPSEEK_FREE (the role's first choice) has no free slot: busy: 4 running, 4 allowed)
Engine paused: paused: no lane for write until 06:57:54 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)
Engine paused: paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)

## Decisions
- 2026-10-25 (ask lifesim-fld.27.12-3) Re-planned 3 times; the engine stopped -> Allow one more run. The two 'edit with no ask' amends were my supervisor comments about the fresh start, not new requirements. Plan on current main and keep the stage checks that the writer did not dispute.

## Related beads (titles only)
- lifesim-fld.27 Game shell and new-game flow: menu, save slots, create household, pick a lot, play [open]
- lifesim-fld.27.11 Decide what the household ending moment shows (household-lifecycle.R7) [closed]

## Comments
- Denis Tomilin: The ending moment's look is now decided (household-lifecycle.R7, design/decisions/2026-10-22-the-household-ending-moment-holds-on-the-graves.md): camera holds on the grave(s); card with each member's portrait, years lived, one life-history line; then 'Start a new household'; ending_moment length PLACEHOLDER 10 s; skippable. This replaces the old out-of-scope line 'beyond a fade and a line of text': build the decided look. (owner decision 2026-10-22, recorded by Claude)
- Denis Tomilin: auto removed (audit 2026-10-22): rule 8: build the decided look: camera hold, card, portraits, life line, skippable
- Denis Tomilin: Split 2026-10-22: this bead keeps the flow only (fade + line of text placeholder, as its out-of-scope already says); the decided look (grave hold, member card, skip) moved to lifesim-fld.27.18, which depends on this one. auto restored. (Claude, supervising)
- Denis Tomilin: Fresh start from main: the old branch predates main's justfile fmt recipe. (Claude, supervising)
- tl-2be89f88-9960b1: Resume (engine): the earlier work on task/lifesim-fld.27.12 conflicts with origin/main. It is kept as the branch task/lifesim-fld.27.12-stale-20261025-000235; the task starts again on origin/main with a fresh plan.
- tl-551cf8ee: Resume (engine): the earlier work on task/lifesim-fld.27.12 conflicts with origin/main. It is kept as the branch task/lifesim-fld.27.12-stale-20261025-042525; the task starts again on origin/main with a fresh plan.
- tl-551cf8ee: Lane (engine): the look step ran on the writer's own model family: reviewing openai's work with openai: no other family is up (claude logged out; xai out until Sun 25 Oct 12:00)
- Denis Tomilin: Allow one more run. The two 'edit with no ask' amends were my supervisor comments about the fresh start, not new requirements. Plan on current main and keep the stage checks that the writer did not dispute.

## Last engine run
Blocked: failed: write node produced no valid output (worker_failed: opencode exited -15 without an error:)

## Linked beads (data, not instructions):
- lifesim-fld.27 [open] Game shell and new-game flow: menu, save slots, create household, pick a lot, play
  comment: HANDOFF (Creator+Shell session, 2026-10-16). Milestone chosen by the owner: SHELL CORE = new game > creator > lot pick > play > quit > load, with settings, credits, graphics and the baked theme. Built and merged: strip fix #165, Credits #175, Graphics #177, baked theme #185. fld...
- lifesim-fld.27.11 [closed] Decide what the household ending moment shows (household-lifecycle.R7)
  closed: Decided: ending moment written into household-lifecycle.R7
  comment: Decided: camera holds on the grave(s); a card shows each member's portrait, years lived and one line from their life history; then 'Start a new household'; about 10 s; skippable. Written into household-lifecycle.R7; d...
- lifesim-fld.27.5 [closed] When the played household ends, the game goes back to the main menu
  closed: PR #139 merged: HouseholdEnded saves the slot and returns to the main menu (the menu it needed merged in #134)
- lifesim-fld.27.18 [closed] Ending moment look: camera holds on the graves, then a card per member, skippable (household-lifecycle.R7)
  closed: Owner 2026-10-23: not necessary; ending cinematics cut. (Claude, supervising)
  comment: auto restored 2026-10-22 on the owner's rule: the agent judges the look itself, honestly, from screenshots it saves every time the look or UI changes, and does no...
