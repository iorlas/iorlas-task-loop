# Header
Task: tl-8bh9.14.139.2; base: 6f368af9b52430f2ca01fc6ac44244776d1e79b5. Depth: small; one dashboard behaviour. No missing decision; .139.1 landed. Evidence budget: 6 model calls. Size: 12 changed files including tests/plan, 1 independent behaviour, 70 implement model calls.

## Outcome and non-goals
Waiting notes exist; Land selection/content remain. Exclude slot labels, outcome wording, PR discovery and delivery controls.

## Settled decisions
Use shared summary mode on selection, outside board polling.
Commands are reference text. PR URL is nullable; publication currently supplies none.

## Open decisions
- None.

## Change map
Source paths below are relative to src/taskloop/.
- dash_land.py (new): reader integrated by _ports.
- dash_model.py: Pydantic delivery response.
- dash_composition.py: _ports callback.
- dash_server.py: DashPorts, _json, _task_api GET.
- dash/static/api.js: apiSource read.
- dash/static/rail.js: landRow, rail selection.
- dash/static/drawer.js: select, render, pane, onTaskMoved.
- tests/steps/test_dash_land.py (new): reader contracts via LandBench.
- tests/cli/test_dash_server.py: Ports callback/route.
- tests/cli/test_dash_composition.py: DashPorts caller.
- tests/dash/rail.test.js: rail/drawer contracts.
- docs/design/tl-8bh9.14.139.2/plan.md: scope.
- land.py: consult land, _summary.
- land_summary.py: consult summary, summarized producers.
- land_data.py: consult land_data, summary_data consumers.
- cli_step.py: consult land.land caller.
- cli_composition.py: consult _landed caller/wiring.
- round_land.py: consult landing.land caller.
- result_data.py: consult LandSummary dispatch.
- step_render.py: consult LandSummary dispatch.
- land_render.py: consult land_lines, summary_lines consumers.

## Read list
- src/taskloop/dash/static/rail.js:197-231 — row.
- src/taskloop/dash/static/drawer.js:24-295 — selection/pane.
- src/taskloop/dash/static/api.js:14-24 — source.
- src/taskloop/dash_model.py:194-220 — shapes.
- src/taskloop/dash_server.py:28-45 — port.
- src/taskloop/dash_server.py:155-187 — routes.
- src/taskloop/dash_composition.py:36-68 — wiring.
- src/taskloop/land.py:65-95 — request.
- src/taskloop/land.py:361-404 — effects.
- src/taskloop/land_summary.py:77-166 — producer.
- src/taskloop/land_data.py:50-89 — consumers.
- src/taskloop/publish.py:1-16 — publication.
- src/taskloop/cli_composition.py:170-197 — caller.
- src/taskloop/cli_step.py:245-267 — caller.
- src/taskloop/round_land.py:45-65 — caller.
- src/taskloop/result_data.py:130-141 — dispatch.
- src/taskloop/step_render.py:39-50 — dispatch.
- src/taskloop/land_render.py:46-85 — consumers.
- tests/cli/test_dash_server.py:25-46 — fake.
- tests/cli/test_dash_composition.py:30-49 — constructor.
- tests/dash/rail.test.js:173-210 — drawer fixture.
- tests/steps/test_land_summary.py:116-135 — effects.
- tests/steps/land_bench.py:1-58 — test integration.
- tests/dash/rail.html:1-14 — browser fixture.
- src/taskloop/dash/static/app.js:313-316 — source caller.

## Contract
Intent: select Land without an attempt number. Effect: shared summary fetch/Git objects and operation bookkeeping; no push, close, claim, delivery reservation or checks. Result: typed actions, diff totals/command, land command, optional PR URL or explained failure. Serialize Pydantic at HTTP edge; no schema change. Ignore stale replies; refresh changed tasks.

## Work packages
1. Backend/Python tests: projection/effect boundary; closes A.
2. Client/browser contracts: selection/content/retry; closes A. Exercise mocked fixture. Last, once each: `just check 2>&1 | tail -60`, `just test 2>&1 | tail -40`.

## Acceptance behaviours
A. Land selection displays actions, diff summary/command and any available PR link; loading/failure/retry and task switching preserve attempt navigation and waiting notes without delivering.
