# Header
Task: tl-8bh9.14.167.2.1
Base: e752ae5d6944787089e270cceaa50faf7207d55e
Depth: small; one recording behaviour
Missing decision: none. Unlanded dependency: none stated.
Evidence: 6 model calls.
Size: 9 files including plan, 1 independent behaviour, 45 implement model calls.

## Outcome and non-goals
Monotonic runtime allowance and round pacing already exist; clock-jump evidence remains. Exclude timeout notifications, dashboard changes and schema changes.

## Settled decisions
- Clock evidence is independent of timeout notification.
- Record wall elapsed minus monotonic elapsed when its magnitude exceeds one second, suppressing sampling noise.
- Advance the baseline after every sample, including failed writes, avoiding duplicate jumps.
- Use existing callbacks; opposing changes entirely between samples cannot be distinguished.

## Open decisions
- None.

## Change map
- `src/taskloop/clock_jumps.py` (new): observer, typed record, codec; integrated by `rounds` and `Attempts._call`.
- `src/taskloop/rounds.py`: `run_rounds` creates observer; `_rounds` calls `_pause` with it; sample round/wait boundaries even with no reservations; emit through `_Log.write`.
- `src/taskloop/attempt.py`: `_run` calls `_call`; `_call` samples entry/finally and wires observation into `CommandSink`.
- `src/taskloop/command_sink.py`: optional observer callback in `CommandSink`; sample `started`, `feed`, `poll`, `end` independently of activity writes.
- `src/taskloop/evidence_files.py`: separate capped clock-jump log via `EvidenceFiles` path/append methods and `CappedLog`.
- `src/taskloop/composition.py`: consult `_run` live-sink producer and `open_attempts` clocks.
- `src/taskloop/cli_composition.py`: consult `open_rounds` clock ports.
- `tests/steps/test_clock_jumps.py` (new): observer/codec and `EvidenceFiles` contracts.
- `tests/steps/test_rounds.py`: wall/runtime fake and boundary evidence.
- `tests/steps/test_attempt_runtime.py`: callback/eventless evidence and runtime invariants.
- `docs/design/tl-8bh9.14.167.2.1/plan.md`: plan artifact.

## Read list
- `src/taskloop/rounds.py:66-184`: logging and pacing.
- `src/taskloop/attempt.py:170-213`: runtime anchor.
- `src/taskloop/attempt.py:242-285`: run/callbacks.
- `src/taskloop/command_sink.py:16-58`: callback and writer lifecycle.
- `src/taskloop/evidence_files.py:33-58`: capped writer.
- `src/taskloop/evidence_files.py:100-108`: attempt directory ownership.
- `src/taskloop/evidence_files.py:253-262`: bounded append pattern.
- `src/taskloop/round_log.py:1-26`: evidence line encoding.
- `src/taskloop/composition.py:89-91`: live sink producer.
- `src/taskloop/composition.py:112-129`: existing clock wiring.
- `src/taskloop/cli_composition.py:290-300`: rounds clock wiring.
- `tests/steps/test_rounds.py:24-88`: scheduler fake and pacing assertions.
- `tests/steps/test_attempt_runtime.py:16-125`: runtime invariants.

## Contract
Intent: observe time. Effect: `ClockJumps` compares samples; pydantic `ClockJump` holds context/direction enums, wall endpoints, monotonic elapsed seconds and signed difference; one codec emits enum/numeric fields. Result: append each discontinuity to rounds.log or the separate attempt log. Stable offsets emit nothing further; reverse jumps remain distinct. Drop evidence errors. Preserve database fields, activity timestamps, timeout budgets, registration and scheduling clocks.

## Work packages
1. Add observer/codec and bounded artifact writer; test repeated offsets, opposite jumps and normal elapsed time.
2. Wire rounds and active run callbacks; test all four context/direction cases, eventless return and failed evidence writes.
3. Verify timing invariants; run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
- Idle/active forward/backward jumps produce distinct records without stable-offset duplicates; failed evidence preserves runtime allowances, timeout outcomes, cadence, backoff and slot-release wakes.
