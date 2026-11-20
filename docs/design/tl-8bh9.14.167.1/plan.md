# Header
Task: tl-8bh9.14.167.1; base: 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: small; one runtime-allowance behaviour
Owner decision: none missing; unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 5 changed files; 1 independent behaviour; 35 implement model calls.

## Outcome and non-goals
Give execution and registration a consistent runtime allowance despite epoch-clock changes. Preserve expiry and result capture. Non-goals: admission, setup and recovery policy, jump evidence, notifications and dashboard durations.

## Settled decisions
- Pinned any-agent enforces timeout on its injected monotonic clock; no shelf change or keep-awake is needed.
- Keep stored epoch deadlines and timestamp writes; introduce no schema change or persisted monotonic value.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt.py`: `Attempts.__init__`, `_start`, `_run`, `_call` — inject monotonic time, anchor the available allowance once, subtract monotonic elapsed time thereafter, and give registration the same expiry basis.
- `src/taskloop/composition.py`: `open_attempts` — supply `time.monotonic`; `_run` continues forwarding the resulting duration to any-agent.
- `tests/steps/test_attempt.py`: `AttemptSurroundings.attempts`, `owner`, expiry and cleanup cases — inject independent clocks and distinguish epoch changes from actual allowance consumption.
- `tests/steps/test_attempt_runtime.py` (new): integrate through `AttemptSurroundings`, `database`, `fake` and `Attempts.execute`; exercise jumps, registration and true exhaustion without processes.
- `docs/design/tl-8bh9.14.167.1/plan.md`: implementation contract.

## Read list
- `src/taskloop/attempt.py:60-104` — constructor and execution entry.
- `src/taskloop/attempt.py:145-258` — launch, dispatch, remaining allowance and callback construction.
- `src/taskloop/composition.py:88-126` — execution adapter and sole production constructor caller.
- `src/taskloop/session.py:15-32` — registration expiry and identity protection.
- `src/taskloop/attempt_types.py:122-138` — existing admission fields.
- `src/taskloop/admit.py:61-78` — epoch-deadline producer contract.
- `src/taskloop/admit_chain.py:145-160` — repeated-attempt deadline producer.
- `src/taskloop/prepare.py:317-332` — preparation gates remain a distinct boundary.
- `tests/steps/test_attempt.py:60-86` — constructor helper and fixture integration.
- `tests/steps/test_attempt.py:94-206` — seeded allowance and expiry assertions.
- `tests/steps/test_attempt.py:276-277` — clock-injecting caller.
- `tests/steps/test_attempt.py:351-368` — registration expiry regression.
- `tests/steps/test_attempt.py:526-560` — launch cleanup and expiry cases.
- `src/taskloop/shelf_digest/facts.py:65-77` — pinned monotonic timeout contract.

## Contract
Intent: after initial eligibility, convert the available epoch allowance once to a monotonic anchor. Subsequent execution remaining time uses monotonic elapsed time; preparation keeps its eligibility policy.
Effect: pass a positive duration to `Execution`; exhausted allowance must not become zero, which disables timeout. Derive the registration expiry clock from the same anchor. Keep timestamp and evidence clocks unchanged.
Result: epoch jumps cannot alter the execution budget or refuse registration. Monotonic exhaustion retains expiry/timeout handling and exactly-once cleanup. Collection never starts another run.

## Work packages
1. Update the two runtime modules and constructor helper; close A1 while preserving existing admission and collection contracts.
2. Add the new focused clock tests and revise expiry/cleanup cases; close A1. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1: Fake epoch jumps forward/backward during handoff and registration preserve the allowance; monotonic runtime exhaustion still expires or times out, with correct capture and cleanup.
