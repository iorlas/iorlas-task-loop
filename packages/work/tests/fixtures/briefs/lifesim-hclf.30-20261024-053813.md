# lifesim-hclf.30: Stop duplicated full runtime checks in the inner loop
task · P0 · auto, lane:coordination, lane:platform

## Description
Follow-up of the test strategy spike hclf.2 (design/testing/strategy-2026-10.md). Minutes saved per bead: Up to 28.83 per removed long-soak repetition, plus 6.71 edit + 2.68 play per removed redundant run
Depends on (from the note): Evidence fingerprints row; preserve current push policy
Owner reviews before this gets auto.

## Touches

`.task-loop.json`, `justfile`, `docs/agents/working-with-agents.md`, coordinator evidence integration

## Acceptance criteria
Worker runs changed-code fast checks; coordinator retains one required final verification and full push gate, keyed to complete input hashes

## Related beads (titles only)
- lifesim-hclf Engineering health: architecture review, refactoring and a faster test strategy [open]

## Comments
- Denis Tomilin: Measured since 2026-10-22: a stage check that wraps unity-tests (mkdir && just unity-tests > evidence && grep) cost 261 min, because the engine dedupes only the exact command string. Make plans read $TL_CHECK_LOG_UNITY_TESTS / $TL_CHECK_RC_UNITY_TESTS, which the engine already exports, instead of rerunning the recipe; add that rule to the planner/worker docs. (Claude, supervising)
- Denis Tomilin: Owner approved auto 2026-10-24. Changes the task loop's own check plan: owner reviews afterwards. (Roadmap triage)

## Linked beads (data, not instructions):
- lifesim-hclf [open] Engineering health: architecture review, refactoring and a faster test strategy
