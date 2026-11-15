# Header
Task: tl-8bh9.14.102.4
Base: ca861999263bd031d4f59007c60cdcf726a50fea
Depth: small
Reason: one snapshot rule.
Decision/dependency: none missing/unlanded.
Evidence budget: 6 model calls.
Size: 8 files, 1 behaviour, 35 implement model calls.

## Outcome and non-goals
Detect public contract drift until deliberate refresh. Adapt the supplied implementation to current producers. Runtime behaviour and schema evolution are outside scope.

## Settled decisions
- Discover api.py files from the current source tree; capture exports, signatures and exposed model fields/methods.
- Exercise CLI parsing and rendering with deterministic facts and fake owning operations.
- Collect SCHEMA.version from its current owner; never pin a version in fixtures or collectors.
- Tests compare without writing; a separate collector prints reviewable replacement JSON.
- Regenerate folder contracts with the existing generator on the implementation tree.

## Open decisions
- None.

## Change map
- `tests/steps/public_surfaces.py` (new): `collect`; restore API/schema collection and comparison.
- `tests/steps/public_surface_cases.py` (new): `cli_cases`; restore `cli.main` cases through `cli_step` and `cli_drain`.
- `tests/steps/public_surface_fixtures.py` (new): `shown_cases`, `step_cases`; adapt `HoldRow.event` and changed constructors.
- `tests/rules/test_public_surfaces.py` (new): drift/refresh coverage consumes `cli_cases` and `collect`.
- `tests/rules/public_surfaces.json` (new): reviewed output of `collect(cli_cases())` on the current installed package.
- `.importlinter`: generated contracts; refresh through `generate_import_contracts.generate`, retaining reviewed settings.

## Read list
- `src/taskloop/agents/api.py:1-5` — current export owner.
- `src/taskloop/factory_schema.py:32-56` — schema version owner.
- `src/taskloop/cli.py:40-111` — inspection/profile/version JSON producers.
- `src/taskloop/cli.py:160-185` — repository JSON producer.
- `src/taskloop/cli_step.py:217-236` — rounds start JSON caller.
- `src/taskloop/cli_step.py:335-355` — result_data.as_data caller.
- `src/taskloop/cli_drain.py:1-38` — both drain JSON callers.
- `src/taskloop/result_data.py:40-74` — populated attempt JSON producer.
- `src/taskloop/result_data.py:138-190` — command and rounds JSON producers.
- `src/taskloop/attempt_status.py:69-98` — AttemptView fixture input.
- `src/taskloop/hold_store.py:62-82` — typed hold fixture input.
- `src/taskloop/task_event.py:24-64` — event construction constraints.
- `tools/generate_import_contracts.py:12-93` — tree collector, generator and entry point.
- `.importlinter:1-35` — existing contract integration.
- `tests/rules/test_slice_contracts.py:10-49` — generator freshness gate.
- `tests/rules/test_policy.py:15-56` — loader and size constraints.

## Contract
Intent: detect public contract drift. Effect: read declarations/schema and render deterministic CLI examples without external actions or snapshot writes. Result: unchanged data passes, drift fails with a difference, deliberate refresh passes. No production type or stored-field changes.

## Work packages
1. Restore the five files from e57e0259f00844d8fc879529a54f00bc32c1f347; adapt fixtures, especially HoldRow/TaskEvent. Close A1.
2. Regenerate JSON from the installed current package and folder contracts from the current tree. Retain API, CLI and schema mutation/refresh cases. Close A1.
3. After installation, run the focused snapshot test using isolated pytest. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each with pipefail. Close A1.

## Acceptance behaviours
A1: Changing any covered API declaration, CLI JSON shape or schema version fails a readable snapshot comparison without writes; unchanged or deliberately refreshed snapshots pass using current repository data.
