# Header
Task: tl-8bh9.14.159.2.2.1
Base: bc8a5ba5f51943d9fff68c9bf25fef131bc16410
Depth: small; one success-family rename.
No open decisions/unlanded dependencies. Budget: 6 calls.
Size: 34 files; 1 behaviour; 30 implement calls.

## Outcome and non-goals
Success types only; preserve stored words, schema and other families.

## Settled decisions
- Naming-map rows 26-27 fix targets.
- Keep factory_commit.Committed(sha) distinct.

## Open decisions
- None.

## Change map
Rename by rows 26-27:
- src/taskloop/attempt_types.py: rename Verified, VerifyResult.
- src/taskloop/commit.py: FactoryCommit: rename types.
- src/taskloop/repeat.py: Settle/_words: rename types.
- src/taskloop/operations.py: Commit/commit_task: rename types.
- src/taskloop/attempt_entry.py: shown/_step: rename types.
- src/taskloop/attempt_reads.py: _verdict_values: rename type.
- src/taskloop/attempt_loads.py: verdict_of: rename constructor.
- src/taskloop/verdict.py: _artifact: rename constructor.
- src/taskloop/implement_step.py: rename Verifiedblob reference.
- src/taskloop/step_guide.py: rename Verified in STEP_ONLY.
- tests/cli/test_cli.py: rename Verified in BUILT.
- tests/steps/killed_rounds_bench.py: rename VerifyResult
- tests/steps/test_restart.py: rename VerifyResult
- tests/steps/test_killed_rounds.py: rename Verified
- tests/steps/test_check_operations.py: rename Verified/VerifyResult
- tests/steps/test_repeat.py: rename Verified/VerifyResult
- tests/steps/test_repeat_dispatch.py: rename Verified/VerifyResult
- tests/steps/test_operations.py: rename Verified/VerifyResult
- tests/steps/test_round.py: rename Verified/VerifyResult
- tests/steps/test_verifier.py: rename Verified/VerifyResult
- tests/steps/test_verifier_leftovers.py: rename Verified
- tests/steps/test_plan_content.py: rename Verified
- tests/steps/test_slot_release.py: rename Verified
- tests/steps/test_drain_fences.py: rename Verified
- tests/steps/test_full_access_environment.py: rename Verified
- tests/steps/test_answer_contract.py: rename Verified
- tests/steps/test_slot_lock.py: rename Verified
- tests/steps/real/test_repeat_real.py: rename Verified
- tests/steps/real/test_publish_real.py: rename Verified
- tests/steps/real/test_release_real.py: rename Verified
- tests/steps/real/test_commit_real.py: rename Verified
- tests/steps/real/test_prepare_real.py: rename Verified

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:26-27 - targets
- src/taskloop/attempt_types.py:226-287 - family
- src/taskloop/commit.py:54-176 - types
- src/taskloop/repeat.py:46-59 - types
- src/taskloop/operations.py:86-90 - port
- src/taskloop/operations.py:520-532 - effects
- src/taskloop/attempt_entry.py:145-155 - words
- src/taskloop/attempt_entry.py:234-244 - consumer
- src/taskloop/attempt_reads.py:242-245 - encoder
- src/taskloop/attempt_loads.py:76-85 - decoder
- src/taskloop/verdict.py:47-49 - producer
- src/taskloop/factory_commit.py:48-56 - Git fact
- tests/steps/killed_rounds_bench.py:149-155 - port
- tests/steps/test_killed_rounds.py:47-58 - type
- tests/steps/test_check_operations.py:245-247 - fake
- tests/steps/test_restart.py:133-139 - port
- tests/steps/test_repeat.py:134-138 - fake
- tests/steps/test_repeat.py:478-508 - types
- tests/steps/test_repeat_dispatch.py:444-448 - fake
- tests/steps/test_operations.py:151-156 - fake
- tests/steps/test_operations.py:414-419 - type
- tests/steps/test_round.py:135-137 - fake
- tests/steps/test_verifier.py:322-347 - reuse

Omitted files: one-to-one rows 26-27 only; check A2.

## Contract
Intent: CommitResult, Committed(blob, reused). Effect: rename without aliases. Result: unchanged.

## Work packages
1. Rename; focused verdict/reuse/operation/repeat tests close A1.
2. A2; last, once each: just check 2>&1 | tail -60; just test 2>&1 | tail -40.

## Acceptance behaviours
A1. Normal/reused success preserves blob, reuse, encoding and effects; refusal/wait stay unchanged.
A2. rg -nw 'VerifyResult|Verified' src/taskloop tests returns no matches.
