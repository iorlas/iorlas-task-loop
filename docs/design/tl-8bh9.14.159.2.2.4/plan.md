# Header
tl-8bh9.14.159.2.2.4; base e4cddc8b1112a91c193f55c44af166e9634bbbf4
Depth: small; one family rename, behaviour preserved
Decisions settled; dependencies landed. Evidence: 6 calls maximum.
Size: 45 files including tests/artifacts; 1 behaviour; 55 implement calls.

## Outcome and non-goals
Expose Uncommitted in results and displays; preserve safety, payloads, repeat eligibility and exit codes. Exclude release/setup families.

## Settled decisions
- Map rows: residual Unsettled → Uncommitted; staged, uncommitted, unsafe, ignored, dirty → uncommitted:<cause>.
- Refusal/wait delivered; residual type qualifies for the task's rename exception. No aliases.

## Open decisions
- None.

## Change map
- src/taskloop/attempt_types.py: Uncommitted, CommitResult; rename residual type.
- src/taskloop/factory_commit.py: Settled, _foreign, refusal, _review, clean_at, leftovers; propagate type.
- src/taskloop/commit.py: FactoryCommit.leftovers, commit; propagate results.
- src/taskloop/operations.py: COMMIT_KINDS, UNKNOWN_KINDS, commit_failure; encode family.
- src/taskloop/repeat.py: StepRepeat._leftovers, _index, _input; rename staged failure.
- src/taskloop/attempt_entry.py: shown; encode family.
- src/taskloop/attempt_status.py: Leftovers, repeat eligibility; update type guards.
- src/taskloop/steps.py: Feedback; update signature.
- src/taskloop/plan_step.py: feedback; update signature.
- src/taskloop/implement_step.py: feedback; update signature.
- src/taskloop/step_text.py: unsafe_details; update signature.
- src/taskloop/dash_verify.py: verification; project the new family only for its causes.
- src/taskloop/dash/static/words.js: result keys; preserve explanations.
- Other imports, signatures, wording and assertions: map-only renames found by the acceptance search.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:163-180 cause rows
- src/taskloop/attempt_types.py:257-310 result contract
- src/taskloop/factory_commit.py:175-395 producers
- src/taskloop/commit.py:133-188 consumers
- src/taskloop/operations.py:597-607 failure encoding
- src/taskloop/repeat.py:100-145 repeat guards
- src/taskloop/attempt_entry.py:146-160 encoding
- src/taskloop/attempt_status.py:220-239 eligibility
- src/taskloop/steps.py:15-25 callback
- src/taskloop/step_text.py:8-21 rendering
- src/taskloop/plan_step.py:253-275 feedback
- src/taskloop/implement_step.py:205-225 feedback
- src/taskloop/dash_verify.py:14-58 projection
- src/taskloop/dash/static/words.js:30-58 wording
- tests/steps/test_operations.py:327-327 callback
- tests/steps/test_repeat.py:312-325 callback
- tests/steps/test_hold_status.py:289-320 callback/display
- tests/steps/test_recovery_status.py:21-30 callback
- tests/steps/test_recovery_entry.py:90-96 callback
- tests/steps/test_round.py:166-182 callback
- tests/steps/test_verifier.py:212-239 safety cases
- tests/steps/test_commit_paths.py:304-325 staged/safety
- tests/steps/test_repeat_dispatch.py:460-480 staged guard
- tests/steps/test_dash_read.py:750-765 projection
- tests/cli/test_dash_words.py:13-45 display contract

## Contract
Intent: rename the family. Effect: same reads/writes, no new stored facts. Result: Uncommitted retains reason, listing and explanations. Only uncommitted/unsafe/ignored remain repeatable. Add the family to UNKNOWN_KINDS; retain unrelated unsettled failures.

## Work packages
1. Update producers, consumers and repeat guard; closes family acceptance.
2. Update displays, map-only callers and assertions; closes display/absence acceptance. Run focused tests, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
- All five causes use the new family with identical payloads, effects and exit codes; repeat eligibility is unchanged.
- CLI, feedback and dashboard show the renamed family with retained listings and explanations.
- `rg -nw 'Unsettled|unsettled:(staged|uncommitted|unsafe|ignored|dirty)' src/taskloop tests` returns no matches.
