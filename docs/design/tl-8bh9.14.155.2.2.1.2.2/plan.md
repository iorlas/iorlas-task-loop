# Header
Task: tl-8bh9.14.155.2.2.1.2.2; base: 61cc8e66744c2e70bbddcd5431dd7933b7421f4c
Depth: medium; three behaviours. No missing decision or unlanded dependency. Evidence: 12 calls. Size: 12 changed files including tests and plan, 3 behaviours, ~55 implement calls.

## Outcome and non-goals
Release custody after verified base parking, with safe replay after reuse. Cleanup already preserves work/ignored bytes and resumes interruptions. Exclude accepted-result delivery, scheduling, publication and shelf changes.

## Settled decisions
- `Record.base` is authoritative, independently of source and target.
- Preserve completed cleanup at its saved/source HEAD before base parking.
- Use the supplied `park(base, clean_keep=(), keep_ignored=True)` contract and retain ignored identities/protection.
- Store release intent/result inside existing `save_data`; no SQL schema/version change.
- Commit completion and deletion together; historical reads authorize no effects.
- Keep unfinished work's locks and fences.

## Open decisions
- None.

## Change map
- `src/taskloop/land_conflict/release_models.py` (new): `Release`, `ReleasePhase`; integrate with `Save`/store.
- `src/taskloop/land_conflict/release.py` (new): `ReleaseSaved`; integrate in `_saved_result`.
- `src/taskloop/land_conflict/models.py`: `Save.release`, validate cleanup and work identity.
- `src/taskloop/land_conflict/store.py`: `save`, release transitions; new `completed` read and atomic `release`.
- `src/taskloop/land_conflict/execute.py`: `execute`, `_saved_result`; replay/release routing.
- `src/taskloop/land_conflict/cleanup.py`: consult `CleanupSaved._park`, `_current`.
- `src/taskloop/land_conflict/cleanup_models.py`: consult `Cleanup`, `transition` prerequisites.
- `src/taskloop/land_conflict/abort.py`: reuse `AbortMerge.observe` for independent evidence.
- `src/taskloop/land_conflict/abort_models.py`: reuse `Checkout` expectations.
- `src/taskloop/land_conflict/preserve.py`: consult `stopped`, `verified` and fences.
- `src/taskloop/land_conflict/reservation_store.py`: consult `owns`, `holds_source`.
- `src/taskloop/land_conflict/admit.py`: consult `admit`, producer of base and caller of `find`/`insert`.
- `src/taskloop/factory_schema.py`: consult `land_conflict`; retain its durable row.
- `src/taskloop/setup_store.py`: consult `SetupStore._held`, caller of `owns`.
- `src/taskloop/land_store.py`: consult `insert`, caller of `holds_source`.
- `src/taskloop/slot_state.py`: consult `SlotState` used by the observer.
- `tests/steps/land_conflict_bench.py`: `ExecutionCase`, add completed-save inspection and reuse setup.
- `tests/steps/test_land_conflict_release.py` (new): exercise `ExecutionCase.resume` and atomic store completion.
- `tests/steps/test_land_conflict_cleanup.py`: adapt `retained` and resume assertions.
- `tests/steps/test_land_conflict_abort.py`: adapt `retained` and resume assertions.
- `tests/steps/test_land_conflict_save.py`: adapt `saved`; preserve accepted custody.
- `tests/steps/test_land_conflict_restart.py`: retain terminal replay coverage.
- `tests/steps/test_land_conflict_execute.py`: consult stale-key/accepted-custody callers.

## Read list
- `src/taskloop/land_conflict/execute.py:46-136` — executor, result routing and work producer.
- `src/taskloop/land_conflict/models.py:89-141` — saved identity and validation.
- `src/taskloop/land_conflict/store.py:22-85` — lookup, CAS writes and custody.
- `src/taskloop/land_conflict/store.py:88-134` — admission producer.
- `src/taskloop/land_conflict/cleanup.py:28-123` — cleanup and completion boundary.
- `src/taskloop/land_conflict/cleanup_models.py:12-47` — expectations and transitions.
- `src/taskloop/land_conflict/abort.py:72-106` — observation and overlaps.
- `src/taskloop/land_conflict/abort_models.py:15-44` — checkout model.
- `src/taskloop/land_conflict/preserve.py:30-99` — workers and retained identity.
- `src/taskloop/land_conflict/preserve.py:170-174` — object/ref verification entry.
- `src/taskloop/land_conflict/reservation_store.py:8-26` — custody consumers.
- `src/taskloop/land_conflict/admit.py:42-59` — admission and retained lookup.
- `src/taskloop/factory_schema.py:64-80` — durable row constraints.
- `src/taskloop/setup_store.py:117-129` — setup ownership consumer.
- `src/taskloop/land_store.py:177-185` — candidate custody consumer.
- `src/taskloop/slot_state.py:28-48` — slot identity and dirtiness.
- `tests/steps/land_conflict_bench.py:73-142` — executor/restart integration for new tests.
- `tests/steps/test_land_conflict_cleanup.py:44-163` — interruptions and success assertions.
- `tests/steps/test_land_conflict_abort.py:45-119` — pending custody and resume.
- `tests/steps/test_land_conflict_save.py:32-85` — preservation/custody assertions.
- `tests/steps/test_land_conflict_restart.py:90-109` — terminal replay.
- `tests/steps/test_land_conflict_execute.py:35-103` — accepted and stale-ownership callers.

## Contract
Add `Save.release: Release | None`. `Release` freezes `work: Work`, `before: Checkout`, `after: Checkout`, `result: Terminal`; `ReleasePhase.PENDING` advances only to `COMPLETE`. Require completed unaccepted preservation/cleanup and matching work/result. Output is detached at `Record.base`, index empty, merge absent, base tracked files plus frozen ignored identities. Reject base/ignored overlaps before effects.

Intent: verify stopped workers, retained object/ref, exact custody/work and cleanup checkout; persist input/output. Effect: outside transactions, park only a matching input. Independently observe repository/root/path/gitdir, HEAD, branch, index, merge, files and ignored identities/protection; disregard park's return as proof. Adopt matching output without repeating parking. Unknown/changed evidence retains custody with an explanation.

Result: `ConflictStore.release(key, previous, updated)` rechecks admission key, slot path/generation, reservation and saved-data CAS in one transaction; record completion and delete exactly one matching reservation or roll back both writes. Ordinary `save` cannot complete release. Preserve admission, merge result, saved object/ref and slot generation. No external effects inside the transaction.

`completed(key) -> Save | None` checks the full historical key and completed release independently of current custody. `execute` returns its result before locking, Git, setup or worker access. Other operations require live custody. Route pending release before cleanup's old-HEAD comparison. Without completion, missing/replaced custody authorizes no repair.

## Work packages
1. Add release models and store operations; new release tests cover rollback/stale writes. Files: `release_models.py`, `models.py`, `store.py`. Closes A2 and A3's durable state.
2. Add `release.py` and `execute.py` routing; new tests cover distinct bases, false park success, observation failures, overlaps and interruptions. Closes A1.
3. Extend bench and cleanup/abort/save/restart tests; forbid effects during replay after reuse. Closes A3 and regressions. Run focused tests as needed; last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, checking command success.

## Acceptance behaviours
A1. Parking proves detached admitted-base HEAD despite differing source/target, clean tracked/untracked state, absent merge and unchanged ignored bytes/protection. Completed parking is adopted after interruption; unknown/changed evidence or ignored overlaps retains custody without destructive retry.
A2. Matching custody is removed once with completion; failure between writes rolls back both. Stale token/generation/path/save or foreign custody changes neither. Saved work/ref and unrelated reservations survive.
A3. Restart returns the same terminal outcome; replay after reuse performs no lock, Git, setup, worker or reservation mutation. Forged keys/pending work remain fenced. Accepted merges and interrupted preservation/cleanup retain coverage.
