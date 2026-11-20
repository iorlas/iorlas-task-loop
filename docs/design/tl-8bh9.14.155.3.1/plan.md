# Header
Task: tl-8bh9.14.155.3.1
Base: 6eb05ff38b6d7305a7c67df52b6f0ca4ea108eca
Depth: medium
Reason: persist completion; safely release custody.
Decision missing: no. Dependency unlanded: no.
Evidence budget: 12 model calls.
Size: 9 changed files; 2 behaviours; 45 implement calls.

## Outcome and non-goals
Accepted results remain reachable after slot release and restart. Preservation already retains the accepted commit; terminal release already atomically records its result and removes its reservation. Extend that path to accepted completion. Candidate validation, target movement, push/close reconciliation and terminal holds remain outside this split; checked task refs and delivery state stay unchanged.

## Settled decisions
- Reuse save, cleanup and release; no schema version change.
- Retain the accepted commit/ref independently of base parking.
- Protect ignored paths through cleanup; accepted work never enters abort.
- Replay completed release independently of current slot ownership.
- Keep the existing handoff delivery boundary.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/models.py` — `Save.consistent`, `consistent_release`: allow accepted cleanup/release; keep abort unfinished-only.
- `src/taskloop/land_conflict/release_models.py` — `Release.result`, `consistent`: validate `Completed | Terminal` against exact work.
- `src/taskloop/land_conflict/cleanup.py` — `CleanupSaved.__call__`, `_resume`: carry accepted results through protected cleanup.
- `src/taskloop/land_conflict/release.py` — `ReleaseSaved`: carry either result through base parking and release.
- `src/taskloop/land_conflict/execute.py` — `_execute`, `_saved_result`: resume saves before merge; complete after release.
- `tests/steps/test_land_conflict_execute.py` — accepted assertions: expect base parking and released reservation.
- `tests/steps/test_land_conflict_save.py` — `saved`, accepted cases: separate retained commit from slot HEAD.
- `tests/steps/test_land_conflict_accepted_release.py` (new) — exercise `ExecutionCase`, `execute`, `ConflictStore` across interruptions and reuse.
- `src/taskloop/land_conflict/store.py` — consult `save`, `release`, `completed`, `_release_admission`: atomic storage boundary.
- `src/taskloop/land_conflict/preserve.py` — consult `Preservation._save`, `verified`: retained commit producer.
- `src/taskloop/land_conflict/cleanup_models.py` — consult `Cleanup`, `transition`: snapshots and ignored identities.
- `src/taskloop/land_conflict/abort.py` — consult `AbortMerge.observe`: checkout observer only.
- `src/taskloop/land_conflict/abort_models.py` — consult `Checkout`: snapshot shape.
- `src/taskloop/land_conflict/reservation_store.py` — consult `owns`, `holds_source`: reservation predicates.
- `src/taskloop/merge/models.py` — consult `Work`, `Completed`, `Terminal`: result contracts.
- `src/taskloop/merge/start.py` — consult `Merge._done`, `_finish`, `_attach`: completion producer.
- `src/taskloop/land_conflict/composition.py` — consult `conflict_handoff.execution`: production caller.
- `src/taskloop/land_conflict/handoff.py` — consult `Handoff.resume`, `start`, `stopped`: result consumers.
- `tests/steps/land_conflict_bench.py` — consult `ExecutionCase.resume`, `restart`: caller and restart fixture.
- `tests/steps/test_land_conflict_release.py` — consult release callers and interruption hooks.
- `tests/steps/test_land_conflict_cleanup.py` — consult `ConflictStore.save` hooks.
- `tests/steps/test_land_conflict_drain.py` — consult park/release hooks.
- `tests/steps/test_land_conflict_handoff.py` — consult executor integration.

## Read list
- `src/taskloop/land_conflict/models.py:83-155` — save invariants.
- `src/taskloop/land_conflict/release_models.py:12-38` — result validation.
- `src/taskloop/land_conflict/cleanup.py:20-120` — ignored protection and parking.
- `src/taskloop/land_conflict/release.py:16-64` — release effects.
- `src/taskloop/land_conflict/execute.py:47-141` — dispatch and replay.
- `src/taskloop/land_conflict/store.py:34-119` — atomic release.
- `src/taskloop/land_conflict/store.py:181-187` — admission fence.
- `src/taskloop/land_conflict/preserve.py:46-99` — accepted checkout checks.
- `src/taskloop/land_conflict/preserve.py:108-185` — object/ref persistence.
- `src/taskloop/land_conflict/cleanup_models.py:18-47` — snapshots.
- `src/taskloop/land_conflict/abort.py:72-89` — observer.
- `src/taskloop/land_conflict/abort_models.py:15-25` — checkout fields.
- `src/taskloop/land_conflict/reservation_store.py:8-26` — ownership.
- `src/taskloop/merge/models.py:78-139` — result types.
- `src/taskloop/merge/start.py:104-130` — completion producer.
- `src/taskloop/land_conflict/composition.py:33-54` — production caller.
- `src/taskloop/land_conflict/handoff.py:30-61` — consumers.
- `tests/steps/land_conflict_bench.py:83-142` — restart fixture.
- `tests/steps/test_land_conflict_execute.py:30-45` — accepted expectations.
- `tests/steps/test_land_conflict_save.py:28-41` — save assertions.
- `tests/steps/test_land_conflict_save.py:99-107` — accepted replay.
- `tests/steps/test_land_conflict_release.py:202-327` — interruption/reuse patterns.
- `tests/steps/test_land_conflict_cleanup.py:115-130` — save hooks.
- `tests/steps/test_land_conflict_drain.py:137-203` — release hooks.
- `tests/steps/test_land_conflict_handoff.py:108-150` — handoff integration.

## Contract
`Release.result` becomes `Completed | Terminal`. Completed results require `Work.phase == Phase.COMPLETE` and exact commit/source/target/explanation; terminal validation stays exact. `Save` binds release work to its key, repo, slot, inputs, completed cleanup and accepted commit. Accepted cleanup requires a completed save, clean detached saved HEAD, no merge and exact completed work. Existing phases and fields suffice.

Intent: retain commit/ref, then freeze cleanup snapshots and ignored identities. Effect: protect ignored files and reconcile cleanup. Result: completed cleanup of the exact accepted checkout. Recheck worker, reservation, repository, ref and files before effects.

Intent: persist `Release(PENDING)` with result and before/after checkouts. Effect: park at the admitted base; adopt observed output after interruption. Result: `ConflictStore.release` writes `COMPLETE` and removes the matching reservation atomically. Foreign/ambiguous evidence returns an explained existing refusal/wait outcome and retains custody.

After release, replay precedes live reservation/merge/checkout reads. Pending saves resume even after parking away from the accepted HEAD, without merge setup or another resolution.

## Work packages
1. Update the five source files above together to carry accepted results through save/cleanup/release; close A1 and establish A2's resumption path.
2. Update the two existing tests and add `test_land_conflict_accepted_release.py` through the bench. Close A1/A2 with a distinct admitted base, ignored files, reopened database, before/after interruptions, transaction rollback and foreign custody; preserve terminal regressions. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each; both must pass.

## Acceptance behaviours
A1. Accepted completion durably retains the exact commit, source, target and explanation; parks the detached slot at its independently admitted base with ignored bytes intact; atomically releases only its reservation; leaves checked task refs and delivery state unchanged.
A2. Interruption during save, cleanup, release intent, parking or release transaction resumes the same resolution without another agent run or repeated completed effect; changed worker/ref/files/repository/reservation evidence prevents release; committed completion replays the same result after slot reuse without inspecting or mutating its new owner's work.
