# Stage test hosts: getting stage tests off EngineTest

Status: design, 2026-11-06 (ARCHVERT-FAKES, follows docs/design/architecture-vertical.md section 10). No code yet.

## Problem

`tests/support/engine_case.EngineTest` builds a whole `Engine` (`builders.make_engine` -> `app/run/engine.py`) and 109 test files subclass or use it: run 32, checks 25, land 16, review 7, write 6, plan 5, others 18. The forward import closure of `app/run/engine.py` is **465 src files in 12 stages**, so a test that only exercises the check runner is selected by an edit anywhere in those 465 files, and the stage cannot be tested, moved or owned alone. Section 10 measured it: directory moves and contract splits do not cut this; the harness does.

## Measured: what each stage needs, if it were tested on its own seam

Forward closure of the stage's own `app/<slice>/*.py` (src files, stages reached besides kernel):

| stage | src files | stages | engine today |
|---|---|---|---|
| checks | 112 | gate, store | 465 / 12 |
| review | 68 | asks, delegate-glue, gate, work | 465 / 12 |
| write | 128 | asks, delegate-glue, gate, store, work | 465 / 12 |
| plan | 158 | + beads | 465 / 12 |
| land | 247 | + delegate, land, slots | 465 / 12 |

`app/run/stage_checks.py` alone reaches 89 files / 6 stages; `app/checks/runner.py` 109 files / 2 stages.

## The seam already exists

The checks stage declares what it needs of its caller: `app/checks/host.py::CheckHost` (a Protocol: bead, wt, run_id, run_dir, home, cfg, log, steps, checklog, stores, spawner, env, sh, checkout, tree_writer, git, waits, warn, halt_point, detail) and `CleanHost` already wraps one. `Checker.run(...)` takes it. `Engine` is one implementation. The tests that matter (`eng.run_checks`, `eng.cfg`, `eng.git`, `eng.wt`, `eng.bead_env`, `eng.log_path`) use a small part of it.

Land has `lander_host.py` and `recheck.RecheckStageChecks`; review and write call the engine through `e.*` attribute access (`Any`-typed hosts), which is the real obstacle there: no Protocol yet.

## Design

1. **`tests/support/hosts/<stage>.py` per stage**, one plain class implementing that stage's host Protocol from real small parts (RunLog, step book, stores on the `workdir`, `real_spawner`/procsim, gitsim) and nothing from `app/run`. It lives in the stage's tests, imports only the stage's own package and the store layer.
2. **Contract, then consumers** (existing rule): one contract test per host Protocol runs against `Engine` (real layer) and the stage host (unit), so the fake cannot drift. A stage's tests use only the stage host; one wiring test per stage on the real `Engine` stays.
3. **Order by gain/cost**: checks first (Protocol exists, 25 test files, closure 465 -> ~112), then review (68, needs a `ReviewHost` Protocol), write, plan, land last (land closure includes delegate; depends on ISOLATION).
4. `EngineTest` shrinks to the e2e-ish flows in tests/run that really cross stages.

## Expected drop (honest)

An edit under `app/run`, `app/launch`, `app/loop`, `app/wire` (the shell, ~half of commits by `reach.py`) stops selecting the converted tests. Checks alone: 25 of 604 test files (4%) leave the shell's reverse closure; all five stages: ~60 files (10%). An edit inside a stage still selects its own tests: no loss. The gain is real but modest: the median commit (273 selected) falls to about 215-230 once all five are converted. It is the only lever left; the packages/ carve stays pointless until it is done.

## Pilot (first PR when approved)

`tests/support/hosts/checks.py` + a `CheckHost` contract test (Engine vs fake) + convert `tests/checks/test_check_quiet.py`, `test_check_trim.py`, `test_check_timeout_park.py`, `test_check_spawn.py` (the real-process ones, 4 files) and report `dev/reach.py` before/after. If the pilot cuts those four to ~112 src files and stays green, convert the other 21 checks files one PR each.

## Risks

- A fake host drifts from `Engine`: the contract test is the guard; without it do not start.
- `Any`-typed hosts in write/review need Protocols first (ruff/pyrefly: no new `Any`); that is the larger part of those two stages.
- Tests today also assert engine side effects (bd comments, closes) through `EngineTest.store`; those stay engine tests.

## Pilot result (checks, 4 test files)

`tests/support/check_host.py` (`FakeCheckHost`, `CheckHostCase`) and `tests/support/world.py` (`SlotWorld`: the temp dir, env and gitsim world that `EngineTest` used to build, now a base without the engine). Converted: `test_check_spawn`, `test_run_id`, `test_run_env`, `test_keyed_env`.

| | before | after |
|---|---|---|
| src files a converted test reaches | 488, 488, 488, 493 | 212, 144, 144, 156 |
| `engine.py` in the closure | yes | no |
| median tests selected per commit (`dev/reach.py`, 107 commits) | 287 | 285 |

The per-test closure falls by two thirds; the median selection barely moves because 4 of 617 tests is 0.6% and the contract test (`tests/checks/test_check_host_contract.py`) must itself reach the Engine. The fake uses the real `Shell`, `Steps`, `Checkout` and `Checker` (no re-implementation, so no drift there); it replaces the Engine's `Waits` with a recorder. The contract test compares results, process env, log row kinds and host facts of the fake and an Engine; four mutations of the fake (empty `bead_env`, a checklog on another log, a set `killed` flag, a wrong `MARKERS`) each fail it.
