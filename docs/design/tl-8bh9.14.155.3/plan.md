# Header
Task: tl-8bh9.14.155.3; base: 145b2b682718090cfe1b34888d5d70a1bbcb48f6
Depth: medium
Reason: 3 behaviours. Owner decision: none missing. Dependencies: none explicitly unlanded.
Evidence budget: 12 model calls.
Size: 22 files, 3 behaviours, 90 implement calls.

## Outcome and non-goals
Promote a retained resolution into the candidate lifecycle with fresh validation and resumable delivery. Conflict admission/execution, unsuccessful cleanup, hand-started eligibility and landing policy are delivered. Accepted release and candidate consumption remain missing. Preserve original checked identities and task branch. Exclude scheduler changes, repeated plan/implementation and tracker synchronization changes.

## Settled decisions
- Preserve checked identities; consume the retained resolution.
- Fresh validation uses current target requirements.
- Delivery precedes close; summary remains read-only.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/handoff.py` — `Handoff`, `stopped`: return accepted results; distinguish waiting from terminal failure.
- `src/taskloop/land_conflict/execute.py` — `_saved_result`, `execute`: release accepted custody and recover completion.
- `src/taskloop/land_conflict/release_models.py` — `Release`: validate completed and terminal results.
- `src/taskloop/land_conflict/models.py` — `Save.consistent`: accept successful release transitions.
- `src/taskloop/land_conflict/release.py` — `ReleaseSaved`: park accepted work safely with ignored bytes protected.
- `src/taskloop/land_conflict/store.py` — `completed`, `find`: recover accepted results after release with exact identity fencing.
- `src/taskloop/land_target.py` — `made_s`, `squashed_onto`: use explicit resolved content through target movement.
- `src/taskloop/land.py` — `_made`, `_delivered`, `_pending`: consume resolution; prioritize candidates; force validation.
- `src/taskloop/land_check.py` — `inserted`, `Squash`: reserve validation for resolved input.
- `src/taskloop/hold_cause.py` — conflict cause: explain terminal retained failure without restart advice.
- `src/taskloop/round_land.py` — `land_passed`, `HOLDING`: consult retry/hold consumer.
- `src/taskloop/land_conflict/composition.py` — `conflict_handoff`, `land_ports`: wire result producer.
- `src/taskloop/cli_composition.py` — `_landed`: consult automatic caller/result adapter.
- `src/taskloop/cli_step.py` — `_land`: consult CLI caller.
- `src/taskloop/dash_land.py` — `build_land`: consult read-only caller.
- `src/taskloop/land_push.py` — `deliver`, `observed`: reuse target retry and delivery adoption.
- `src/taskloop/land_close.py` — `closed`: reuse close adoption.
- `tests/steps/test_land_conflict_handoff.py` — resolution scenarios: replace successful-refusal expectations.
- `tests/steps/test_round_land.py` — hold/retry scenarios: assert actual decision and single hold.
- `tests/steps/land_bench.py` — `LandBench`: extend semantic fault injection if needed.
- `tests/steps/test_land_resolved.py` (new) — race/crash scenarios through `LandBench` and handoff fixtures.
- `docs/design/tl-8bh9.14.155.3/plan.md` — implementation contract.

## Read list
- `src/taskloop/land.py:205-350` — candidate creation, continuation and close ordering.
- `src/taskloop/land_conflict/handoff.py:19-69` — admission/resume/result conversion.
- `src/taskloop/land_conflict/execute.py:49-148` — result producer.
- `src/taskloop/land_conflict/release.py:19-64` — parking reconciliation.
- `src/taskloop/land_conflict/release_models.py:11-37` — release invariants.
- `src/taskloop/land_conflict/models.py:85-151` — saved reference and release invariants.
- `src/taskloop/land_conflict/store.py:35-145` — historical results, save fencing and retained lookup.
- `src/taskloop/land_conflict/cleanup.py:29-44` — existing verified checkout observer.
- `src/taskloop/land_conflict/preserve.py:160-185` — ref verification.
- `src/taskloop/land_target.py:22-81` — target requirements, squash and gate checks.
- `src/taskloop/land_check.py:98-168` — settled versus reserved candidate admission.
- `src/taskloop/land_store.py:35-105` — existing immutable candidate/input linkage.
- `src/taskloop/land_push.py:173-230` — bounded retry, adoption and delivery reconciliation.
- `src/taskloop/land_close.py:29-91` — delivery reason and idempotent close.
- `src/taskloop/merge/models.py:117-140` — explained execution result types.
- `src/taskloop/round_land.py:28-69` — retry/hold consumer.
- `src/taskloop/hold_cause.py:103-119` — obsolete conflict advice and adjacent causes.
- `src/taskloop/land_conflict/composition.py:33-62` — production handoff and land composition.
- `src/taskloop/cli_composition.py:179-196` — automatic land wiring and result adapter.
- `src/taskloop/cli_step.py:259-267` — direct CLI consumer.
- `src/taskloop/dash_land.py:29-48` — dashboard summary consumer.
- `tests/steps/test_land_conflict_handoff.py:35-128` — execution fixture and existing conflict invariants.
- `tests/steps/test_round_land.py:104-149` — holds, explanation and retry contracts.
- `tests/steps/land_bench.py:118-245` — shared land world and observable effects.
- `tests/steps/land_conflict_bench.py:1-120` — execution fixture used by handoff tests.

## Contract
`Handoff` returns `Completed | Failed | None` on lookup and `Completed | Failed` on start. Verify commit/source/target against retained record/ref. Encode typed causes at `Failed`; running/uncertain work stays retryable.

Accepted release stores work, before/after checkouts and `Completed` in save/release. Validate `Phase.COMPLETE` and retained ref; preserve terminal invariants. Persist intent, park outside transactions, observe checkout, then atomically complete release/remove reservation. Mismatch retains custody; historical reads cannot authorize checkout effects.

Admission retains checks linkage and stores target/candidate/required checks. Existing wrappers build from resolved content; inspect its gate and disable `same_tree` settlement. Missing validation time leaves resolution recoverable. Resume candidates before execution.

Moved main permits at most one replacement per invocation from accepted content, with current requirements and fresh checks. A new textual conflict stops with retained evidence, without repeating plan/implementation. Repeated movement is retryable. Observe candidate containment before another push and tracker completion before another close. Reuse stored fields and shelf APIs.

## Work packages
1. Conflict models/store/release/execute/handoff: test accepted save, park and custody-release interruptions; closes acceptance 1's restart conditions.
2. Land/target/check/composition: test resolved admission and failed fresh checks; closes acceptance 1's validation conditions.
3. New `test_land_resolved.py` and land orchestration: cover moved target, candidate resume and push/close interruptions; closes acceptance 2.
4. Hold explanation and round tests: verify actual decisions and CLI/dashboard integration; closes acceptance 3. Finally run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each.

## Acceptance behaviours
1. Accepted resolution retains its ref, safely releases custody and validates fresh without changing checked identities; restart at save/park/admission/check boundaries cannot deliver unchecked content or repeat plan/implementation.
2. Moved-target replacements retain resolved edits and validate fresh; push/close interruptions adopt effects, confirming one delivery/completion without repeating successful validation or agent execution.
3. Active/uncertain work stays retryable; terminal decisions produce accurate status and one hold without automatic restart; summary performs no execution, admission, validation, push or close.
