# S1b: taskloop_dash into packages/dash (design only, bead tl-e5t0.12)

Status: design, no code. Follows [workspace.md](workspace.md) (section 6, step 2). Measured on main at 25d2d95a. The owner-side decision (defer until C-PIPELINE lands) stands; this note says what the move needs, so it can start when released.

## 0. A correction to the premise

An earlier note (mine, in the S1b hand-off) said "taskloop_dash imports taskloop 126 times". **That number was wrong**: the grep matched `from taskloop_dash`, the dashboard's own imports. Measured by AST, the dashboard imports **nothing of `taskloop`**: its non-stdlib imports are `tlkernel` (27 files import it directly, about 55 distinct kernel modules) and one `tlpaths`. The contract `dash-imports-contracts-only` already enforces it. So the dashboard is already a clean leaf member in the sense of workspace.md section 2, cleaner than `artifacts` was. Nothing in it has to become a port or move to the kernel.

## 1. The edges

| edge | count | what it needs |
|---|---|---|
| dash -> taskloop | **0** | nothing |
| dash -> tlkernel | 27 files | `dependencies = ["tlkernel"]`; no change |
| engine -> dash (`app/launch` only, contract `only-launch-imports-dash`) | 3 files: `launch/dash.py` (`bind`, `cli.dash`, the `DASH` script path, the `python -m taskloop_dash --ports taskloop.app.launch.dash_ports:ports` spawn), `launch/dash_ports.py` (`Env`/`Ports`), `launch/reindex.py` (`Env`, `Ports`, `index.reindex`, `readers.records`) | **no inversion needed**: launch is a composition root, and a root importing a member is the allowed direction. The dashboard already receives the engine's facts as `Ports` built by a `module:func` string, so the reverse edge is a string, not an import. Only the path constant `DASH = SRC / "taskloop_dash" / "__main__.py"` (it names the process for `ps` matching) and the child's `sys.path` change. |
| `src/taskloop/__init__.py` `ours = ("taskloop", "taskloop_dash", ...)` | 1 | a name list; unchanged if the import root keeps its name |

The child process: `__main__.py` builds `VENDOR = parents[2] / "skills/task-loop/_vendor"`. After the move that `parents[2]` is `packages/dash`, so it must derive the repo root another way (import `tlpaths`, which already knows the root, then the vendor path), and the spawned `python3 -m taskloop_dash` must find `packages/dash/src` on its path (the spawn env or `tlpaths`, as for the kernel).

## 2. Naming

workspace.md rule: folder `packages/<stage>`, project and import root `tl<stage>`. For the two that are already top-level packages (`taskloop_dash`, `delegate`) the rename costs about 70 import sites in tests, dev and the engine for no isolation gain. Recommendation: **keep the import root `taskloop_dash`** (folder `packages/dash`, project `taskloop-dash`), and write the exception in workspace.md and in `dev/packages.py`'s manifest reading. Consequences to handle in the move PR: `justfile` builds `--package "tl$p"`, so it must read the project name from the manifest (add it to `dev/packages.py` output) and `host_ban.code_dir()` is not involved (dash is not a converted stage).

## 3. What moves

- `src/taskloop_dash` (61 .py files, 4,838 lines, 31 non-Python files under `static/`) to `packages/dash/src/taskloop_dash`, `git mv`, history kept. Static assets: the page is one HTML file read by path; as an editable workspace member nothing else is needed. A non-editable build needs `[tool.hatch.build.targets.wheel] include` for `static/`; the spike's `uv run --isolated` is editable, so not needed now.
- Path literals naming `src/taskloop_dash`: **25 files**, grouped: static-asset readers in tests (`test_dash_static` x2, `test_dash`, `test_dash_write_policy`, `test_dash_artifacts`, `test_dash_xss`, `test_dashboard_verbs`, `test_mainstate`, `dev/dash_fixtures.py`), rule tests that walk the dash tree (`gate_rules`, `test_dash_state_paths`, `test_runstate_rule`, `test_stage_parts`, `test_dash_engine_sql`, `test_store_path`, `test_envvars`, `test_env_below_edge`), `tests/rules/layout_lock.py` (its `src/taskloop_dash` node rule), `dev/reach.py` TOP map, `dev/move_kernel.py` (obsolete: delete). Each becomes a glob or the new path. The 22 files that only `import taskloop_dash...` (tests/adapters, asks, contracts x3, loop, rules, run x2, support x4, track, wire x2, dev x3) **do not change**, because the import root keeps its name.
- Claim to retire: "~88 files collide". Real exposure is the 61 renamed source files (a PR that edits a dash file merges through a rename cleanly) plus 25 path-literal files.

## 4. The tests (the real work)

`tests/dash` has 50 files. By what they import beyond dash and the kernel:

| group | files | home after |
|---|---|---|
| only `taskloop_dash`, kernel, stdlib, `support.*` | about 35 | `packages/dash/tests` |
| import `taskloop.*` (launch x4, pipeline x3, adapters x6, run x2, asks x2): they test the engine's side of the ports (`dash_ports`, reindex, usage) | 15 | stay in `tests/` (move to `tests/launch` or `tests/e2e`): a test that needs another package's real code belongs to the shell (CLAUDE.md, stage-packages charter) |
| `support.*` helpers | 46 files use them | see below |

`tests/support` is what blocks the move, not the code. TESTISO (#524) forbids a member's test importing `support`, so the helpers the dash tests use must be reachable as declared packages:

- generic, used outside dash too: `case` (36 dash files), `tmpdir` (21), `paths` (26), `fakes`, `repos`, `runs`, `memstores`, `logs`: move to **`tltestkit`** (a prerequisite PR, not dash-specific; it also unblocks every later carve, which hit the same `support.case` wall in the artifacts spike).
- dash-only: `dashlogs` (21), `narrow` (17), `factory_index` (13), `dashes` (8), `dash_fixtures`, `look_world`: move with the tests into `packages/dash/tests/support` (the package's own helper folder, its own import root `dash_testsupport` or a conftest fixture module).
- `tests/support` helpers that the dash tests share with engine tests *and* build engine objects (e.g. `repos`, `runs`) need a kernel-only variant first; list them in the testkit PR.

## 5. Order of the S1b work (each one PR, after the hold on C-PIPELINE is lifted)

1. **TESTKIT-SUPPORT** (any time, no dash edit): move `case`, `tmpdir`, `paths` and the kernel-only helpers into `tltestkit`; `tests/support` re-exports nothing (callers updated). Collides with every test PR that imports `support.case` (very wide): do it as one mechanical sweep, last-minute rebase, or make `tests/support/case.py` a one-line re-export for one release and delete it next (a rule of CLAUDE.md says no compat shims: so sweep it in one PR instead).
2. **DASH-TESTSPLIT**: the 15 engine-touching dash tests leave `tests/dash` for `tests/launch` / `tests/e2e`; no code moves yet. Pure `git mv`.
3. **DASH-MOVE** (S1b proper): `git mv` source, tests and dash support; path literals (25 files); `packages/dash/pyproject.toml` (`taskloop-dash`, dependency `tlkernel`, dev group `pytest`, `tltestkit`; pythonpath for the vendor dir as in artifacts); `ruff.toml` extending the kernel's; `__main__.py` and `launch/dash.py` path fixes; `justfile` project-name lookup; `ruff.toml`/`pyrefly.toml`/`.importlinter` member lines (contract `dash-imports-contracts-only` stays, now also true as a member manifest); `Layout-allow` lines (move, node, contract). Acceptance (bead): dash tests run from `packages/dash/tests` alone; dash server starts (`tests/live` is human-started, so the check is `python3 -m taskloop_dash --help` under the isolated env plus the existing dash real tests).

## 6. Selection effect (honest)

As the bead's 2026-11-06 comment says, a path move changes selection little: a kernel change reaches dash today and still will, because dash declares `tlkernel`. What changes: dash tests run alone in 0.5 to a few seconds in their own environment; a dash-only edit selects the dash package plus the 3 launch tests instead of the dash files plus the importers the AST graph finds. Measure it in the DASH-MOVE PR with `dev/affected.py --changed` before and after, as workspace.md section 5 did.

## 7. Collisions

C-PIPELINE (`run/*`): none in dash; it touches `launch` only if it edits `dash_ports.py` (check at the time). pix-archvert-a and any open dash PR: rename-followed merges; the 25 path-literal files are the conflict surface. Step 1 (TESTKIT-SUPPORT) is the widest, so schedule it when few test PRs are open.
