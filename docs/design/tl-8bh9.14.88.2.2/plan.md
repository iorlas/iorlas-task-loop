# Header
Task: tl-8bh9.14.88.2.2
Base: e76751b88df9a2571ed086c123832fb11c9d95b4
Depth: medium
Reason: three owning modules; no missing decision; dependency landed.
Evidence budget: 12 model calls.
Size: 16 changed files, 3 behaviours, about 55 implement model calls.

## Outcome and non-goals
Finish the attempt read boundary, preserving load results, fencing and conflict atomicity. Status queries and registration configuration already have a store owner. Preserve schema, stored values, public AttemptStore operations and external effects. Supporting stores relocate existing code to meet size caps. No shelf change.

## Settled decisions
- Keep RetainedInputs, PlanEvidence and SQL-free decoding in attempt_loads.py.
- Keep attempt_reads.py's connection boundary and codecs SQL-free.
- Put the remaining load queries and retained_on in attempt_store.py.
- ConflictStore.insert passes its current transaction connection to retained_on; no independently opened connection or nested transaction.
- Split existing status and write implementations into supporting store modules so the expanded owner fits the source cap; preserve AttemptStore and AttemptReads imports from attempt_store.py.
- Concrete AttemptLoads comes from attempt_store.py; migrate every direct constructor and type consumer.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_store.py`: concrete `AttemptLoads`, `retained_on`, `AttemptStore`; own load SQL and compose the existing read/write implementations.
- `src/taskloop/attempt_loads.py`: `AttemptLoads`, `RetainedInputs`, `PlanEvidence`, `verdict_of`; retain models, decoding and fencing orchestration with typed abstract query hooks implemented by the concrete store class; remove SQL and retained_on.
- `src/taskloop/attempt_reads.py`: `StoreConnection`, codecs; consult and preserve.
- `src/taskloop/attempt_status_store.py` (new): `AttemptReads`; relocate existing status/listing/chain implementation, integrated by attempt_store.py.
- `src/taskloop/attempt_write_store.py` (new): `AttemptWrites`; relocate existing AttemptStore writer methods, deriving from the SQL-free load base and integrated by AttemptStore's inheritance.
- `src/taskloop/land_conflict/store.py`: `ConflictStore.insert`; import retained_on from its owner and retain the current connection.
- `src/taskloop/land_conflict/admit.py`: `Ports.attempts`; use the concrete load store type.
- `src/taskloop/land_conflict/composition.py`: `conflict_handoff`; construct the concrete load store with the existing connect/begin pair.
- `src/taskloop/land_conflict/models.py`: `RetainedInputs` consumer; preserve import.
- `src/taskloop/resume_plan.py`: `PlanEvidence` consumer; preserve import.
- `tests/steps/land_conflict_bench.py`: `bench`; migrate AttemptLoads producer.
- `tests/steps/land_bench.py`: `Bench` conflict port producer; migrate AttemptLoads construction.
- `tests/steps/test_round_land.py`: conflict ports; migrate AttemptLoads construction.
- `tests/steps/refusal_inventory.py`: stored verdict rejection location; retain or update according to verdict_of's final location.
- `tests/steps/test_plan_content.py`: `verdict_of` consumer; preserve import.
- `tests/rules/test_attempt_sql_ownership.py`: SQL boundary assertion; include attempt_loads.py and retain existing protected modules.
- `tests/steps/test_attempt_loads.py` (new): load-result and fencing contracts; integrate with existing factory fixture and AttemptStore seeding patterns.
- `tests/steps/test_land_conflict_admit.py`: retained-input race coverage using existing bench.
- `tests/steps/test_recovery_callbacks.py`: callback contracts; consult.
- `tests/steps/test_attempt_store.py`: registration and connection contracts; consult.
- `tests/steps/test_attempt.py`: fixture producer; consult without growing this 800-line file.

## Read list
- `src/taskloop/attempt_store.py:1-228` — status relocation and configuration.
- `src/taskloop/attempt_store.py:229-492` — writers and recovery.
- `src/taskloop/attempt_loads.py:1-303` — query extraction and codecs.
- `src/taskloop/attempt_reads.py:175-252` — connection boundary and codecs.
- `src/taskloop/land_conflict/store.py:140-187` — transaction-local retained validation and reservation write.
- `src/taskloop/land_conflict/admit.py:8-76` — load port and pre-transaction retained read.
- `src/taskloop/land_conflict/composition.py:12-55` — connection and transaction injection.
- `src/taskloop/land_conflict/models.py:1-90` — inspect request matching.
- `src/taskloop/resume_plan.py:1-86` — inspect PlanEvidence consumer.
- `tests/steps/land_conflict_bench.py:1-70` — concrete load-store producer.
- `tests/steps/land_bench.py:190-225` — conflict port producer.
- `tests/steps/test_round_land.py:140-165` — conflict load-store constructor.
- `tests/steps/refusal_inventory.py:60-80` — verdict rejection source association.
- `tests/steps/test_plan_content.py:1-20` — verdict decoder integration.
- `tests/rules/test_attempt_sql_ownership.py:1-20` — current AST boundary enforcement.
- `tests/steps/test_attempt_store.py:1-110` — factory fixture, seed and registration/load contracts.
- `tests/steps/test_land_conflict_admit.py:1-140` — admission races, rollback and original-input retention.
- `tests/steps/test_recovery_callbacks.py:1-141` — callback identity, stale workers and restart capture.
- `tests/steps/test_attempt.py:1-150` — inspect fixture producers.

## Contract
Intent: preserve AttemptStore's API; expose concrete AttemptLoads from attempt_store.py. Its SQL-free base retains decoding and fencing with typed abstract query hooks for existing optional row projections. No persisted fields change.

Effect: AttemptWrites inherits the SQL-free load base; concrete AttemptLoads implements its hooks; AttemptStore combines both with AttemptReads. Preserve connections and statements. Check inheritance order and imports; shared models and codecs must not import the concrete store.

Result: load, collect, callback, retained, latest_plan, earlier, earlier_for and slot_base preserve values, missing results, malformed-row errors and identity fences. Preserve newest-plan selection, released retained inputs and callback authorization. retained_on returns RetainedInputs or None on the caller's connection without opening or committing a transaction.

## Work packages
1. Relocate existing status and writer classes into the two supporting store modules; keep stable AttemptStore/AttemptReads exports. Move remaining queries into attempt_store.py behind the minimal typed hooks used by attempt_loads.py. Keep changed source files within 400 lines and functions within 80. Closes acceptance 1.
2. Migrate the concrete load-store imports and all producers listed above; move retained_on's import in conflict admission. Retain model/codec imports and adjust the refusal inventory only if its referenced rejection moves. Add focused load contracts and a race that changes retained inputs between observation and insertion, asserting refusal and no reservation write. Closes acceptance 2 and 3.
3. Extend the AST boundary assertion to both read modules, preserving current protections. Verify optional rows, newest plans, reservation/callback fences and transaction reuse. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, retaining exit outcomes.

## Acceptance behaviours
1. Both read modules contain no SQL statements or database execution calls; all remaining load queries execute through attempt_store.py.
2. Fenced loads and execution reads return the same typed values, absent results and refusals, including released retained inputs, latest unsuccessful plans and stale recovery identities.
3. Conflict admission validates retained inputs on its current write connection; changed inputs refuse admission without reserving a slot, while repetition retains the original admission.
