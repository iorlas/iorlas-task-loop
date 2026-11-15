# Header
Task: tl-8bh9.14.88.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; SQL boundary across 3 modules.
Decisions missing: none. Unlanded dependencies: none stated.
Evidence budget: 12 model calls.
Size: 15 files; 1 behaviour (A1); ~60 implement model calls.

## Outcome and non-goals
Admission queries and writes have one owner and named results. Fresh admission, repeat and advance retain their effects and refusals. `admit.py` already executes no SQL; it needs import integration. Existing tests cover races, claim timing and advancement. The gap is extraction, caller migration and boundary coverage. Other slices' own SQL, schema changes and connection-lifecycle redesign are outside scope.

## Settled decisions
- Use `admit_store.py` for admission SQL, including the shared current-attempt query and reservation transfer.
- Keep `admit_rows.py` for data definitions; keep orchestration and refusal decisions in `admit.py` and `admit_chain.py`.
- Replace imported SQL constants with store reads; update helper imports directly rather than retaining forwarding functions.
- Preserve the caller's transaction: reservation insertion or transfer, generation update, attempt insertion and task-content evidence succeed or roll back together.

## Open decisions
- None.

## Change map
- `src/taskloop/admit_store.py` (new): `unheld`, `reserve`, `insert_attempt`, `issue`, `issued`, `next_seq`, `task_attempted`, `transfer`, `task_of`, `previous`, `current`; extract SQL and private binding/decoding; integrate all callers below.
- `src/taskloop/admit_rows.py`: retain `Free`; add `Task`, `Previous` and `Current` data definitions; remove SQL helpers.
- `src/taskloop/admit.py`: `AttemptAdmission._observe`, `_input`, `_commit`, `_compensate`; import store helpers directly, preserving rechecks and claims.
- `src/taskloop/admit_chain.py`: `ChainAdmission._takeover_open`, `NextAdmission._previous`, `_advance`; consume named store results; remove `PREVIOUS`, `CURRENT`, `transfer` and `task_of` implementations.
- `src/taskloop/check_admit.py`: `next_number`, `ChecksAdmission`; migrate `task_of`, current-attempt read and generation/reservation helper imports.
- `src/taskloop/land.py`: `_task`; replace `CURRENT` execution and positional decoding with the current-attempt store read; migrate `task_of`.
- `src/taskloop/land_check.py`: `_reserved`; migrate `issued`, `unheld`, `reserve` imports.
- `src/taskloop/check_repeat/store.py`: `CheckRepeatStore.generation`, `admit`; migrate generation, slot, reservation and attempt helpers.
- `src/taskloop/answer_repair_store.py`: `AnswerRepairStore._insert`; migrate `insert_attempt` and `transfer` without changing repair-session writes.
- `src/taskloop/land_conflict/store.py`: `ConflictStore`; migrate `reserve`.
- `tests/steps/test_checks_round.py`: candidate fixture producer; migrate `issued` and `reserve` imports.
- `tests/steps/test_land_conflict_admit.py`: reservation fixture producers; migrate `reserve` import.
- `tests/steps/test_admit_store.py` (new): structural SQL boundary and atomic admission/reservation coverage; integrate existing SQLite fixtures and admission helpers.
- `docs/design/tl-8bh9.14.88.1/plan.md`: implementation contract.
- `docs/design/tl-8bh9.14.88.1/plan-metadata.json`: preparation commit and consulted paths.

## Read list
- `src/taskloop/admit_rows.py:15-98` — slot observation and all extracted row helpers.
- `src/taskloop/admit.py:123-188` — constructor, input preparation and generation read.
- `src/taskloop/admit.py:205-326` — observation, claim boundaries and atomic fresh admission.
- `src/taskloop/admit_chain.py:55-176` — repeat query, transfer and takeover fencing.
- `src/taskloop/admit_chain.py:179-224` — current query and task data definition.
- `src/taskloop/admit_chain.py:264-386` — advance reads, transactional rechecks and task lookup.
- `src/taskloop/check_admit.py:24-113` — imported helpers and current-attempt checks.
- `src/taskloop/check_admit.py:130-163` — generation and task lookup callers.
- `src/taskloop/check_admit.py:219-239` — reservation caller under its write transaction.
- `src/taskloop/land.py:116-134` — shared current-attempt consumer.
- `src/taskloop/land_check.py:118-139` — generation, slot selection and reservation consumer.
- `src/taskloop/check_repeat/store.py:60-113` — helper consumers and atomic repair admission.
- `src/taskloop/answer_repair_store.py:91-111` — attempt insertion, repair-session effect and transfer.
- `src/taskloop/land_conflict/store.py:146-177` — reservation caller and surrounding writes.
- `src/taskloop/task_content_store.py:10-27` — evidence insertion joins admission's transaction.
- `src/taskloop/factory_schema.py:280-324` — admitted column lists and successor expressions.
- `src/taskloop/factory_store.py:20-47` — schema validation.
- `tests/steps/test_admit.py:59-167` — semantic tracker, slots and admission helpers.
- `tests/steps/test_admit.py:249-293` — free-slot race acceptance coverage.
- `tests/steps/test_admit_chain.py:218-244` — concurrent advance regression coverage.
- `tests/steps/test_checks_round.py:410-420` — reservation fixture producer.
- `tests/steps/test_land_conflict_admit.py:130-156` — reservation producers; the same import serves the later caller at 284.

## Contract
Intent: orchestration asks the store to observe or mutate admission facts. `Free` remains the process observation. `Task` moves from `admit_chain` into the data module. `Previous` and `Current` are validated pydantic row models with named fields corresponding to the existing queries; `Current` includes the attempt key, done predicate, step, end commit, tracker root, sequence and label. `Previous` preserves repeat eligibility, successor presence, copied choices and sequence. Store reads return these models or absence, never a cursor or positional database row. Invalid stored data follows the existing store-error path.

Effect: the store executes queries and parameter binding. Its mutation helpers join the supplied transaction and neither commit nor open a nested transaction. `insert_attempt` continues to delegate evidence insertion to `TaskContentStore`; a plan without evidence fails before admission can commit. A failed fenced transfer triggers the caller's existing rollback path, including earlier writes in that transaction. Store imports depend on data definitions, never admission orchestration.

Result: existing admission outcome types, reasons, database columns, constraints, sequence ordering and generation semantics stay unchanged. Rechecks remain under the same write lock. There is no new stored state, schema version or external action. Shared callers use store functions directly; their unrelated queries remain in their existing owners.

## Work packages
1. Extract SQL and binding/decoding into the new store; introduce named row models in `admit_rows.py`; integrate fresh, repeat and advance orchestration. Closes A1 for the named admission modules.
2. Migrate every SQL/helper consumer in the change map and the two fixture producers. Closes A1 for shared reservation and current-attempt reads, without exported SQL constants.
3. Add `test_admit_store.py` boundary coverage and an atomic rollback scenario that fails after reservation or attempt insertion; exercise existing race, repeat and advance coverage. Closes A1's preservation criterion. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last; both must pass.

## Acceptance behaviours
A1: The three admission modules execute no SQL; the admit store owns their queries and shared helper effects, while successful admissions and stale or failed admissions retain the same outcomes, reservation fencing, generation/sequence values, task-content evidence and all-or-nothing writes through fresh, repeat, advance and shared callers.
