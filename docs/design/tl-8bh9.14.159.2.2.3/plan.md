# Header
tl-8bh9.14.159.2.2.3; base 37310318ea4b1c142a321e25ccfd9e80a6b38795
Depth: small; one naming migration.
Decisions settled; no unlanded dependency. Evidence: 6 calls.
Size: 21 changed files incl. tests/artifacts; 1 behaviour; 40 implement calls.

## Outcome and non-goals
Expose commit waits consistently. Refusal migration is delivered. Preserve custody, verdicts and remaining Unsettled file causes.

## Settled decisions
- Naming-map result-family and worker_alive rows apply; neither qualifies for the rename exception.
- Release-specific process reasons and unrelated unavailable outcomes stay unchanged.

## Open decisions
- None.

## Change map
- src/taskloop/attempt_types.py: VerifyUnavailable, CommitResult, Unsettled; define CommitWaiting and typed reasons.
- src/taskloop/commit.py: applicable, commit, _committed, _quiet, _settle, _kept; produce/propagate waits.
- src/taskloop/factory_commit.py: Settled, GitQuiet, _blocked; carry pre-write waits.
- src/taskloop/operations.py: FailureKind, UNKNOWN_KINDS, COMMIT_KINDS, commit_failure; encode retryable waiting.
- src/taskloop/attempt_entry.py: shown; print waiting.
- src/taskloop/repeat.py: _leftovers, _stopped; forward waits.
- src/taskloop/step_refusal_guide.py: REFUSALS; explain waiting through step_guide.GUIDE and round_guide.GUIDE.
- src/taskloop/hold.py: hold; update cause example.
- src/taskloop/hold_facts.py: Kept; update cause example.
- tests/steps/test_verifier.py: commit cases; assert waits.
- tests/steps/test_slot_lock.py: custody cases; assert waits.
- tests/steps/test_commit_paths.py: quiet callback; assert no write.
- tests/steps/test_operations.py: failure cases; assert encoding.
- tests/steps/test_repeat.py: stop/forward cases; assert no admission.
- tests/steps/refusal_inventory.py: constructor inventory; replace producers.
- tests/cli/test_step_cli.py: failure presentation; assert waiting/exit 3.
- tests/steps/test_hold.py: refusal fixture; update example.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:165-221 contract.
- src/taskloop/attempt_types.py:254-291 families.
- src/taskloop/commit.py:45-195 producers/propagation.
- src/taskloop/factory_commit.py:56-179 pre-write ports.
- src/taskloop/operations.py:59-70 vocabulary; 599-606 encoder.
- src/taskloop/attempt_entry.py:144-157 display.
- src/taskloop/repeat.py:97-164 forwarding/stop proof.
- src/taskloop/attempt_status.py:220-238 repeat eligibility.
- src/taskloop/step_refusal_guide.py:1-25 guidance.
- src/taskloop/step_guide.py:1-100 integration.
- src/taskloop/round_guide.py:1-60 integration.
- src/taskloop/hold.py:59-67 example.
- src/taskloop/hold_facts.py:30-44 example.
- tests/steps/test_verifier.py:490-558 waits; 775-790 worker.
- tests/steps/test_slot_lock.py:108-151 custody.
- tests/steps/test_commit_paths.py:88-108 callback.
- tests/steps/test_operations.py:400-420 encoding.
- tests/steps/test_repeat.py:445-485 forwarding.
- tests/steps/refusal_inventory.py:10-15 constructors; 145-153 producers.
- tests/cli/test_step_cli.py:170-185 presentation.
- tests/steps/test_hold.py:260-275 fixture.

## Contract
Intent: obtain commit evidence. Effect: existing observation/custody checks. Result: CommitWaiting for mapped reasons, including worker_alive; no verdict, release or repeat follows a wait. Preserve suffixes and diagnostics through typed reasons and boundary codecs. No schema change or aliases.

## Work packages
1. Types, producers, ports and forwarding: close A/B.
2. Guidance, examples and tests: close C. Run focused cases, then just check and just test once each, last.

## Acceptance behaviours
A. Mapped waits print waiting with the original reason; exit remains 3 and no verdict or unsafe write occurs.
B. Waiting admits no repeat; staged, uncommitted, unsafe, ignored and dirty retain results and feedback.
C. rg -nw 'VerifyUnavailable|unsettled:worker_alive' src/taskloop tests returns no matches; assertions cover typed worker waits and shared wording.
