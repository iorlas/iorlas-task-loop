# Header
Task: tl-8bh9.14.88.3.4
Base: 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: small; one SQL ownership behaviour in one module
No missing owner decision or unlanded dependency.
Evidence budget: 6 model calls.
Size: 3 changed files, 1 independent behaviour, 20 implement model calls.

## Outcome and non-goals
Queries already live in attempt stores. The remaining gap is that the ownership guard omits attempt_entry.py. Protect this boundary and preserve entry behaviour. Sibling moves and schema changes are outside scope.

## Settled decisions
- SQL execution excludes _step's Attempts.execute application operation.
- Retain store ownership and entry interfaces.
- Extend the AST guard; allow app.execute only in attempt_entry.py.

## Open decisions
- None.

## Change map
- tests/rules/test_attempt_sql_ownership.py: test_attempt_read_modules_and_registration_callers_have_no_sql adds entry coverage with the app.execute allowance.
- src/taskloop/attempt_entry.py: _registered, _record, _step, database_exists, shown, arguments and main stay unchanged.
- src/taskloop/attempt_store.py: AttemptStore retains SQL owner composition.
- src/taskloop/attempt_status_store.py: AttemptReads retains status SQL.
- src/taskloop/attempt_write_store.py: AttemptWrites retains write SQL.
- src/taskloop/check_entry.py: _registered consumes database_exists, EntryArgs and arguments unchanged.
- src/taskloop/launch.py: ENTRY_MODULE produces entry invocations unchanged.
- tests/steps/test_attempt_entry.py: Entry validates dispatch and refusal unchanged.
- tests/steps/test_recovery_entry.py: run_entry consumes enter and EntryArgs unchanged.
- tests/steps/test_check_entry.py: EntryArgs consumer unchanged.
- tests/steps/test_verifier.py: shown consumer unchanged.
- tests/steps/test_repeat_dispatch.py: shown consumer unchanged.
- tests/steps/test_launch.py: launcher argv and module assertions unchanged.
- docs/design/tl-8bh9.14.88.3.4/plan.md: new plan.
- docs/design/tl-8bh9.14.88.3.4/plan-metadata.json: new evidence metadata.

## Read list
- tests/rules/test_attempt_sql_ownership.py:1-20 — extend existing guard.
- src/taskloop/attempt_entry.py:119-201 — read-only existence check and store delegation.
- src/taskloop/attempt_entry.py:214-244 — application execute calls requiring allowance.
- src/taskloop/attempt_store.py:14-40 — registration SQL owner.
- src/taskloop/attempt_store.py:42-112 — query owner composition.
- src/taskloop/attempt_status_store.py:19-48 — status query ownership.
- src/taskloop/attempt_write_store.py:33-80 — fenced write ownership.
- src/taskloop/check_entry.py:35-75 — shared entry helper consumer.
- src/taskloop/launch.py:1-35 — entry invocation producer.
- tests/steps/test_attempt_entry.py:194-261 — normal execution and missing database refusal.
- tests/steps/test_recovery_entry.py:1-55 — recovery entry consumer.
- tests/steps/test_check_entry.py:20-35 — EntryArgs consumer.
- tests/steps/test_verifier.py:23-28 — shown consumer.
- tests/steps/test_repeat_dispatch.py:23-28 — shown consumer.
- tests/steps/test_launch.py:145-151 — invocation contract.

## Contract
Intent: run the registered attempt. Effect: stores own SQL; app.execute runs the application. Result: typed results, refusal words and exit codes stay unchanged. No new runtime types, fields or states. The guard rejects SQL literals and cursor/executemany/executescript calls; only the entry's app.execute calls are exempt from the execute ban.

## Work packages
1. Extend tests/rules/test_attempt_sql_ownership.py; validate the acceptance behaviour with existing entry tests. Run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last.

## Acceptance behaviours
- Registered entry execution and refusal outcomes remain identical while SQL stays owned by attempt stores; adding database execution to the entry fails the ownership guard without rejecting Attempts.execute.
