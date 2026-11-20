# Header
Task: tl-8bh9.14.100; base: c8906e46b26e0dc092047e0e681f075e8f89fe46
Depth: medium; two behaviours.
Decisions: settled; no explicitly unlanded dependency.
Evidence budget: 12 model calls.
Size: 7 changed files; 2 independent behaviours; 50 model calls per implement attempt.

## Outcome and non-goals
Make transaction-boundary violations fail an AST check and guarded fake execution. Preserve the recursive SQL census and relative-path ownership; add regressions for nested stores with identical basenames. Extend existing claim guards, admission Git guards and launcher write-lock probes. No schema, workflow, shelf API or dependency changes.

## Settled decisions
- Enforcement (3): Git reads/writes, tracker calls and process start must execute outside write transactions; static and runtime checks complement each other.
- Enforcement (4): compare owners by paths relative to `src/taskloop`, retaining the exact verb/table ownership census.
- Preserve `WRITERS` and its uniqueness check; path identity and recursive discovery already exist in `sql_writes`.
- Reuse injected `begin`, `_connection(write=True)` and `begin_immediate` boundaries, plus existing semantic fakes and runtime guards.

## Open decisions
- None.

## Change map
- `tests/rules/test_policy.py` — `sql_writes`, `test_every_sql_write_has_its_one_owner`, `write_of`: parameterize the census root; retain recursive relative paths and exact comparison; add ownership regressions.
- `tests/rules/test_transaction_boundaries.py` (new) — AST scanner and repository check: integrate with rules collection; recognize write contexts and external port calls, report file/function/line, and exercise rejecting and permitted snippets.
- `tests/steps/test_admit.py` — `Tracker.claim`, `Tracker.unclaim`, guarded admission fixtures: add a deliberate transaction violation proving rejection before tracker effects; preserve ordinary admission coverage.
- `tests/steps/test_launch.py` — `FakeStart`, launcher registration/write-lock probe: add a negative control proving a held writer makes the fake start boundary fail before permission, while ordinary registration remains outside the lock.
- `tests/steps/test_publish.py` — `ScriptedPushRepo`, `Pushing.push`, publication fixtures: guard Git entry using `outside_transaction`; assert successful publication runs outside the transaction and a deliberate violation fails before the fake push.
- `tests/steps/admission_boundaries.py` — consult `outside_transaction` and `guard_git`; preserve their signatures. All discovered consumers to consult: `test_admit.py`, `test_admit_chain.py`, `test_check_admit.py`, `test_resume_plan.py`.
- `src/taskloop/attempt_reads.py`, `admit.py`, `check_release.py`, `merge/store.py`, `publish_store.py`, `launch.py` — consult transaction producers, SQL callbacks and effect callers to calibrate the AST rule; no planned application edits.
- `docs/design/tl-8bh9.14.100/plan.md` — implementation and acceptance contract.
- `docs/design/tl-8bh9.14.100/plan-metadata.json` — preparation commit and consulted paths.

## Read list
- `tests/rules/test_policy.py:64-164` — ownership map, recursive census and its callers.
- `tests/rules/test_policy.py:168-208` — existing Git API matching; do not confuse Git writes with all external calls.
- `tests/rules/test_sqlite_contracts.py:41-81` — existing store-path enforcement, separate from table ownership.
- `tests/steps/admission_boundaries.py:25-47` — typed runtime wrapper and existing Git guards.
- `tests/steps/test_admit.py:76-104` — tracker guards and side effects.
- `tests/steps/test_admit.py:142-150` — guarded admission integration.
- `tests/steps/test_admit_chain.py:105-106` — next-admission guard consumer.
- `tests/steps/test_admit_chain.py:131-131` — shared Git guard consumer.
- `tests/steps/test_admit_chain.py:247-247` — concurrent admission guard consumer.
- `tests/steps/test_check_admit.py:33-34` — checks-admission guard consumer.
- `tests/steps/test_resume_plan.py:75-78` — resume Git and tracker guard consumers.
- `tests/steps/test_launch.py:51-90` — fake start, callback and permission boundaries.
- `tests/steps/test_launch.py:142-161` — independent writer probe before and after registration.
- `tests/steps/test_publish.py:41-79` — semantic Git push boundary.
- `tests/steps/test_publish.py:359-390` — effects during push and fenced recording.
- `src/taskloop/attempt_reads.py:175-204` — injected transaction provider and write-context wrapper.
- `src/taskloop/admit.py:121-142` — typed external ports and transaction provider.
- `src/taskloop/check_release.py:309-346` — Git outside the transaction; SQL callbacks inside it.
- `src/taskloop/merge/store.py:15-36` — nested store and write/read contexts.
- `src/taskloop/publish_store.py:66-95` — transaction containing SQL, codecs and clock only.
- `src/taskloop/launch.py:150-181` — separate writer and durable dispatch boundary.
- `src/taskloop/launch.py:227-245` — process start and registration callback caller.

## Contract
No new runtime types, states or stored fields. New check helpers take explicit paths or AST input and return typed violation records/collections; diagnostics identify the offending location and external call.

Static boundary: recognize `begin(...)`, `begin_immediate(...)`, `_connection(write=True)`, imported aliases and injected receiver forms. Scan source recursively. Reject identified Git, tracker and start calls in active write scopes, including later expressions of a compound `with`. Cover reads, callable ports, retained methods and straightforward aliases. Uncalled nested functions are not execution. Fixture-test recognized forms; runtime guards cover indirect effects. Permit SQL, codecs, clocks and database-only store callbacks.

Runtime boundary: durable intent precedes effects; fake entry observes no transaction or permits an independent writer. Violations stop before effects or launch permission. Preserve fenced result recording and positive scenarios; add negative controls for Git, tracker and spawn.

Ownership boundary: intent is an exact allowed `(verb, table, relative owner path)` census; effect is recursive source discovery; result rejects unknown writers, competing owners, missing expected writes and basename collisions. `one/store.py` and `two/store.py` remain different owners. Do not replace table ownership with the separate SQLite-import rule.

## Work packages
1. `tests/rules/test_policy.py`: parameterize the census root without changing its default and add nested-store fixtures, including moving a write to the wrong sibling store. Closes A2.
2. New `tests/rules/test_transaction_boundaries.py`: implement the scoped AST check, exercise direct/aliased Git reads and writes, tracker and start calls, nested/compound contexts, allowed database calls and calls after transaction exit. Run against current source. Closes static A1.
3. `tests/steps/test_admit.py`, `test_launch.py`, `test_publish.py`: extend existing fake-port scenarios with deliberately violating controls; reuse `admission_boundaries` and retain all discovered consumers. Closes runtime A1.
4. Run focused contract/scenario files as needed. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each; capture their actual exit status with pipeline failure propagation. Reconcile any failure within this scope before delivery.

## Acceptance behaviours
- A1: Git reads/writes, tracker calls and process starts in write scopes fail the AST check and guarded fake execution before effects; ordinary intent/effect/result execution and database-only work pass.
- A2: recursively discovered sibling `store.py` files keep separate relative-path identities; misplaced, competing and unexpected SQL writers fail while the current exact ownership census passes.
