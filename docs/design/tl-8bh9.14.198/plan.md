# Header
Task: tl-8bh9.14.198
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: small; one hold-notice retry behaviour
Owner decision/unlanded dependency: none stated.
Evidence budget: 6 model calls.
Size: 4 files incl. artifacts; 1 independent behaviour; 18 implement calls.

## Outcome and non-goals
One attempt delivers at most one hold notice despite changed retry text. Keep label handling, release ordering, rendering and storage unchanged.

## Settled decisions
- Pass `key=attempt_id` at the tracker adapter boundary.
- Notice inputs can change: `_comment` rereads saved commits, `facts` consumes current leftovers, and release results are rebuilt.
- Already delivered: attempt identity reaches `TrackerHolds.comment`, with leases and ambiguous-delivery coverage. Remaining gap: the adapter discards identity; existing retry coverage repeats identical text.

## Open decisions
- None.

## Change map
- `src/taskloop/tracker_client.py`: edit `tracker_holds.comment` and its text-matching documentation; preserve `TrackerHolds`.
- `tests/steps/test_tracker_holds.py`: edit delivery and ambiguous-post cases for keyed delivery and changed retry text.
- `src/taskloop/hold.py`: consult `_comment`, the sole production comment caller, and `_abandoned`, its release producer.
- `src/taskloop/hold_facts.py`: consult `facts`, the leftovers producer.
- `src/taskloop/hold_text.py`: consult `HoldFacts`, `_details`, notice rendering.
- `src/taskloop/hold_store.py`: consult `saved`, `add`, saved-commit ownership.
- `src/taskloop/round.py`: consult `_held` and `_cleared`, application callers.
- `src/taskloop/cli_composition.py`: consult `HoldPorts` construction and adapter wiring.
- `tests/steps/test_hold.py`: consult `Tracker.comment`, `holds`, `Bench.ports`, application fixtures.
- `tests/steps/round_bench.py`: consult `holding`, fixture adapter wiring.
- `tests/steps/doubles.py`: consult `no_holds`, fixture adapter construction.
- `tests/steps/test_round.py`: consult `ports`, fixture application wiring.
- `docs/design/tl-8bh9.14.198/plan.md`: new implementation plan.
- `docs/design/tl-8bh9.14.198/plan-metadata.json`: new preparation metadata.

## Read list
- `src/taskloop/tracker_client.py:245-314` — port, adapter and effect mapping.
- `tests/steps/test_tracker_holds.py:94-162` — delivery, ambiguity and timeout coverage.
- `src/taskloop/hold.py:181-220` — release inputs, rebuilt notice, caller.
- `src/taskloop/hold_facts.py:108-139` — leftovers and evidence inputs.
- `src/taskloop/hold_text.py:68-127` — fields and mutable details.
- `src/taskloop/hold_store.py:131-137` — saved-commit ownership.
- `src/taskloop/round.py:309-327` — application callers.
- `src/taskloop/cli_composition.py:181-187` — production wiring.
- `tests/steps/test_hold.py:55-140` — keyed double and hold fixture.
- `tests/steps/round_bench.py:234-237` — fixture wiring.
- `tests/steps/doubles.py:230-239` — fixture adapter.
- `tests/steps/test_round.py:181-188` — round fixture.

## Contract
Intent: identify a notice by attempt ID within its tracker task. Effect: `Bd.comment_once(task_id, text, key=attempt_id)`. Result: preserve `HoldAnswer` and lease handling; confirmed delivery finishes the hold, ambiguous delivery stays retryable. Retain the first delivered text when saved commits or leftovers change. No new types, states or stored fields.

## Work packages
1. Update `tracker_client.py` and `test_tracker_holds.py` through the existing `Bd` seam. Close A1 with successful delivery, lost response plus failed readback, changed saved-commit/leftovers text, and another attempt. Assert one add per attempt. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. Retrying an ambiguously delivered hold notice for the same attempt with different saved commits and leftovers posts no duplicate; another attempt can deliver its own notice.
