# Header
Task: tl-8bh9.14.155.2.3; base: 06d1561b5b2b93364a1e051594457f16ff8309ae
Depth: medium; three behaviours
Decisions: none missing; dependencies A/B landed.
Evidence budget: 12 model calls.
Size: 14 changed files including plan; 3 independent behaviours; 65 implement calls.

## Outcome and non-goals
Ordinary land currently refuses a conflicting squash with restart instructions. Connect it to the delivered admission, execution, preservation and release operations; return their explained outcome without advancing delivery. Keep summaries observational.
No schema upgrade, new command, adoption of resolutions as checked work, or change to merge execution limits. Preserve conflict-free delivery.

## Settled decisions
- Parts A and B landed.
- The shared land operation owns admission/resumption; CLI and automatic rounds use that same operation.
- Existing records retain their original target, deadline, inputs and ownership across retries.
- Summary uses object inspection only and never invokes conflict admission or execution.
- Retained resolution is evidence of merge work, not a validated delivery candidate.
- Reuse typed outcomes and the Failed boundary; explanations state the situation in words.

## Open decisions
- None.

## Change map
- `src/taskloop/land.py`: `_made`, `_delivered` — resume retained work first; dispatch new conflicts and stop delivery; extract code to bring this 404-line file below its cap.
- `src/taskloop/land_target.py`: `squashed_onto` — return typed `Conflicted` to its only production caller, `_made`; remove restart advice.
- `src/taskloop/land_check.py`: `LandPorts` — require a conflict handoff port.
- `src/taskloop/land_conflict/handoff.py` (new): connect `ConflictStore.find`, `admit`, `execute` and explained results to `_made`.
- `src/taskloop/land_conflict/composition.py` (new): construct handoff dependencies for `open_land` using existing adapters.
- `src/taskloop/cli_composition.py`: `open_land`, `_landed` — wire the port; preserve round result translation; delegate wiring to stay below the cap.
- `tests/steps/land_bench.py`: `LandBench.ports`, `land` — wire semantic conflict dependencies.
- `tests/steps/real/test_land_real.py`: `ports` — supply the required port; no live execution.
- `tests/steps/test_land_conflict_handoff.py` (new): use both existing benches to cover durable retries and effect boundaries.
- `tests/steps/test_land_summary.py`: conflict coverage — assert no admission or execution effects, including with retained work.
- `tests/steps/test_conflict_recovery.py`: conflict assertions — replace automatic restart advice expectations; preserve independent manual recovery coverage.
- `tests/steps/test_round_land.py`: `Bench.land` coverage — retry temporary results; hold terminal task refusals once.
- `tests/steps/test_dash_land.py`: `build_land` coverage — selection cannot admit or resume work.
- `docs/design/tl-8bh9.14.155.2.3/plan.md`: contract.
- Consult callers: `cli_step` calls `land.land`; `round_land.land_passed` calls `_landed`; `dash_land.build_land` calls summary mode; `_summary` calls `made_s` and `land_summary.summarized`; `squashed_onto` also calls `made_s`.
- Consult producers: `admit` supplies `Record`; `execute` supplies merge results; `ConflictStore.find/existing` matches source/checks regardless of new target. All LandPorts constructors are listed above; other land tests use the shared bench.

## Read list
- `src/taskloop/land.py:217-404` — candidate creation, resume ordering, summary dispatch and outer effect guard.
- `src/taskloop/land_target.py:45-96` — squash producer and conflict conversion.
- `src/taskloop/land_check.py:54-82` — LandPorts contract.
- `src/taskloop/cli_composition.py:185-198` — round result adapter.
- `src/taskloop/cli_composition.py:365-392` — owning wiring and resource lifetime.
- `src/taskloop/cli_step.py:260-269` — CLI caller and interruption mapping.
- `src/taskloop/round_land.py:24-69` — shared-operation consumer and refusal holds.
- `src/taskloop/dash_land.py:27-48` — summary-only caller.
- `src/taskloop/land_summary.py:140-170` — typed summary production.
- `src/taskloop/land_conflict/models.py:20-94` — exact Request, Record and admission outcomes.
- `src/taskloop/land_conflict/admit.py:24-76` — admission ports, retained lookup and refusals.
- `src/taskloop/land_conflict/execute.py:29-148` — execution dependencies, resume and preservation boundary.
- `src/taskloop/land_conflict/store.py:24-47` — retained lookup and historical result reads.
- `src/taskloop/land_conflict/store.py:126-168` — find, slot observation and checked-source admission.
- `src/taskloop/merge/models.py:29-59` — reason and disposition vocabularies.
- `src/taskloop/merge/models.py:112-149` — execution results.
- `src/taskloop/composition.py:73-87` — environment and existing harness runner adapter.
- `src/taskloop/composition.py:130-170` — checking dependencies available to wiring.
- `tests/steps/land_bench.py:180-201` — shared LandPorts producer and caller.
- `tests/steps/land_conflict_bench.py:35-142` — admission and execution integration fixtures.
- `tests/steps/real/test_land_real.py:120-133` — third LandPorts producer.
- `tests/steps/test_conflict_recovery.py:86-116` — existing conflict expectations and manual recovery.
- `tests/steps/test_land_summary.py:125-164` — conflict and summary invariants.
- `tests/steps/test_round_land.py:30-100` — round result fixtures and consumer expectations.
- `tests/steps/test_dash_land.py:1-65` — dashboard read integration.

## Contract
Intent: after existing source/checks, repository and tracker guards, find retained work before another squash. New main or a now-clean squash cannot bypass it. Resume the stored Record, target and deadline without requiring another free slot.

Effect: on a fresh Conflicted result require minutes before admission. Build existing Request from exact implement/checks keys, repo, tracker binding, checked commit and fetched target. Admission owns reservation and races; execute only its returned key outside write transactions. Withdraw, summary and no-change cannot admit or execute.

Result: return Failed carrying typed outcome explanations. In-progress/unavailable results remain retryable; terminal task conflicts use the existing conflict refusal for round holding. Completed resolutions also stop before inserted, validated, deliver or closed. Repeated calls resume/read the same operation; task refs and checked input stay unchanged. Do not parse explanations or expose backend commands. Any new closed vocabulary uses an enum and one edge codec. No stored fields change.

Require the port in every LandPorts producer; reuse adapter lifetimes. No new shelf API.

## Work packages
1. Add both conflict modules and wire LandPorts/open_land and test producers. Close A1 with actual admission/execution, semantic fakes, restart and race coverage.
2. Connect `_made` and typed squash results; revise conflict recovery assertions. Close A1/A3 for fresh/retained conflicts, missing minutes and completed saves.
3. Extend summary/dashboard/round coverage for A2 and consumer aspects of A1/A3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; no live tests.

## Acceptance behaviours
A1: Land admits once and resumes after restart/main movement with the same target, deadline and ownership; unavailable work retries, terminal task conflicts are held once by rounds.
A2: Summary/dashboard reads report conflicts without admission, reservation, execution, validation, delivery or close, including with retained work.
A3: Completed resolutions, including repeated reads, preserve checked input/task refs and create no candidate, push or close; conflict-free delivery still passes its guards.
