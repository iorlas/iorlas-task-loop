# Header
Task: tl-8bh9.14.155.2.2.1.2.1; base: 9719b1fc1ee1cde800fee37458c4b6ec2aeb7ea3.
Depth: small; one cleanup behaviour. No missing decision or explicitly unlanded dependency. Evidence: 6 model calls.
Size: 9 files including tests/plan; 1 behaviour; 45 implement model calls.

## Outcome and non-goals
Resume cleanup while retaining saved work, ignored bytes and custody. Preservation and abort reconciliation already exist. Final parking at the admitted base and release belong to the chained task; accepted results bypass cleanup.

## Settled decisions
- Freeze ignored identities before abort changes ignore rules; pin worktree-local exclusions.
- Clean at the retained HEAD or abort-result HEAD.
- Use existing save_data; no schema version change.
- Shelf below means `~/.local/share/task-loop/checkouts/iorlas-task-loop/.venv/lib/python3.15/site-packages/git_porcelain`.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/cleanup_models.py` (new): Cleanup, CleanupPhase using Checkout.
- `src/taskloop/land_conflict/cleanup.py` (new): CleanupSaved integrates Preservation and AbortMerge.
- `src/taskloop/land_conflict/models.py`: validate Save.cleanup.
- `src/taskloop/land_conflict/store.py`: ConflictStore.save cleanup transitions.
- `src/taskloop/land_conflict/execute.py`: _saved_result routes both AbortMerge callers and replay.
- `src/taskloop/land_conflict/abort.py`: AbortMerge tolerates recorded exclusions only.
- `tests/steps/test_land_conflict_cleanup.py` (new): ExecutionCase restart/refusal coverage.
- `tests/steps/test_land_conflict_abort.py`: retain abort guarantees.
- This plan: acceptance.

## Read list
- `src/taskloop/land_conflict/execute.py:63-139`: producer and both abort callers.
- `src/taskloop/land_conflict/models.py:81-143`: Save validation.
- `src/taskloop/land_conflict/store.py:35-80`: save CAS and custody.
- `src/taskloop/land_conflict/abort.py:24-114`: effect reconciliation and observations.
- `src/taskloop/land_conflict/abort_models.py:14-48`: Checkout and transition.
- `src/taskloop/land_conflict/preserve.py:21-173`: saved-object verification and liveness.
- `src/taskloop/land_conflict/reservation_store.py:8-21`: exact reservation predicate.
- `tests/steps/land_conflict_bench.py:75-100`: execution fixture integration.
- `tests/steps/test_land_conflict_abort.py:33-72`: mixed file states and interruptions.
- `tests/steps/test_land_conflict_abort.py:205-268`: failure and transition contracts.
- Shelf `fake_write.py:222-241`: collisions and park order.
- Shelf `fake.py:388-405`: exclusions.
- Shelf `real.py:410-418`: park delegation.

## Contract
Intent: verify preservation and process stop; CAS Cleanup into Save with Work, checkout expectations and ignored path/blob identities. CleanupPhase covers exclusion, parking and completion; retention facts stay immutable.
Effect: fence custody outside transactions; pin literal ignored paths, reconcile abort, then park at cleanup HEAD with clean_keep=() and keep_ignored=True. Verify saved bytes first. Record observable intermediate states and adopt completed effects on replay.
Result: verify detached HEAD, clear index/merge state, removed saved local paths and unchanged ignored bytes before completion CAS. Foreign changes, live workers and collisions yield explained Unavailable with custody retained. Replay never launches resolution or changes reservations.

## Work packages
1. Models/store/executor/abort: typed intent and transitions (A1).
2. Cleanup and tests: fence effects; interrupt before/after effects and completion persistence (A1). Run just check and just test once each, last.

## Acceptance behaviours
A1: Restart at each boundary retains saved tracked/untracked content in the verified object/ref and ignored bytes in place, reaches clean detached cleanup HEAD, keeps exact custody, and refuses foreign changes without rerunning resolution.
