# Header
Task: tl-8bh9.14.88.4.3
Base: 7408f9824de955d8cfa8c49c3a9dd80230391616
Depth: medium; three SQL ownership areas.
Decision: none missing. Dependency: none unlanded.
Evidence budget: 12 model calls.
Size: 16 changed files, 3 independent behaviours, ~40 implement model calls.

## Outcome and non-goals
Admission and schema compatibility reads execute in their owning stores. Protect recovery's existing store delegation. Preserve ordering, refusals, transactions and restart safety. Declarative DDL and shared fragments stay in factory_schema.py. No schema upgrade, recovery redesign, sibling extraction or shelf change.

## Settled decisions
- Extract only the latest-checks projection; next_number retains admission policy and refusal wording.
- Add check_admit_store.py rather than extending check_store.py, which already has 448 lines.
- Move current, refusal and _recorded together to factory_store.py; update callers directly, without forwarding aliases or an import cycle.
- Keep SCHEMA version 31 and its pinned DDL unchanged.
- Recovery's SQL already belongs to recovery/state_store.py and recovery/store.py. Their SQL stays there; application execute methods are use-case calls, not SQL execution.
- Supplied discussion establishes independent sibling work; this task requires no sibling delivery.

## Open decisions
- None.

## Change map
- `src/taskloop/check_admit_store.py` (new): `LatestChecks`, `latest` own LATEST SQL; integration: check_admit.next_number and factory_schema.LANDED/LANDING.
- `src/taskloop/check_admit.py`: `next_number`, `ChecksAdmission` use the store at both reads; remove LATEST.
- `src/taskloop/check_store.py`: `ChecksAdmitted`, `insert` produce numbered rows; consult only.
- `src/taskloop/factory_schema.py`: remove `current`, `refusal`, `_recorded` and database-access imports; retain schema declarations.
- `src/taskloop/factory_store.py`: own `current`, `refusal`, `_recorded`; preserve `open_ro` validation/cleanup.
- `src/taskloop/admit.py`: `open_store` import current from factory_store.
- `src/taskloop/attempt_reads.py`: `StoreConnection._connection` import current from factory_store.
- `src/taskloop/slots_store.py`: `SlotsStore.require_current` import current from factory_store.
- `src/taskloop/slot_release_store.py`: `SlotReleaseStore._connected` import current from factory_store.
- `src/taskloop/publish_store.py`: `PublishStore._connect` import current from factory_store.
- `src/taskloop/check_release.py`: `_connected` import current from factory_store.
- `src/taskloop/drain/composition.py`: import `current`, `refusal` from factory_store; preserve writer recheck.
- `tests/steps/test_check_admit.py`: admission scenarios cover numbering, refusal precedence and races.
- `tests/steps/test_factory_schema.py`: compatibility scenarios cover moved reads and unavailable version diagnostics.
- `tests/rules/test_attempt_sql_ownership.py`: extend AST guard to admission, schema and recovery orchestration, recognizing inspected application calls.

## Read list
- `src/taskloop/check_admit.py:39-111` — latest-checks projection and admission policy.
- `src/taskloop/check_admit.py:140-236` — preflight and transactional revalidation callers.
- `src/taskloop/check_store.py:230-247` — insert produces numbered checks rows under the reservation fence.
- `src/taskloop/factory_schema.py:330-395` — land predicates, helpers and executable version reads.
- `src/taskloop/factory_store.py:1-46` — compatibility owner and open/close behaviour.
- `src/taskloop/admit.py:355-372` — open_store compatibility gate; update its current import.
- `src/taskloop/attempt_reads.py:185-210` — connection gate; update its current import.
- `src/taskloop/slots_store.py:1-40` — slot compatibility gate and import.
- `src/taskloop/slot_release_store.py:87-100` — release compatibility gate; update its current import.
- `src/taskloop/publish_store.py:1-80` — publication imports and connection gate.
- `src/taskloop/check_release.py:100-110` — release connection gate; update its current import.
- `src/taskloop/drain/composition.py:16-80` — imports, writer recheck and refusal translation.
- `src/taskloop/recovery/store.py:43-148` — execution intent and read/write transaction ownership.
- `src/taskloop/recovery/state_store.py:1-51` — persisted intents and callback fences.
- `src/taskloop/recovery/recover.py:73-178` — orchestration delegates snapshot and authorization reads.
- `src/taskloop/recovery/continue_attempt.py:60-115` — application execute call sites.
- `src/taskloop/recovery/complete_attempt.py:35-49` — captured completion application call.
- `tests/steps/test_check_admit.py:125-233` — reruns, land refusals and admission races.
- `tests/steps/test_factory_schema.py:1-108` — DDL pin and read-only compatibility assertions.
- `tests/steps/test_schema_words.py:60-113` — incompatible restart preserves storage and wording.
- `tests/steps/test_recovery_store.py:61-148` — reopen, single owner and failed-commit preservation.
- `tests/steps/test_recovery_snapshot.py:26-118` — drift, capture precedence and transactional clock.
- `tests/rules/test_attempt_sql_ownership.py:1-33` — existing AST ownership guard.

## Contract
Admission: latest reads the highest checks number and task-wide land predicates on the borrowed connection. Result: None or frozen pydantic LatestChecks with number and boolean facts for failed-and-released, abandoned, landed and landing. next_number retains refusal order/messages. Both preflight and write-locked revalidation use latest; it opens no connection and commits nothing.

Compatibility: current reads the borrowed connection; _recorded opens read-only for diagnosis and always closes it. Results remain bool, optional version and existing refusal text, including unavailable storage and incomplete schemas. factory_schema imports no store and executes no SQL.

Recovery: existing store transactions and state_store writes observe/authorize unfinished work, returning existing snapshots, intents and outcomes. Ownership, deadlines and rollback stay unchanged. The AST guard rejects SQL execution in orchestration, allowing only inspected application execute calls; factory_schema may retain declarative SQL constants.

## Work packages
1. Add check_admit_store.py, update check_admit.py and focused admission coverage. Close A1 through initial admission, rerun, refusal and race scenarios.
2. Move compatibility functions to factory_store.py; update all seven consumers above. Extend test_factory_schema.py for missing diagnostics; rerun schema_words coverage. Close A2.
3. Extend test_attempt_sql_ownership.py; retain recovery store/snapshot coverage and precise application-call exceptions. Close A3. Run focused tests through the installed package. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, preserving exit status.

## Acceptance behaviours
- A1: Initial admission selects number 1; only a failed, released latest checks attempt permits the next number; abandoned or landed/landing work refuses in the same order, and a concurrent start wins without our reservation being written.
- A2: Compatible databases remain usable; incompatible, incomplete or unreadable version storage yields the existing outcome and diagnostic without modifying database bytes or leaking diagnostic connections.
- A3: Admission orchestration, schema declarations and recovery orchestration execute no SQL; recovery SQL remains in its stores, and reopened ownership, exact snapshot comparison and failed-commit rollback preserve their existing results.
