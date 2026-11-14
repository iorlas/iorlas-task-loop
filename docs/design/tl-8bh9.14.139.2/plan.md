# Header
Task: tl-8bh9.14.139.2; base: f99143708fba9163ea75f95a8facb62c2e8fe507. Depth: small; one dashboard behaviour. No missing decision; prerequisite landed. Evidence budget: 6 model calls. Size: 13 files including tests/plan, 1 independent behaviour, 70 implement model calls.

## Outcome and non-goals
Status/waiting wording exists; selection and delivery content remain. Exclude slot labels, outcome translations and delivery execution controls.

## Settled decisions
Use shared land summary mode, loaded on selection outside board polling.
Commands are reference text; inspection never initiates delivery.
Use available publication facts for PR links, without new PR discovery.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_land.py` (new): reader/presenter integrated by `_ports`.
- `src/taskloop/dash_model.py`: Pydantic delivery response.
- `src/taskloop/dash_composition.py`: `_ports` wires summary/publication reads.
- `src/taskloop/dash_server.py`: `DashPorts`, `_task_api` add delivery GET.
- `src/taskloop/dash/static/api.js`: client GET consumed by drawer.
- `src/taskloop/dash/static/rail.js`: `landRow`, `rail` add accessible selection.
- `src/taskloop/dash/static/drawer.js`: `select`, `render`, `pane` load/show Land.
- `tests/steps/test_dash_land.py` (new): reader contracts via semantic fakes.
- `tests/cli/test_dash_server.py`: endpoint and `DashPorts` caller.
- `tests/cli/test_dash_composition.py`: `_ports` and `DashPorts` caller.
- `tests/dash/rail.test.js`: drawer/rail behaviour.
- `tests/steps/test_land_summary.py`: summary effect assertions if needed.
- `docs/design/tl-8bh9.14.139.2/plan.md`: scope.
Consult `land.land`, `_summary`, `LandSummary`, `land_data.summary_data`, publication facts, `show_render` and CLI wiring; preserve existing callers.

## Read list
- `src/taskloop/dash/static/rail.js:193-237` — final entry.
- `src/taskloop/dash/static/drawer.js:24-100` — selection/lifetime.
- `src/taskloop/dash/static/drawer.js:195-295` — pane.
- `src/taskloop/dash/static/api.js:1-36` — client reads.
- `src/taskloop/dash_model.py:164-220` — detail shapes.
- `src/taskloop/dash_server.py:28-45` — port consumers.
- `src/taskloop/dash_server.py:176-205` — routing.
- `src/taskloop/dash_composition.py:36-68` — port producer.
- `src/taskloop/land.py:65-95` — request/results.
- `src/taskloop/land.py:361-404` — effects.
- `src/taskloop/land_summary.py:76-100` — summary facts.
- `src/taskloop/land_data.py:1-70` — projection.
- `src/taskloop/publish.py:1-70` — publication facts.
- `src/taskloop/show_render.py:1-70` — summary consumer.
- `src/taskloop/cli_step.py:1-80` — CLI integration.
- `src/taskloop/cli_composition.py:1-100` — application wiring.
- `tests/cli/test_dash_server.py:1-90` — server fixtures.
- `tests/cli/test_dash_composition.py:1-80` — composition callers.
- `tests/dash/rail.test.js:173-208` — drawer fixture.
- `tests/dash/rail.test.js:296-307` — waiting regression.
- `tests/steps/test_land_summary.py:1-52` — shared summary fixture.

## Contract
Intent: select Land without an attempt number. Effect: shared summary read, including its fetch/Git-object creation and operation bookkeeping; no push, close, claim, delivery reservation or checks. Result: typed actions, diff summary/command, land command, optional PR URL or explained failure. No stored fields change. Ignore obsolete responses; refresh on task changes and allow retry.

## Work packages
1. Backend files/Python tests: projection and effect boundaries; closes A.
2. Client files/browser tests: selection, content and retry; closes A. Run mocked browser fixture. Last, once each: `just check 2>&1 | tail -60`, `just test 2>&1 | tail -40`.

## Acceptance behaviours
A. Land selection shows actions, diff summary and commands, links an available PR, handles loading/failure/retry and task switching, preserves numbered-attempt selection and waiting notes, and performs no delivery.
