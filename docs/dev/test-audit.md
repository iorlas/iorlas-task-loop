# Test audit: who needs a real git or a real process (PR2 of the test-speed plan)

Source: the touch run on idle pix (`docs/dev/test-strategy-data/` on `origin/testspeed-wip`, 4696 tests; 760 spawn). The class per
directory is judged from what the directory tests and from its `real_proc` / `real_git` reasons, not test by test; the numbers are counts of
spawning tests per directory in that run.

(a) CONTRACT = the subject is the port's real adapter (git, process, locks, bd): keep, once per port. (b) CONSUMER = the subject is
something else that happens to run on real git/processes: move onto gitsim / procsim / fake_clock and keep one wiring test.

## Ports and their contract suites (real adapter and fake run the SAME suite)

| port | suite | real adapter | fake | status |
|---|---|---|---|---|
| Git / SlotGit | `tests/ports/git_contract*.py` | `ports/real/test_git.py` (RealGit) | `ports/test_git.py` (gitsim) | both, no drift |
| Checks | `ports/test_checks.py` | ArgvChecks | FakeChecks | both |
| Beads | `ports/beads_contract.py` | `adapters/test_bd.py` | `support/fake_beads.py` | both |
| Delegate | `ports/delegate_contract.py` | delegate.api | fake_delegate | both |
| Clock | `ports/test_clock.py` (new in this PR) | SystemClock | FakeClock | both (was NO suite) |
| Spawner / Sh / procsim | none | `adapters/spawner.py`, `procs.py` | `support/procsim.py` | **gap**: procsim has only its own guard tests (`rules/test_procsim.py`); a Spawner contract is the next piece |

## Spawning tests by directory (760)

| dir | real/ | outside real/ | class | verdict |
|---|---|---|---|---|
| ports | 64 | 5 | (a) git / checks contracts | keep |
| adapters | 72 | 1 | (a) RealGit, bd, spawner, procs adapters | keep |
| stores | 0 | 2 | (a) locks across real processes | keep (marks stay: kernel flock is the subject) |
| checks | 44 | 2 | (a) resources/flock/lease | keep |
| hook | 27 | 0 | (a) the plain-python3 hook in git's path | keep (real by design) |
| loop | 123 | 0 | (b) consumer of Git (queue, fetch, base rule) | switch to gitsim, one wiring test: PR2b |
| slots | 56 | 0 | (b) consumer of SlotGit | PR2b |
| doctor | 28 | 0 | (b) | PR2b |
| prune | 25 | 0 | (b) | PR2b |
| report | 23 | 0 | (b) | PR2b |
| cli | 16 | 0 | (b), a few are the tl entry (wiring) | PR2b |
| release | 11 | 0 | (b) | PR2b |
| land | 18 | 0 (was 5) | mixed: signal/child-tree tests are (a)-like process subjects | the 5 declared-logic spawners moved to `land/real/test_engine_signals.py` (this PR); real_git cells stay |
| run | 10 | 0 | process subject (kill trees, engine child) | already in real/ |
| rules | 13 | 2 | gate rules against a real repo | keep, PR5 |
| e2e | 29 | 0 | whole flows | keep (cap 10 is a target, not met) |
| delegate | 0 | **207** | the delegate CLI/route.py as a child process is the subject: (a) of the CLI, but 33 files mix pure and spawn tests and import each other by flat name and `parents[2]` | NOT moved: needs per-test split, own PR, `just test-delegate` run |

Declared-logic spawners (222 at the start): delegate 207, land 5, stores 2, checks 2, ports 5 (the `@real_proc` classes whose contract
is the point), adapters 1: after this PR land is 0 (baseline lowered), the rest are (a) or the delegate block.

## What this PR changed
- 5 land tests (SIGTERM during Popen / the gate / the land command / the push retry) moved from `tests/land/test_engine_land_1.py` to `tests/land/real/test_engine_signals.py` (a real child tree is the subject); land baseline 6 -> 0.
- `tests/ports/test_clock.py`: the Clock contract on SystemClock and FakeClock.

## Not done, not measured
- The (b) switch for loop, slots, doctor, prune, report, cli, release (about 280 tests) and the delegate split: each needs a read of what the test asserts; no CPU gain claimed yet. Moving a test between folders changes no CPU.
- The class column is judged by directory, not test by test.

## Real sleeps (PR3 census)
Of the 93 tests that sleep over 0.5 s (147 s of `time.sleep`, idle pix), about 80 are in `tests/delegate` (watchdog, kill-tree and grace tests:
the wait IS the subject, with a real child process, so a fake clock needs a clock seam in `src/delegate`), and only run when a change touches
delegate. Outside delegate the rest are thread race windows of 10-300 ms (asks/rmw_store, checks/resources, slots, write_idle) and real-process
waits in `real/` (slots, loop hold e2e, adapters). The one avoidable wait outside them, `tests/adapters/test_links.py` (3.0 s, a sleep standing
in for a hung link check), now waits on an Event (0.5 s). The clock seam for delegate's watchdog landed after this census (tl-wnup.6, #69).

## sqlite template (PR4): refuted by a profile, not built
The plan said 1241 tests open a real sqlite store (48 CPU s, 25%) and a seeded copy would make a store a file copy. Measured on pix:
- a fresh `factorydb.open_rw` costs 1.6 ms; copying a seeded file and opening it costs 4.2 ms (WAL side files): the template is slower.
- cProfile of all of `tests/run` outside real/ (534 tests, 49 s): every sqlite call together is 0.87 s (1.7%). The 25% in the touch table counts
  every test that opens a store, not what the store costs: those tests are engine tests, whose time is the engine.
- Where the time goes instead (same profile): 320k file opens (254k `Path.read_text`; gitsim's `Repo.ref` alone 100k, `common_of` 53k), 3.7M
  `os.environ` lookups (3.4 s cumulative, 7%: `git_porcelain.real_env.base` rebuilds the child environment on every git call, 5 s cumulative;
  that module is vendored, so the fix belongs in the shelf), and pathlib string building (5 s).
- Next real levers: cache or hoist `real_env.base()` (shelf), keep gitsim refs in memory (the engine's ref memo needs a new inode per write:
  tests/support/gitsim/model.py `atomic_write`), and fewer `Path` objects per git question.

## Handoff (testspeed session, 2026-11-06)
Done: layers and guards (#59), contract-then-consumers audit and Clock contract (#62), sleep census (#67), in-process selection (#70), sqlite template refuted, ambient env and vendored stream_proc/git_porcelain fixes (#75, #100), slowest-tests table (#80), inner loop (#81), ratchets judged on the change, no baseline files (#116), scratch root off ~/.config (#115). Suite: 4192 tests in 68 s wall on an idle 4-worker host (was 189 s loaded).
Left: (1) tl-wnup.4, 255 `TemporaryDirectory` test sites to the `workdir` fixture: not worth the churn, #116 stops growth. (2) tl-wnup.2/.3, delegate spawners into real/ and a Spawner/procsim contract: pix-delegate. (3) land-stack phase timing in the run manifest (fetch, worktree, gate, push, judge): invisible today, pix-engine. (4) Tail by size: rules whole-tree walkers sum ~12 s CPU, `dev/affected.Repo` build is 3.1 s per worker; an on-disk AST cache was judged not worth it.
