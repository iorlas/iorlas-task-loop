# Depth
Medium: abort reconciliation and parking reconciliation are two independently testable behaviours. No missing owner decision is identified. Conflict preservation (tl-8bh9.14.155.2.2.3) is a named dependency, not explicitly unlanded in the supplied task; source commit cdf44d72 includes its implementation. Evidence budget: 12 model calls total.

## Size
Estimated changed files: 11, including this plan, five source files and five test/helper files. Estimated model calls for one implement attempt: 65. Two independent behaviours:

1. Abort reconciliation. Acceptance: interrupt immediately before and after an owned merge abort and its durable result write, reopen the intact database, and resume without another resolution or save. The retained ref and its bytes/parents survive, and the reservation remains until parking is verified. Foreign merge inputs, changed files/ref, stale ownership, unsettled setup or unconfirmed worker exit prevent destructive effects.
2. Parking reconciliation and release. Acceptance: interrupt before and after parking and release recording, reopen and resume; observe an already completed park instead of repeating it, remove only the matching reservation exactly once, and return the original completed/terminal merge outcome on subsequent calls. Retained records, refs and work survive; changed slot identity or work prevents release.

These estimates include failure injection and focused regression coverage. Process-aware drain is a separate task and is not an additional behaviour here. No database schema version change is needed: typed release intent/result can use the existing conflict save JSON column.

## Scope and evidence
The task is Conflict release, tl-8bh9.14.155.2.2.1. Implement restartable cleanup of the detached conflict slot after its owning executor has durably preserved a completed or terminal merge. Use the supplied meanings of task, attempt, slot, worktree and land. The glossary further distinguishes reservation from slot custody and defines D as the admitted slot HEAD, the parking destination.

At cdf44d72, `execute` holds slot custody and reconciles setup before executing the merge. `Preservation` records a frozen tree, commit and retained ref through `SavePhase.COMPLETE`, and verifies the checkout still matches. It returns the merge outcome while retaining the reservation. There is no production caller of the detached executor outside its slice yet; its existing callers are focused tests. Candidate admission already uses `reservation_store.holds_source` to exclude a source while its conflict reservation exists. Keep that exclusion until release commits.

The shared implement/check release paths have different rows and ownership proofs. Their general parking helper refuses an active merge. Use those paths as safety references; the new operation belongs to `land_conflict`, whose store owns its tables. Do not route the detached conflict through an unrelated attempt release or return the source task's tracker claim.

## Implementation
Add **new** `src/taskloop/land_conflict/release.py` for the owning release operation. Its existing integration points are `execute._execute`/`_saved_result`, `Preservation`, `ConflictStore`, `Save`, and the reservation predicates. Add **new** `tests/steps/test_land_conflict_release.py`, using the existing execution bench and semantic Git/process fakes. All other changes are in the existing files identified below.

### Persist intent and retain the original outcome
Extend the typed save payload with release progress, using stdlib enums for closed phases and pydantic models at the database boundary. An initial absence of release intent means no release was requested; it must never authorize inferring progress from logs. Keep the frozen preservation identity/tree/commit immutable. Add separate store operations for release transitions rather than weakening `ConflictStore.save`'s monotonic save checks.

Record enough immutable facts to observe an interrupted effect: the exact attempt key and slot identity, retained ref/commit, saved pre-abort state, expected post-abort HEAD, destination `record.base`, and original completed/terminal result. The store supplies an exact-key retained read for a completed release without requiring a reservation that has already been removed. This read does not permit mutation or take over a later slot generation. Validate matching identity/token/generation even on repeated calls.

Use existing `land_conflict.save_data` for the validated release payload; do not add tables, bump the database version, reconstruct state from files, or add a fallback reader. A short write transaction records each intent, external Git effects run outside it, and a short fenced transaction records observed completion. Store methods compare the previous payload and exact reservation identity. Only the conflict store accesses conflict/reservation SQL for this operation.

### Abort under custody
Call release after preservation succeeds for an owned `Completed` or `Terminal` outcome. A preservation refusal or pending save returns as today and cannot reach abort. Preserve explicitly held/terminal work and its original cause; release of the slot does not make a task runnable or retry resolution.

Before destructive IO, recheck setup settlement, all recorded resolution process identities, slot custody, repository/gitdir/path, generation, detached HEAD, retained ref and saved working tree. Use the existing narrow process observations; any process not proven gone, including an unregistered capture, keeps ownership. Do not add spawn, signal, wait or drain orchestration.

Write abort intent before calling the owning Git worktree API. Abort only the recorded active merge with the recorded inputs and captured contents. Observe the resulting checkout before recording completion. If restart finds abort already finished, adopt only the expected clean detached post-abort state under that pending intent; do not recapture the reverted tree, make another save, or run resolution again. A naturally non-merging completed result skips abort after validating its saved state. A dirty non-merging terminal checkout must still exactly match the durable save before parking is allowed to replace those saved files. Foreign/extra edits always keep the reservation.

### Park, then release
Record parking intent with the admitted destination D. Verify the retained ref still points to the saved commit, and re-observe the expected checkout immediately before parking through the owning Git API. Preserve the existing handling of ignored files; never delete retained refs, worktrees, evidence or saved records. Confirm a clean detached checkout at D with no active merge after parking. If interruption happened after the effect, the same exact observation allows adoption without another Git write.

In one final short transaction, fence the saved release state and exact reservation, record completed release and remove only that reservation. Keep the conflict admission, frozen save and retained ref so the outcome and work remain readable. Do not mutate the implement attempt, checks attempt, tracker claim or candidate state. Source exclusion ends by the existing reservation predicate.

Route pending release through the executor before its existing preservation code, because post-abort/post-park state deliberately differs from the original capture. A completed release returns its retained original outcome without setup, merge, capture, Git writes or reservation reacquisition. Protect that retained-read route from wrong keys and later slot reuse. Keep generic explained outcomes; do not add backend tool text to factory vocabularies or instructions telling the owner to run a command.

## Read list
- `src/taskloop/land_conflict/execute.py:25-122` — executor ports, custody, setup reconciliation, outcome producer and release caller; edit routing.
- `src/taskloop/land_conflict/models.py:13-117` — admission/save models and save codec vocabulary; edit typed release payload.
- `src/taskloop/land_conflict/store.py:20-78` — retained reads, exact ownership and monotonic save writes; add release persistence and receipt read.
- `src/taskloop/land_conflict/store.py:94-129` — admission producer and reservation creation; retain its immutable identity contract.
- `src/taskloop/land_conflict/preserve.py:20-106` — stopped-process proof, owned capture, immutable save identity; share necessary verification with release.
- `src/taskloop/land_conflict/preserve.py:108-181` — save/ref completion and live checkout verification; preserve existing guarantees.
- `src/taskloop/land_conflict/reservation_store.py:1-26` — ownership and source-exclusion predicates consumed by release/admission.
- `src/taskloop/land_conflict/admit.py:30-72` — admission caller and retained-operation reuse; ensure release cannot restart work.
- `src/taskloop/merge/models.py:15-114` — existing merge phases, terminal causes, recorded executions and result provenance.
- `src/taskloop/merge/start.py:24-64` — producer of completed/terminal results; preserve its terminal semantics.
- `src/taskloop/merge/start.py:113-130` — detached merge completion and parking precedent.
- `src/taskloop/slot_release.py:107-132` — existing safe parking contract; consultation only.
- `src/taskloop/factory_schema.py:59-78` — existing JSON storage and identity constraints; consultation only, no schema change.
- `src/taskloop/land_store.py:174-190` — candidate-admission caller of conflict source exclusion; consultation only.
- `tests/steps/land_conflict_bench.py:67-142` — execution producer, fake ports and intact-database restart helper; extend only for release assertions.
- `tests/steps/test_land_conflict_execute.py:30-102` — stale ownership, custody and unsettled setup regressions; update/extend caller expectations.
- `tests/steps/test_land_conflict_restart.py:31-104` — executor restart callers and effect-adoption coverage; adapt to released terminal results.
- `tests/steps/test_land_conflict_save.py:32-80` — preservation caller assertions about retained bytes, parents and slot state; update for post-release checkout.
- `tests/steps/test_land_conflict_save.py:265-296` — later-edit protection and terminal outcome callers; retain cause and saved work assertions.

## Verification
Use pytest functions and semantic fakes in the existing declared environment. The new release tests must independently exercise abort and parking, with injected failures before/after external effects and before/after durable result recording. Reopen factory.db between attempts; assert the reservation remains at every unresolved boundary, retained ref/tree/parents are unchanged, and completed effects are not repeated. Cover both successful and terminal merge outcomes, no-active-merge saved work, stale token/generation, changed path/gitdir, foreign merge inputs, later edits, moved/missing retained refs, busy custody and unconfirmed process exit. Verify external effects occur outside write transactions and final release touches no unrelated reservation or claim.

Update affected existing executor/save/restart assertions to read preserved work from its owning retained ref and receipt after parking. Existing pending-save, ref-contention and foreign-work refusals must continue to reserve the checkout. Test repeated release after a later slot generation is reserved: return only the original receipt and leave the new owner's checkout/reservation untouched. Test that candidate source exclusion holds while parking is pending and clears only after confirmed release.

Run the focused conflict admission/execution/save/restart/release tests and relevant policy/isolation tests. Complete the required gates `just check` and `just test` using the factory-provided commands; do not launch whole-suite/live tests separately. Keep source files within 400 lines, functions within 80, test files within 800, and introduce no Any/cast/ignore escapes. This planning attempt does not run implementation gates.

## Completion
Both Size acceptance criteria and required gates pass. Every unresolved destructive action keeps exact ownership; intact-database restart adopts already completed effects; successful release leaves the slot parked and saved conflict work reachable. No process-aware drain implementation, new CLI/dashboard surface, remote publication, schema upgrade or tracker change is part of this task.
