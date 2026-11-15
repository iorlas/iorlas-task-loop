# Header
Task: tl-8bh9.14.88.4.1
Base: 7408f9824de955d8cfa8c49c3a9dd80230391616
Depth: medium; two owning modules
Owner decision: none; unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 6 changed files including artifacts; 1 independent behaviour; 30 implement model calls.

## Outcome and non-goals
The remaining admission race query belongs to land_store. land.py already has no .execute calls; protect that property alongside land_check.py. Preserve the distinction between a competing land and ordinary slot exhaustion, including messages and absence of new effects. No changes to candidate eligibility, reservation sequencing, delivery, validation, schema or sibling task modules.

## Settled decisions
- Extract only the remaining query; land_store already owns candidate reads and admission fences.
- Return a boolean from the store; land_check retains application failure construction.
- Read on the existing admission transaction's connection, after slot selection fails, preserving the current snapshot and ordering.
- Keep LandPorts and inserted signatures unchanged; CLI, dashboard, conflict composition and test producers keep their wiring.
- Independent sibling work needs no prerequisite integration; no shelf change is required.

## Open decisions
- None.

## Change map
- `src/taskloop/land_store.py`: add `admission_raced`; own the max-number/LANDING query and decode its boolean result.
- `src/taskloop/land_check.py`: `_reserved` calls the store predicate and retains failure mapping; remove `_raced` and unused sqlite3/LANDING imports.
- `src/taskloop/land.py`: `_made` calls `inserted`; retain its behaviour and existing SQL-free implementation.
- `tests/steps/test_land.py`: extend admission coverage through `LandBench.land`, exercising lost slot selection with and without a competing candidate.
- `tests/rules/test_attempt_sql_ownership.py`: add land.py and land_check.py to the existing AST ownership assertion.
- `src/taskloop/factory_schema.py`: consult `LANDING`; preserve its full predicate.
- `tests/steps/test_land_store.py`: consult candidate fixtures, insert fences and existing store coverage.
- `tests/steps/conftest.py`: consult `checking` and `landing` fixture producers.
- `tests/steps/land_bench.py`: consult `LandPorts` producer and `LandBench.land`, rows and reservations observations.
- `src/taskloop/cli_composition.py`: consult unchanged `LandPorts` import/producer.
- `src/taskloop/dash_land.py`: consult unchanged `LandPorts` consumer.
- `src/taskloop/land_conflict/composition.py`: consult unchanged `LandPorts` integration.
- `tests/cli/test_land_cli.py`: consult unchanged `LandPorts` producer.
- `tests/cli/test_dash_composition.py`: consult unchanged `LandPorts` integration.
- `tests/steps/test_land_resolved_validation.py`: consult unchanged `LandPorts` integration and retained-resolution coverage.
- `tests/steps/real/test_land_real.py`: consult unchanged `LandPorts` producer; no live execution.
- `src/taskloop/land_push.py`: search also found its unrelated `_raced`; preserve this remote-push predicate.
- `docs/design/tl-8bh9.14.88.4.1/plan.md`: new implementation plan, integrated through this task's design directory.
- `docs/design/tl-8bh9.14.88.4.1/plan-metadata.json`: new preparation metadata alongside the plan.

## Read list
- `src/taskloop/land_check.py:18-74` — imports and unchanged LandPorts boundary.
- `src/taskloop/land_check.py:104-168` — settled/reserved insertion, race query and refusal mapping.
- `src/taskloop/land_store.py:139-191` — existing transaction-scoped helpers, eligibility fence and candidate insertion.
- `src/taskloop/land.py:210-240` — candidate producer and sole inserted caller.
- `src/taskloop/factory_schema.py:343-352` — shared candidate-blocking predicate.
- `tests/steps/test_land.py:1-103` — public operation fixture and state/effect assertions.
- `tests/steps/test_land_store.py:151-220` — candidate admission fixtures and fence cases.
- `tests/rules/test_attempt_sql_ownership.py:1-32` — extend existing structural enforcement.
- `tests/steps/conftest.py:127-155` — SQLite fixture setup.
- `tests/steps/land_bench.py:224-245` — operation entry and observable outcomes.
- `tests/steps/land_bench.py:295-313` — fake repository and bench creation.
- `src/taskloop/cli_composition.py:50-60` — LandPorts composition integration.
- `src/taskloop/dash_land.py:1-18` — LandPorts consumer.
- `src/taskloop/land_conflict/composition.py:10-22` — LandPorts integration.
- `tests/cli/test_land_cli.py:15-30` — LandPorts producer integration.
- `tests/cli/test_dash_composition.py:15-26` — LandPorts integration.
- `tests/steps/test_land_resolved_validation.py:12-25` — unchanged boundary imports.
- `tests/steps/test_land_resolved_validation.py:143-169` — existing retained-completion regression coverage.
- `tests/steps/real/test_land_real.py:25-38` — existing producer import; consult only.
- `src/taskloop/land_push.py:157-173` — distinguish the unrelated remote race helper.

## Contract
`land_store.admission_raced(con: sqlite3.Connection, checks: str, number: int) -> bool` is a transaction-scoped read helper, matching the store's existing connection-taking functions. It receives the checks attempt identity and proposed candidate number; it returns true exactly when the checks row exists and either its maximum candidate number is at least the proposed number or the shared LANDING predicate holds. Missing checks rows return false, as before. No cursor or raw row escapes the store.

Intent: a previously observed free slot can no longer be selected. Effect: read the same query on the same connection inside the active reservation transaction, without another connection, transaction, reservation or candidate write. Result: `_reserved` maps true to the existing refused/landing failure with RACED and “Nothing was recorded.”; false maps to unavailable/no_free_slot with NO_SLOT. `_held` handling and StoreRefused translation in inserted retain their ordering. No changed stored fields, states or external effects.

## Work packages
1. In land_store.py and land_check.py, extract the predicate and replace its caller without changing transaction scope. Preserve all boolean branches, including a missing checks row. Closes acceptance 1 and 2.
2. In test_land.py, exercise admission through the public operation using real SQLite and semantic Git fakes. Arrange a slot-selection race at the existing unheld boundary, both with no competitor and with candidate-number or LANDING evidence. Assert failure kind/reason/detail and no additional candidate, reservation, validation, push or close effects relative to the arranged competing state. Extend the existing ownership rule for both modules. Closes acceptance 1–3.
3. Review the diff for scope and unused imports. Focused verification may use the permitted isolated pytest command for test_land.py and the ownership rule; retain existing store and resolved-validation coverage. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last, retaining command failure status.

## Acceptance behaviours
1. Lost slot selection still distinguishes a competing candidate from ordinary exhaustion using the same number and LANDING facts, with unchanged failure details and no additional effects.
2. Candidate creation, validation and delivery retain their existing successful and refused outcomes after moving the read.
3. Both named application modules contain no SQL execution calls; land_store owns the extracted query and the existing structural rule rejects its reintroduction.
