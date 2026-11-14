# Depth
Large: persisting land conflict attempts requires a schema version change. Detached merge execution, restart recovery, retry limits and preservation are one cohesive lifecycle. No owner decision is missing and no dependency is explicitly unlanded; git-porcelain 0.21.0 is already pinned. Evidence budget: 20 model calls total.

## Size
Estimated implementation: 34 changed files, including source, focused tests, test helpers and this plan; three independently testable behaviours; 90 model calls for one implement attempt. These estimates include integration and regression fixes, rather than only the new feature folder. No task split or delivery prerequisite is needed.

1. Detached land conflict resolution: a textual conflict produces a structurally accepted, durably retained merge commit through the pinned shelf, leaving the checked task branch unchanged. Acceptance: a lifecycle test resolves divergent text, retains automatic changes and both parents, and observes no validation, push or tracker close.
2. Restart and bounded execution: interruption resumes the same operation and reservation without duplicating a registered execution; at most three resolution executions are spent. Acceptance: reconstructing the operation after each recorded effect adopts completed effects, waits for surviving/unknown processes and reaches exhaustion without a fourth execution.
3. Preservation and release: terminal resolution or abandonment preserves work before aborting or freeing its slot. Acceptance: failure injection around save, abort and release retains edits and ancestry, reconciles a completed save once, and prevents release while any owned process may survive.

## Read list
- `src/taskloop/factory_schema.py:45-100` — schema version, reservation ownership and execution tables; add the land conflict record.
- `src/taskloop/merge/models.py:19-114` — existing phases, reasons, executions and detached Work contract.
- `src/taskloop/merge/store.py:15-43` — durable phase writes, conditional updates and process inventory.
- `src/taskloop/merge/start.py:97-199` — detached completion, effect reconciliation, structural acceptance and retry exhaustion.
- `src/taskloop/merge/resolve.py:20-142` — registration-before-execution, session/evidence capture and restart handling.
- `src/taskloop/merge/git.py:13-102` — parent/provenance checks, textual conflict restrictions and exact edited paths.
- `src/taskloop/land.py:218-249` — candidate producer and the insertion point before ordinary validation/delivery.
- `src/taskloop/land_target.py:45-78` — typed shelf conflict producer and existing refusal conversion.
- `src/taskloop/land_check.py:52-139` — land ports and existing free-slot reservation pattern.
- `src/taskloop/land_store.py:139-178` — candidate admission fences and mutual exclusion with existing land work.
- `src/taskloop/cli_composition.py:369-395` — shared CLI/round land composition root and bounded registration wiring.
- `src/taskloop/composition.py:76-141` — agent run adapter and Checking environment/process/evidence ports.
- `src/taskloop/round_land.py:26-68` — caller's distinction between pending work and a terminal task-change refusal.
- `src/taskloop/drain/composition.py:15-35` — owning process inventory integration.
- `src/taskloop/admit_rows.py:12-17` — owning reservation write API to call inside admission.
- `src/taskloop/attempt_loads.py:58-122` — owning source-attempt reader; expose immutable retained input/settings without requiring its released reservation.
- `src/taskloop/attempt_types.py:104-155` — existing keys, source admission settings/input and process identities.
- `src/taskloop/environment.py:160-224` — explicit setup target, preparation and reconciliation ports.
- `src/taskloop/slot_release.py:278-292` — process-stop proof before any preservation or release.
- `src/taskloop/wip.py:139-204` — idempotent save/adoption, merge ancestry and refusal to park an active merge.
- `tests/steps/merge_bench.py:16-85` — semantic shelf fake and durable merge fixture.
- `tests/steps/test_merge_resolution.py:74-171` — existing execution/capture interruption and three-execution contracts.
- `tests/steps/test_merge_release.py:50-113` — preservation-before-abort and interrupted release contracts.
- `tests/steps/land_bench.py:174-192` — shared land ports fixture for application integration tests.
- `tests/steps/test_land.py:119-123` — replace the old textual-conflict refusal expectation with persisted resolution behaviour.

## Change map
The checkout is clean at source commit 81e5f3a1. This task has no existing plan or task-specific unfinished commit in the inspected history. The retained merge slice is implemented preparation machinery, not evidence that land conflict attempts are already complete. Its Work supports `branch=None`; its caller currently supplies reservation, process ownership, setup and custody. Land still converts a shelf Conflicted result directly into a restart refusal.

Add a `src/taskloop/land_conflict/` feature folder. New modules are `models.py` for validated inputs/records/results, `store.py` for its tables, `admit.py` for reservation admission, `resolve.py` for the application transition, `release.py` for preservation/release, and `composition.py` for wiring, plus `__init__.py`. Use existing Merge, Resolution and WIP operations rather than copying their implementations. New focused test modules cover admission/resolution, restart/retry, and release/drain/schema contracts; a new small fixture module joins the existing semantic merge and land benches.

Existing integration points are the files in the read list. Expected edits are schema, source-context reading, land conflict detection/handoff and ports, land composition, candidate exclusion, drain inventory, and the focused regression fixtures/tests. Modify shared merge code only where land exercises a missing detached or reconciliation contract. Keep the existing preparation consumer working. Reserve the remaining file estimate for directly affected callers and tests discovered by targeted searches; expand the read list only by replacing less necessary entries, keeping its maximum of 25.

## Implementation
1. Persist ownership before external actions. Add a pydantic v2 record retaining the checked attempt and X, immutable target O, task/repo identity, operation key/token, slot generation/path/base, owning foreground process identity, deadline, captured agent setting/input reference, retained result reference and release/preservation progress. Use existing enums where applicable and one codec for any additional closed vocabulary. The merge record remains the owner of merge phases and resolution executions; reference it rather than copying those facts.

   Admission observes candidate/slot availability through owning APIs, then atomically records this operation and reserves the slot. Enforce one active operation for the checked source; concurrent requests adopt it. Candidate admission must refuse while this operation owns the task, and conflict admission must refuse an incompatible candidate. Keep SQL inside store modules and use owning reservation APIs. Create the merge intent through MergeStore before the first Git effect; restart can finish that creation from the persisted owner record.

   Increment factory.db compatibility version from 22 to 23, or the next version if the base changes. Drain old processes before discarding an old-schema database. Refuse incompatible state; provide no migration, backup reader, reconstruction or fallback.

2. Preserve the structured conflict at the application boundary. Let land distinguish the shelf's typed conflict before converting it to display text. Only the ordinary land path admits/resumes resolution; summary, withdraw and no-change reads must not launch an agent or reserve a slot. Use the already fetched X/O and current source-attempt context, not discussion parsing or a refetched target that changes mid-operation.

   Run the bounded operation in land's existing foreground process, with recorded process identity, claim renewal and slot custody. Supply explicit clock, evidence, agent, setup and process-observation ports. Reuse the selected implement attempt's captured settings and requirements through its owning reader. Prepare the environment at the pinned target before beginning the stopped merge; restarting a resolution must not reset its edited worktree. Reuse the existing harness adapter and registration protocol; no new process launcher, scheduler or step name is required.

3. Start/resume Merge with `branch=None`, source X and immutable target O. Use Worktree.start_merge, merging, finish_merge and abort_merge from the existing 0.21.0 pin. Retain the supported-text restriction, baseline of automatic merge changes, exact safe answer paths, marker/index checks, recorded parents and provenance. Semantic ambiguity and unsafe/invalid edits retain typed causes and explanations. Agent sessions, execution identity, input and evidence remain owned by the existing merge execution record.

   Before each effect, fence current task/source ownership, reservation generation/token, deadline, process ownership and slot identity. On restart observe the world before taking another action. Adopt an already-started merge only with matching source/target; adopt an already-finished commit only with matching parents/provenance. Observe registered workers before accepting results or retrying. An unregistered intent can be retried only under the existing registered-start guarantee that no target executed before registration committed. Alive or unknown identity retains custody/reservation and consumes no additional execution. A confirmed stopped interrupted execution is accounted for before another execution is allowed. Preserve the durable three-execution ceiling across requests, deadlines and intact-DB restarts; terminal records never start fresh work automatically.

4. Retain successful results before releasing the worktree. Record a Git reference creation intent for the accepted detached merge, create it conditionally through the Git shelf, and adopt a matching existing reference after interruption. Store its commit/source/target and return the existing typed completed merge result through the land conflict operation. Keep X and its task branch unchanged on success. A database hash alone is insufficient protection from Git object collection.

   This part finishes when that result is durably available independently of delivery. The land integration reports in words that resolution is retained and awaits the delivery continuation; it must not enter ordinary candidate insertion, report Landed, reuse X's checks for the new commit, push, or close. Part 3 consumes the retained result and owns fresh validation, target movement and delivery. There is no dependency on part 1 and no dependency on part 3 landing first.

5. Give the operation its owning release. Confirm the foreground owner, every merge execution and setup command stopped before writing or aborting. Under slot custody, preserve terminal/abandoned work using WIP's save/adoption API and both immutable merge inputs. Record the preservation result before abort_merge, then park and remove the reservation with a conditional database write. A changed ref, failed save, unknown process, foreign merge or changed reservation keeps the slot reserved. Reconcile crashes after reference creation/save, abort, parking and before release recording; never delete evidence or a worktree to make progress.

   Successful release protects the accepted commit with its retained ref; terminal release protects unresolved edits and ancestry with the saved work. Retain typed terminal causes after release so repeated land calls do not retry the same refusal. Map terminal conflict outcomes into the existing land task-change refusal path with their explanations; pending/unknown outcomes remain pending. Messages state the situation and decision without instructing the owner to run a command. Add foreground owners to drain inventory; existing MergeStore and setup inventory continue supplying their process facts. Drain must observe these processes rather than claiming idle while they remain live or unknown.

Keep source files at most 400 lines, functions at most 80 and test files at most 800. land.py is already 404 lines and cli_composition.py is 395: extract the affected cohesive land coordination/wiring into the new feature modules so edited files meet the caps. Do not add Any, cast, ignore, direct subprocess/process-control calls, or baseline imports. The bounded read list describes implementation inputs, not permission to copy whole old packages.

## Validation
Use pytest functions and semantic Git/process/agent fakes. Add focused application tests rather than a test per private helper:

- Detached textual resolution retains both histories and automatic changes, keeps the task branch at X and returns a Git-retained result without running checks or delivery. Unsafe/nontextual conflicts and misleading answer paths cannot be accepted.
- Concurrent calls reserve once. Recreate objects and reopen the intact database around admission, merge start, registered execution, evidence capture, finish and result-ref recording; assert matching effects are adopted and a live/unknown execution is never duplicated.
- Across restarts, three failed/interrupted executions exhaust the original operation; a fourth land call does not dispatch. An interrupted unregistered intent spends no extra execution, and a terminal owner decision stays terminal.
- Failure injection before/after preservation, abort and parking demonstrates durable saved bytes/ancestry, no duplicate save and no early reservation removal. Live/unknown setup or agent processes prevent release and prevent an idle drain result.
- Replace the old textual-conflict refusal regression. Assert summary remains read-only, conflict success never reaches candidate validation/push/close, and ordinary non-conflicting land and preparation merges retain their behaviour. Reject version-22 state and test the current schema with the new records.

After the declared environment is installed, run focused tests through the installed successor package, without baseline editable installs or PYTHONPATH injection. Run the required `just check` and `just test` gates; do not add whole-suite/live runs beyond these supplied gates. Check the plan/code diff and line caps. No implementation checks are needed for this planning-only change.
