# Header
Task: tl-8bh9.14.155.3.3; base: f548d5ee858797fb472983bffd3d47b6d0a88bd5
Depth: medium
Reason: 3 behaviours. Owner decision: none; predecessor landed.
Evidence budget: 12 model calls.
Size: 3 changed files; 3 independent behaviours; ~45 implement model calls.

## Outcome and non-goals
Resolution retention, fresh validation and generic push/close adoption exist. Remove the target-movement veto and cover interrupted delivery of resolved candidates through shared land. Exclude admission/release redesign, status and terminal-hold policy, tracker synchronization, schema and dashboard changes.

## Settled decisions
- Consume verified `Completed.commit`; retain its original source and target as immutable resolution evidence.
- Keep the checked commit and task branch unchanged; candidate rebuilding uses retained resolved content.
- Rebuilt resolved candidates receive fresh current-target checks, including when their tree equals the checked tree.
- A new merge conflict stops delivery with the accepted resolution intact; do not start another resolution agent or fall back to the checked commit.
- Reuse delivery observation, tracker observation and fenced recording; an interrupted effect is adopted before it can be repeated.
- Preserve existing bounded candidate rebuilding and non-forced push behaviour.

## Open decisions
- None.

## Change map
- `src/taskloop/land.py`: edit `_made` to allow target movement; consult `_delivered.again`, `_pending`, `_resumed`, `_tracker`, `_no_change`, `_closing`, `_withdrawn`, `_summary` for all delivery, observation and squash callers.
- `tests/steps/test_land_resolved_validation.py`: extend `completed`, `preserved` and scenarios for movement, actual renewed conflicts and interrupted effects.
- `docs/design/tl-8bh9.14.155.3.3/plan.md`: new implementation plan.
- `src/taskloop/land_target.py`: consult `squashed_onto`, `made_s` and gate/profile reads; retain existing source argument.
- `src/taskloop/land_conflict/handoff.py`: consult `Handoff.resume`, `_result`, verified completion producers.
- `src/taskloop/land_check.py`: consult `inserted`, `checked`, `released`, candidate lifecycle producers.
- `src/taskloop/land_push.py`: consult `deliver`, `observed`, `withdraw`, `reconcile_delivery`; retain observation and bounded retries.
- `src/taskloop/land_close.py`: consult `closed`, `_recorded`, called by `_closing`.
- `src/taskloop/land_store.py`: consult `LandRow`, `supersede`, `record_delivery`, `record_close` fences.
- `src/taskloop/tracker_client.py`: consult `_closed`, `tracker_claims.close`, observed close producers.
- `src/taskloop/land_conflict/composition.py`: consult `land_ports`, conflict/close port wiring.
- `src/taskloop/cli_step.py`: consult `land.land` caller; preserve request contract.
- `src/taskloop/round_land.py`: consult `landing.land` caller; preserve request contract.
- `src/taskloop/dash_land.py`: consult summary-only `land` caller; preserve read-only behaviour.
- `src/taskloop/drain/reconcile.py`: consult `reconcile_delivery` caller and tracker observation.
- `tests/steps/land_bench.py`: consult `Racing`, `LandBench`, race/effect injection.
- `tests/steps/land_conflict_bench.py`: consult `ExecutionCase.restart`, intact-DB restart.
- `tests/steps/test_land_push.py`: consult `Losing` and delivery adoption scenarios.
- `tests/steps/test_land_close.py`: consult `Losing` and close adoption scenarios.

## Read list
- `src/taskloop/land.py:192-341` — completion consumption, rebuilding, delivery and close ordering; edit `_made` here.
- `src/taskloop/land.py:350-365` — summary's separate `made_s` caller.
- `src/taskloop/land_target.py:22-82` — fetched target, source-aware squash and gate checks.
- `src/taskloop/land_conflict/handoff.py:44-88` — verified completion producer and conflict handoff.
- `src/taskloop/merge/models.py:117-120` — existing completion fields.
- `src/taskloop/land_check.py:83-101` — validation and release integration.
- `src/taskloop/land_check.py:151-159` — candidate insertion integration.
- `src/taskloop/land_push.py:88-230` — remote observation, recording, delivery retries, withdraw and drain observer.
- `src/taskloop/land_close.py:39-91` — fenced adoption and close invocation.
- `src/taskloop/land_store.py:78-111` — candidate identity and persisted effect facts.
- `src/taskloop/land_store.py:288-325` — supersession, delivery and close fences.
- `src/taskloop/tracker_client.py:157-172` — observe task status before closing.
- `src/taskloop/tracker_client.py:222-225` — injected close port.
- `src/taskloop/land_conflict/composition.py:57-62` — production port wiring.
- `src/taskloop/cli_step.py:257-267` — CLI land caller.
- `src/taskloop/round_land.py:50-62` — round land caller.
- `src/taskloop/dash_land.py:23-35` — summary caller.
- `src/taskloop/drain/reconcile.py:38-65` — recovery observer integration.
- `tests/steps/test_land_resolved_validation.py:24-216` — fixtures, preserved attribution, moved-target expectation and existing resume assertions.
- `tests/steps/land_bench.py:70-109` — target race and push injection.
- `tests/steps/land_bench.py:170-246` — tracker effects, ports, candidate and content inspection.
- `tests/steps/land_conflict_bench.py:104-116` — reopening the same database after interruption.
- `tests/steps/test_land_push.py:22-84` — lost delivery records and ancestry adoption examples.
- `tests/steps/test_land_close.py:26-108` — interrupted close and lost close record examples.

## Contract
No new public typed names or stored fields. `Completed` remains the accepted input; `LandRow.checked` is the checked task commit, `origin` the fetched target, and `commit` the candidate. Remove the target-equality veto: source-aware squash produces a current-target candidate or a typed conflict/failure, retaining completion evidence. Preserve required checks and gate consent.

Intent: persist candidate content and target before delivery. Effect: observe origin, then push only when needed, outside the store transaction. Result: `record_delivery` adopts the candidate or containing tip once. Movement supersedes the undelivered candidate and rebuilds from the same resolution with fresh validation; retries remain bounded.

Intent: record delivery before completion. Effect: the close adapter observes tracker status and closes only when necessary. Result: `record_close` adopts closed status once; final reruns have no effects. Unavailable observation records no success. Retained refs, branch, checked attribution and completion evidence survive failures.

## Work packages
1. Edit `land.py` and `test_land_resolved_validation.py` for target movement and renewed conflicts, asserting content, fresh checks and retained evidence. Closes A1.
2. In that test file lose the delivery record after push, reopen the database with fresh ports and cover origin at/beyond the candidate. Closes A2 through existing delivery code.
3. In that test file interrupt before close and lose its record after close; restart, adopt and verify final reruns have no effects. Closes A3 through existing close code. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both must pass.

## Acceptance behaviours
A1. Clean target movement at construction, validation or push time retains the resolved edits and new target changes, validates each rebuilt candidate against current requirements and lands; an actual renewed conflict preserves the resolution and leaves delivery untouched.
A2. After a push succeeds but its result is not recorded, intact-DB restart adopts the same resolved candidate from origin or a containing tip exactly once, without repeating resolution, validation or push.
A3. After delivery, restart finishes an unperformed close or adopts an already-performed close exactly once; a recorded final result repeats no Git or tracker effect and retains original checked attribution.
