# Header
Task: tl-8bh9.14.88.3.1
Base: 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: small
Reason: one publication SQL ownership move.
Owner decision missing: no. Unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 6 changed files; 1 behaviour; 30 implement model calls.

## Outcome and non-goals
Extract publication persistence; preserve results, messages and Git ordering. Exclude schema, sibling slices and policy changes.

## Settled decisions
- Preserve BranchPublish's constructor and public results.
- Reuse injected AttemptStore connection/transaction providers.
- Retain success, retry, concurrency, abandonment and recording-failure coverage.

## Open decisions
- None.

## Change map
- `src/taskloop/publish.py`: BranchPublish._read/_record delegate; remove SQL, decoding and connections.
- `src/taskloop/publish_store.py` (new): PublishStore wraps AttemptStore for BranchPublish persistence.
- `tests/steps/test_publish.py`: add changed-commit-during-push coverage.
- `tests/rules/test_attempt_sql_ownership.py`: guard publish.py.
- `src/taskloop/composition.py`: consult open_publisher wiring.
- `src/taskloop/cli_composition.py`: consult open_verify/open_publish providers.
- `src/taskloop/attempt_entry.py`: consult _branch caller.
- `src/taskloop/operations.py`: consult Publish, verify_task, publish_task callers.
- `src/taskloop/round.py`: consult publish_task invocation.
- `src/taskloop/step_render.py`: consult _released_lines consumer.
- `src/taskloop/result_data.py`: consult _publish_data consumer.

## Read list
- `src/taskloop/publish.py:52-270` — persistence extraction.
- `src/taskloop/attempt_store.py:100-112` — store composition.
- `src/taskloop/attempt_write_store.py:1-40` — write pattern.
- `src/taskloop/attempt_reads.py:32-41` — PublishedRow.
- `src/taskloop/attempt_reads.py:160-205` — decoding/providers.
- `src/taskloop/factory_schema.py:299-329` — fields/fence.
- `src/taskloop/factory_schema.py:363-375` — schema guard.
- `src/taskloop/composition.py:214-219` — construction.
- `src/taskloop/cli_composition.py:319-345` — CLI providers.
- `src/taskloop/attempt_entry.py:308-317` — invocation.
- `src/taskloop/operations.py:100-110` — publisher port.
- `src/taskloop/operations.py:519-534` — verify caller.
- `src/taskloop/operations.py:585-598` — explicit publish caller.
- `src/taskloop/round.py:469-482` — round caller.
- `src/taskloop/step_render.py:147-160` — text output.
- `src/taskloop/result_data.py:121-126` — structured output.
- `tests/steps/test_publish.py:142-253` — success/preconditions.
- `tests/steps/test_publish.py:356-399` — races/failures.
- `tests/steps/real/test_publish_real.py:157-214` — integration expectations.
- `tests/rules/test_attempt_sql_ownership.py:1-20` — ownership guard.

## Contract
PublishStore.read(key) returns pydantic PublishRow or absence with strict decoding. record(key, commit, clock) returns existing PublishedRow or stdlib RecordOutcome enum (recorded, abandoned, changed). Preserve public result/error mapping.

Intent: read before Git. Effect: push outside transactions. Result: after Pushed only, atomically check existing publication and the unchanged verification/dispatch/generation/abandonment/current-attempt fence, then insert unchanged fields. Call the clock after fencing. Store owns connections and SQL.

## Work packages
1. Extract publish_store.py; delegate publish.py persistence. Closes ownership acceptance.
2. Extend test_publish.py and test_attempt_sql_ownership.py; closes preservation acceptance. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipefail.

## Acceptance behaviours
- publish.py has no SQL or execute calls; its store owns queries/transactions.
- Precondition order, idempotent/concurrent results and refusal classifications stay unchanged.
- A lost fence records nothing; the remote keeps the commit and retries remain possible.
