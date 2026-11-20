# Header
Task: tl-8bh9.14.88.3.3
Base: 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: small; one slots SQL ownership move.
Decision: none missing. Unlanded dependency: none.
Evidence: 6 model calls maximum.
Size: 15 files incl. tests/artifacts; 1 independent behaviour; 40 implement model calls.

## Outcome and non-goals
Slot persistence moves to slots_store.py; slots.py keeps Git checks and result assembly. Existing adoption, observation and race tests cover behaviour; SQL ownership remains the gap. Sibling moves and schema changes are excluded.

## Settled decisions
- Direct callers supply SlotsStore instead of connections/callbacks.
- Keep folder selection and Git/lock checks in slots.py.
- Preserve the post-probe reservation read and insert-plus-reread transaction.

## Open decisions
- None.

## Change map
- src/taskloop/slots.py: adopt, observe, _adopted, _folder, _again delegate persistence; remove sqlite access.
- src/taskloop/slots_store.py (new): SlotsStore owns schema checks, SQL and transactions; callers below construct it.
- src/taskloop/composition.py: adopt_slots constructs SlotsStore with existing connection/transaction ports.
- src/taskloop/admit.py: free_slots wraps its existing connection with SlotsStore without taking ownership of its lifetime.
- tests/steps/test_slots.py: adopt/observe callers migrate; fill failure/race coverage gaps.
- tests/steps/test_admit.py: adoption fixture supplies SlotsStore.
- tests/steps/test_prepare.py: adoption fixture supplies SlotsStore.
- tests/steps/test_slot_release.py: adoption and observation callers supply SlotsStore.
- tests/steps/real/test_release_real.py: adoption/observation fixtures migrate; no live execution.
- tests/steps/real/test_publish_real.py: adoption fixture migrates.
- tests/steps/real/test_prepare_real.py: adoption fixture migrates.
- tests/rules/test_policy.py: slot INSERT owner becomes slots_store.py.
- tests/rules/test_attempt_sql_ownership.py: include slots.py in the no-SQL contract.

## Read list
- src/taskloop/slots.py:113-253 — persistence and orchestration.
- src/taskloop/composition.py:237-247 — adoption producer.
- src/taskloop/admit.py:369-383 — observation caller.
- tests/steps/test_slots.py:17-288 — fixtures, failures, races, naming.
- tests/steps/test_admit.py:100-110 — adoption caller.
- tests/steps/test_prepare.py:365-375 — adoption caller.
- tests/steps/test_slot_release.py:410-422 — adoption/observation callers.
- tests/steps/real/test_release_real.py:85-180 — adoption/observation callers.
- tests/steps/real/test_publish_real.py:85-93 — adoption caller.
- tests/steps/real/test_prepare_real.py:65-71 — adoption caller.
- tests/rules/test_policy.py:110-155 — SQL owner enforcement.
- tests/rules/test_attempt_sql_ownership.py:1-25 — AST contract.
- src/taskloop/factory_schema.py:354-375 — schema helpers used by the store.

## Contract
SlotsStore accepts connection/transaction ports or a borrowed connection; it never closes borrowed connections. Methods return decoded paths/identifiers and translate SQLite errors. No SQL or sqlite3.Connection enters slots.py.
Intent: validate candidates outside a write transaction. Effect: INSERT OR IGNORE accepted slots and reread paths atomically. Result: preserve idempotence and refusals. Observation rereads reservations after probing; unreadable slot rows raise SlotsUnavailable, reservation failures yield unknown views.

## Work packages
1. Extract persistence and migrate listed callers/fixtures; preserve connection lifetime and transaction timing. Closes A1.
2. Update ownership rules and focused coverage. Run focused slot tests, then just check and just test once each, last, with prescribed tail limits. Closes A1.

## Acceptance behaviours
A1. slots.py contains no SQL execution; the slice store owns it while adoption results, ordering, failure handling, lock probing and concurrent reservation visibility remain unchanged.
