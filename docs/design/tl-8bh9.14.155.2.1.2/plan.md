# Depth
Medium: three independent behaviours—fenced setup and ownership, adoption of a matching effect, and the durable three-execution bound. No owner decision is missing. Part 1 is a named dependency, not explicitly unlanded in the task text; subsequent evidence confirms it landed as 2a79a335 and is present at source 7936263c. Evidence budget: 12 model calls total.

## Size
Estimate: 13 changed files including this plan, three independent behaviours, and 55 model calls for one implement attempt. Allow up to 16 files and 70 calls for integration corrections; these remain below the 60-file, three-behaviour and 100-call limits.

1. Fenced setup and ownership: an admitted conflict can prepare and execute only under its exact operation key, reservation generation, repository and slot custody. Independently testable acceptance: changing the token, generation, reservation or slot identity prevents setup/launch/Git writes; a busy slot or live/unknown previous worker retains work without duplicate execution. Setup process identities remain visible to drain.
2. Matching-effect adoption: a fresh operation object and database connection resume the retained source/target and adopt a matching merge already performed before a crash. Independently testable acceptance: crashes after parking, starting and finishing a detached merge produce one accepted result with the recorded parents and provenance; mismatched effects are retained with an explained refusal, and the checked task branch never moves.
3. Durable three-execution bound: resolution executions retain their identities, input/evidence references and ordinal across restart. Independently testable acceptance: three unsuccessful executions reach a durable exhausted result; repeated resumes never start a fourth; a registered live/unknown worker is never duplicated, and a validated success can complete on execution three.

These are estimates for an implementation attempt, distinct from the planning evidence budget. No schema version change is proposed: admission and merge tables already exist and the existing merge record supports a detached continuation.

## Read list
- `src/taskloop/land_conflict/models.py:16-75` — retained admission identity, source, target and explained admission results.
- `src/taskloop/land_conflict/admit.py:42-59` — producer of the record consumed by execution.
- `src/taskloop/land_conflict/store.py:19-80` — admission lookup, retained inputs and reservation write ownership.
- `src/taskloop/land_conflict/reservation_store.py:6-12` — existing cross-slice reservation predicate and reciprocal candidate exclusion.
- `src/taskloop/attempt_loads.py:42-67` — original requirements and agent setting retained independently of the released slot.
- `src/taskloop/merge/models.py:19-114` — phases, typed reasons, detached Work and bounded Execution records.
- `src/taskloop/merge/start.py:24-199` — shared lifecycle, effect intents, adoption checks and resolution acceptance; all phases participate in restart.
- `src/taskloop/merge/resolve.py:22-153` — durable launch registration, liveness reconciliation, evidence capture and retained prompt inputs.
- `src/taskloop/merge/store.py:15-43` — persisted merge operations, compare-and-swap updates and process ownership reads.
- `src/taskloop/merge/git.py:13-102` — matching parents/provenance, branch attachment bypass and structural resolution validation.
- `src/taskloop/merge/prepare.py:28-83` — existing producer/caller of the shared merge lifecycle; preserve ordinary preparation semantics.
- `src/taskloop/environment.py:159-212` — explicit setup request and shared preparation operation.
- `src/taskloop/setup_store.py:34-166` — setup ownership predicates, bounded registration writes and process enumeration.
- `src/taskloop/slot_lock.py:39-79` — existing nonblocking slot custody acquisition and landing context.
- `src/taskloop/drain/composition.py:32-35` — existing consumer of setup and merge process owners.
- `src/taskloop/factory_schema.py:45-78` — current version and already-landed conflict/merge storage; confirm this task needs no DDL change.
- `tests/steps/land_conflict_bench.py:22-51` — admitted-source fixture and retained artifact integration.
- `tests/steps/merge_bench.py:44-85` — semantic merge fixture and operation construction.
- `tests/steps/test_merge_prepare.py:63-146` — crash-after-effect and detached-continuation regression patterns.
- `tests/steps/test_merge_resolution.py:49-83` — registered fake harness, evidence and session assertions.
- `tests/steps/test_setup_store.py:1-80` — focused setup store fixtures and ownership contracts.
- `tests/steps/test_environment.py:1-100` — focused setup preparation fixtures and contracts.
- `tests/steps/test_drain.py:83-134` — setup/agent ownership and uncertain-liveness regression contracts.
- `docs/glossary.md:141-142` — reserved, locked and held have distinct meanings; preserve explicitly held work.

## Current evidence and boundary
There is no existing plan for this task and the worktree starts clean. The current history includes part 1, which retains exact checked inputs and atomically reserves a free detached slot. Its ConflictStore deliberately does not start execution. Work already accepts branch=None, and MergeStore already persists lifecycle intents and execution history independently of an ordinary attempt row. Drain already reads merge workers and setup workers.

SetupStore currently authorizes ordinary attempts, checks and land candidates, but does not authorize conflict operations. Merge._setup currently accepts source/target heads rather than the newly reserved free slot's base. Merge._start can restart a merge if the effect completed without MERGE_HEAD before its next database write. These are integration gaps to address, not reasons to introduce another execution store.

The application operation added here consumes a durable admission and returns the shared typed merge result. Its producer is conflict admission; focused lifecycle tests are its direct consumers in this task. Automatic detection of a land conflict, scheduling it in rounds, candidate validation/publication, task completion and slot release are outside this execution-and-restart slice. Preserve the reservation and result for their owning continuation, including on refusal. Do not change the original checked source or task branch.

## Implementation
Add new `src/taskloop/land_conflict/execute.py` as the narrow application operation. Its existing integration points are ConflictStore/Record, MergeStore/Work, Merge/Resolution, Preparation.prepare_for and slot_lock.landing. Supply time, Git views, evidence, harness execution, setup, renewal and liveness through explicit ports. Resolve an input key back to its durable admission; caller-supplied records cannot replace retained facts.

Extend the conflict slice's own store with exact-key loading and a reservation check, including the slot path and current generation. Expose a narrow predicate from reservation_store for SetupStore to authorize conflict setup without reading conflict tables elsewhere. Keep setup's existing registration and reconciliation behavior, and test that its existing three-owner binding still works when adding conflict ownership. Do not manufacture an ordinary attempt, acquire another tracker claim, or reread requirements from the tracker.

Acquire slot custody before external effects and retain it through setup, resolution and result recording. Validate repository root, gitdir, detached state and admitted base on initial entry. A retained operation is resumed from its own phase and observed world, rather than repeating initial clean-slot requirements over intentional merge edits. Recheck the full conflict key/reservation before each external action and registration. Lost ownership, busy custody and uncertain liveness yield explained typed results without clearing the reservation or resetting files. Use existing vocabulary and enum codecs for results.

Build Work once under the conflict operation ID from the retained checked source, immutable admission target, original input reference and agent setting, reserved slot/base and deadline; set branch=None. Validate any already-stored Work against those immutable facts before resuming. Persist intent before parking/setup or launching. Prepare the detached slot at the retained target through the existing environment operation, passing scrubbed credentials and the existing sandbox probe where required. Extend shared merge setup only enough to accept the recorded clean reservation base for a detached consumer; ordinary preparation keeps its current guards. Never rerun setup over a stopped merge.

Use the existing shared merge lifecycle for automatic merging and bounded textual resolution. Reconcile phase START as well as FINISH when the Git effect completed before the next write: adopt only a clean detached result with the exact recorded parents and provenance. Matching MERGE_HEAD must retain the recorded source and target; a foreign merge, moved branch/head, dirty completed effect or mismatched provenance cannot be adopted or overwritten. Already-contained and ancestor cases may use the existing no-merge completion paths. A completed detached result remains detached, and neither the task ref nor local main changes.

Reuse Resolution and its existing Execution tuple as the only execution counter. Keep ordinal allocation durable before launch, process registration before target execution, and result/evidence capture separate from acceptance. Reconcile a registered worker before any retry; alive or unknown keeps the reservation. A gone worker consumes its existing execution even when capture was interrupted, retaining edits and the original input context. Reuse an unregistered intent only under the owning harness's existing registration-before-execution guarantee. Do not add retries hidden inside adapters. Preserve validated answers and captured evidence across restart; persist exhaustion after three unsuccessful executions and never reset the tuple. Owner answers remain terminal and are not retried. Change shared merge/resolve code only where the conflict lifecycle tests expose an actual gap.

Expected implementation edits: conflict models/store/reservation_store, setup_store, merge/start and, if needed, merge/resolve, plus the existing conflict fixture. New test files: `tests/steps/test_land_conflict_execute.py` for ownership/setup and `tests/steps/test_land_conflict_restart.py` for adoption and execution limits. Their existing integration points are land_conflict_bench, merge_bench and the focused merge/setup fixtures listed above. Add focused regressions to test_merge_prepare and test_setup_store where shared behavior changes. Keep the plan current with the final file list. No new schema, dependencies, glossary terms, private process APIs or subprocess usage.

## Validation
Exercise the three acceptance criteria through pytest functions with semantic Git/process/harness fakes and persistent database reopen tests. Inject interruption between intent, effect and result at setup, merge start/finish, worker registration and evidence capture. Assert effect counts, durable identities, retained edits, target/source identity and unchanged task ref, rather than testing private helpers. Include foreign effects, failed registration fences, uncertainty, interrupted capture, success on execution three and repeated resumes after exhaustion. Confirm setup and merge owners remain visible through existing drain reads without adding a second owner enumeration path.

Run the new focused lifecycle tests and existing conflict admission, merge preparation/resolution and setup-store tests through the declared installed environment. Run `just check` and `just test` as the required focused gates; do not run whole-suite or live tests. Implementation uses `just install` before any direct CLI execution, and direct CLI checks use `uv run --frozen --no-sync python -I -m taskloop ...`. Enforce 400 source lines per file, 80 per function and 800 per test file, with no new Any/cast/ignore escapes. Planning itself does not run implementation checks.
