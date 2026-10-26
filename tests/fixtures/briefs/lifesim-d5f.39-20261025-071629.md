# lifesim-d5f.39: Lifer arrives at the object's front, turns, steps back and sits (no snap to the slot)
task · P2 · lane:live, needs-info

## Description
## Goal
The begin clip plays from where the route ended at the object's front.
## Context
d5f.23 owner question; needs object fronts (d5f.26).
## Done when
- defined after d5f.26 lands
## Touches
client/Assets/Features/Live/PoseLines.cs, RoutePlace.cs
## Out of scope
facing fix

## Acceptance criteria
A lifer walks to the cell in front of the object's use slot (the slot facing, as d5f.58 chooses it), turns to the slot facing, then plays the begin clip from there; no snap to the slot. A PoseTests-style test covers sit on the sofa and the bed; Play screenshot.

## Notes
## Decisions
- 2026-10-24 (ask lifesim-d5f.39-2) Re-planned 3 times; the engine stopped -> Allow one more planner run. This change is visual: the lifer's walk-up, turn, step back and sit play on screen. Do not claim logic_only. Name LiveShots in the stage's shots so the review gets frames of a lifer sitting on an object. If LiveShots cannot capture a sit mid-clip, say which frame it shows and why that is enough.
- 2026-10-24 (ask lifesim-d5f.39-3) The task needs inputs this factory does not have: - External coordinator evidence handoff is unavailable ... -> Drop those criteria as written. TL_CHECK_RC_* does not exist, and TL_CHECK_LOG_<ID> is set only while an acceptance check runs, never in a write session. Read the Unity test results inside an acceptance check through $TL_CHECK_LOG_UNITY_TESTS and $TL_CHECK_LOG_UNITY_PLAY_TESTS (the engine orders such a check after the check it reads). A failed check already fails the gate, so no RC variable is needed. Keep PoseShots for the visual proof.
Engine paused: paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)
Engine paused: paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.)

## Related beads (titles only)
- lifesim-d5f Live view: the client draws and drives the simulation (rung 2a in the client) [open]
- lifesim-d5f.38 Sitting lifer faces away from the sofa back (yaw conversion pinned by a test) [closed]

## Comments
- Denis Tomilin: Owner 2026-10-21 (playing Live): sink and shower are not approached from the right side. Bug filed as lifesim-d5f.58: the use cell is the first ring cell in scan order (src/Sim.Core/Modules/Lot/LotGrids.cs:162), not the front side. The front-side choice there and the object fronts here (d5f.26) need one design.
- Denis Tomilin: Not ready: needs deferred d5f.26 (object fronts as content) and its AC is a placeholder. Undefer d5f.26 with a design or rewrite on d5f.58's slot-facing front. (Chain review)
- Denis Tomilin: Rewrote the acceptance so one run can finish it. (Chain review)
- Denis Tomilin: Owner approved this auto batch in the roadmap session, 2026-10-24 ('yes yes'). (Roadmap triage)
- tl-551cf8ee: Resume (engine): the earlier work on task/lifesim-d5f.39 conflicts with origin/main. It is kept as the branch task/lifesim-d5f.39-stale-20261024-180914; the task starts again on origin/main with a fresh plan.
- Denis Tomilin: Allow one more planner run. This change is visual: the lifer's walk-up, turn, step back and sit play on screen. Do not claim logic_only. Name LiveShots in the stage's shots so the review gets frames of a lifer sitting on an object. If LiveShots cannot capture a sit mid-clip, say which frame it shows and why that is enough.
- Denis Tomilin: Replan cap hit over missing shots. Allowed one more run: visual change, name LiveShots in shots. (Claude, supervising)
- tl-551cf8ee: Resume (engine): the earlier work on task/lifesim-d5f.39 conflicts with origin/main. It is kept as the branch task/lifesim-d5f.39-stale-20261024-225533; the task starts again on origin/main with a fresh plan.
- Denis Tomilin: Drop those criteria as written. TL_CHECK_RC_* does not exist, and TL_CHECK_LOG_<ID> is set only while an acceptance check runs, never in a write session. Read the Unity test results inside an acceptance check through $TL_CHECK_LOG_UNITY_TESTS and $TL_CHECK_LOG_UNITY_PLAY_TESTS (the engine orders such a check after the check it reads). A failed check already fails the gate, so no RC variable is needed. Keep PoseShots for the visual proof.
- Denis Tomilin: Drop those criteria as written. TL_CHECK_RC_* does not exist, and TL_CHECK_LOG_<ID> is set only while an acceptance check runs, never in a write session. Read the Unity test results inside an acceptance check through $TL_CHECK_LOG_UNITY_TESTS and $TL_CHECK_LOG_UNITY_PLAY_TESTS (the engine orders such a check after the check it reads). A failed check already fails the gate, so no RC variable is needed. Keep PoseShots for the visual proof. (Claude, supervising)
- tl-551cf8ee: Lane (engine): the review step ran on the writer's own model family: reviewing openai's work with openai: no other family is up (claude logged out; xai out until Sun 25 Oct 12:00)
- Denis Tomilin: Play-test budget: your new play tests take long in the default lane (ShareableLoop about 137 s each; BothBodiesApproach 72 s). Keep each default-lane test under 30 s or mark it release/nightly lane. See lifesim-hclf.46. (Claude, supervising)
- tl-551cf8ee: Resume (engine): the earlier work on task/lifesim-d5f.39 conflicts with origin/main. It is kept as the branch task/lifesim-d5f.39-stale-20261025-052514; the task starts again on origin/main with a fresh plan.

## Last engine run
Reflect (engine): outcome=blocked; filed=0; cost=$0.00; minutes=3; writes=1; rounds=0; reviews=0; replans=0; nodes=2; tests_added=0; tests_removed=0; tokens_in=57783; tokens_cached=26880; tokens_out=3482; why=paused: no lane for write until 07:02:12 (no_lane: No worker lane is available. Hold the task; a few lines the orchestrator may write itself.); trace=lifesim-d5f.39-20261025-061744 (tl trace 

## Linked beads (data, not instructions):
- lifesim-d5f [open] Live view: the client draws and drives the simulation (rung 2a in the client)
  comment: PICK-UP GUIDE for the next Live-lane session (written 2026-10-16 by the session that closed d5f.5, 9, 12, 14, 15, 17, 18, 19, 21). Read this, then `bd ready` and `bd list --label lane:live`. STATE Merged to main by this lane in this stretch: orders and queue (PR 164), guardian notice (1...
- lifesim-d5f.38 [closed] Sitting lifer faces away from the sofa back (yaw conversion pinned by a test)
  closed: merged 3e14661cf700 to main: The code fix is done and committed as WIP 8615638e. It passed every stage-1 check plus 443/443 Unity tests on this tree. Only the Play proof is left. The last Play run did not crash because of the fix. The writer's own eval did it: `return w.Cold.Snapsho...
- lifesim-d5f.58 [closed] Lifers do not approach the sink and the shower from the front side
  closed: merged 2dfba7db0f5e to main: The front-approach fix is already on the branch (wip commits c37da613..a98a76f4). The shower and toilet are used from their front, a blocked front falls back to another side, and the overruled urgency guard is gone, so DeciderSystem matches base 53cc3447 again. A r...
- lifesim-hclf.46 [open] Play-test time budget: keep slow walkthroughs out of the default lane and flag tests over 30 s
