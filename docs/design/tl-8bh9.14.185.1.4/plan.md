# Depth
Large: the supplied code map names more than 60 files; the task has one cohesive behavior, code map generation with contract coverage. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 20 model calls. The file-list trigger does not imply independent work requiring a split.

## Size
Estimated changed files: 4, including this plan and three existing test files: `tests/steps/test_code_map.py`, `tests/steps/test_input_context.py`, and `tests/steps/test_check_repeat.py`. Allow a fifth file, `src/taskloop/input_context.py`, only if the focused contracts expose a generator defect. No new files beyond this plan are expected.

Independent behaviors: 1. Generated agent-step inputs provide the repository code map. Acceptance: focused contracts demonstrate the complete sorted committed path inventory and truthful established layout hints, placed once inside factory context after the glossary and before its end marker, in plan and implement inputs and after context refresh on ordinary and failed-check retries. Dirty checkout content and obsolete paths cannot enter the map.

Estimated model calls for one implement attempt: 25, including focused verification and final gates. These estimates are below 60 files, 3 independent behaviors and 100 model calls. The large planning depth reflects the supplied inventory, not the implementation footprint.

## Current implementation and scope
Use the supplied glossary meanings of step, attempt, plan, task and worktree; no missing term requires a glossary read.

`input_context.read` already obtains paths at the selected source commit through `GitProfileFiles.paths`, filters to `src/`, `tests/` and `docs/design/`, and sorts the result. `InputContext.render` already emits `CODE MAP` after the glossary within the delimited factory context. `_layout` emits only established taskloop hints and conditions the shared-helper hint on committed pytest settings. The Git adapter uses the owning Git API rather than checkout traversal.

Both step input renderers already consume this shared context. Admission and advancement construct it at their selected source; dispatch refreshes it at the prepared commit using the pinned Git directory; failed-check repair refreshes the original input at the checked commit. Existing tests already cover large inventories without truncation, excluded prefixes, dirty and deleted paths, empty maps, conditional hints, listing errors and replacement of an old map. Existing dispatch and ordinary-repeat tests assert one map, but the initial input contract does not pin its placement and the failed-check dispatch contract does not explicitly inspect its map contents.

The supplied discussion splits answer rules, early-stop instructions, Read list generation and code map generation into independent children. This task owns only the last part. Reuse the shared producer and existing callers; do not recreate their machinery or change sibling instructions. No prerequisite child is stated to be unlanded. Leave AGENTS.md unchanged.

## Read list
- `src/taskloop/input_context.py:32-123` — map input port, committed producer, layout hints, rendering and refresh owner.
- `src/taskloop/git_views.py:105-147` — committed listing and blob adapter, including typed read failures.
- `src/taskloop/plan_step.py:152-156` — plan input caller and context placement relative to task and closing instructions.
- `src/taskloop/implement_step.py:120-124` — implement input caller using the same context renderer.
- `src/taskloop/steps.py:32-58` — step entry points for parameterized contracts.
- `src/taskloop/admit.py:119-175` — common task input assembly and first admission's committed context source.
- `src/taskloop/admit_chain.py:238-259` — advancing admission's context producer and shared task input call.
- `src/taskloop/attempt.py:193-203` — dispatch refresh at the prepared commit and retained launched input.
- `src/taskloop/check_repeat/repair.py:52-74` — failed-check retry refresh before feedback framing.
- `tests/steps/test_code_map.py:1-95` — existing map behavior contracts and committed-tree fixtures to extend.
- `tests/steps/test_input_context.py:1-80` — imports, semantic input fake and initial input contracts for both steps.
- `tests/steps/test_input_context.py:136-167` — committed fixture and admission source-selection coverage.
- `tests/steps/test_input_context.py:183-240` — moved-source dispatch and ordinary retry contracts to strengthen.
- `tests/steps/test_check_repeat.py:45-65` — existing failed-check setup; reuse its owned lifecycle fixtures.
- `tests/steps/test_check_repeat.py:97-123` — actual failed-check retry dispatch and launched input assertions.
- `tests/steps/test_steps.py:14-19` — existing task fixture used by input contracts.
- `tests/steps/doubles.py:169-187` — existing pinned Git semantic fake; do not add a competing fake.
- `pyproject.toml:46-50` — committed pytest helper placement and import settings used by map hints.

## Change map and implementation
1. Extend `tests/steps/test_code_map.py` using its existing FakeRepo and GitProfileFiles fixtures. Assert section order and boundaries, exact inventory contents and hint placement rather than only substring presence. Keep the existing complete-inventory, empty-tree and failure contracts. Strengthen conditional-hint coverage with an absent feature/test folder and incompatible pytest import settings, checking that absent facts are not advertised. Test the public rendered result; avoid tests for each private helper.
2. Extend `tests/steps/test_input_context.py` with a nonempty map in the parameterized plan/implement input contract. Assert one standalone `CODE MAP` heading inside the factory context, after the supplied glossary and before `END FACTORY INPUT CONTEXT`, with the expected paths and layout hints in that section. Assert factory context follows task prose and precedes each step's closing instructions without snapshotting sibling instruction text. Strengthen existing moved-source and ordinary-repeat tests to check that the refreshed map section contains current paths, drops obsolete paths and remains inside the single context block. Preserve task prose, saved-work framing and launched-input evidence assertions.
3. Strengthen the existing failed-check dispatch test in `tests/steps/test_check_repeat.py`: inspect the map section separately from task prose and plan references, assert a tracked path from the checked task commit appears there exactly once, and assert the map stays inside the single refreshed context block. Reuse its existing semantic fixtures and retained launched-input comparison. Do not add live tests or new lifecycle orchestration.
4. Runtime generation is already present and needs no parallel implementation. If these contracts reveal an actual mismatch, make the smallest correction in `input_context.py` and keep the same producer, Git port and callers. Do not broaden the inventory scope, introduce new hints, schema changes, subprocesses, fallback readers or new vocabulary. All required edits and consultation points are listed above; an unexpected wider defect requires reassessment before expansion.

## Verification and completion
After edits, use `just install` before focused execution. Run the permitted focused command separately for each changed test file as needed: `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`, with pipefail enabled so failures are visible. Do not run pytest or ruff directly. Keep tests as pytest functions and preserve the source, function and test-file size caps; the current test files are well below 800 lines.

Last, run `just check 2>&1 | tail -60` and then `just test 2>&1 | tail -40`, once each with pipefail enabled, following the implement step's final-gate rules. Completion requires passing gates and focused contracts for map contents and placement across the existing input routes. This planning attempt does not run implementation gates. Commit only the task's selected files through the factory; no AGENTS.md changes or unrelated edits.
