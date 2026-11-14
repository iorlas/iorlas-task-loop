# Header
Task: tl-8bh9.14.167.2.2
Base: 3488b8098a2a0a868bfe0d9923466d91321c6b7f
Depth: small; one notification behaviour.
Owner decisions settled; no known unlanded dependency.
Evidence budget: 6 model calls, used 6.
Size: about 9 files, 1 behaviour, 40 implementation model calls.

## Outcome and non-goals
Close the ambiguous-delivery gap in timeout notices. Classification, leases and delivery recording already exist. Scheduling, clock-jump evidence and tracker implementation are outside this change.

## Settled decisions
- Use the owner-supplied Bd.comment_once(bead, key, text) contract, keyed by attempt ID.
- Retry BdError only through comment_once; never plain comment.
- Accept the shelf limit: two processes racing the same key can both post. The local lease reduces this race without strengthening that guarantee.
- beads-client 0.3.0 is already pinned.

## Open decisions
- None.

## Change map
- src/taskloop/tracker_client.py: Comment, TrackerHolds, tracker_holds.comment carry the key and invoke the keyed operation.
- src/taskloop/hold.py: _comment passes leased.attempt_id; retain lease, retry and completion fences.
- tests/steps/test_tracker_holds.py: update all four direct comment call sites and construction checks; cover keyed delivery.
- tests/steps/test_hold.py: Tracker.comment, Tracker.holds and Bench.ports support the key; extend recovery and concurrency cases.
- tests/steps/round_bench.py: holding binds the updated producer; trace and update self.tracker.comment at its definition.
- tests/steps/doubles.py: no_holds supplies the updated port.
- docs/design/tl-8bh9.14.167.2.2/plan.md: this plan.
These cover discovered comment callers and TrackerHolds producers; clear_holds retains its clear port.

## Read list
- src/taskloop/hold.py:206-220 - delivery caller.
- src/taskloop/tracker_client.py:245-315 - port and adapter.
- src/taskloop/hold_store.py:181-207 - lease and delivery writes.
- src/taskloop/attempt_result.py:10-18 - timeout producer.
- src/taskloop/hold_status.py:51-64 - hold cause.
- tests/steps/test_hold.py:47-77 - tracker producer.
- tests/steps/test_hold.py:293-335 - concurrency and retry coverage.
- tests/steps/test_hold.py:110-123 - port construction.
- tests/steps/test_tracker_holds.py:93-139 - direct comment callers.
- tests/steps/round_bench.py:221-224 - producer binding; trace its definition before editing.
- tests/steps/doubles.py:230-239 - refusing producer.
- pyproject.toml:12-25 - declared pin.
- uv.lock:23-25 - resolved pin.
- docs/shelf-digest.json:1-1 - package identity; keyed semantics use the owner contract.

## Contract
Intent: one notification identity per held attempt. Pass the existing attempt ID through Comment; add no stored field or schema change.
Effect: acquire the existing lease, call the keyed operation outside the store transaction, then record delivery. Retry unavailable results with the same key, including after restart or failure to record completion.
Result: successful posting or finding an existing keyed comment maps to done. Preserve missing and unavailable outcomes with explanations. Backend errors remain inside tracker_client. Recorded delivery suppresses further effects. Check the multi-command operation fits within the lease duration.

## Work packages
1. Update the port, adapter, caller and test producers together; close A1-A3 with semantic delivery tests.
2. Verify A1-A3, then run just check and just test once each, last, using the prescribed output tails.

## Acceptance behaviours
A1. A genuine timeout produces an owner-visible notice; repeating the hold or overlapping it under a live lease produces no additional notice.
A2. A lost post response or failed completion recording converges through the same key to one notice after retry or restart, subject to the accepted cross-process race limit.
A3. Separate timeout attempts use distinct keys; unavailable delivery stays retryable without plain posting or a false delivered record.
