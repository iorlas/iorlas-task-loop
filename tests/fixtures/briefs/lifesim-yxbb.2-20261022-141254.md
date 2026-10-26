# lifesim-yxbb.2: Client soak: Live in Play mode for N game days at top speed, 1 and 3 lifers, no exception, no stuck lifer, memory flat
task · P1 · auto, lane:live, unity-play

## Description
## Goal
The real client survives many game days on screen.

## Context
The sim soak does not cover the view (animation, UMA atlases, notices, camera). UMA memory is known heavy (lifesim-vuck: 8.6 GB at 10 characters; lifesim-8iux). Use the play-mode harness from lifesim-gfr.31 (unattended editor drive, screenshots).

## Done when
- A play-mode test or batch script runs Live on furnished-flat for 7 game days at the top speed with 1 lifer, then with 3 lifers.
- Unity log has no exception or error line (grep per client/AGENTS.md); no lifer stands idle on screen longer than 60 game minutes (read from the sim state).
- Process working set sampled each game day: slope under 5 percent per day after day 2, and peak under a stated budget written in the test.
- A screenshot per game day is saved and the agent judges them honestly (no black frames, lifers visible, HUD intact); paths in the bead comment.
- just check green.

## Touches
client/Assets/Tests/PlayMode/, client/Assets/Editor/ (soak driver), justfile

## Out of scope
Sim-side soak; build/buy interaction; performance tuning (lifesim-gfr.2).

## Acceptance criteria
The soak driver exits 0 for 1 and 3 lifers on this Mac with log greps clean, memory slope under limit and 7 screenshots saved; the agent has judged them in a bead comment.

## Related beads (titles only)
- lifesim-yxbb Shareable local build: the core loop works and holds up [open]
- lifesim-yxbb.4 Several lifers share a home: enough beds, toilets and kitchen for the household, no double use, no deadlock, no starvation [closed]

## Comments
- Denis Tomilin: Answer (b), same rule as lifesim-yxbb.1: stuck = idle for more than 30 game minutes while a need is below its urgent threshold and a reachable object satisfies it; that check is strict and never waived. Idling with all needs satisfied is not a stability failure: print the longest idle stretch per lifer as a measured number, marked KNOWN against lifesim-iqad. Whether satisfied lifers should find something to do is a separate owner question (asked). (Claude, supervising)
- Denis Tomilin: Parked over budget (226 of 180 min): one 'just client-soak 1' run alone took over an hour of wall time. Scope change for the loop: the acceptance check runs a short client soak, 2 game days each for 1 and 3 lifers at top speed, which must finish in under 20 min wall time together; keep 'just client-soak <days> <lifers>' as a recipe for longer runs, which the loop does not wait on. The 14-day stability proof is the sim soak (lifesim-yxbb.1); this bead proves the client side (no exception, no stuck lifer, memory flat over the short run). Continue from the existing work in the slot. (Claude, supervising)

## Last engine run
Blocked: over budget: $0.00 of $15, 226 of 180 min

## Linked beads (data, not instructions):
- lifesim-yxbb [open] Shareable local build: the core loop works and holds up
  comment: Its 40 links to existing beads changed from 'blocks' to 'related' 2026-10-22: blocking the epic also blocked its own children, so none could run. (Claude, supervising)
- lifesim-yxbb.4 [closed] Several lifers share a home: enough beds, toilets and kitchen for the household, no double use, no deadlock, no starvation
  closed: merged 152e9eda4caa to main: The sim already stops two lifers using the same slot at once. SlotClaims in src/Sim.Core/Modules/Adverts/Availability.cs marks a slot that is in use as unavailable (AvailabilityRefusal.InUse), and ActionCause ...
- lifesim-vuck [open] UMA fork: convert + compress without atlas reuse drives the player past 8.6 GB working set at 10 characters
  comment: Raised to P1: 8.6 GB at 10 characters; a household of 3-4 must stay within memory on this Mac. Epic lifesim-yxbb. (Claude Opus, roadmap review)
- lifesim-8iux [open] UMA uses about 100-185 MB of VRAM per character (atlases per character): 25 characters = 5.4 GB of a 6 GB card, 50 pages (GPU 150 ms)
  comment: auto removed (audit 2026-10-22): rule 2: Findings with screenshots of faces at each atlas size
- lifesim-gfr.31 [open] Unity agent tooling: an agent drives the editor unattended (open, rebuild, play, click, screenshot)
- lifesim-gfr.2 [open] Runtime memory and speed on the client: GC pause budget, incremental GC, IL2CPP versus Mono, a frame-budget check
  comment: Phase 3 merged (PR 204, 2026-10-15): the client was built and run as a Windows player on Mono and IL2CPP (development builds, Direct3D 12, 600 frames per scene). Allocation per frame is the same on both: Creator 12.3-12.8 KB mean, Live median 3.6-3....
- lifesim-yxbb.1 [closed] Multi-day soak in the simulation: N game days, 1 and 4 lifers, with save and load between days
  closed: merged d65c08d2248d to main: Most of the soak is already in the tree from the wip commit: SoakRun, SoakCheck, SoakCommand, SoakHeap, SoakLimits, SoakResult, soak-known-red.json, a `just soak` recipe and SoakTests. This change applies the owner's two answers. (1) The...
- lifesim-iqad [open] Retune idle time and the pace spread across seeds against the seed-sweep limits
  comment: Also from yxbb.1: every lifer's longest idle stretch is 66-160 min each day against the 30 min limit after ar3h. Part of this retune. (Claude, supervising)
