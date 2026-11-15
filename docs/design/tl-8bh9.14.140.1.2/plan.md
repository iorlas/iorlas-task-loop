# Header
Task: tl-8bh9.14.140.1.2
Base: 72b2ea3d82e7200c98773b426fe37318b8ca2790
Depth: medium
Reason: projection and rail.
Decisions: none missing. Dependency: .140.1.1 landed.
Evidence budget: 12 model calls.
Size: 11 changed files; 2 independent behaviours; ~45 implement calls.

## Outcome and non-goals
Show recorded operations and measured durations beside their owning attempts, preserving incomplete evidence across refresh and restart. Keep verification, checks and land selection. Exclude capture, storage and workflow changes.

## Settled decisions
- Consume `EvidenceFiles.operations`; retain `OperationKind` and `OperationState` as the vocabulary.
- Operations have no selection routes and contribute neither attempt counts nor usage.
- Place by ownership; timestamps order operations within owners, never reorder attempts.
- Treat ACTIVE as completion unrecorded, without extrapolating elapsed time. Its stored zero is a start observation, not a duration measurement.
- Retain approximate timestamp gaps as separately labelled gaps, never as measurements of factory operations.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_operation.py` (new): `OperationDetail`, `project` project samples and ownership; integrates with `dash_task.build_task`.
- `src/taskloop/dash_model.py`: `TaskDetail.operations` carries a tuple of the new typed projection.
- `src/taskloop/dash_task.py`: `build_task`, `_chain` collect agent/check samples once; map checks via `ChecksRow.after` and existing numbering/past boundaries.
- `src/taskloop/dash/static/drawer.js`: `render` passes task operations to `rail` without altering selection or attempt counts.
- `src/taskloop/dash/static/rail.js`: `rail`, `groupRows`, `pastGroup`, `summary` place operations and expose incomplete/failed history; `gapWords` labels approximation.
- `tests/steps/test_dash_operations.py` (new): projection and `build_task` contract coverage; reuse `test_dash_read` setup and existing evidence writers.
- `tests/dash/operation-rail.test.js` (new): rendering cases invoked by `rail.test.js`.
- `tests/dash/rail.test.js`: import/run new cases; update gap assertions; retain existing rail and drawer selection cases.
- `.importlinter`: add the new source module to applicable exhaustive module lists, preserving contracts.
- `docs/design/tl-8bh9.14.140.1.2/plan.md`: implementation scope and acceptance.
- `docs/design/tl-8bh9.14.140.1.2/plan-metadata.json`: consulted paths and preparation commit.
- Callers: `dash_composition._ports.task` → `build_task` → `history`; `drawer.render`, `rail.test.mount` → `rail`; duration/usage/discussion dashboard tests → `build_task`. Default-empty operations preserve callers.
- Producers to consult: `factory_commit._commit`/`_reviewed`, `publish.Publisher._pushed`, `launch.Launcher._start` → `measured`; `composition._operation_observer` wires capture; `EvidenceFiles.operations` → `operation_file.read` owns reads.

## Read list
- `src/taskloop/dash_task.py:235-344` — chain and ownership.
- `src/taskloop/dash_model.py:171-222` — payloads.
- `src/taskloop/dash/static/rail.js:1-60` — grouping, numbering and gap semantics.
- `src/taskloop/dash/static/rail.js:132-194` — history and disclosure.
- `src/taskloop/dash/static/rail.js:262-285` — rail entry and pending steps.
- `src/taskloop/dash/static/drawer.js:213-230` — rail caller/scroll.
- `src/taskloop/dash_composition.py:37-67` — task/body/feed consumers.
- `src/taskloop/dash_server.py:170-176` — JSON boundary.
- `src/taskloop/operation_evidence.py:15-94` — sample states and producer contract.
- `src/taskloop/operation_file.py:18-48` — reads/order.
- `src/taskloop/evidence_files.py:148-163` — owning read/write boundary.
- `src/taskloop/check_store.py:73-90` — checks identity and implement ownership.
- `src/taskloop/factory_commit.py:94-159` — measured commit producers and cached paths.
- `src/taskloop/publish.py:178-190` — measured publication producer.
- `src/taskloop/launch.py:230-266` — checks-start producer uses the checks key.
- `src/taskloop/composition.py:199-209` — observer wiring.
- `tests/steps/test_dash_read.py:1-100` — fixtures.
- `tests/steps/test_dash_duration.py:1-40` — read-only projection testing pattern.
- `tests/steps/test_dash_usage.py:1-100` — task projection consumer.
- `tests/steps/test_discussion_dashboard.py:1-100` — task projection consumer.
- `tests/steps/test_operation_evidence.py:1-42` — existing operation evidence fixtures.
- `tests/steps/test_check_operations.py:94-120` — checks admission.
- `tests/dash/rail.test.js:1-35` — test integration and rail caller.
- `tests/dash/rail.test.js:90-225` — gaps, folded history and drawer selection regressions.
- `.importlinter:650-750` — module lists.

## Contract
Intent: `build_task` projects display evidence after resolving the existing agent/check chain. Read each key once; checks samples belong to their checks try, whose historical membership follows its implement owner. Missing/corrupt observations omit only the affected evidence, without creating successful, zero-duration or workflow rows.

Effect: read through `EvidenceFiles.operations` only. No database fields, schema version, writes, process probes or producer changes. A new frozen Pydantic `OperationDetail` carries operation id, owner step/number, past flag, existing kind/state enums, validated ISO start timestamp and nullable measured milliseconds. `TaskDetail.operations` defaults to an empty tuple. Invalid display timestamps are rejected per observation. Existing JSON serialization handles the nested model.

Result: retain every retry identity. Within each owner, sort by recorded start then operation id. Show commit/publication after the owning agent row, including its attached verification; show checks-start before its checks row, even when checks have no recorded start. Keep operations inside the owner's history group and before following attempts/land events. Use measured elapsed only for terminal COMPLETED/FAILED/UNCERTAIN samples; UNCERTAIN names the unconfirmed result. ACTIVE shows completion unrecorded and duration unavailable, with no wall-clock or restart extrapolation. Missing evidence creates no placeholder operation. Rows are explanatory, not selectable attempts. Folded summaries expose failed, uncertain or incomplete operations without hiding existing verification failures. Approximate gap text remains independent and is not subtracted from or added to measured time.

## Work packages
1. Add `dash_operation.py`, extend `dash_model.TaskDetail`/`dash_task.build_task`, update `.importlinter`, add `test_dash_operations.py`. Closes A1.
2. Wire `drawer.js`, render in `rail.js`, add `operation-rail.test.js` via `rail.test.js`. Closes A2.
3. Run focused Python tests via the prescribed isolated pytest command and local rail fixture checks. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last. Report any unavailable local JS runner; Python gates do not exercise those cases.

## Acceptance behaviours
A1. Task detail projects all valid commit, publication and checks-start observations once, with stable retry identities, correct owner numbering/past membership and measured terminal durations; missing, malformed or incomplete evidence cannot invent success or elapsed time, and projection writes no state.
A2. The rail places measured operations in owner order before subsequent steps, distinguishes failed/unconfirmed/incomplete outcomes and approximate gaps, folds them with their owner while preserving visible failure summaries, and retains attempt/verification/land selection, disclosure, scroll, counts and usage across redraws.
