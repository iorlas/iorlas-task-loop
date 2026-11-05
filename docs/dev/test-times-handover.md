# Test-speed work: handover to the pix run

Branch `testspeed-wip`. Results so far are in `docs/dev/test-times.md` (ranking, per-dir totals, levers, telemetry design); raw data in `docs/dev/test-times-data/`. Nothing here is a PR.

## The plugin
- `dev/testtimes.py`: pytest plugin, loaded only by `-p testtimes` with `PYTHONPATH=dev`. Records per test and phase (setup/call/teardown) CPU s (user+sys of the process plus waited-for children) and wall s, and per-fixture own setup time (nested fixtures subtracted). Writes JSON to `$TL_TEST_TIMES`, rewritten every 25 tests (a killed run keeps its data). Overhead measured ~0 CPU s.
- `dev/testtimes_report.py <json> [--tests 50] [--fixtures 20]`: top tests, top fixtures, per-directory totals.

## How to run (the whole tree, which the Mac could not finish)
```bash
TL_DELEGATE_TESTS=1 TL_TEST_TIMES=/tmp/full.json PYTHONPATH=dev uv run pytest -p testtimes tests -m "not live" -q
python3 dev/testtimes_report.py /tmp/full.json
```
- `-m "not live"` overrides pyproject's `-m 'not real and not e2e'`, so real and e2e tests run. `TL_DELEGATE_TESTS=1` collects tests/delegate. No xdist (one worker): CPU numbers stay comparable.
- On the Mac a full tree start made 6% in 16 min (load ~80, `nice -n 10`), so it was stopped; the 5-dir run took 60 min wall for 307 CPU s. Wall was 12x CPU. On an idle host expect minutes.
- macOS-only assumptions in the repo (Mac paths, `proc_pid_rusage` in tests/support/work.py falls back to CPU time elsewhere) may fail tests on NixOS: record failures, do not chase them.

## Measured so far (Mac, 5 dirs, 2214 tests, 307 CPU s)
| dir | tests | CPU s | share |
|---|---|---|---|
| land | 401 | 125.5 | 40.9% |
| run | 551 | 70.4 | 22.9% |
| delegate | 589 | 68.7 | 22.4% |
| checks | 318 | 36.1 | 11.8% |
| dash | 355 | 6.3 | 2.0% |

Median test 0.017 CPU s; worst 9.7 s. 12 of the top 13 are `tests/land/real` (fresh bare remote + clone + worktree + engine per test, 4.8-9.7 s each, 74 s together). 11 failures in `checks/real` (pass_files x5, tl_check x2, check_hooks, checks_speed, gateplan, lanes_real): not investigated. Not measured: adapters, loop, contracts, domain, asks, rules, slots, ports, plan, review, wire, cli, prune, hook, report, launch, track, release, doctor, write, e2e, artifacts, look, fixtures.

## Static suspects
- 112 "every_/all_" tests: a loop of full runs inside one test (e.g. delegate `test_run_stops::test_every_answer_carries_the_stop_facts`: 7 runs; `test_classify::test_every_fixture_row...` 36.7 s wall).
- Not pytest-native: 246 `setup_method`/`setUp`, 282 `subTest`/`subtests`, 14 `parametrize`. Per-test xunit setup of RunCommand/RunStops/RunVendors ~57 ms x ~100 uses.
- `@real_proc` tests living in `tests/delegate` and `tests/run` (not under `real/`) with `LIMIT_S = 60` per module.
- sleeps: delegate/test_delegate_kill_tree (10), checks/test_resources (5), adapters/real/test_kill_tree (4), spawner tests (3 each); real sockets in dash and delegate/test_net.
- Subprocess spawns of tl/uv: wire/real/test_shim_resolve (9), release/test_manifest (9), land/test_race_invariants (6).
- No hypothesis tests exist.
- Kind counts per dir: `grep -E '^\s*def test_'`: delegate 589, run 551, land 382, dash 329, checks 310, loop 246 (123 real), adapters 236 (73 real), contracts 230, domain 165, asks 152, rules 151, slots 149 (56 real).

## Still to do on pix
1. Full-tree run as above (once), report top 50 / 20 fixtures / per-dir totals.
2. Fill the Top-50 table's "why slow" for the new entries (the existing column was inferred from names and a read of the tests, not profiled).
3. Root-cause the 11 `checks/real` failures (Haiku read-only first).
4. Telemetry design lives in `test-times.md` (always-on plugin in dev/runtests.py, per-run JSON under the tl config dir, 5 s CPU budget with capped warnings, warn-then-fail, `slow(reason=)` marker, .NET via TRX). Design only; Denis files the bead.
