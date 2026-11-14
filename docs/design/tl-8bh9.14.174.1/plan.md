# Header
tl-8bh9.14.174.1 @ b197f7de810c5dc9bf7fe3d0b33dccda5cb96b15
Depth: small; one durable-evidence behaviour.
Decision missing: no. Unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 1 changed file (plan); 1 behaviour; 12 implement model calls.

## Outcome and non-goals
Verify existing A1 implementation; no runtime gap identified. Exclude plan reuse, Git validation and resume routing.

## Settled decisions
- One snapshot supplies prompt and digest.
- Normalize line endings and source/relationship ordering; preserve other text and comment order/duplicates.
- Exclude factory hold notifications from hashing, retaining prompt text and owner quotations.
- Retain current schema and immutable evidence.

## Open decisions
- None.

## Change map
- `docs/design/tl-8bh9.14.174.1/plan.md`: revise scope.
- `src/taskloop/task_content.py`: consult `digest`.
- `src/taskloop/task_content_store.py`: consult `TaskContentStore`.
- `src/taskloop/discussion.py`: consult `collect`, `for_task`, `empty`.
- `src/taskloop/tracker_discussion.py`: consult `read_discussion`.
- `src/taskloop/tracker_client.py`: consult `tracker_discussion`.
- `src/taskloop/tracker.py`: consult `inspect_task`, `task_comments`.
- `src/taskloop/task.py`: consult `TaskInspection`.
- `src/taskloop/composition.py`: consult `open_discussion`.
- `src/taskloop/admit.py`: consult `admit`, `_commit`.
- `src/taskloop/admit_rows.py`: consult `insert_attempt`.
- `src/taskloop/admit_chain.py`: consult `_takeover_open`, `admit_next`.
- `src/taskloop/repeat.py`: consult `_input`, `repeat`.
- `src/taskloop/check_repeat/repair.py`: consult `repair`.
- `src/taskloop/check_repeat/store.py`: consult `admit`.
- `src/taskloop/factory_schema.py`: consult `SCHEMA`.

## Read list
- `src/taskloop/task_content.py:15-65` — codec.
- `src/taskloop/task_content_store.py:10-24` — persistence.
- `src/taskloop/discussion.py:20-90` — producers.
- `src/taskloop/tracker_discussion.py:16-35` — filtering.
- `src/taskloop/tracker_client.py:35-44` — binding.
- `src/taskloop/tracker.py:71-89` — task producer.
- `src/taskloop/tracker.py:152-157` — comment producer.
- `src/taskloop/task.py:40-57` — inputs.
- `src/taskloop/composition.py:225-280` — wiring.
- `src/taskloop/admit.py:140-178` — snapshot consumer.
- `src/taskloop/admit.py:267-325` — admission.
- `src/taskloop/admit_rows.py:22-29` — delegation.
- `src/taskloop/admit_chain.py:140-170` — repeat writer.
- `src/taskloop/admit_chain.py:323-376` — advance writer.
- `src/taskloop/repeat.py:75-146` — refresh.
- `src/taskloop/check_repeat/repair.py:48-72` — text consumer.
- `src/taskloop/check_repeat/store.py:90-118` — implement writer.
- `src/taskloop/factory_schema.py:45-62` — DDL.
- `tests/steps/test_task_content.py:18-65` — normalization.
- `tests/steps/test_task_content_store.py:17-58` — durability.
- `tests/steps/test_admit.py:346-357` — rollback.
- `tests/steps/test_discussion.py:157-241` — integration.

## Contract
Intent: `DiscussionSnapshot` carries validated `TaskContentDigest`.
Effect: `insert_attempt` writes required plan evidence to `task_content(attempt_id,digest)` within admission.
Result: immutable evidence survives reopen; rollback leaves none. Implement advances/repairs consume text only.

## Work packages
1. Verify mapped producers, codec and callers against A1 using existing tests; no additional runtime edits indicated.
2. Finish with pipeline failure propagation: `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`, once each. Closes A1.

## Acceptance behaviours
A1. Digest stability follows normalization and hold filtering; retained task/acceptance/discussion changes alter it. Initial/repeated plan admissions save evidence atomically; reopen preserves it and failed admissions leave none.
