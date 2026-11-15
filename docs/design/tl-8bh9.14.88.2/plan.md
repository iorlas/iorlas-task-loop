# Header
Task: tl-8bh9.14.88.2
Base: 8234d1a09e34c2ed2af728a936a8375a3a28438f
Depth: medium; one SQL boundary across three modules.
Decisions: none missing; .88.1 landed.
Evidence budget: 12 model calls.
Size: 18 changed files, 1 independent behaviour, about 75 implement model calls.

## Outcome and non-goals
Attempt persistence has one SQL entry point; status, recovery, registration and conflict admission retain their results. Read modules provide models and pure decoding. Leave delivered admission extraction intact. No schema, command, scheduling, shelf or shared-connection consolidation.

## Settled decisions
- `AttemptStore` owns queries, fragments, traversal, transaction scopes and existing writes.
- Retain shared models, scalar validation, exceptions and `StoreConnection`; remove concrete `AttemptReads` and `AttemptLoads` classes and migrate direct users.
- Extract pure decoding and decision preparation to meet existing file/function caps.
- Conflict admission's retained-input read uses its existing connection and transaction.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_reads.py`: `AttemptReads`, `STEP`, `RELEASED`, `_attempts`, `chain`; move SQL and traversal to the store, retain row models and pure status decoders; keep shared connection plumbing unchanged.
- `src/taskloop/attempt_loads.py`: `AttemptLoads`, `retained_on`, `_load`, `_repair_source`, `_execution`, `_callback`; move database operations to the store; retain `RetainedInputs`, `PlanEvidence`, `verdict_of` and pure decoders. Host pure write-decision helpers extracted from the store when needed for its cap.
- `src/taskloop/attempt_store.py`: `AttemptStore`; inherit shared connection plumbing directly, expose existing status/load/write operations, own all moved SQL, and delegate decoding. Move `retained_on` here for transaction-local callers.
- `src/taskloop/setup_store.py`: `SetupStore`, `registering`; replace the removed read-class base/type with the concrete attempt store, preserving bounded registration connections and setup's process override.
- `src/taskloop/composition.py`: `open_attempts`, `open_checking`; construct `AttemptStore` for bounded registration reads with the same connection and begin functions.
- `src/taskloop/land_conflict/admit.py`: `Ports.attempts`; use the concrete attempt-store type.
- `src/taskloop/land_conflict/composition.py`: `AttemptLoads` construction; construct `AttemptStore` with the existing shared connection and transaction factory.
- `src/taskloop/land_conflict/store.py`: `retained_on` import/call; call the relocated helper inside admission's existing write transaction.
- `tests/steps/test_check_store.py`: registration-connection fixture; migrate direct `AttemptReads` construction, retaining connection-routing assertions.
- `tests/steps/test_setup_store.py`: registration-connection fixture; migrate direct `AttemptReads` construction, retaining routing assertions.
- `tests/steps/test_round_land.py`: conflict-admission ports; replace direct `AttemptLoads` construction.
- `tests/steps/land_bench.py`: `Checking.conflicts`; replace direct `AttemptLoads` construction.
- `tests/steps/land_conflict_bench.py`: admission-port construction; replace direct `AttemptLoads` construction.
- `tests/steps/test_attempt_store.py`: store fixtures and behaviour checks; extend coverage for fenced loads, retained inputs and malformed stored data only where existing tests leave a gap.
- `tests/steps/test_attempt_listing.py`: scoped-history/current-row coverage; verify results after moving query assembly and hydration.
- `tests/rules/test_policy.py`: SQL ownership contract; reject SQL literals and execution calls in both read modules without changing existing write-owner or size rules.
- `docs/design/tl-8bh9.14.88.2/plan.md`: new implementation plan.
- `docs/design/tl-8bh9.14.88.2/plan-metadata.json`: new preparation commit and consulted-path metadata.

## Read list
- `src/taskloop/attempt_reads.py:20-395` — shared models/connection API, all status queries and chain decoding.
- `src/taskloop/attempt_loads.py:47-300` — retained inputs, plan evidence, fenced loads, repair and execution decoding.
- `src/taskloop/attempt_store.py:40-352` — existing write decisions and transactions that consume the moved reads.
- `src/taskloop/setup_store.py:134-160` — read-class inheritance, registration dependency and process override.
- `src/taskloop/composition.py:123-190` — ordinary and bounded connection wiring.
- `src/taskloop/land_conflict/admit.py:30-76` — consumer of retained inputs through attempt ports.
- `src/taskloop/land_conflict/composition.py:12-40` — direct load-class construction.
- `src/taskloop/land_conflict/store.py:140-160` — retained-input read within admission transaction.
- `tests/steps/test_check_store.py:261-274` — bounded registration connection assertion.
- `tests/steps/test_setup_store.py:133-152` — setup registration routing assertion.
- `tests/steps/test_round_land.py:146-160` — conflict-admission store construction.
- `tests/steps/land_bench.py:208-219` — shared conflict ports.
- `tests/steps/land_conflict_bench.py:48-60` — seeded retained-input producer and admission wiring.
- `tests/steps/test_attempt_store.py:20-204` — seeded admission producer, registration fences and unavailable-store coverage.
- `tests/steps/test_attempt_listing.py:20-209` — history/current queries, scope and restart-count expectations.
- `tests/rules/test_policy.py:17-58` — AST policy and effective size accounting.
- `tests/rules/test_policy.py:112-165` — existing SQL ownership enforcement.
- `src/taskloop/factory_schema.py:286-297` — authoritative stored-column order used by decoders.
- `src/taskloop/admit_store.py:18-71` — delivered admission query/write pattern and attempt-row producer.
- `src/taskloop/factory_store.py:1-46` — existing schema/error boundary; consult without moving its ownership.

## Contract
Intent: preserve `AttemptStore` operation signatures and results: `AttemptRow`, `SlotUse`, `AttemptRecord`, `StoredExecution`, `RetainedInputs`, `PlanEvidence`. Removed read-class users use this store; shared models retain their imports.

Effect: SQL, predicates, execution, traversal and database-dependent checks belong in `attempt_store.py`. Decoders accept fetched values only. Extract pure write preparation as needed. Fencing, schema validation and SQLite error translation retain their transaction boundaries. Connection-taking store helpers never open or commit a second transaction.

Result: preserve absence/errors, scope/order, latest selection, snapshot counts, repair-skipping chains, reservation generations, callback authorization, write idempotence, revisions, deadlines and registration routing. No stored fields or outcomes change.

## Work packages
1. Refactor the three attempt modules together: move queries and database-dependent checks into `AttemptStore`, extract pure decoders/decision helpers and keep each module within its cap. Closes acceptance A.
2. Migrate setup/composition/conflict callers and their five direct-construction test/helper files; preserve bounded registration and transaction-local retained reads. Closes acceptance A at integration points.
3. Extend focused store/listing coverage for any uncovered result or fence and add the read-module SQL ownership policy. Finish implementation with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last. Closes acceptance A's regression and ownership evidence.

## Acceptance behaviours
A. Listings, chains, loads and retained inputs preserve scoped/ordered results and absent, malformed, superseded or stale-reservation outcomes through `AttemptStore`; registration retains its bounded connection and conflict admission its transaction; neither read module contains SQL or executes database statements.
