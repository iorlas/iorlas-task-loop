# Header
Task: tl-8bh9.14.155.2.2.2
Base: fd1be071c69c3e6eaf063d3e19ed8091a1049f3a
Depth: medium; two behaviours
Missing decision: none. Explicitly unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 2 files incl. tests/plan; 2 behaviours; 40 implement calls.

## Outcome and non-goals
Close the integration-test gap between conflict execution, production drain observations and saved-work release across database reopen. Existing tests separately cover surviving workers, conservative observations, restartable parking and atomic release. Drain observes executions and fences admission; conflict execution owns save, parking and release. No scheduler, adapter, schema or policy changes.

## Settled decisions
- Use production `open_drain` readers with injected observations/waits and semantic Git fixtures.
- `Resolution._capture` sets `Execution.ended` only after `WorkerGone` confirms exit; preserve that contract and `MergeStore.active_processes` filtering.
- A completed drain can leave idle reservations intact. Confirmed exit permits existing conflict reconciliation; it does not authorize drain to park or free a slot.
- Reuse `ExecutionCase` and release semantics for combined assertions.

## Open decisions
- None.

## Change map
- `tests/steps/test_land_conflict_drain.py` (new): integrate `execution_case`, `open_drain`, `inspect`, `drain` and `ExecutionCase.resume/restart`; inject liveness/interruption and assert reservation and saved-work effects.
- `docs/design/tl-8bh9.14.155.2.2.2/plan.md`: this bounded implementation contract.
Consulted integration points and callers below retain their interfaces:
- `src/taskloop/drain/composition.py`: `open_drain/_owners` combines owning process readers.
- `src/taskloop/merge/store.py`: `active_processes` feeds `_owners`.
- `src/taskloop/merge/resolve.py`: `Resolution._capture` produces stop-proof state.
- `src/taskloop/land_conflict/execute.py`: `_saved_result` calls preservation, cleanup and release.
- `src/taskloop/land_conflict/preserve.py`: `Preservation.stopped` guards effects.
- `src/taskloop/land_conflict/release.py`: `ReleaseSaved._resume` parks.
- `src/taskloop/land_conflict/store.py`: `ConflictStore.release` completes atomically.
- `src/taskloop/cli_drain.py`: `run` consumes drain.
- `src/taskloop/drain/restart.py`: `restart` consumes drain/inspect.
- `src/taskloop/cli_composition.py`: imports `open_drain`.
- `tests/steps/test_drain.py`: `opened` consumes production composition.
- `tests/steps/test_drain_fences.py`: consumes drain composition and reconciliation.
- `tests/cli/test_open_rounds.py`: consumes `open_drain/drain`.
- `tests/cli/test_drain_cli.py`: consumes drain ports.
- `tests/steps/test_land_conflict_execute.py`: consumes setup/attempt process readers.
- `tests/steps/test_merge_resolution.py`: asserts `active_processes` results.
- `tests/steps/test_land_conflict_restart.py`: asserts `active_processes` after restart.

## Read list
- `src/taskloop/drain/composition.py:33-36` — all production process-owner readers.
- `src/taskloop/drain/composition.py:50-96` — independent validated database connections and reconciliation wiring.
- `src/taskloop/drain/drain.py:15-98` — injectable observations, unresolved actions, waiting and interrupted results.
- `src/taskloop/drain/models.py:34-77` — typed roles, observations, conclusions and identities.
- `src/taskloop/drain/observe.py:18-32` — existing conservative process/group observation contract.
- `src/taskloop/drain/restart.py:7-17` — resume an incomplete drain without reopening its boundary.
- `src/taskloop/cli_drain.py:24-38` — CLI composition and result handling.
- `src/taskloop/merge/store.py:30-43` — durable work updates and merge-owner production.
- `src/taskloop/merge/resolve.py:33-108` — registration/capture continuation and confirmed-exit semantics.
- `src/taskloop/land_conflict/execute.py:47-140` — custody, replay and pending-release dispatch.
- `src/taskloop/land_conflict/preserve.py:20-49` — injected stop proof and reservation-preserving wait.
- `src/taskloop/land_conflict/release.py:19-64` — restartable verified parking and completion.
- `src/taskloop/land_conflict/store.py:97-115` — exact atomic save completion and reservation deletion.
- `tests/steps/land_conflict_bench.py:73-142` — fake worker, interruption and reopened-store fixture.
- `tests/steps/test_land_conflict_restart.py:116-147` — surviving-worker and capture-interruption patterns.
- `tests/steps/test_land_conflict_release.py:25-100` — terminal dirty-work fixture and pending-release injection.
- `tests/steps/test_land_conflict_release.py:188-224` — atomic rollback and completion-interruption patterns.
- `tests/steps/test_drain.py:120-190` — production composition with semantic observations and interrupted waiting.
- `tests/steps/test_drain_observe.py:10-41` — existing live-group, unknown and reused-identity coverage.
- `tests/steps/test_merge_resolution.py:74-102` — existing ended-worker and surviving-worker expectations.
- `src/taskloop/cli_composition.py:39-39` — production composition import consumer.
- `tests/steps/test_drain_fences.py:209-239` — authorized work and interrupted-action reconciliation during drain.
- `tests/cli/test_open_rounds.py:16-17` — existing drain composition imports.
- `tests/cli/test_drain_cli.py:15-15` — CLI test's drain ports import.
- `tests/steps/test_land_conflict_execute.py:46-92` — conflict execution process-reader integration assertions.

## Contract
No new runtime typed names, states or stored fields. The new test module uses existing `Identity`, `Owner`, `Seen`, `Conclusion`, `State`, `Disposition` and `ReleasePhase` values.

Intent: register a worker and begin drain. Effect: collect production owners with live/unknown/gone observations; interrupt waiting/capture and reopen SQLite. Result: live or uncertain work retains reservation, checkout and fence without duplicate execution or cleanup.

Intent: reconcile a terminal conflict after confirmed exit. Effect: resume with interruptions before/after parking and durable release. Result: adopt recorded effects, preserve saved work, remove only its reservation once and replay without effects. Drain may complete before this reconciliation.

Distinguish caller and worker observations. Bound fake waits; use no real processes or clock waits. Reuse existing typed identity/group observations without adding shelf assumptions.

## Work packages
1. In the new test module, construct the existing conflict fixture and production `open_drain` ports. Cover a worker interrupted after registration and a captured result whose worker remains live, then unknown; interrupt drain and reopen the database. Close acceptance A with snapshots of reservation identity/generation, checkout bytes and invocation count.
2. In the same module, confirm exit and resume a terminal conflict using the existing save/cleanup/release path. Inject interruptions on both sides of parking and durable release, reopen and reconcile; assert exact reservation removal, retained ref/tree, ignored bytes and effect-free replay. Close acceptance B. Reuse isolated release tests for detailed foreign/stale ownership cases.
3. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipeline failure status preserved. Reassess scope if failures require runtime contract changes.

## Acceptance behaviours
A. Across registration/capture and interrupted drain with database reopen, a live or uncertain owned worker keeps the same reservation and checkout; drain cannot report verified idle or trigger another execution, parking or release.
B. After confirmed exit, drain can verify idle without freeing the reservation; interrupted conflict parking/release reconciles on reopen, retains saved and ignored bytes, frees only the exact reservation once and replays without repeating effects.
