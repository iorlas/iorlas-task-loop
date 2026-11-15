# Header
Task: tl-8bh9.14.88.4.2
Base: 7408f9824de955d8cfa8c49c3a9dd80230391616
Depth: medium
Reason: two named owning modules.
Owner decision: none; unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 2 artifact files, 1 independent behaviour, 10 implement model calls.

## Outcome and non-goals
Confirm the existing SQL ownership and registration behaviour satisfy this task. Both target modules already delegate registration configuration to the attempt slice store; the structural rule already covers both. The remaining work is verification, with no production or test edits currently indicated. Do not duplicate the helper or widen this task into sibling SQL extractions, connection-port redesign, schema changes or shelf changes. The two changed artifacts are this plan and its new metadata file.

## Settled decisions
- Keep `AttemptStore`'s existing `configure_registration` as the registration SQL owner.
- Preserve the connection-local 1500 ms registration wait and ordinary 5000 ms wait.
- Preserve registration transactions, failure propagation, registration before permission and existing launch outcomes.
- Reuse the existing structural and behavioural coverage; add no duplicate tests merely to produce an implementation diff.
- The supplied parent discussion establishes independent sibling scope, with no dependency to await.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_store.py` — `configure_registration`, `REGISTRATION_BUSY_MS`: retain the existing SQL owner and timeout; verify its contract.
- `src/taskloop/launch.py` — `Launcher.launch`: retain its helper call before dispatch and existing failure translation; confirm absence of SQL.
- `src/taskloop/composition.py` — `_registration`, `open_attempts`, `open_checking`, `open_recovery_registration`: retain bounded connection wiring through the helper; confirm absence of SQL throughout the module.
- `tests/steps/test_attempt_store.py` — `test_registration_configuration_is_connection_local_and_preserves_transaction`, `test_registration_configuration_propagates_sqlite_errors`: verify the helper's direct callers and effect boundaries.
- `tests/steps/test_launch.py` — `test_launch_registers_before_the_permit_and_leaves_the_child_alone`, `test_the_registration_write_waits_briefly_and_a_busy_store_registers_nothing`: verify dispatch and store failure behaviour.
- `tests/cli/test_writer_lifetime.py` — `test_entry_ordinary_and_bounded_connections_remain_distinct`: verify production wiring separates registration and ordinary writers.
- `tests/steps/test_continuation_composition.py` — `test_real_composition_retains_custody_through_native_execution`: verify continuation registration wiring and custody.
- `tests/rules/test_attempt_sql_ownership.py` — `test_attempt_read_modules_and_registration_callers_have_no_sql`: retain existing coverage for both named modules.
- `docs/design/tl-8bh9.14.88.4.2/plan.md` — new plan: record verification work and acceptance.
- `docs/design/tl-8bh9.14.88.4.2/plan-metadata.json` — new metadata: bind the plan to the supplied commit and consulted paths.

## Read list
- `src/taskloop/attempt_store.py:14-23` — registration SQL owner, exported helper and constant.
- `src/taskloop/launch.py:151-188` — connection acquisition, helper caller, failure translation and closure.
- `src/taskloop/launch.py:202-268` — registered callback, permission and process-start outcomes.
- `src/taskloop/composition.py:64-90` — bounded connection producer and recovery registration integration.
- `src/taskloop/composition.py:98-191` — continuation, attempt and checks wiring consuming bounded connections.
- `src/taskloop/composition.py:222-235` — agent and checks launch composition.
- `tests/steps/test_attempt_store.py:44-63` — transaction, timeout isolation and error propagation assertions.
- `tests/steps/test_launch.py:133-175` — launch registration ordering and refusal assertions.
- `tests/steps/test_launch.py:293-306` — busy registration failure coverage.
- `tests/cli/test_writer_lifetime.py:83-100` — distinct production connections and their timeout assertions.
- `tests/steps/test_continuation_composition.py:67-111` — continuation timeout and custody assertions.
- `tests/rules/test_attempt_sql_ownership.py:1-32` — existing AST guard against SQL calls and SQL literals.

## Contract
No new typed names, states, stored fields or schema version. Preserve `configure_registration(con: sqlite3.Connection) -> None` inside the attempt slice store: intent is to bound registration lock waits; effect is the connection-local busy-timeout setting; result is normal return or the original SQLite exception. It neither starts nor commits a transaction.

The existing direct callers are `Launcher.launch`, `_registration.bounded` and the two configuration tests listed above. Launch configures its writer before the registered callback can permit entry execution. Composition configures each returned registration connection while ordinary connections retain their own wait. A failed registration permits no target execution and preserves existing unavailable/refused outcomes. SQL remains behind the existing slice-store operations; callers keep their current public contracts.

## Work packages
1. Verify the existing implementation and structural coverage in `launch.py`, `composition.py`, `attempt_store.py` and the listed tests. Close acceptance A1 using existing code; no extraction or additional implementation is currently needed. If code changed since planning, inspect only the affected callers before any bounded correction.
2. After `just install`, run the five focused test files from the Read list using the permitted isolated pytest invocation, one file per invocation. Then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; preserve their actual exit status. These checks supply evidence for A1. Do not describe planning-time inspection as passing tests; if verification succeeds, finish without manufacturing source changes.

## Acceptance behaviours
A1. Both named modules remain free of SQL execution and SQL statements, with registration SQL owned by the attempt slice store; registration timeouts remain connection-local, transaction ownership and error propagation are preserved, and dispatch and continuation retain their existing permission, failure and custody behaviour.
