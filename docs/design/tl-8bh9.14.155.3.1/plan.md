# Header
Task: tl-8bh9.14.155.3.1
Base: d9b52867e400af323cea689db8eb7ff7e6823fa3
Depth: medium; persistence and interruption-safe release.
Decision missing: no. Unlanded dependency: none.
Evidence: 12 model calls.
Size: 1 artifact, 0 source files; 2 behaviours; 10 implement calls.

## Outcome and non-goals
The accepted save, cleanup and release path and its interruption coverage are present. The remaining gap is verification at the current base: confirm A1/A2 through existing tests and required gates. Reuse this implementation and coverage. Candidate validation, target movement, push/close reconciliation and terminal holds belong to later split tasks. No new delivery transition or schema change is needed.

## Settled decisions
- Accepted content stays reachable through its retained commit/ref after slot parking.
- Accepted work uses cleanup/release; abort remains unfinished-merge-only.
- Release completion and removal of its exact reservation share one transaction.
- Completed-result replay precedes live custody or checkout access.
- Keep the existing handoff delivery boundary and checked task refs.

## Open decisions
- None.

## Change map
- `docs/design/tl-8bh9.14.155.3.1/plan.md` — revise remaining scope and Size; sole planned artifact change.
- `src/taskloop/land_conflict/models.py` — consult `Save.consistent`, `consistent_release`: accepted cleanup/release identity.
- `src/taskloop/land_conflict/release_models.py` — consult `Release.consistent`: exact completed/terminal result.
- `src/taskloop/land_conflict/cleanup.py` — consult `CleanupSaved`: ignored protection and observed cleanup reconciliation.
- `src/taskloop/land_conflict/release.py` — consult `ReleaseSaved._resume`: cleanup consumer, release intent and base parking.
- `src/taskloop/land_conflict/execute.py` — consult `execute`, `_execute`, `_saved_result`: cleanup/release callers and replay.
- `src/taskloop/land_conflict/store.py` — consult `completed`, `save`, `release`, `_release_admission`: atomic persistence.
- `src/taskloop/land_conflict/preserve.py` — consult `Preservation._preserve`, `_owned`, `_intent`: accepted-save producer.
- `src/taskloop/merge/models.py` — consult `Work`, `Completed`, `Terminal`: result contract.
- `src/taskloop/merge/start.py` — consult `Merge._finish`, `_attach`: completed-work producer.
- `src/taskloop/land_conflict/composition.py` — consult `conflict_handoff.execution`: production executor caller.
- `src/taskloop/land_conflict/handoff.py` — consult `Handoff.resume`, `start`: execution-result consumers.
- `tests/steps/land_conflict_bench.py` — consult `ExecutionCase.resume`, `restart`: executor caller and restart fixture.
- `tests/steps/test_land_conflict_accepted_release.py` — consult accepted coverage and save/release hooks for A1/A2.
- `tests/steps/test_land_conflict_execute.py` — consult `test_execution_prepares_the_reserved_base_and_keeps_checked_refs`.
- `tests/steps/test_land_conflict_save.py` — consult `test_foreign_ref_during_initial_intent_is_never_overwritten`, save hook.
- `tests/steps/test_land_conflict_release.py` — consult `test_release_completion_interruption_is_restartable`, save/release hooks.
- `tests/steps/test_land_conflict_cleanup.py` — consult `ConflictStore.save` interception and cleanup regression.
- `tests/steps/test_land_conflict_abort.py` — consult `interrupt`: save hook and unfinished-only abort regression.
- `tests/steps/test_land_conflict_drain.py` — consult `ConflictStore.release` interception and parking hook.
- `tests/steps/test_land_conflict_handoff.py` — consult `test_production_handoff_wiring_executes_over_the_existing_adapters`: executor caller.

## Read list
- `src/taskloop/land_conflict/models.py:114-157` — save and accepted cleanup invariants.
- `src/taskloop/land_conflict/release_models.py:17-42` — result and parking validation.
- `src/taskloop/land_conflict/cleanup.py:20-120` — cleanup intent, effects and evidence.
- `src/taskloop/land_conflict/release.py:19-64` — release intent, parking and completion.
- `src/taskloop/land_conflict/execute.py:47-141` — replay, dispatch and cleanup/release callers.
- `src/taskloop/land_conflict/store.py:34-119` — retained-result reads and atomic release.
- `src/taskloop/land_conflict/store.py:181-187` — exact admission fence.
- `src/taskloop/land_conflict/preserve.py:46-99` — accepted-save producer.
- `src/taskloop/merge/models.py:78-139` — work and result types.
- `src/taskloop/merge/start.py:104-130` — completion producer.
- `src/taskloop/land_conflict/composition.py:33-54` — production execution integration.
- `src/taskloop/land_conflict/handoff.py:30-61` — retained execution consumers.
- `tests/steps/land_conflict_bench.py:83-112` — executor caller and restart fixture.
- `tests/steps/test_land_conflict_accepted_release.py:51-115` — retention and durable-write interruptions.
- `tests/steps/test_land_conflict_accepted_release.py:169-217` — parking adoption and rollback.
- `tests/steps/test_land_conflict_accepted_release.py:219-300` — changed evidence, reuse and invariants.
- `tests/steps/test_land_conflict_execute.py:35-45` — accepted parking and checked refs.
- `tests/steps/test_land_conflict_save.py:316-338` — foreign-ref save hook.
- `tests/steps/test_land_conflict_release.py:202-226` — release interruption hook.
- `tests/steps/test_land_conflict_cleanup.py:115-130` — cleanup save hook.
- `tests/steps/test_land_conflict_abort.py:54-70` — unfinished-merge save/abort hooks.
- `tests/steps/test_land_conflict_drain.py:137-156` — parking/release interception.
- `tests/steps/test_land_conflict_handoff.py:210-230` — production executor caller.

## Contract
Keep `Release.result: Completed | Terminal`. Accepted release binds the completed work's commit, source, target and explanation; `Save` also binds attempt, repository, slot, inputs and completed cleanup. Accepted cleanup requires the exact clean detached completed checkout. No new typed names, phases or stored fields are required.

Intent: persist accepted save and retained commit/ref, then cleanup snapshots and ignored identities. Effect: protect ignored paths and reconcile cleanup while retaining custody. Result: verified cleanup of the exact accepted checkout.

Intent: persist `Release(PENDING)` with frozen result and before/after checkouts. Effect: park at the independently admitted base outside the write transaction, adopting an already observed output after interruption. Result: `ConflictStore.release` atomically stores `COMPLETE` and removes only the matching reservation. Changed worker, ref, files, repository or reservation evidence prevents release and preserves available custody.

Completed replay returns the stored result before locking, live ownership checks, merge reads or checkout access. Pending saved work resumes without another resolution.

## Work packages
1. Verify A1/A2 against the existing implementation and callers in the read list. Preserve accepted-release and terminal regression coverage; introduce no duplicate tests or source changes when these contracts hold.
2. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, preserving command exit status. Both must pass. These close the verification gap for A1/A2.

## Acceptance behaviours
A1. Accepted completion retains the exact commit, source, target and explanation independently of slot HEAD; parks at the admitted base with ignored bytes intact; atomically releases only its own reservation while preserving checked task refs and delivery state.
A2. Interruptions during retention, cleanup, parking or release resume the same resolution without another agent run or repeated completed effect; changed evidence prevents release; completed replay after slot reuse returns the same result without touching the new owner's work.
