# Header
Task: tl-8bh9.14.88.2.1; base: bd92e6dd4727b4047958c1d21eb7917c497b4b10
Depth: medium; read ownership and registration across modules.
Owner decisions missing: none; unlanded dependencies: none.
Evidence budget: 12 model calls.
Size: 13 changed files, 3 behaviours, about 40 implement calls.

## Outcome and non-goals
`attempt_store.py` owns the status/listing/chain queries and registration timeout SQL. Existing consumers receive the same values and failures through the same ordinary or bounded connections. Keep the current public `AttemptStore` API. Remaining execution/load SQL and conflict admission belong to the separate loads task; no schema, runtime lifecycle or shelf change is needed.

## Settled decisions
- No numbered task decisions or unresolved prerequisites are supplied.
- Scoped history, current-row selection and whole-task counts are delivered; preserve them.
- Remaining gaps: `AttemptReads` owns queries; `composition._registration` and `Launcher.launch` issue timeout SQL.
- Keep execution/verification writes in `attempt_store.py`; relocate SQL-free codecs and fence helpers for space.
- Move the query-only `AttemptReads` class into `attempt_store.py`; keep its existing models, connection boundary and decoding helpers in `attempt_reads.py`. Update its consumers without a compatibility re-export.
- Change `AttemptLoads` to inherit `StoreConnection`. Compose `AttemptStore` from `AttemptLoads` and the relocated `AttemptReads`, sharing the existing connection initializer. Move `previous_abandoned` with the status queries because it calls `release_of`; other load queries stay put.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_reads.py`: move query class/constants out; add listing decoder and execution/verdict encoders.
- `src/taskloop/attempt_store.py`: receive `AttemptReads`, `STEP`, `RELEASED`, `previous_abandoned`; compose `AttemptStore`; add `configure_registration`; retain writes/timeout constant.
- `src/taskloop/attempt_loads.py`: inherit `StoreConnection`; move `previous_abandoned` out; receive SQL-free `_fence`/`_owned`.
- `src/taskloop/setup_store.py`: migrate `AttemptReads` import for base and registration parameter.
- `src/taskloop/composition.py`: migrate constructors in `open_attempts`/`open_checking`; replace `_registration` SQL with helper call.
- `src/taskloop/launch.py`: replace `Launcher.launch` timeout SQL with helper call.
- `tests/steps/test_attempt_listing.py`: extend status/listing/chain coverage.
- `tests/steps/test_attempt_store.py`: cover timeout helper and missing result/failure assertions.
- `tests/steps/test_setup_store.py`: migrate registration import/constructor; preserve routing assertion.
- `tests/steps/test_check_store.py`: migrate registration import/constructor; preserve routing assertion.
- `tests/rules/test_attempt_sql_ownership.py` (new): enforce scoped SQL boundary via existing rules-suite discovery/source inspection.
- `tests/steps/test_launch.py`: consult bounded busy-writer assertion.
- `tests/cli/test_writer_lifetime.py`: consult connection separation/lifetime assertions.
- `src/taskloop/attempt_status.py`: consult `StatusPorts` and listing consumers.
- `src/taskloop/attempt_entry.py`: consult entry store/failure consumers.
- `src/taskloop/recovery/registration.py`: consult `registration_hook`.
- `src/taskloop/drain/store.py`: consult `blocked`/`pending` dependencies.
- `tests/rules/test_policy.py`: consult size/write-owner contracts.
- `tests/steps/test_repeat.py`: consult chain constraints.
- `docs/design/tl-8bh9.14.88.2.1/plan.md`: bounded plan artifact.
- `docs/design/tl-8bh9.14.88.2.1/plan-metadata.json`: preparation/citation artifact.

## Read list
- `src/taskloop/attempt_reads.py:1-213` — types/codecs/connection.
- `src/taskloop/attempt_reads.py:214-395` — query class.
- `src/taskloop/attempt_store.py:1-69` — encoders/imports.
- `src/taskloop/attempt_store.py:70-244` — fences/registration.
- `src/taskloop/attempt_store.py:245-352` — retained writes.
- `src/taskloop/attempt_loads.py:12-42` — imports.
- `src/taskloop/attempt_loads.py:104-137` — base/release dependency.
- `src/taskloop/attempt_loads.py:164-229` — load/fences.
- `src/taskloop/setup_store.py:134-155` — base/registration.
- `src/taskloop/composition.py:63-90` — registration producer.
- `src/taskloop/composition.py:121-190` — attempt/check wiring.
- `src/taskloop/launch.py:145-183` — writer/timeout.
- `src/taskloop/attempt_status.py:13-60` — status consumers.
- `src/taskloop/attempt_entry.py:29-45` — store failures.
- `src/taskloop/recovery/registration.py:1-19` — hook.
- `src/taskloop/drain/store.py:1-28` — fence dependencies.
- `tests/steps/test_attempt_listing.py:1-120` — projections/snapshot.
- `tests/steps/test_attempt_store.py:1-165` — registration/failures.
- `tests/steps/test_setup_store.py:131-155` — routing.
- `tests/steps/test_check_store.py:264-275` — routing.
- `tests/steps/test_launch.py:293-305` — busy writer.
- `tests/cli/test_writer_lifetime.py:83-106` — isolation/timeouts.
- `tests/rules/test_policy.py:1-64` — source inspection/caps.
- `tests/rules/test_policy.py:120-153` — write owners.
- `tests/steps/test_repeat.py:555-578` — chain constraints.

## Contract
Intent: read status/listings/slot metadata/input/chains. Effect: SELECTs execute in `attempt_store.py` through `StoreConnection`, without new fences or writes. Result: unchanged `AttemptRow`, `ReleaseRow`, `PublishedRow`, `SlotUse`, `ChainLink`, `FileRef`, optional values, ordering and exceptions.

Intent: configure registration. Effect: `configure_registration(con: sqlite3.Connection) -> None` sets the existing 1500 ms timeout on that connection, without connection/transaction ownership changes. Result: `None`; callers retain SQLite failure handling.

SQL-free codecs/fences keep the store within its cap. Callback/reservation fencing retains its transaction. No fields, states or edge models change. The ownership test covers `attempt_reads.py` and both registration callers, excluding deferred load SQL and setup/check stores.

## Work packages
1. Relocate the read class/constants and SQL-free conversions; adjust `AttemptLoads`, move `previous_abandoned`, and compose `AttemptStore` without an import cycle. Files: reads, loads, store, listing/store tests. Closes A1 and A2.
2. Centralize timeout SQL and migrate all identified registration constructors/imports. Files: store, composition, launch, setup store, setup/check tests. Reuse launcher/writer-lifetime coverage. Closes A3.
3. Add the scoped ownership contract and run focused affected files using `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40` after installation. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each as the final gates. Closes the ownership condition across A1–A3.

## Acceptance behaviours
A1. Historical/current and scoped listings, status/slot/input reads and whole-task counts return identical typed values, ordering and unavailable/malformed-data failures; listing selection completes before external observations.
A2. Chains retain oldest-first numbering, repair skipping, the attempt bound and broken-chain failures; previous-abandoned reads retain their release semantics.
A3. Attempt, setup, checks and recovery registration retain the same writer selection, transaction owner, timeout, contention/refusal outcomes and ordinary-connection isolation; neither registration caller nor `attempt_reads.py` issues SQL.
