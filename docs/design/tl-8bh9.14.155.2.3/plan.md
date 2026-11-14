# Header
Task: tl-8bh9.14.155.2.3; base: 78b59e0ec982ab229fbce5f586806059f12d9610
Depth: medium; 3 behaviours: admission/resume, summary reads, resolution isolation.
Decisions: none missing; A/B landed.
Evidence budget: 12 model calls.
Size: 2 files (test, plan); 3 behaviours; 20 implement calls.

## Outcome and non-goals
Handoff, production wiring and individual admission, restart, summary and retained-resolution tests already exist. The remaining gap is combined regression coverage: summary/dashboard reads after an actual saved resolution, followed by ordinary land when main becomes clean. Verify current pins. No production rewrite, schema change, new command or automatic adoption of retained work is proposed.

## Settled decisions
- Ordinary land uses Handoff; summary uses object inspection.
- Retained Record owns target, deadline and checked identities across retries.
- Completed conflict work returns an explained refusal before candidate creation.
- Existing conflict-free delivery and round retry/hold behaviour remain acceptance baselines.
- Reuse the execution fixture and semantic adapters; no additional shelf contract is needed.

## Open decisions
- None.

## Change map
- `tests/steps/test_land_conflict_handoff.py`: `executing`, `unchanged_input`, completed-resolution coverage — extend through repeated summary/dashboard reads, main movement and ordinary land.
- `docs/design/tl-8bh9.14.155.2.3/plan.md`: remaining contract and verification scope.
- `src/taskloop/land.py`: `_made`, `_delivered`, `_summary`, `land` — consult effect ordering; no planned edit.
- `src/taskloop/land_target.py`: `squashed_onto`, `made_s` — consult conflict producer; callers are `_made`, and `_summary`/`squashed_onto`, respectively.
- `src/taskloop/land_check.py`: `LandPorts.conflicts` — consult required port.
- `src/taskloop/land_conflict/handoff.py`: `request_for`, `Handoff.resume/start/conflicted`, `stopped` — consult admission and result conversion.
- `src/taskloop/land_conflict/execute.py`: `execute` — consult saved-result handling.
- `src/taskloop/land_conflict/store.py`: `completed`, `saved`, `find` — consult retained identity/save readers.
- `src/taskloop/land_conflict/composition.py`: `conflict_handoff`, `land_ports` — consult production Handoff/LandPorts producers.
- `src/taskloop/cli_composition.py`: `open_land`, `_landed` — consult `land_ports` caller and round land adapter.
- `src/taskloop/cli_step.py`: `land.land` call — consult CLI consumer.
- `src/taskloop/round_land.py`: `land_passed` — consult shared-operation consumer and hold/retry translation.
- `src/taskloop/round.py`: `land_passed` call — consult round integration.
- `src/taskloop/dash_land.py`: `build_land` — use existing summary consumer in regression coverage.
- `src/taskloop/dash_composition.py`: `_ports.delivery` — consult `build_land` caller.
- `tests/steps/land_bench.py`: `LandBench.ports/conflicts` — reuse LandPorts/Handoff producers.
- `tests/steps/land_conflict_bench.py`: `ExecutionCase` — reuse execution with fake external effects.
- `tests/steps/real/test_land_real.py`: `ports` — consult remaining LandPorts/`conflict_handoff` producer; no live run.
- `tests/steps/test_land_summary.py`: retained-work coverage — consult existing summary assertions.
- `tests/steps/test_dash_land.py`: retained-work coverage — consult existing `build_land` callers.
- `tests/steps/test_round_land.py`: `Lands.landing`, refusal/retry coverage — consult remaining Landing producer and baselines.

## Read list
- `tests/steps/test_land_conflict_handoff.py:32-181` — fixtures, invariants and completed-result coverage to extend.
- `tests/steps/test_land_conflict_handoff.py:183-207` — production wiring and handoff caller.
- `tests/steps/land_bench.py:185-223` — shared ports and execution fakes.
- `tests/steps/land_conflict_bench.py:74-125` — execution counters and restart fixture.
- `src/taskloop/land.py:209-238` — retained lookup before squash/validation.
- `src/taskloop/land.py:282-390` — delivery ordering, summary dispatch and outer boundary.
- `src/taskloop/land_target.py:44-76` — object-only producer and conflict result.
- `src/taskloop/land_check.py:54-78` — required port.
- `src/taskloop/land_conflict/handoff.py:19-68` — request, lookup, admission and result mapping.
- `src/taskloop/land_conflict/execute.py:47-106` — retained completion and execution boundary.
- `src/taskloop/land_conflict/store.py:24-64` — matching and saved-result readers.
- `src/taskloop/land_conflict/store.py:127-140` — retained lookup.
- `src/taskloop/land_conflict/composition.py:33-62` — production port producers.
- `src/taskloop/cli_composition.py:175-196` — round Landing producer/result adapter.
- `src/taskloop/cli_composition.py:365-383` — open_land lifetime and port creation.
- `src/taskloop/cli_step.py:257-270` — CLI caller.
- `src/taskloop/round_land.py:28-69` — automatic consumer, retry and hold.
- `src/taskloop/round.py:188-199` — round caller and reservation accounting.
- `src/taskloop/dash_land.py:29-48` — dashboard summary integration.
- `src/taskloop/dash_composition.py:69-73` — dashboard delivery reader caller.
- `tests/steps/real/test_land_real.py:122-133` — remaining LandPorts producer.
- `tests/steps/test_land_summary.py:136-154` — retained-work summary baseline.
- `tests/steps/test_dash_land.py:19-74` — dashboard callers and read baseline.
- `tests/steps/test_round_land.py:30-60` — Landing producer.
- `tests/steps/test_round_land.py:102-144` — terminal holds and temporary retries.

## Contract
Intent: keep Request, Record, Handoff, Completed and Failed unchanged. Exercise actual conflict completion through `executing`, rather than substituting a canned result.

Effect: establish an accepted saved resolution and snapshot its identity, execution count, reservation, environment events, checked inputs and task refs. Invoke summary and `build_land` repeatedly without minutes, against conflicting main and after main contains the checked changes. Object creation/fetch and outer land operation bookkeeping are allowed; conflict admission/execution, validation, delivery and tracker completion are not.

Result: summary reports current Git facts, including no-change after main movement. Subsequent ordinary land still returns the retained operation's explained conflict result, preserving its original target/deadline and saved result. Assert no extra agent run, candidate, validation command, push or close. Compare remote main to the deliberately advanced target. No new typed names, states or stored fields.

## Work packages
1. Extend `tests/steps/test_land_conflict_handoff.py` with completed-save summary/dashboard observations before and after main movement; reuse `executing` and `unchanged_input`. Close A2 and strengthen A3.
2. Review existing A1 coverage and production callers in the read list. Verify ordinary land still returns the completed operation after those reads. Close A1/A3 through existing coverage plus the extended scenario. No production edit is expected; a demonstrated failure requires reassessing its bounded fix.
3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, recording gate exit status. Verify current pins and regressions without live tests.

## Acceptance behaviours
A1: Fresh conflicts admit once; retries, restart, races and moved main preserve checked identities, target and deadline; temporary outcomes retry and terminal task refusals hold once.
A2: Repeated summary/dashboard reads with an accepted saved resolution report current conflicting or clean Git facts without conflict execution, reservation changes, validation, push or close.
A3: Ordinary land after a saved resolution and now-clean main still stops with an explanation, preserving saved work, checked input and task refs without creating a candidate; conflict-free delivery retains its guards.
