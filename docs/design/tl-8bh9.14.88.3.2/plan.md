# Header
Task: tl-8bh9.14.88.3.2
Base: 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: small
Reason: one module's SQL extraction. Decisions missing: none. Unlanded dependencies: none. Evidence: 6 calls.
Size: 10 changed files, 1 behaviour, 35 implement calls.

## Outcome and non-goals
Existing tests cover settlement, abandon, races and retries; persistence ownership remains the gap. Extract its store. Exclude sibling extractions and schema changes.

## Settled decisions
- Keep release results, construction and effect ordering.
- Deletion consumers import the store directly.

## Open decisions
- None.

## Change map
- src/taskloop/slot_release.py: SlotRelease delegates persistence.
- src/taskloop/slot_release_store.py (new): SlotReleaseStore, ReleaseRow and free; called by SlotRelease and deletion consumers.
- src/taskloop/check_release.py: free import changes.
- src/taskloop/land_conflict/store.py: free import changes.
- tests/steps/test_slot_release.py: preserve outcomes and races.
- tests/steps/test_recovery_release.py: drift_record uses the store's ReleaseRow.
- tests/rules/test_policy.py: WRITERS names new owner.
- tests/rules/test_attempt_sql_ownership.py: extend SQL-free coverage to slot_release.py.
- src/taskloop/composition.py: open_releaser unchanged.
- src/taskloop/attempt_entry.py: SlotRelease unchanged.
- src/taskloop/cli_composition.py: SlotRelease unchanged.
- src/taskloop/result_data.py: release_word unchanged.
- src/taskloop/check_repeat/repair.py: stop proofs unchanged.
- src/taskloop/check_entry.py: release_word unchanged.
- src/taskloop/step_render.py: release_word unchanged.
- src/taskloop/repeat.py: ParkHold unchanged.
- src/taskloop/land_check.py: release_word unchanged.
- src/taskloop/operations.py: ReleaseResult unchanged.
- src/taskloop/round.py: release_word unchanged.
- tests/steps/doubles.py: ReleaseResult unchanged.

## Read list
- src/taskloop/slot_release.py:42-391 — SQL and orchestration.
- src/taskloop/attempt_store.py:1-40 — connection integration.
- src/taskloop/setup_store.py:129-133 — setup observation.
- src/taskloop/recovery/store.py:49-55 — recovery read.
- src/taskloop/check_release.py:335-346 — deletion transaction.
- src/taskloop/land_conflict/store.py:100-116 — atomic deletion.
- src/taskloop/composition.py:204-211 — producer.
- src/taskloop/attempt_entry.py:337-343 — producer.
- src/taskloop/cli_composition.py:70-70 — consumer.
- src/taskloop/result_data.py:33-33 — consumer.
- src/taskloop/check_repeat/repair.py:29-29 — consumer.
- src/taskloop/check_entry.py:45-45 — consumer.
- src/taskloop/step_render.py:37-37 — consumer.
- src/taskloop/repeat.py:40-40 — consumer.
- src/taskloop/land_check.py:43-43 — consumer.
- src/taskloop/operations.py:54-54 — consumer.
- src/taskloop/round.py:71-71 — consumer.
- tests/steps/doubles.py:33-33 — result fake.
- tests/steps/test_slot_release.py:332-566 — races and retries.
- tests/steps/test_recovery_release.py:128-149 — recovery drift.
- tests/rules/test_policy.py:118-153 — SQL owners.
- tests/rules/test_attempt_sql_ownership.py:1-20 — SQL-free guard.

## Contract
Store read returns ReleaseRow or absence, retaining validation and setup/recovery facts. Record compares snapshot and fence, inserts release and deletes reservation atomically. Flip/completion retain predicates and row counts. free uses caller transactions. Connections stay in stores; observation, park and tracker calls stay outside writes. Pass time into record. Stored fields unchanged.

## Work packages
1. Extract store; wire consumers and guards, closing ownership acceptance.
2. Preserve release/recovery tests; cover gaps, closing behaviour acceptance. Run focused tests, then just check and just test once each, last, with prescribed tails.

## Acceptance behaviours
- Release outcomes, fences, atomic deletion and claim retries remain identical; slot_release.py has no SQL execution and its store owns persistence.
