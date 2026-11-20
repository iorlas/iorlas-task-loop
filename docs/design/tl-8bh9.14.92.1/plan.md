# Header
tl-8bh9.14.92.1 | Base ea06b229f3c7761ec7769a1bc12a907c3bd4df36
Depth: medium; selection + recipe integration
Decision missing: no; unlanded dependency: none.
Evidence ceiling: 12 model calls.
Size: 5 changed files incl. tests/artifacts; 2 independent behaviours; ~60 implement calls.

## Outcome and non-goals
Select Python tests through reverse import reachability. Import-boundary enforcement exists; the selector and its integration remain absent. No boundary refactoring, factory runtime changes, shelf changes or persisted graph cache.

## Settled decisions
- Worktree.diff and Worktree.dirty supply changed paths; no shelf change is needed.
- Build the graph with Python AST and filesystem reads, without importing application or test modules.
- Use the configured Python test roots in pyproject.toml, with tests/steps also resolving bare helper imports as configured by pytest.
- Default comparison is HEAD plus local changes; an optional --base adds committed changes from that reference to HEAD. Do not fetch or mutate repository state.
- Invoke pytest in the selector process, preserving configured options and returning its exit status. No selected tests means successful completion without calling pytest.
- Conservative inclusion takes precedence over narrowing when an import or changed path cannot be classified safely.

## Open decisions
- None.

## Change map
- tools/affected.py (new): changed_paths, select_tests and main; shelf reads, AST reachability and pytest execution. Integrates pyproject.toml test roots/helper path and justfile test-fast.
- justfile: test-fast; invoke the new tool through the declared isolated environment, retaining installation and applicable existing recipe prerequisites. Recipe inspection is deferred by the plan input's explicit prohibition on reading this file.
- tests/rules/test_affected.py (new): fixture projects, shelf observations and pytest-call spies; selection and recipe integration. Load the tool as test_tool_versions.py does.
- docs/design/tl-8bh9.14.92.1/plan.md (new): bounded implementation contract.
- docs/design/tl-8bh9.14.92.1/plan-metadata.json (new): prepared commit and consulted paths.
- pyproject.toml: consult pytest configuration. tests/steps/conftest.py, tests/cli/conftest.py and tests/steps/doubles.py produce implicit fixture/helper dependencies.
- tests/rules/test_policy.py and .importlinter: consult policy/integration constraints; tools are outside FILES today, so the selector's own rules test must cover its absence of process escape hatches.
- Caller search across tools, src/taskloop and tests found no selector/test-fast callers; test-fast is the new production caller.

## Read list
- justfile:1-1 — recipe-file entry only; locate test-fast during implementation, since recipe inspection is prohibited during planning.
- pyproject.toml:7-53 — dependencies, source packaging and pytest roots/helper resolution.
- tests/rules/test_tool_versions.py:1-16 — load a standalone tool in rules tests without changing application packaging.
- tests/rules/test_policy.py:13-55 — source/test discovery and AST policy conventions.
- tests/rules/test_policy.py:309-382 — existing process-escape matcher; consult for selector coverage.
- .importlinter:1-20 — application import-contract roots; selector remains a development tool.
- tests/steps/conftest.py:1-68 — implicit fixtures and helper import edges.
- tests/cli/conftest.py:1-24 — directory-scoped fixture dependencies.
- tests/steps/doubles.py:1-38 — shared bare helper imports and their transitive application dependencies.
- .venv/lib/python3.15/site-packages/git_porcelain/api.py:286-300 — Worktree acquisition through Repo.
- .venv/lib/python3.15/site-packages/git_porcelain/api.py:370-382 — changed-path read signatures and docstrings.
- .venv/lib/python3.15/site-packages/git_porcelain/api_results.py:121-148 — Change.path, Diff.changes and Dirty fields.
- .venv/lib/python3.15/site-packages/git_porcelain/real.py:108-146 — read-only Git view construction and timeout.
- .venv/lib/python3.15/site-packages/git_porcelain/testing.py:1-32 — semantic fake exports for structured Git observations.
- src/taskloop/git_views.py:24-43 — existing bounded, unmemoized shelf view construction convention; no runtime import needed.

## Contract
Intent: changed_paths(worktree: Worktree, base: str) -> frozenset[str] obtains repository-relative changes. Effect: diff(base, "HEAD", cap=0) plus dirty(), unioning Change.path, Dirty.tracked and Dirty.untracked. Result: normalized paths; Git errors remain explicit failures, never an empty successful selection. All Git commands remain inside shelf.

Intent: select_tests(root: Path, changed: frozenset[str]) -> tuple[Path, ...] computes a deterministic selection. Effect: read configured test roots, source and test/helper ASTs; build module-to-file and reverse-import edges. Result: sorted, unique, existing test files reachable from changed modules, plus directly changed tests. Resolve absolute, relative, aliased and from-package imports; include package initializers and transitive helper edges. Model conftest as an implicit dependency of tests in its directory tree. Traverse cycles with a visited set.

Use lexical module identities for deleted files so remaining imports still reach their consumers; renames must retain effects from both old and new identities, conservatively widening when the available path observations cannot establish them. Unknown imports, unresolved local modules, syntax failures, non-Python resource changes and project/test configuration changes widen to all configured tests. Documentation-only changes may select none. External imports add no local edges. Dynamic imports with literal local names can add edges; unresolved dynamic imports conservatively prevent unsafe narrowing. Do not execute imports to resolve them.

Intent: main(argv: list[str] | None = None) -> int composes local reads and pytest. Effect: construct a fresh shelf worktree at the repository root, select tests and pass explicit paths to pytest.main. Result: pytest status, or zero without invocation for an empty selection; observation/parse failures are diagnosed or safely widened before tests run. No shell, process replacement, spawning or signal API belongs to this tool.

## Work packages
1. Implement tools/affected.py and tests/rules/test_affected.py with fixture projects and semantic shelf fakes. Closes A1-A4.
2. Wire justfile test-fast to main, preserving environment/install prerequisites. Test invocation, empty selection and failure propagation in process. Closes A5-A6.
3. Complete focused verification, then run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last; preserve pipeline failure status. These are implementation gates, not planning checks.

## Acceptance behaviours
A1. A change selects direct and transitive importing tests while excluding an unrelated test; aliases, relative/package imports, shared bare helpers and cycles resolve safely.
A2. Changed tests are selected directly, conftest changes select their directory descendants, and deleted or renamed modules retain affected consumers or widen safely.
A3. Unclassifiable dependencies, resources and configuration changes run the full configured suite; documentation-only changes and a clean comparison can select none.
A4. Committed differences and staged, unstaged and untracked paths are combined through structured shelf observations, and failed Git reads cannot masquerade as no changes.
A5. test-fast uses the selector in the installed isolated environment; selected paths run once in stable order, and an empty selection invokes no pytest run.
A6. Test failures reach the recipe's exit status, and selection/execution use no direct process or Git command escape hatch.
