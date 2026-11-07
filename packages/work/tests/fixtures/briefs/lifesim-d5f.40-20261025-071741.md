# lifesim-d5f.40: Spike: measure sleeper penetration through each bed and propose a mattress-top rule
task · P2 · auto, lane:live, spike, unity-play

## Description
## Goal
Numbers for how far the sleeper sinks into or floats over each bed, and a proposed lie height rule.
## Context
d5f.22: body half inside the blanket texture, legs through the bed model; pose is SleepGround from the floor with live.poses.lie_root_y 0.5, no knowledge of mattress or blanket; slot height is the starting point. Beds: content/objects/single-bed.yaml (ithappy models 0.74-0.77 m, see lifesim-ylci).
## Done when
- Per bed: max depth of sampled bone/skin points under the mattress top and through the frame, at the loop pose
- Proposed rule (per-object body height from slot height or mesh bounds) with predicted depth/float numbers
- Findings in design/research/sleeper-on-bed/README.md with close-up screenshots
- file follow-up tasks for gaps found
## Touches
design/research/sleeper-on-bed/ (new); no game code
## Out of scope
Blanket mesh; changing content
## Output
design/research/sleeper-on-bed/README.md

## Acceptance criteria
- Per bed: max depth of sampled bone/skin points under the mattress top and through the frame, at the loop pose
- Proposed rule (per-object body height from slot height or mesh bounds) with predicted depth/float numbers
- Findings in design/research/sleeper-on-bed/README.md with close-up screenshots
- file follow-up tasks for gaps found

## Notes
## Decisions
- 2026-10-24 (ask lifesim-d5f.40-4) gate red on the rebased tree after 2 fix rounds: it needs the owner's hint ... -> Hint: every evidence check fails because .task/lifesim-d5f.40/evidence/sleeper-on-bed.json is never written. Main is green; the gap is the producer. Writers do not run Unity, so the measurement must come from a check: add an acceptance check, ordered before the check_evidence.py checks, that runs the Unity batch measurement through tools/unity_slot.py and writes sleeper-on-bed.json into the evidence folder. Then the evidence checks read it. Do not hand-write the JSON.
Engine paused: paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)
Engine paused: paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)

## Related beads (titles only)
- lifesim-d5f Live view: the client draws and drives the simulation (rung 2a in the client) [open]

## Comments
- Denis Tomilin: Owner rule 2026-10-22: agents run this and judge the look honestly from saved screenshots; no owner gate; the owner reviews later via an owner-look bead. owner-taste removed, auto added. (Claude, supervising)
- Denis Tomilin: Owner hint 2026-10-24: the stage-2 check reads .task/lifesim-d5f.40/evidence/sleeper-on-bed.txt, which stage 1 never wrote (FileNotFoundError). Make stage 1 write that probe report first, or make the check read where the report really goes. (Claude, supervising)
- Denis Tomilin: allow one more
- tl-2be89f88-0f25a9: Resume (engine): the earlier work on task/lifesim-d5f.40 conflicts with origin/main. It is kept as the branch task/lifesim-d5f.40-stale-20261024-123256; the task starts again on origin/main with a fresh plan.
- Denis Tomilin: run again. Hint (supervisor): the sandbox denied a long rg command with many -g globs. To look for conflict markers use: git grep -n -I -E '^(<<<<<<<|>>>>>>>)( |$)' -- . ; keep shell reads short and simple.
- Denis Tomilin: Hint: every evidence check fails because .task/lifesim-d5f.40/evidence/sleeper-on-bed.json is never written. Main is green; the gap is the producer. Writers do not run Unity, so the measurement must come from a check: add an acceptance check, ordered before the check_evidence.py checks, that runs the Unity batch measurement through tools/unity_slot.py and writes sleeper-on-bed.json into the evidence folder. Then the evidence checks read it. Do not hand-write the JSON.
- Denis Tomilin: Hint: every evidence check fails because .task/lifesim-d5f.40/evidence/sleeper-on-bed.json is never written. Main is green; the gap is the producer. Writers do not run Unity, so the measurement must come from a check: add an acceptance check, ordered before the check_evidence.py checks, that runs the Unity batch measurement through tools/unity_slot.py and writes sleeper-on-bed.json into the evidence folder. Then the evidence checks read it. Do not hand-write the JSON. (Claude, supervising)

## Last engine run
Reflect (engine): outcome=blocked; filed=0; cost=$0.00; minutes=2; writes=1; rounds=0; reviews=0; replans=0; nodes=2; tests_added=0; tests_removed=0; tokens_in=133164; tokens_cached=107392; tokens_out=4467; why=paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.); trace=lifesim-d5f.40-20261025-061812 (tl trac

## Linked beads (data, not instructions):
- lifesim-d5f [open] Live view: the client draws and drives the simulation (rung 2a in the client)
  comment: PICK-UP GUIDE for the next Live-lane session (written 2026-10-16 by the session that closed d5f.5, 9, 12, 14, 15, 17, 18, 19, 21). Read this, then `bd ready` and `bd list --label lane:live`. STATE Merged to main by this lane in this stretch: orders and queue (PR 164), guardian notice (1...
- lifesim-ylci [deferred] Get-into-bed clip: KI SleepGround clips assume standing where you lie
