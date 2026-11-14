# Header
Task: tl-8bh9.14.139.2; base: 91246785cac7f3f09ffedd3199b8c21d78a922d1
Depth: small
Reason: one dashboard interaction. Decision: none missing; dependency: landed. Evidence budget: 6 model calls.
Size: 12 changed files incl. tests/plan; 1 independent behaviour; 70 implement model calls.

## Outcome and non-goals
Summary facts already exist; Land selection/details are missing. Preserve waiting notes and attempt navigation. Exclude slot/outcome wording, PR discovery and delivery controls.

## Settled decisions
Reuse land.land summary on selection, outside polling.
Commands are reference text; use only available structured PR URLs.

## Open decisions
- None.

## Change map
- dash_land.py (new): build_land uses land.land via open_land; maps summary/failure.
- dash_model.py: Pydantic LandDetail response.
- dash_composition.py: _ports wires build_land.
- dash_server.py: DashPorts/_task_api/_json add delivery GET/serialization.
- dash/static/api.js: apiSource delivery read.
- dash/static/rail.js: landRow/rail accessible selection.
- dash/static/drawer.js: select/render/pane/onTaskMoved load/refresh details.
- test_dash_land.py (new): LandBench reader contracts.
- test_dash_server.py: Ports/route success, missing, failure.
- test_dash_composition.py: DashPorts wiring.
- rail.test.js: drawerSelection covers details/navigation.
- docs/design/tl-8bh9.14.139.2/plan.md: scope.
- land.py: consult land/_summary and LandRequest.
- land_summary.py: consult summarized/summary producers.
- land_gate.py: consult Gate diff facts.
- cli_composition.py: consult open_land/_landed caller.
- cli_step.py: consult land.land caller.
- round_land.py: consult landing.land caller.
- dash/static/app.js: consult apiSource caller.
- test_land_cli.py: consult open_land fake/callers.
- test_land_summary.py: consult summarized callers.
- test_land_gate.py: consult summary caller.
- test_drain_fences.py: consult landing.land callers.
- land_bench.py: consult LandBench integration.

## Read list
- src/taskloop/dash/static/rail.js:197-231 - row.
- src/taskloop/dash/static/drawer.js:24-340 - selection.
- src/taskloop/dash/static/api.js:13-30 - source.
- src/taskloop/dash/static/app.js:310-318 - caller.
- src/taskloop/dash_model.py:194-220 - response.
- src/taskloop/dash_server.py:28-200 - route.
- src/taskloop/dash_composition.py:36-68 - wiring.
- src/taskloop/land.py:66-95 - request.
- src/taskloop/land.py:361-404 - effects.
- src/taskloop/land_summary.py:77-166 - producer.
- src/taskloop/land_gate.py:35-95 - diff.
- src/taskloop/cli_composition.py:366-385 - open_land.
- src/taskloop/cli_composition.py:190-197 - caller.
- src/taskloop/cli_step.py:250-267 - caller.
- src/taskloop/round_land.py:45-62 - caller.
- tests/cli/test_dash_server.py:25-65 - fake.
- tests/cli/test_dash_composition.py:30-49 - constructor.
- tests/dash/rail.test.js:173-210 - fixture.
- tests/cli/test_land_cli.py:70-105 - fake.
- tests/steps/test_land_summary.py:116-162 - effects.
- tests/steps/test_land_gate.py:146-157 - caller.
- tests/steps/test_drain_fences.py:194-223 - callers.
- tests/steps/land_bench.py:1-58 - integration.

## Contract
Intent: select Land without an attempt number. Effect: summary may fetch, create Git objects and record its operation; never deliver, close, claim or run checks. Result: LandDetail carries actions, diff totals/command, land command, nullable PR URL or explained failure. No display parsing/schema change. Ignore stale replies; refresh changed tasks.

## Work packages
1. Reader/model/route/wiring and Python contracts close A.
2. Rail/API/drawer and mocked browser contracts close A. Last, once each: `just check 2>&1 | tail -60`; `just test 2>&1 | tail -40`.

## Acceptance behaviours
A. Land selection shows actions, diff summary/command and available PR link; loading/failure/retry and task switching preserve navigation/waiting notes without delivering.
