# Header
Task: tl-8bh9.14.159.2.2.1
Base: 6a0bd3db681dec4fe29ab4b8abbfa4583a67c526
Depth: small; one success-family rename.
Decisions settled; no unlanded dependency. Evidence budget: 6 calls.
Size: 34 files; 1 behaviour; 30 implement calls.

## Outcome and non-goals
Finish success types; operation names are delivered. Exclude schema, stored/display words and other families.

## Settled decisions
- Naming-map rows 26-27 fix both targets.
- factory_commit.Committed(sha) stays distinct.

## Open decisions
- None.

## Change map
Rename mapped types in these symbols and their consumers; STEP_ONLY/BUILT follow the wording.
- src/taskloop/attempt_types.py: Verified, VerifyResult
- src/taskloop/commit.py: FactoryCommit
- src/taskloop/repeat.py: Settle, _words
- src/taskloop/operations.py: Commit, commit_task
- src/taskloop/attempt_entry.py: shown, _step
- src/taskloop/attempt_reads.py: _verdict_values
- src/taskloop/attempt_loads.py: verdict_of
- src/taskloop/verdict.py: _artifact
- src/taskloop/implement_step.py: Verified.blob
- src/taskloop/step_guide.py: STEP_ONLY
- tests/cli/test_cli.py: BUILT
- tests/steps/killed_rounds_bench.py: VerifyResult
- tests/steps/test_restart.py: VerifyResult
- tests/steps/test_killed_rounds.py: Verified
- tests/steps/test_check_operations.py: Verified
- tests/steps/test_repeat.py: Verified
- tests/steps/test_repeat_dispatch.py: Verified
- tests/steps/test_operations.py: Verified
- tests/steps/test_round.py: Verified
- tests/steps/test_verifier.py: Verified
- tests/steps/test_verifier_leftovers.py: Verified
- tests/steps/test_plan_content.py: Verified
- tests/steps/test_slot_release.py: Verified
- tests/steps/test_drain_fences.py: Verified
- tests/steps/test_full_access_environment.py: Verified
- tests/steps/test_answer_contract.py: Verified
- tests/steps/test_slot_lock.py: Verified
- tests/steps/real/test_repeat_real.py: Verified
- tests/steps/real/test_publish_real.py: Verified
- tests/steps/real/test_release_real.py: Verified
- tests/steps/real/test_commit_real.py: Verified
- tests/steps/real/test_prepare_real.py: Verified

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:26-27 - targets
- src/taskloop/attempt_types.py:226-287 - family
- src/taskloop/commit.py:54-129 - signatures
- src/taskloop/repeat.py:46-59 - signatures
- src/taskloop/operations.py:86-90 - protocol
- src/taskloop/operations.py:520-532 - effects
- src/taskloop/attempt_entry.py:145-155 - formatter
- src/taskloop/attempt_reads.py:242-245 - encoder
- src/taskloop/attempt_loads.py:76-85 - decoder
- src/taskloop/verdict.py:47-49 - producer
- src/taskloop/factory_commit.py:48-56 - Git fact
- tests/steps/killed_rounds_bench.py:149-155 - callback
- tests/steps/test_killed_rounds.py:47-58 - signature
- tests/steps/test_check_operations.py:245-247 - fake
- tests/steps/test_restart.py:133-139 - callback
- tests/steps/test_repeat.py:134-138 - fake
- tests/steps/test_repeat.py:478-480 - signature
- tests/steps/test_repeat_dispatch.py:444-448 - fake
- tests/steps/test_operations.py:151-156 - fake
- tests/steps/test_operations.py:414-419 - signature
- tests/steps/test_round.py:135-137 - fake
- tests/steps/test_verifier.py:322-347 - reuse

Omissions use only one-to-one map rows 26-27; A3 covers their callers.

## Contract
Intent: CommitResult and Committed(blob, reused), including Verdict membership. Effect: rename constructors, patterns and signatures without aliases. Result: identical encoding, verdicts and release/publication effects.

## Work packages
1. Rename the change map; close A1-A2 using existing focused verdict, reuse, operation and repeat tests. Real-test files: type renames only.
2. Close A3; run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last.

## Acceptance behaviours
A1. Normal/reused success retains blob and reused through storage and consumers.
A2. Refusal/wait results and release/publication order stay identical.
A3. rg -nw 'VerifyResult|Verified' src/taskloop tests returns no matches.
