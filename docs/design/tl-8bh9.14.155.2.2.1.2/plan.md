# Header
Task: tl-8bh9.14.155.2.2.1.2; base: 28400434144adcee7c7e4728a1e6352e5f255c83.
Depth: medium; 3 behaviours. No missing decision or unlanded dependency. Evidence: 12 model calls.
Size: 13 changed files including tests/plan, 3 independent behaviours, about 70 model calls per implement attempt.

## Outcome and non-goals
Finish terminal conflict cleanup, park at the admitted base, and release custody. Retention and abort reconciliation already exist; continue from their verified result. Preserve the terminal reason/explanation. Exclude candidate acceptance, publication, tracker changes, task-branch saves and general slot release. Successful resolutions remain reserved.

## Settled decisions
- Reuse the retained conflict ref and immutable save; do not move the checked task ref.
- Completed abort authorizes cleanup, not release.
- Pin ignored paths before changing tracked ignore rules. Never overwrite ignored data to reach the base.
- Remove only recorded tracked/untracked content already durably saved.
- Park at `Record.base`; verify the checkout rather than trusting the returned SHA.
- Extend the structured save payload; no SQL table/column changes.
- Release terminal work only; repeated admission returns the retained operation.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/release_models.py` (new): `Release`, `ReleasePhase`; expectations/transitions integrated by `Save`/`ConflictStore`.
- `src/taskloop/land_conflict/release.py` (new): `ReleaseConflict`; reconcile cleanup/parking and invoke store release.
- `src/taskloop/land_conflict/checkout.py` (new): observation extracted from `AbortMerge._observe`, shared with release.
- `src/taskloop/land_conflict/abort.py`: `AbortMerge`; use the shared observation without changing abort authorization.
- `src/taskloop/land_conflict/models.py`: `Save`; validated release progress bound to saved identity.
- `src/taskloop/land_conflict/store.py`: `ConflictStore.save/load/saved`; transitions, atomic release and completed-result lookup.
- `src/taskloop/land_conflict/execute.py`: `execute`, `_execute`, `_saved_result`; resume release before save/abort replay.
- `tests/steps/test_land_conflict_release.py` (new): `ExecutionCase` integration; interruption, parking and release scenarios.
- `tests/steps/test_land_conflict_abort.py`: terminal assertions distinguish interrupted abort custody from completed release.
- `tests/steps/test_land_conflict_save.py`: retain save/ref assertions while allowing the terminal path to park and release.
- `tests/steps/test_land_conflict_restart.py`: terminal replay after release performs no further cleanup.
- `tests/steps/test_land_conflict_execute.py`: terminal release and successful-resolution custody expectations.
- `docs/design/tl-8bh9.14.155.2.2.1.2/plan.md`: scope/acceptance.

Callers/producers: both `_execute` branches call `_saved_result`, which calls `Preservation`/`AbortMerge`; both write `Save`. `admit` calls `find/insert`. `ExecutionCase.resume/restart` calls/constructs execution ports; save/abort tests intercept `save`. Consult `slot_release.free` for deletion.

## Read list
- `src/taskloop/land_conflict/execute.py:46-136` — dispatch/custody.
- `src/taskloop/land_conflict/abort.py:30-106` — abort/observation.
- `src/taskloop/land_conflict/abort_models.py:15-44` — checkout model.
- `src/taskloop/land_conflict/models.py:81-127` — save invariants.
- `src/taskloop/land_conflict/store.py:17-79` — lookup/CAS.
- `src/taskloop/land_conflict/store.py:99-131` — reservation producer.
- `src/taskloop/land_conflict/reservation_store.py:8-25` — custody predicates.
- `src/taskloop/land_conflict/preserve.py:108-185` — save verification.
- `src/taskloop/land_conflict/admit.py:42-75` — retained admission.
- `src/taskloop/slot_state.py:28-48` — slot identity.
- `src/taskloop/slot_release.py:143-162` — park caller/deletion.
- `src/taskloop/wip.py:145-204` — existing save/park.
- `tests/steps/land_conflict_bench.py:73-142` — execution/reopen.
- `tests/steps/test_land_conflict_abort.py:33-124` — interruptions.
- `tests/steps/test_land_conflict_save.py:33-78` — saved bytes.
- `tests/steps/test_land_conflict_restart.py:30-100` — replay.
- `tests/steps/test_land_conflict_execute.py:35-115` — result/custody.
- `/home/iorlas/.local/share/task-loop/checkouts/iorlas-task-loop/.venv/lib/python3.15/site-packages/git_porcelain/real.py:346-418` — effect API.
- `/home/iorlas/.local/share/task-loop/checkouts/iorlas-task-loop/.venv/lib/python3.15/site-packages/git_porcelain/fake.py:389-449` — delegation.
- `/home/iorlas/.local/share/task-loop/checkouts/iorlas-task-loop/.venv/lib/python3.15/site-packages/git_porcelain/fake_write.py:222-240` — park contract.
- `/home/iorlas/.local/share/task-loop/checkouts/iorlas-task-loop/.venv/lib/python3.15/site-packages/git_porcelain/real_write.py:289-310` — ignored pinning.

## Contract
`Save.release` holds frozen pydantic `Release`: operation/work identity, base, terminal result, retained commit/ref, checkout expectations, ignored path/blob identities and authorized removable paths. `ReleasePhase` enumerates ignore pinning, tracked cleanup, untracked cleanup, parking and completion. Transitions preserve inputs and require observation.

Intent: under the slot lock verify stopped workers, reservation/generation/token, repository/path/gitdir, terminal work, complete save and completed abort when needed. Persist each effect's expectations first. Pin ignored paths with literal exclude patterns; reject file/directory collisions with tracked destinations before cleanup.

Effect: pin exclusions, hard reset saved tracked edits at the recorded HEAD, clean only authorized saved untracked paths, then `park(base, keep_ignored=True)` without unrestricted cleaning. Recheck identity/save fences; run effects outside write transactions. Retry adopts observed results or finishes authorized effects. Partial cleaning is adoptable only for recorded removals with unchanged survivors. Foreign/unreadable states retain custody with an explained outcome.

Result: verify detached base, no merge, matching tracked tree/index, removed leftovers and unchanged ignored bytes. One transaction fences ownership, records completion and calls `slot_release.free`; failure rolls both writes back. Completed lookup accepts only the exact key without `owns`. Replay returns the stored terminal result without checkout/process/reservation effects, including after slot reuse. Pending release requires custody.

## Work packages
1. Models/store/checkout/abort: durable transitions and completed lookup; preserve abort authorization. Closes A1/A3.
2. Release/executor: reconcile cleanup/parking, verify and finish atomically. Closes A1-A3.
3. Release and affected abort/save/restart/execute tests: interrupt before/after effects and completion; reopen the database; inject identity/ref/byte changes. Closes A1-A3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both pass.

## Acceptance behaviours
A1. Cleanup interruption/reopen retains tracked edits, deletions and untracked bytes in the same saved object and ignored bytes in place despite disappearing ignore rules; no repeated agent invocation/save.
A2. Saved tracked edits do not block checkout; parking independently verifies the detached admitted base, clean index and no merge. Ignored collisions, foreign edits, ref movement or unexpected results retain custody with an explanation.
A3. Exactly the matching reservation is deleted once, atomically with its result. Restart/replay leaves reused slots and other reservations untouched; successful resolutions remain reserved.
