# Evaluate pytest features and plugins

Task: `tl-8bh9.14.120`. Prepared 2026-11-13 against task-branch HEAD `79f57c17`.
Origin: owner round 19, architecture-review session `local_16bd6c79`, 2026-11-13.
Status: proposed implementation plan; no dependency, test or gate changes made by this planning attempt.

## Purpose and limits

Make focused tests faster to run and smaller to maintain. Prefer pytest's built-in features, retain xdist,
and evaluate every requested plugin on the repository's Python 3.15 environment. Adopt a plugin only after
compatibility and a measured speed or size benefit are demonstrated with the same behavioral protection.
An unsuccessful trial is a valid evaluation result; installing all candidates is not the objective.
Preserve the owner's requirement that implementation follows their yes; this document records proposals,
not blanket approval of dependencies or completion of the evaluation.

Read the foundation plan and glossary. Follow the architecture review's testing decisions X1–X4 in
`docs/design/architecture-review/decision-register.md`: parametrization and native subtests, scoped test
groups, semantic fakes, bounded Hypothesis use, snapshots of public contracts and ad hoc order checks.
That register also mentions other plugin trials; they are outside this task's requested list.
Do not restore the reference implementation's runners, conftest, affected-test scripts or imports.
No factory runtime changes, source-folder redesign, new scheduler, production dependencies or glossary terms.

## Current code and constraints

- `pyproject.toml` requires Python `>=3.15`; `.python-version` is `3.15`. Dev dependencies are exactly
  `pytest==9.2.0` and `pytest-xdist==3.8.0`; retain both pins unless a separately evidenced incompatibility
  requires an owner decision. xdist is installed but the current test recipe supplies no worker option.
- Pytest uses importlib imports, disables cacheprovider, and adds `tests/steps` to its configured test path
  for the `doubles` import. Collection roots are `tests/cli`, `tests/steps` and `tests/rules`.
- `tests/steps/conftest.py` creates function-scoped mutable database, fake Git, slot and attempt fixtures.
  It imports attempt/check/land schema and supporting modules at collection time. This is a concrete source
  of test coupling; merely adding an impact-selection plugin would not remove it.
- Parametrization, `tmp_path`, `capsys` and `monkeypatch` already have substantial use. Examples include
  `tests/steps/test_answer_contract.py`, `test_round_bound.py` and `tests/cli/test_step_status_cli.py`.
  Extend these patterns where they remove repeated arrangements or assertions; avoid mechanical rewrites.
- Recovery behavior is already exercised in `tests/steps/test_land_resume.py` and related land tests.
  `src/taskloop/steps.py` supplies current step sequencing. The proposed general flow table from review A5
  is not an implemented general-purpose state machine here. Test existing behavior; coordinate flow-table
  totality with its owning implementation rather than inventing a table to justify Hypothesis.
- Most source modules are still flat under `src/taskloop`. Match test filenames to owning modules now;
  align `tests/<slice>/` folders with actual feature folders as their owning tasks introduce them.
  Keep per-slice conftest imports local; do not move the broad steps conftest to the test root.
- `tests/cli/test_dash_server.py` exercises real HTTP on loopback. Blanket network blocking needs a narrow
  allowance for these tests. Tests under `tests/steps/real` include external-tool and process contracts.
- `just install` installs a wheel using frozen uv dependencies. `just check` installs then runs lint,
  types and import rules. `just test` currently hardcodes all three collection roots. Do not execute that
  default whole-suite recipe as an agent. Extend the recipe to accept explicit pytest paths/options,
  preserving its existing default for authorized callers, so required focused gates can use `just test`.

## Online version and Python support check

Checked primary package pages and project documentation on 2026-11-13. These are exact **trial pins**,
not additions to this branch's environment. Recheck release/yank status at implementation time; record
any replacement exact pin and reason. Never substitute an unbounded dependency or prerelease silently.

“Advertised” below means upstream explicitly names 3.15. An open-ended Requires-Python or a universal
wheel is only installation eligibility, not evidence of working support. No local compatibility or gain
measurements have been made in this documentation-only attempt. Every row requires the trial described below.

| Candidate and exact trial pin | Upstream Python 3.15 evidence | Trial and measurable benefit required |
|---|---|---|
| [pytest-testmon==2.3.0](https://pypi.org/project/pytest-testmon/2.3.0/) | Requires Python >=3.11; no explicit 3.15 claim found on package page. Compatibility unverified. | Compare cold recording, warm no-change and changed-code focused runs; adopt only for repeatable net time savings with no missed expected failing tests. |
| [hypothesis==6.170.15](https://pypi.org/project/hypothesis/6.170.15/) | Advertises 3.15 and publishes CPython 3.15 wheels. [Changelog](https://hypothesis.readthedocs.io/en/latest/changes.html) added 3.15 support in 6.165.7. | One crash/restart state-machine trial and, when implemented, flow-table properties. Require less total test/support code for equivalent invariants within the focused runtime budget. |
| [syrupy==7.0.0](https://pypi.org/project/syrupy/7.0.0/) | Release metadata explicitly lists 3.15. Use this release's metadata; the description's compatibility table still calls 7.x unreleased. | Compare one CLI JSON/public-schema contract with ordinary assertions and inline-snapshot. Count snapshot files as maintained code/data. Adopt at most one snapshot plugin. |
| [inline-snapshot==0.36.2](https://pypi.org/project/inline-snapshot/0.36.2/) | Requires Python >=3.9; no explicit 3.15 claim found on package page. Compatibility unverified, including source rewriting dependencies. | Same contract comparison as Syrupy; require smaller complete tests, useful diffs, stable serialization and noninteractive read-only check mode. |
| [pytest-timeout==2.4.0](https://pypi.org/project/pytest-timeout/2.4.0/) | No explicit 3.15 claim found. Compatibility unverified. 2.5.0 is yanked; exclude it. The review register also names 2.4.0. | Bound a controlled hang and measure time to useful failure plus normal-run overhead. Adopt only if failure becomes measurably faster or existing watchdog code can be removed. |
| [pytest-randomly==5.0.0](https://pypi.org/project/pytest-randomly/5.0.0/) | Advertises 3.15; [release notes](https://github.com/pytest-dev/pytest-randomly/blob/5.0.0/CHANGELOG.rst) explicitly add it. | Ad hoc focused seeded order-independence runs; measure overhead and removed order-reset scaffolding or faster reproduction of an observed order bug. Do not claim ordinary runtime savings from randomization. |
| [pytest-socket==0.8.1](https://pypi.org/project/pytest-socket/0.8.1/) | Requires Python >=3.10; released metadata lists through 3.14, not 3.15. Compatibility unverified. | Verify blocked accidental network and narrowly allowed loopback; measure reduced bespoke blocking code or faster failure of accidental network use. |
| [pytest-cov==7.1.0](https://pypi.org/project/pytest-cov/7.1.0/) | Released classifiers list through 3.14. Plugin compatibility unverified; its coverage dependency supports 3.15 at the pin below. | Record per-test contexts and affected-slice costs. Require a concrete smaller test dependency closure or faster focused selection enabled by the report, including collection cost. |
| [pytest-xdist==3.8.0](https://pypi.org/project/pytest-xdist/3.8.0/) | Existing exact pin; latest non-yanked release checked. Metadata lists through 3.13; local 3.15 compatibility must be demonstrated. | Retain it. Compare serial with a bounded two-worker run; enable workers for a selection only where startup/collection costs are repaid. |
| [coverage==7.17.3](https://pypi.org/project/coverage/7.17.3/) | Advertises 3.15 and supplies CPython 3.15 wheels. | Exact shared trial pin for testmon/cov, including contexts and xdist combination; account for instrumentation overhead separately. |

The [pytest-cov 7.1.0 manifest](https://raw.githubusercontent.com/pytest-dev/pytest-cov/v7.1.0/pyproject.toml)
requires coverage >=7.10.6. Testmon's [current manifest](https://github.com/tarpas/pytest-testmon/blob/main/pyproject.toml)
allows coverage >=6,<8 and pytest <10. Verify the *released* 2.3.0 wheel metadata when resolving the trials;
main-branch metadata is not a release guarantee. Coverage 7.17.3 is a proposed common pin, subject to that check.
Keep every accepted direct dependency exact in `pyproject.toml` and all resolved versions/hashes in `uv.lock`.
For rejected plugins, retain the evaluated pin and reason in the evidence without retaining the dependency.

## Implementation sequence

### 1. Establish focused measurements and compatibility

Use the existing assigned worktree and the declared Python interpreter. Record commit, full Python build,
OS, uv/pytest/plugin versions, exact commands, collected node IDs and test counts. Run `just install` before
repository tests; use `uv run --frozen --no-sync python -I -m pytest ...` or the focused `just test` recipe.
Verify that imported taskloop code is the installed successor wheel, with no editable or baseline fallback.
Resolve candidate environments separately and keep trial dependencies out of the accepted dev group until chosen.
Do not run `uv run --with` opportunistically against the frozen project and call that a reproducible trial.

Start with three bounded, named selections: answer/CLI JSON contracts, land recovery using semantic fakes,
and slice import/policy contracts. List actual paths before running. Exclude live tests; use additional
specific contract nodes only when needed for a plugin capability. No whole-suite benchmark or collection.

Measure baseline collection and execution independently with pytest's built-in durations reporting and a
wall clock at the command boundary. For each comparison, use one warm-up and at least five paired runs,
alternating baseline/candidate on the same host with the same selection, worker count and environment.
Report individual timings, medians, range, collected/executed/deselected counts, and total maintained lines
before/after including helpers, fixtures, snapshots and configuration. Report install/cold cache cost separately.
Treat a speed gain below observed noise as inconclusive; use a 10% median improvement as the initial useful
threshold, repeated in another batch if ranges overlap. A size-only adoption must not materially regress
focused latency; report the tradeoff rather than hiding it in an aggregate score.

For each plugin, check resolution, import, collection, a focused passing behavior, a deliberate failing
behavior and teardown on Python 3.15 with pytest 9.2.0. Exercise relevant serial/xdist combinations,
especially snapshots, fixture isolation and coverage. Record unsupported behavior as a rejection/defer
with an exact version and evidence. Do not downgrade Python or pytest to make a plugin pass.

### 2. Use pytest features in one bounded pilot

Select land recovery as the initial fixture/test-structure pilot; use answer-contract and CLI JSON tests
only for their respective comparisons. Preserve failure-path assertions and public behavior coverage.

- Replace repetitive case loops with `parametrize` and descriptive `pytest.param(..., id=...)`. Use native
  pytest 9 [subtests](https://docs.pytest.org/en/stable/how-to/subtests.html) where one expensive arrangement
  can safely support independent read assertions. Do not add pytest-subtests or share mutable case state.
- Keep database connections, mutable fake repos, reservations, environment edits and locks function-scoped.
  Consider module/session scope only for measured expensive immutable inputs; use `tmp_path_factory` for
  such inputs and function-local copies where mutation is required. Use `tmp_path` for all mutable files.
  Preserve yield/`finally` cleanup and ensure isolation with two xdist workers and alternate test orders.
- Split only fixtures needed by the pilot into its owning conftest/support module. Avoid unrelated imports
  during collection. Follow actual source slices as folders migrate; update collection roots and imports
  atomically when tests move, retaining all collected cases. Keep CLI and architecture contracts distinct.
  Remove the global `doubles` path addition only when all its consumers have moved to explicit scoped imports.
- Register a small set of markers for fast behavior, adapter contracts, real-tool contracts and CLI smoke,
  following the existing review categories. Add strict marker validation and demonstrate focused selection.
  A marker labels tests; it does not silently skip existing required checks or authorize agent live tests.
- Reuse owning shelf semantic fakes. Do not create global fixture registries, copy SQL fixtures into competing
  stores, widen production ports for tests, or write a test for every helper. Respect 400/80/800 caps and typing rules.

### 3. Run bounded plugin trials

**Impacted tests and budgets.** [Testmon](https://www.testmon.org/) records executed-code dependencies in
`.testmondata`, independent of Git. Scope its first database and runs to the named focused selection; no
whole-suite seed. Compare selected failures with running that complete selection after controlled changes
to a leaf module, shared dependency, fixture/conftest, test addition, JSON/profile input and configuration.
Use disposable trial inputs and restore intentional trial changes. Check wheel reinstall/path handling,
empty/missing/stale database, branch changes and simultaneous worker behavior. Use documented cache ownership;
never share an unproven writable database between slots. Non-Python inputs and imports not executed by an
earlier test cannot be assumed covered. Keep explicit slice selection as the correctness path and treat
unknown/configuration changes conservatively. Testmon's database is disposable test tooling, never factory state
or proof of a check pass. Do not add it to default required checks until selection correctness is demonstrated.

Use pytest-cov's documented [per-test contexts](https://pytest-cov.readthedocs.io/en/latest/contexts.html)
(`--cov-context=test`) with coverage pointed at the installed package. Attribute setup/run/teardown execution
to tests and combine worker data using supported APIs. Dynamic line coverage is not an import graph: record
collection imports/timing separately. Establish the pilot's observed affected-test count and runtime as a
recorded budget, then demonstrate a local change stays within it without dropping expected tests. This trial
must produce a concrete test-closure improvement to justify ongoing instrumentation. Avoid a speculative
global coverage percentage, generic impact service or default coverage overhead on every fast run.

**Stateful properties.** Use at most one or two cheap semantic state machines. For land recovery, express an
independent model of intent, observable external action, recorded result and restart; inject failures through
existing explicit ports at those boundaries. Assert no duplicate accepted effect, preservation of reservations
until owned release, and agreement after reconciliation. Cover applicable crash boundaries explicitly with
parametrized examples; randomness alone does not prove all boundaries. Use `run_state_machine_as_test` from a
pytest function; do not generate Hypothesis unittest TestCase classes. Construct fresh state for every machine
execution and clean up without mutating a shared function-scoped fixture across examples. Start with 20 examples
and 20 stateful steps, report measured cost and retain failing reproductions. Adjust only with evidence.
For a finite flow table, exhaustively enumerate declared step/result pairs with parametrization for totality;
Hypothesis may add sequences/invariants when the owning table exists. Do not test a copy of production logic.

**Public snapshots.** Compare Syrupy and inline-snapshot against ordinary typed assertions on one stable CLI
JSON response and one public answer-schema surface. Assert parsed JSON values; stabilize only genuinely variable
paths/identifiers/time through explicit ports or narrow field normalization. Keep meaningful status, required fields,
error explanations and exit/stderr checks visible. Measure net maintained size and diagnostic quality after
adding/removing a public field. Reject wholesale object repr/private-storage snapshots and tautological imports
of the implementation's expected output. Choose at most one plugin, or neither. Missing/changed snapshots must
fail normal checks; all check commands must be noninteractive and write no snapshots/source. Snapshot updates
are an explicit development action whose complete diff is reviewed; never accept a golden file automatically.

**Timeouts, order and sockets.** Use a controlled in-process hang in an isolated test invocation, launched only
through the owning process API, to verify timeout failure and diagnostics. Test signal-method interaction with
the existing interrupts handlers; the thread method may terminate the interpreter without fixture cleanup.
Do not install a second application signal owner or rely on timeout teardown to release real external resources.
Choose timeouts from measured normal costs with headroom; do not apply arbitrary short deadlines to all tests.
Use fixed logged randomly seeds and replay a failing seed. Run this ad hoc rather than multiplying default checks;
check that reseeding does not compromise Hypothesis reproducibility or fixture isolation. With pytest-socket,
block outbound connections by default only for the evaluated offline selections, assert that blocking works,
and allow numeric loopback hosts solely on the dashboard server contract tests. Do not broadly enable network
for a folder or confuse blocking Python sockets with blocking external-tool network access. Retain process/Git
sandbox boundaries. Measure all three plugins' normal overhead and specific failure/size benefit separately.

### 4. Adopt only demonstrated improvements

Write evaluation evidence under this task's design directory: exact environment/commands, compatibility per
pin, timing and line-count comparisons, preserved contracts, decision and limitations for **every** plugin.
Replace all “unverified/not measured” entries with measured results or an explicit unsupported/unavailable
reason. Keep xdist even if serial wins the smallest selections. Retain built-in feature improvements that pass
the same comparison. Reject/defer plugins with no demonstrated gain; remove trial-only dependencies, configuration,
artifacts and source changes. Caches and raw execution artifacts remain local and are not committed.

The later implementation's expected files are `pyproject.toml`, `uv.lock`, the focused `justfile` recipe,
the selected test/conftest files and task-local evaluation evidence. Exact changed test paths follow the bounded
pilot, not a repository-wide migration. No other package/library is introduced without showing that tests shrink.

## Completion and verification

1. Every requested plugin has an exact evaluated version, explicit Python 3.15 result, measured gain/cost
   or a substantiated reason it could not be trialed, and an adopt/reject/defer decision. No compatibility
   statement is inferred solely from Requires-Python. No timings or reductions are invented.
2. Accepted changes reduce focused runtime or total test maintenance size while preserving behavioral
   contracts, node selection and deliberate-failure detection. At most one snapshot plugin is retained.
3. Focused tests use scoped fixtures, tmp_path, meaningful parametrization/subtests and registered markers;
   test collection does not gain unrelated slice imports. New folders mirror implemented slice ownership.
4. Run `just check` and `just test` with explicit affected paths/options after the focused recipe change.
   Include policy/import isolation, changed CLI contracts, the recovery pilot and relevant plugin interactions.
   Exercise retained xdist with two workers and replayable alternate ordering; inspect artifact cleanup.
   No whole-suite/live agent run, baseline environment fallback or direct subprocess/signal escape.
5. Report changed files, exact commands/results, unresolved compatibility limitations and task status.
   Do not weaken checks, silently widen the evaluation or claim the task factory is complete.

Planning validation: inspected source/configuration, foundation plan, glossary and upstream sources; no tests
run because this attempt changes only this plan. The local tracker lookup did not resolve this task ID;
do not create a replacement task, change claims or close the assigned task based on that lookup.
