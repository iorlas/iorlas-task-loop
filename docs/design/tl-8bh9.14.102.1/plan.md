# Header
Task: tl-8bh9.14.102.1
Base: 3f0f48292becc35d10f14f67ff6a915b75307a18
Depth: small
Reason: one rule in tests/rules.
Decision/dependency: none missing or explicitly unlanded.
Evidence budget: 6 model calls.
Size: 3 changed files, 1 behaviour, 40 implement model calls.

## Outcome and non-goals
Add enforcement around existing step and claim codecs without migrating callers or changing runtime/import contracts. The AST census has 115 accesses in 33 modules, including 99 outside step, claim and stores; these are candidates, not proven enum violations.

## Settled decisions
- Permit only taskloop.step, taskloop.claim and store modules (store.py or *_store.py).
- Keep other existing codec modules, including task_event_codec, subject to the census.
- Use static analysis without importing application modules; unresolved receivers require exact exceptions.
- Freeze exceptions explicitly; remove resolved entries and never regenerate or enlarge them to pass checks.

## Open decisions
- None.

## Change map
- `tests/rules/test_enum_values.py` (new): AST scanner, receiver classification, exact exception constant and focused fixtures; integrates through pytest discovery. Repository enumeration supplies its source inputs; no runtime caller invokes it.
- `docs/design/tl-8bh9.14.102.1/plan.md`: implementation scope and acceptance.
- `docs/design/tl-8bh9.14.102.1/plan-metadata.json`: preparation commit and consulted paths.

## Read list
- `tests/rules/test_ratchet.py:286-371`: exact ceilings, stale exceptions and adversarial fixtures.
- `tests/rules/test_sqlite_contracts.py:20-49`: AST policy and independent source enumeration.
- `tests/rules/test_slice_contracts.py:23-40`: temporary source-tree fixtures.
- `pyproject.toml:40-50`: size caps and rules discovery.
- `src/taskloop/step.py:1-17`: Step producer and encode_step consumer.
- `src/taskloop/claim.py:1-20`: ClaimWord producer and encode_claim consumer.
- `src/taskloop/machine_config.py:24-25`: non-enum Setting.value producer.
- `src/taskloop/cli_step.py:174-195`: settings value consumers.
- `src/taskloop/result_data.py:194-202`: mixed settings value projection.
- `src/taskloop/agent_credentials.py:77-93`: typed enum consumer machine_credentials.
- `src/taskloop/task_event.py:24-55`: enum fields and consistent consumer.
- `src/taskloop/task_event_codec.py:19-61`: reason and _checks consumers requiring census entries.
- `src/taskloop/profile.py:43-44`: enum declaration evidence.

## Contract
Intent: inspect every Python module under src/taskloop. Effect: parse ASTs; index declarations/import aliases, annotations and straightforward assignments to identify enum and non-enum receivers. Uncertain receivers remain conservative; an attribute name alone proves nothing.
Result: each enum or unresolved access outside permitted modules must match the census. Identify sites by relative path, enclosing symbol, normalized receiver and occurrence; lines are diagnostics only. Preserve multiplicity to reject duplicates. Exact equality rejects stale entries; removing a site requires shrinking its exception. Fixtures use the repository scanner. No runtime API, database or external effects change.

## Work packages
1. Add the scanner and census in test_enum_values.py, using current AST sites and receiver evidence; close A1.
2. Add focused synthetic cases for rejection, permission, non-enum discrimination, unresolved receivers and census shrinkage; close A1. Run the focused file, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, preserving exit status.

## Acceptance behaviours
A1. The rule rejects new enum .value access outside permitted modules; permits step, claim and store access and proven non-enum fields; tolerates only exact existing enum or unresolved exceptions; rejects added, duplicated, moved or stale sites until resolved and the census shrinks.
