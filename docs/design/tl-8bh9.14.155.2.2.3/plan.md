# Depth
Medium: two behaviours cover retaining conflict work and reconciling interrupted saves without loss or duplicate effects. No owner decision is missing; Part A of .155.2.2 is explicitly landed. Evidence budget: 12 model calls total. This assessment uses the supplied task text; the repository file inventory is context, not a list of requested edits.

## Size
Estimate: 10 changed files, including this plan, two new files, source and tests; 2 independent behaviours; 65 model calls for one implement attempt.

1. Conflict preservation: after confirmed stop, unfinished conflict files and both recorded merge inputs remain reachable through an operation-owned Git ref; a completed detached result is likewise retained. Acceptance: tests inspect saved bytes, deletions, ancestry, provenance and ref ownership, while the checked task ref, reservation and checkout contents remain intact.
2. Interrupted-save reconciliation: restart finishes the same durable save without losing work or duplicating accepted effects. Acceptance: failure injection before and after capture, object creation, ref update and result recording, followed by database reopen and repeated execution, yields the same retained commit and one completed save record; foreign changes refuse safely.

The necessary persisted save record requires a cohesive schema update, discovered during inspection. It supports these two behaviours rather than introducing a separate workflow. No implementation estimate exceeds the task's limits.

## Scope and existing integration
Part A supplies immutable admission facts, reservation fencing, detached merge execution and durable execution evidence. `land_conflict.execute.execute` is currently consumed directly by its focused tests; there is no production CLI/round caller to wire in this task. The shared merge engine returns terminal results before any conflict-specific preservation, and `wip.save` preserves onto the task branch. Calling that save unchanged would move the checked task ref and violate detached execution's contract.

Add the preservation use case inside `land_conflict`. Keep admission facts in `Record` immutable, merge progress owned by `MergeStore`, and conflict save intent/result owned by `ConflictStore`. Use the supplied meanings of task, attempt, slot, land and plan; saved work and hold retain their existing meanings. No new glossary term is proposed.

Abort, parking, reservation release, tracker changes, drain orchestration and public command integration belong to the later split work. This task leaves ownership in place and exposes a durable saved result those operations can consume.

## Implementation
1. Add validated save input/result models and a closed enum for save progress in `land_conflict/models.py`. Record the admitted key, repository/slot identity, source and target, observed HEAD, retained ref, expected prior ref, fixed commit timestamp/message/parents, captured tree and resulting commit as applicable. Use one codec at the store boundary. Save records identify preservation separately from an accepted merge result.
2. Add a nullable validated save-data column to `land_conflict` and bump factory schema version from the inspected 23 to the next unused version. Add fenced compare-and-swap store operations for save intent and completion; check reservation ownership in every write transaction. Do not alter immutable `Record` equality or use hold records for these facts. SQL and connections remain in the owning store. This is an incompatible persisted-state change: deployment drains old running attempts first, stops old entries, then deliberately discards the old database through the existing owning procedure. Preserve retained Git refs and evidence. No migration, backup reader or reconstruction from files.
3. Add **new** `src/taskloop/land_conflict/preserve.py`, one typed preservation operation used by the executor and available to the later release task. Its existing integration points are the conflict models/store, `execute.py`, `MergeStore` reads, slot observation and shelf Git APIs. Derive a valid operation-specific branch ref from the durable operation identity, under a dedicated prefix distinct from `task/`; keep the naming inside the Git-facing implementation. Never derive it from display text or accept a foreign ref as ours.
4. Under the executor's slot custody and reservation fence, reconcile setup and require confirmed stopped resolution workers before capture or index/ref mutation. Reobserve repository identity, slot path/gitdir, detached HEAD, merge inputs and `MERGE_HEAD`. A live or uncertain worker, changed reservation, unrelated merge or foreign ref returns an explained typed refusal/unavailability and keeps the work reserved. Existing terminal states do not bypass these checks.
5. For unfinished owned work, persist capture intent before staging unresolved entries for capture. Preserve working bytes, staged and unstaged edits, automatic merge changes, deletions and nonignored untracked files. Reuse the existing WIP provenance format and immutable source/target metadata; retain source, target and observed detached HEAD in the commit ancestry. Save on the operation ref, leaving the task branch unchanged. Do not reset, abort or park the checkout. Unsupported capture must retain the checkout and reservation and explain what prevented saving.
6. Freeze tree, parents, message and timestamp in a short transaction before commit creation. Create the object outside transactions, record the resulting SHA, then compare-and-swap the retained ref outside transactions. Commit creation with the same persisted inputs is idempotent. After a crash, observe the ref and verify exact commit/tree/provenance: adopt the intended effect if already present, retry if absent, refuse an unrelated value. Record completion in a second short transaction. Never overwrite a completed save with later unrecorded edits; report changed work and retain it in the slot for the owning follow-up.
7. For a clean completed detached merge, retain its existing result commit directly rather than making a WIP result. Use the same durable ref intent/reconciliation boundary. `Completed.commit` remains the actual accepted merge commit. For owned terminal results (owner answer, exhausted resolution, expired deadline or unsupported conflict), complete preservation before returning the terminal outcome; pending save failures remain retryable with the original merge reason recorded. On restart load and finish pending save state before returning a cached terminal/completed merge result or launching another agent. Reload current merge progress after `Merge.resume`; its input object can be stale. Never treat the preservation commit as an implementation/check/land result.

Keep native Python and shelf Git/process/lock ports; introduce no subprocess or signal path. Keep source files at most 400 lines, functions at most 80 and test files at most 800. No new dependencies, `Any`, casts or ignore escapes.

## Verification
Add **new** `tests/steps/test_land_conflict_save.py`, integrating with `land_conflict_bench.py` and the existing semantic Git fakes. Extend that bench only for real preservation scenarios and failure injection. Cover unresolved markers, partially edited files, staged/unstaged changes, automatic changes, deletions, untracked versus ignored files, both input commits, and completed detached results. Assert the checked task ref and reservation do not move, working bytes survive and preservation never launches another resolution process.

Inject interruption on both sides of every durable boundary: initial intent, staging/capture, frozen object inputs, object creation, recorded SHA, ref compare-and-swap and final save recording. Reopen the database using the bench's restart and repeat the owning operation. Check one retained SHA, one completed record and no duplicate agent call. Vary the clock across restarts to prove the timestamp is frozen. Test failed capture, unavailable Git/store, CAS rejection, foreign retained ref, changed slot/merge input, stale generation and live/unknown worker; all retain work and ownership with nonempty explanations. Assert Git effects happen outside write transactions. Preserve existing terminal/exhaustion and successful merge semantics in the executor/restart tests, adjusting whole-branch-map assertions only for the new retained prefix.

Run the focused preservation, execution, restart, WIP merge and schema refusal tests through the declared installed environment; use semantic fakes rather than live tests. Then run the required `just check` and `just test` gates. Do not invoke whole-suite/live tests separately. This planning attempt runs no implementation checks and claims no passing results.

## Read list
- `src/taskloop/land_conflict/models.py:1-76` — immutable admission producer and integration point for new validated save models.
- `src/taskloop/land_conflict/admit.py:30-76` — admission producer; preserve its key and immutable facts.
- `src/taskloop/land_conflict/store.py:20-90` — admission persistence and integration point for fenced save intent/result writes.
- `src/taskloop/land_conflict/reservation_store.py:8-26` — exact reservation predicate and source protection caller contract.
- `src/taskloop/land_conflict/execute.py:44-107` — owning executor, custody, environment reconciliation and save caller.
- `src/taskloop/merge/models.py:19-114` — existing merge phases, reasons, execution identities and immutable inputs.
- `src/taskloop/merge/start.py:24-89` — restart dispatch and cached terminal/completed outcomes.
- `src/taskloop/merge/start.py:104-130` — completed detached result acceptance and attachment effects.
- `src/taskloop/merge/start.py:173-216` — unsupported conflicts, capture baseline and terminal resolution producers.
- `src/taskloop/merge/resolve.py:33-119` — process-stop proof and interrupted execution capture semantics.
- `src/taskloop/merge/store.py:15-43` — current merge progress, CAS writes and process visibility.
- `src/taskloop/merge/git.py:11-48` — completed-merge provenance validation and shelf ref observation/CAS pattern.
- `src/taskloop/slot_state.py:29-138` — detached checkout facts and verified repository/slot observation.
- `src/taskloop/attempt_types.py:19-112` — existing checkout and file ports used by preservation.
- `src/taskloop/wip.py:28-92` — existing saved-work identity and provenance message helpers.
- `src/taskloop/wip.py:145-204` — preservation safety semantics and task-ref destination that cannot be reused unchanged.
- `src/taskloop/factory_schema.py:45-78` — schema version and conflict table edit point.
- `tests/steps/land_conflict_bench.py:43-136` — durable admission, semantic Git and database-reopen fixtures to extend.
- `tests/steps/merge_bench.py:16-33` — inherited semantic merge fake and detached HEAD reader used by the conflict bench.
- `tests/steps/test_land_conflict_execute.py:30-151` — executor callers, checked-ref assertions and ownership/process fences.
- `tests/steps/test_land_conflict_restart.py:30-201` — restart callers, failure injection and terminal outcomes to extend.
- `tests/steps/test_wip_merge.py:22-154` — retained bytes/ancestry and interrupted-save regression contracts.
- `tests/steps/test_schema_words.py:25-84` — version refusal contract for the persisted-state upgrade.

The ten estimated changed files are this plan; `land_conflict/models.py`, `store.py`, `execute.py`; `factory_schema.py`; `land_conflict_bench.py`; the executor and restart test modules; and the two new files identified above. Remaining read-list entries are bounded consultation/regression targets. Targeted caller searches may refine ranges if implementation discovers changed source.
