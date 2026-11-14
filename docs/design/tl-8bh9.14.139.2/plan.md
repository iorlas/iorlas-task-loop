# Header
Task: tl-8bh9.14.139.2; base: 4bfe055aa07744a6ccd0753e765d02919b482177
Depth: small
Reason: one dashboard interaction. Owner decision: none missing. Dependency: landed. Evidence: 6 model calls.
Size: 12 changed files incl. tests/plan; 1 independent behaviour; 70 implement model calls.

## Outcome and non-goals
Exclude slot/outcome wording, PR discovery and delivery controls.

## Settled decisions
Reuse land summary mode on selection, outside polling.
Commands are reference text; PR URL uses available structured facts.

## Open decisions
- None.

## Change map
Source paths relative to src/taskloop/.
- dash_land.py (new): reader wired by _ports.
- dash_model.py: Pydantic LandDetail.
- dash_composition.py: _ports callback.
- dash_server.py: DashPorts/_json/_task_api delivery GET.
- dash/static/api.js: apiSource read.
- dash/static/rail.js: landRow/rail selection.
- dash/static/drawer.js: select/render/pane/onTaskMoved.
- tests/steps/test_dash_land.py (new): LandBench contracts.
- tests/cli/test_dash_server.py: Ports route.
- tests/cli/test_dash_composition.py: DashPorts caller.
- tests/dash/rail.test.js: selection/content.
- docs/design/tl-8bh9.14.139.2/plan.md: scope.
- land.py: land/_summary.
- land_summary.py: summary/summarized producers.
- land_gate.py: Gate changes.
- cli_composition.py: _landed wiring.
- cli_step.py: land.land caller.
- round_land.py: landing.land caller.
- land_data.py: land_data/summary_data.
- result_data.py: LandSummary dispatch.
- step_render.py: LandSummary dispatch.
- land_render.py: land_lines/summary_lines.
- dash/static/app.js: apiSource caller.
- tests/cli/test_land_cli.py: summary caller.
- tests/steps/test_land_summary.py: summary contracts.
- tests/steps/test_land_gate.py: summary caller.
- tests/steps/test_drain_fences.py: land callers.
- tests/steps/land_bench.py: LandBench.

## Read list
- src/taskloop/dash/static/rail.js:197-231 — row.
- src/taskloop/dash/static/drawer.js:24-310 — selection.
- src/taskloop/dash/static/api.js:13-24 — source.
- src/taskloop/dash_model.py:194-220 — shapes.
- src/taskloop/dash_server.py:28-186 — ports/routes.
- src/taskloop/dash_composition.py:36-68 — wiring.
- src/taskloop/land.py:361-404 — effects.
- src/taskloop/land_summary.py:77-166 — producer.
- src/taskloop/land_gate.py:35-95 — diff.
- src/taskloop/land_data.py:50-84 — consumers.
- src/taskloop/cli_composition.py:170-197 — wiring.
- src/taskloop/cli_step.py:250-267 — caller.
- src/taskloop/round_land.py:45-62 — caller.
- src/taskloop/result_data.py:130-141 — dispatch.
- src/taskloop/step_render.py:39-50 — dispatch.
- src/taskloop/land_render.py:46-85 — consumers.
- src/taskloop/dash/static/app.js:310-318 — caller.
- tests/cli/test_dash_server.py:25-46 — fake.
- tests/cli/test_dash_composition.py:30-49 — constructor.
- tests/dash/rail.test.js:173-210 — fixture.
- tests/cli/test_land_cli.py:167-176 — consumer.
- tests/steps/test_land_summary.py:116-142 — effects.
- tests/steps/test_land_gate.py:146-157 — consumer.
- tests/steps/test_drain_fences.py:194-223 — callers.
- tests/steps/land_bench.py:1-58 — integration.

## Contract
Intent: select Land without an attempt number. Effect: summary may fetch, create Git objects and record operations; no delivery, close, claim, reservation or checks. Result: LandDetail carries actions, diff totals/command, land command, nullable PR URL or explained failure. Derive typed facts, never parse display text. Pydantic at HTTP edge; no schema change. Ignore stale replies; refresh changed tasks.

## Work packages
1. Reader/route and Python contracts: closes A.
2. Rail/drawer and mocked browser contracts: closes A. Last, once each: `just check 2>&1 | tail -60`; `just test 2>&1 | tail -40`.

## Acceptance behaviours
A. Land selection shows pending actions, diff summary/command and available PR link; loading/failure/retry and task switching preserve attempt navigation and waiting notes without delivering.
