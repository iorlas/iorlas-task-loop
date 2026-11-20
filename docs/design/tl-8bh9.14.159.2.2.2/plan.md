# Header
tl-8bh9.14.159.2.2.2; base 87f8cd1663c7b2b48d844e7b182c5ce77268a087
Depth: small; one refusal-family migration.
Decisions settled; part 1 landed.
Evidence: 6 calls, 6 used.
Size: 20 changed files with tests/artifacts; 1 behaviour; 35 implement calls.

## Outcome and non-goals
Route refusals through CommitRefused. Success is delivered; wait/file families, schema and dashboard are excluded.

## Settled decisions
- Naming-map rows VerifyRefused, Unsettled and VerifyUnavailable fix the refusal targets.
- Preserve verdict precedence, custody and repeat eligibility.

## Open decisions
- None.

## Change map
- attempt_types.py: replace VerifyRefused; retain listings; update CommitResult and residual cause documentation.
- factory_commit.py: _observed, settle, _blocked, _moved, clean_at, leftovers forward refusals; widen unions, callbacks and guards.
- commit.py: applicable, _committed, _quiet, _settle, _kept, leftovers route refusals without swallowing them.
- operations.py: COMMIT_KINDS/commit_failure encode refused and listing detail; retain inconsistent diagnostics.
- attempt_entry.py: shown encodes CommitRefused.
- repeat.py: _leftovers preserves stale-reservation reconciliation.
- attempt_status.py: widen Leftovers, preserve SHOWN refs, narrow file feedback before unsafe_details.
- test_verifier.py: migrate refusal/race cases; cover session_fault and inconsistent.
- test_operations.py: codec and branch-status assertions.
- test_repeat.py: refusal forwarding.
- test_repeat_dispatch.py: superseded prevents writes.
- test_verifier_leftovers.py: branch/head_moved previews.
- test_hold_status.py: head_moved fixture.
- test_slot_lock.py: read_only refuses without writes.
- real/test_commit_real.py: redirected/head_moved expectations.
- refusal_inventory.py: renamed constructor and dynamic entries.

## Read list
- docs/design/tl-8bh9.14.159.1/naming-map.md:21-39 names.
- docs/design/tl-8bh9.14.159.1/naming-map.md:162-230 causes.
- src/taskloop/attempt_types.py:256-287 results.
- src/taskloop/factory_commit.py:55-393 producers/guards.
- src/taskloop/commit.py:47-196 operation/custody.
- src/taskloop/operations.py:64-70 dispatch.
- src/taskloop/operations.py:599-608 codec.
- src/taskloop/attempt_entry.py:140-157 display.
- src/taskloop/repeat.py:98-114 reconciliation.
- src/taskloop/attempt_status.py:47-56 port.
- src/taskloop/attempt_status.py:225-239 feedback.
- tests/steps/test_verifier.py:364-802 refusals.
- tests/steps/test_operations.py:405-412 codec.
- tests/steps/test_operations.py:493-536 status.
- tests/steps/test_repeat.py:465-478 forwarding.
- tests/steps/test_repeat_dispatch.py:250-267 fencing.
- tests/steps/test_repeat_dispatch.py:400-410 supersession.
- tests/steps/test_verifier_leftovers.py:11-43 previews.
- tests/steps/test_hold_status.py:300-320 refs.
- tests/steps/test_slot_lock.py:180-187 writer.
- tests/steps/real/test_commit_real.py:130-260 safety.
- tests/steps/refusal_inventory.py:1-15 registry.
- tests/steps/refusal_inventory.py:140-150 dynamic calls.
- tests/steps/test_commit_paths.py:98-102 retained wait callback.

## Contract
Intent: stop further effects. Result: CommitRefused(reason, listing, explanations), no stored verdict. Migrate the map's refusal causes; retain refusal suffixes. Preserve bounded refs and diagnostics; inconsistent becomes refused externally. Other Unsettled/VerifyUnavailable causes retain their types. No aliases.

## Work packages
1. Types/producers and their tests above: route refusal causes.
2. Consumers/inventory above: preserve refs, custody and repeat policy.
3. Focused tests, then just check and just test once each, last, with required tails.

## Acceptance behaviours
- Mapped causes yield CommitRefused with diagnostics/refs and unchanged write guards.
- Wait/file results, stored-verdict reuse and repeat eligibility retain their behaviour.
- `rg -nw 'VerifyRefused' src/taskloop tests` returns no matches.
