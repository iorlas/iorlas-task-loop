# Review, lens 7: delivery and operations (OPS-FABLE)

Read 2026-11-02. Code opened: the main checkout `/home/iorlas/Workspaces/iorlas-task-loop` at 0.23.293 (`tl/` = `src/taskloop/`), the C4
worktree `/home/iorlas/Workspaces/wt/C4` at 0.23.299 where a cited file differs between the two (prefix `C4:`; `diff` showed
`release/suite.py`, `tests/conftest.py`, `loop/loop.py`, `checks/resources.py`, `run/reload.py` and `contracts/config.py`'s cited lines
identical in both), delegate in `/home/iorlas/Workspaces/wt/UNITYD` (`dg:` = `src/delegate/`). Numbers come from `wc`, `ls | wc`, `du`
and `git log` on this devbox; nothing was run. The installed plugin on this box is 0.23.301 (`~/.claude/plugins/installed_plugins.json`),
eight releases past the main checkout.

Operational facts measured here, because the rest leans on them:

- **Release cadence:** 378 release commits since 2026-10-18 (`git log` subjects `N.N.N:`); by day, Oct 28 to Nov 1: 59, 40, 69, 33, 22
  = 223 releases in five days, about one every 32 minutes around the clock.
- **Red-gate rate:** `~/.config/task-loop/releases/` holds 356 `suite-*.log` files (only a red suite writes one: `tl/app/release/suite.py:45-48`),
  314 distinct timestamps, 218 MB, written Oct 27 to Nov 1 (119, 55, 87, 46, 45 per day). So in the same five days the release suite went
  red about 314 times against 223 green releases: the gate is red more often than green.
- **Suite cost on this box:** the last red logs say `3185 passed, 20 skipped ... in 59.90s` for the parallel run and `8 passed ... in 3.72s`
  for the serial group: about 3205 tests, one minute, eight xdist workers. The justfile calls it "the 35-minute suite" (`justfile:21`); that
  is the Mac's number.
- **Plugin cache:** `~/.claude/plugins/cache/iorlas-marketplace/iorlas-task-loop/` has 224 version dirs, 1.8 GB; delegate 21 dirs, 42 MB.
  Nothing in either app deletes one (`tl/app/release/catalog.py:19-27` reads them; `tl/app/loop/versions.py:85-89` and
  `tl/app/release/pins.py:35-63` iterate them).
- **Test kinds:** 415 `def test_` under `tests/*/real/`, 25 in `tests/e2e/`, 7 in `tests/live/` (explicit-only, `tests/conftest.py:102-108`);
  `dev/race.py` is "NOT in the gate or the suite" (`dev/race.py:7-9`).

---

## Top 10 by importance

1. **OPS-FABLE-22** Nothing on either machine knows the load: lanes, check lanes, repo test runners and delegate slots multiply with no
   machine-wide CPU budget; the Mac at load 280 is the design working as written.
2. **OPS-FABLE-01** Every change runs the full suite three times (engine gate, release, CI) and the release's suite cache can never hit on a
   fresh release because the version bump changes the tree it is keyed on.
3. **OPS-FABLE-03** The suite's wall-clock limits per test turn host load into red releases; the knob to scale them exists and nobody sets it.
4. **OPS-FABLE-17** The loop ends itself with exit 0 (two no-verdict runs, low disk, storm, `--until`) and nothing restarts it or tells anyone;
   the "no OS service" rule is why Trust Night can die at 01:00 unnoticed.
5. **OPS-FABLE-31** 24 releases a day is the root of the hop problem (Z05/Z21): batch releases, and most of the hop machinery stops mattering.
6. **OPS-FABLE-18** There is no notification path in the code at all; asks, deaths and releases wait for the owner to open a dashboard.
7. **OPS-FABLE-14** A bead has no wall cap: the budget counts spent time only, and a resource lease wait polls forever.
8. **OPS-FABLE-07 / 06** Disk grows without a janitor on the machine that releases: 1.8 GB of plugin versions, 218 MB of red-suite logs in
   five days, pruned only when a loop starts on that machine.
9. **OPS-FABLE-20** The Mac's version is decided by whoever runs `claude plugin update` there; the owner already has `tl pin`, so the Night
   should start pinned.
10. **OPS-FABLE-19** Two machines, two dashboards, no view of the other: version, load, disk and lanes of the Mac are invisible from the devbox.

---

## Idea ledger

| id | idea | evidence (file:line) | kind | sev | effort | verdict | reason |
|---|---|---|---|---|---|---|---|
| OPS-FABLE-01 | The suite runs three times per change: the engine's gate check on task-loop beads is `python3 dev/suite-docker.py` (`.task-loop.json` of the repo, `run: gate`); the release runs it again; CI runs it a third time. The release's SuiteCache is keyed on `HEAD^{tree}` after the bump commit that rewrites `plugin.json` and `MANIFEST.sha256`, so the tree is always new and the cache hits only on a retry of the same release | `tl/app/release/flow.py:50-61`, `tl/app/release/suite.py:242-253`, `tl/app/release/cache.py:19-26`, `.github/workflows/test.yml:25-26` | duplicated work; wrong cache key | P1 | S | ✅ | 537 suite runs in five days for 223 releases; a bead's green gate on the same source tree is thrown away |
| OPS-FABLE-02 | The release gate is red more often than green (314 red runs vs 223 releases, five days); nothing records why beyond a log file; `releases/last.json` keeps only the last result | counts above; `tl/app/release/flow.py:139-147` | missing observability | P1 | M | ❓ | What would test it: a `releases/ledger.jsonl` row per attempt with the first failing test; my manual tally of the 356 logs says: real-process slot/loop tests, goldens, ratchets, time limits (OPS-FABLE-03/04/13) |
| OPS-FABLE-03 | Per-test wall-clock limits (`logic` 2 s, `real` 15 s) fail a passing test when the host is loaded; the release runs while Codex workers and lanes run on the same box; `TL\_TIME\_SCALE` exists and no caller sets it. The red logs contain about 20 "took X s, over its limit" failures in five days | `tests/conftest.py:55-58`, `:94-99`; grep of `releases/suite-*.log` | flake generator | P1 | S | ✅ | A limit meant to catch slow tests is firing on slow hosts |
| OPS-FABLE-04 | The most frequent red tests are real-process ones with the 15 s limit: `tests/slots/real/test_slots.py` (7-12 reds each), `tests/loop/real/test_loop_more.py`, `tests/loop/real/test_hold_e2e.py`, `tests/slots/real/test_areas.py`; 415 real tests run under the same xdist spread as the logic ones | log tally; `tests/conftest.py:63-74` | test design vs host | P2 | M | ✅ | They spawn real `tl` processes (uv start, 200-module import, `tests/conftest.py:34-42`) under eight workers on a busy box |
| OPS-FABLE-05 | A red suite writes its log twice on a host without docker: `dev/suite.py` (inside `suite-docker.py`'s host fallback) calls `red()` and then `container_suite` calls `red()` on the same output; 42 of 356 log files are such doubles (same second, two pids) | `tl/app/release/suite.py:45-48`, `:201`, `:205-215`; `dev/suite-docker.py:54-64`, `:73-76` | duplicated effect | P3 | S | ✅ | Doubles the 218 MB and confuses the tally |
| OPS-FABLE-06 | `releases/suite-*.log` are swept only by `tl prune`, which runs at loop start, with a floor of 30 days; the devbox releases and rarely loops, so 218 MB in five days grows without bound here | `tl/app/loop/loop.py:118-123`, `tl/app/prune/runs.py:48-50`, `:61`, `tl/contracts/runlife.py:18` | growth with no janitor on the writer | P2 | S | ✅ | The writer should sweep its own output |
| OPS-FABLE-07 | 224 plugin version dirs, 1.8 GB, no GC: Claude Code installs a new dir per release and nothing in task-loop removes one; `versions.target` scans them on every move check and `install_key` stats every `src/*.py` of each refused version | `tl/app/release/catalog.py:19-27`, `tl/app/loop/versions.py:31-42`, `:57-62`, `:85-89` | growth; cost per pass | P2 | M | ✅ | A live engine may run from an old dir (`dev/release.py:26`), so the sweep must honour live `code_dir`s; whether Claude Code has its own GC is (unverified) |
| OPS-FABLE-08 | On macOS `host_available_mb` falls to `SC_AVPHYS_PAGES` (free pages), which macOS keeps small; `host_workers = min(cpu, mem // 2048)` then gives one worker, and `refuse_if_short` aborts the release when free pages are under 2 GB, which a Mac with four lanes and Unity will be | `tl/app/release/suite.py:72-84`, `:87-91`, `:180-185` | platform mis-measure | P2 | S | ❓ | What would test it: on the Mac, print `available_mb()` and `host_workers()` from that module during a Night; if 1, the "35-minute suite" is partly the worker count, not only the endpoint scanner (`dev/suite-docker.py:5-8`) |
| OPS-FABLE-09 | `RUN_WALL_S = 1200` kills one pytest run after 20 minutes; the Mac's suite is documented at 35 minutes; when docker is down on the Mac the fallback runs on the host and every Mac release is red by timeout | `tl/app/release/suite.py:28`, `:128-132`; `justfile:21`; `dev/suite-docker.py:73-76` | contradiction between constants | P2 | S | ❓ | What would test it: one Mac release with `TASK_LOOP_SUITE_HOST=1`; if red at 1200 s, raise the wall or fix OPS-FABLE-08 |
| OPS-FABLE-10 | The suite cache command string says "container suite" whenever `TASK_LOOP_SUITE_HOST` is unset, also on the devbox where `suite-docker.py` always falls back to the host; the recorded green names a runner that did not run | `tl/app/release/suite.py:246`; `dev/suite-docker.py:73-76` | wrong key text | P3 | S | ✅ | Harmless today (per-machine cache), wrong the day two runners differ |
| OPS-FABLE-11 | CI runs the whole suite on every push and no release, hook or dashboard reads the result; it is the third run per change with no reader | `.github/workflows/test.yml:14-26` | spend with no consumer | P3 | S | ✅ | Keep `check` (lint, types, rules), delete the `unit` job, or make the release consult it: one reader or none |
| OPS-FABLE-12 | The concurrency invariants (two loops, two releases, slot line, land lock) are checked end to end only by `dev/race.py` and `tests/live`, which no gate runs; the 24-a-day releases rely on them | `dev/race.py:7-9`, `:19-25`; `tests/conftest.py:102-108`; `tests/live/conftest.py:1-6` | untested path | P2 | S | ✅ | A GitHub Actions `schedule` job for `just test-live` and `race.py --seeds 1-2` (no docker needed on ubuntu for most), red filed as a bead |
| OPS-FABLE-13 | Goldens and ratchets go red in the release suite ten times each (`tests/contracts/test_wire.py::Golden`, `::RoundTrip`, `tests/rules/test_type_ratchet.py`): `just rules` now runs the ratchets, not `test_wire.py`, so a writer learns of a missing sample only from the release | `justfile:41-47`; log tally | gate ordering | P3 | S | ✅ | Add `tests/contracts/test_wire.py` to the `rules` recipe: seconds, and it is exactly what Codex breaks |
| OPS-FABLE-14 | No wall cap on a bead: `budget_min` counts spent time; resource waits are "outside the run's budget"; `_take` polls for a lease forever; per-step caps are 45/120/60/90/10 min and stages repeat; delegate's `--timeout` is "none by default" | `tl/contracts/config.py:202`, `:210-223`; `tl/app/checks/resources.py:4-5`, `:84-107`; `dg:cli/parser.py:90` | missing limit | P2 | S | ✅ | A slot and a Unity lease can be held for a whole night by one bead that is "within budget" |
| OPS-FABLE-15 | The engine's suite-shaped check and the release suite share `suite-host.lock`; a check queued on it spends its `check_wall_min` (60 min) waiting, then is recorded as a stopped check, not a queue | `tl/app/release/suite.py:117-119`, `:175`; `tl/contracts/config.py:221` | wait counted as spent | P3 | S | ✅ | Report the lock wait as a `WaitWhat`, as resource leases do |
| OPS-FABLE-16 | `caffeinate -i -w <pid of lane 1>`: agrees with Z22, with two additions: `-i` stops idle sleep only (a closed lid or a scheduled sleep still sleeps; `-s` is the flag on AC power), and the dashboard server is never covered | `tl/adapters/factory.py:6-8`; `C4:tl/app/launch/factory.py:116-119`; `README.md:73` | platform gap | P2 | S | ❓ | What would test it: `pmset -g assertions` and `pmset -g log | grep Sleep` after a Night; low confidence on which Mac model this is |
| OPS-FABLE-17 | The loop ends with exit 0 and no restart on: stop, `--until`, `--max-beads`, low disk (`min_free_gb` 5), two no-verdict runs in a row, storm (exit 2); `tl factory start` "installs no OS service and does not restart after reboot"; a rules test forbids OS services | `tl/app/loop/loop.py:160-185`; `tl/contracts/config.py:145`, `:154`; `tl/app/loop/settle.py:116`; `README.md:73`; `tests/rules/test_no_os_services.py` (name only) | no supervisor, no alert | P1 | M | ✅ | Within the rule: `tl factory start` leaves a tiny supervisor process (it already waits for the child's state, `C4:tl/app/launch/factory.py:95-119`) that restarts a lane N times with backoff and writes the reason; the OS-service rule itself is an owner decision I would reverse for the Mac |
| OPS-FABLE-18 | No notification channel exists: grep of `src/` for notify, ntfy, osascript, webhook finds only the dashboard's JS and a comment. An ask, a dead lane, a red release or a landed bead reach the owner only when he opens the dashboard | grep; `tl/app/launch/loop.py:154-161` (chores: lanes, asks, reflect) | missing seam | P2 | S | ✅ | One argv in `host.json` (`notify: ["ntfy", ...]`), run like a check (no shell), on ask raised, loop ended, release done |
| OPS-FABLE-19 | Two machines, two dashboards: `World.host` and `version` are the dashboard's own; a lane's version is in its LoopState only; no page shows the other machine's version, load, free disk or lanes | `src/taskloop_dash/readers/world.py:145`; `tl/app/launch/loop.py:250-252` | missing cross-machine view | P2 | M | ✅ | The dashboard fetches `/api/snapshot` of peers listed in `host.json` over the tailnet and draws a hosts strip (version, pinned, lanes, free GB); the medium already exists (both bind the tailnet) |
| OPS-FABLE-20 | The Mac moves only when `installed_plugins.json` changes there; the release's `claude plugin update` runs on the releasing machine only; if Claude Code refreshes marketplace plugins at session start (unverified), the Mac hops when a session happens to open mid-Night. `tl pin` already exists and would make the Night deterministic | `tl/app/release/publish.py:73-95`; `tl/app/loop/versions.py:77-83`; `tl/app/release/pins.py:35-63`; `skills/task-loop/tl.py:49-50` | control the owner has and does not use | P2 | S | ✅ | Agrees with Z21; the fix needs no code: `tl pin <v>` at Night start, `tl pin --clear` at the end, and `tl status` says pinned |
| OPS-FABLE-21 | At 24 releases a day a three-hour bead meets about three safe-point hops; `reload_fallback` is 120 s: a run that dies 121 s after the move is not attributed to the move and the version is never marked bad | `tl/app/run/reload.py:68-88`; `tl/contracts/config.py:152`; `tl/app/loop/run.py:79-88` | fragile attribution | P2 | S | ✅ | Agrees with Z05/R2; until then, the fallback window should be "until the next step boundary", not a clock |
| OPS-FABLE-22 | No load awareness: `getloadavg` appears nowhere; `cpu_count` only in the release suite. Concurrency compounds: N factory lanes (default `slots.count`) x check lanes as threads x the repo's own `-n auto` test runners x delegate `max_parallel` 4 per lane x Unity. The only limiter is `engine.resources` leases per named tool | grep of `src/`; `tl/app/release/suite.py:87-91`; `C4:tl/cli/factory.py:29`; `tl/app/checks/lanes.py:42-49`; `dg:skills/delegate/routing.json:30`; `tl/app/checks/resources.py:84-107` | missing seam | P1 | M | ✅ | Load 280 is four lanes each running a parallel test runner at once; a per-tool lease does not bound cores |
| OPS-FABLE-23 | Per-worker `RLIMIT_AS` and `PR_SET_PDEATHSIG` are Linux only: on the Mac a runaway test has no memory cap and an orphaned xdist worker outlives a killed controller | `tests/conftest.py:123-130`, `:146-149` | platform gap | P3 | S | ❓ | What would test it: kill a running controller on the Mac and `pgrep -f tl-worker` |
| OPS-FABLE-24 | SessionStart and PreCompact hooks are `uv run --quiet --script` with a 20 s timeout: a cold uv cache without network (home ISP down at night) times out, so no shim and no githooks are written for that session, and the pre-push then runs whatever install wrote the shim last (Z14) | `hooks/hooks.json:6`, `:12`; `tl/adapters/childenv.py:122-125` (no `--offline`) | fragile bootstrap | P3 | S | ❓ | What would test it: `uv cache clean` then start a session with the network off |
| OPS-FABLE-25 | A broken `dev/release.py` or `src/` on origin/main blocks every release including its own fix: the launcher execs the clone's origin/main release code before `--from-branch` is replayed; the escape hatch `TL_RELEASE_REEXEC=1` is undocumented in the script's own docstring | `tl/app/release/selfupdate.py:20-27`, `:30-37`; `dev/release.py:11-14` | undocumented recovery | P3 | S | ✅ | One sentence in the docstring and in `docs/cutover.md` |
| OPS-FABLE-26 | Every release and marketplace commit carries a hard-coded `Co-Authored-By: Claude Opus 5.5` trailer whoever released (Codex writes, other models orchestrate) | `tl/app/release/publish.py:15` | provenance noise | P3 | S | ✅ | Contrarian and cosmetic: the trailer is a lie 223 times in five days; drop it or take it from the session |
| OPS-FABLE-27 | The marketplace repo is the release ledger: one commit and one tag per release (223 in five days), and `require_clean_main` demands a clean `~/Workspaces/iorlas-marketplace` on every releasing machine | `tl/app/release/publish.py:18-42`, `:52-66`; `tl/app/release/flow.py:41-47`, `:162` | release coupling | P3 | S | ❓ | Low confidence it hurts; what would test it: count how often a release aborted on a dirty marketplace checkout (the logs would say "is dirty") |
| OPS-FABLE-28 | `tl doctor` has no operations checks: git worktree config, globs and the profile only; nothing reports disk, load, plugin cache size, releases-behind per machine, or the vendor transcript dirs (`~/.codex/sessions`, `~/.claude/projects`) that nobody prunes | `tl/app/wire/doctor.py:1-40`; `tl/app/release/catalog.py:45-48` | missing observability | P3 | S | ✅ | The data is all local and cheap |
| OPS-FABLE-29 | `loop.keep_days` defaults to 14 but run data is kept `max(configured, 30)`; the 14 applies to merged worktrees under `build_dir` only: one key, two meanings, the default dead for one of them | `tl/contracts/config.py:153`; `tl/app/prune/runs.py:48-50`; `tl/contracts/runlife.py:18` | doc-code mismatch | P3 | S | ✅ | Two keys, or one floor |
| OPS-FABLE-30 | The dashboard shows 7 days (`RETAIN`) while run data is kept 30: 23 days of evidence nobody can see except by `ls` | `tl/contracts/runlife.py:17-18`; `src/taskloop_dash/readers/world.py:99` | wasted retention | P3 | S | ❓ | Contrarian: either keep 7 (and cut disk) or show 30; what would test it: whether `tl report --since 30d` is ever used |
| OPS-FABLE-31 | Release batching: land to main continuously (the engine already does), but bump, tag, marketplace and install hourly or on demand from a green main. Cuts suite runs from 3 per change to about 1 per batch, hops from 24 a day to a handful, marketplace commits likewise | counts above; `tl/app/release/flow.py:95-124` | owner decision | P2 | M | ❓ | Still "only through `dev/release.py`"; what would test it: a week with `--batch` and the hop and red-gate counts before and after |
| OPS-FABLE-32 | Do not spend effort speeding the suite on Linux: 3205 tests in 64 s is already fine; the cost is the count of runs (OPS-FABLE-01) and the red rate (02), and the Mac's 35 minutes is a platform artefact (08/09, endpoint scanner) | suite logs; `dev/suite-docker.py:5-8` | refuse a direction | P3 | - | ❌ | Refuse "shrink tests for time" as a goal; volume-tests work should shrink lines, not seconds |
| OPS-FABLE-33 | Evidence cap 200 MB per run x 30 days x N beads a night: nothing reports `runs/` size or days until `min_free_gb`; the low-disk end then comes as a surprise exit 0 | `tl/contracts/config.py:228`, `:154`; `tl/app/loop/loop.py:174-179` | missing observability | P3 | S | ✅ | `tl status` prints `runs/` size and the days left at the last week's rate |
| OPS-FABLE-34 | The owner cannot start or stop the factory from the phone: the dashboard's nine verbs act on runs and asks (per c4-task-loop; `dash/api/writes.py` not opened here), `tl factory` is SSH only | `skills/task-loop/tl.py:46-52` | missing control | P2 | S | ✅ | Add `factory stop` and `factory start` as owner verbs that spawn `tl` (Z08's way); the hop and the Night both need a remote stop |
| OPS-FABLE-35 | The loop's run-log stems use local time (`%Y%m%d-%H%M%S`, `time.localtime`) and the log is opened in append mode "so a rerun of the same stem never cuts a log": on the DST repeat hour two runs share a stem and interleave; events use epoch, logs do not | `tl/app/loop/run.py:64`, `:70` | time handling | P3 | S | ❓ | Low confidence it has bitten; what would test it: grep stems of the night of the last DST change on the Mac |
| OPS-FABLE-36 | The main checkout on the devbox lags the release by eight versions (0.23.293 vs 0.23.301) because the release "never touches" it; reviewers and sessions read three different versions on one box (checkout, C4 worktree, installed) | `dev/release.py:14-15`; `.claude-plugin/plugin.json` here vs `installed_plugins.json` | operations of review | P3 | S | ❓ | Contrarian: let the release fast-forward a clean main checkout; what would test it: how often `git status` of the main checkout is clean on main at release time |
| OPS-FABLE-37 | Delegate's live file is capped at 20 MB and then "stops growing; the call goes on", its history rotates at 1 MB keeping 14 days, agent-runs deletes anyone's files after 7 days, the codex overlay is never cleaned: four growth rules, none visible in a status | `dg:contracts/live.py:128`; `dg:contracts/stores.py:23`, `:113-118`; `dg:adapters/agent_runs.py:38-44` | scattered retention | P3 | S | ✅ | One retention table in `status --json` (bytes per store, oldest row); agrees with Z10 on deleting agent-runs |

### First step of each ✅ idea

- **01** Key `SuiteCache` on the hash of `git ls-tree -r HEAD` with `.claude-plugin/plugin.json` and `MANIFEST.sha256` removed, and let the
  engine's gate (`python3 dev/suite-docker.py`) record the same key, so a bead's green is the release's green.
- **03** In `tl/app/release/suite.py:isolated_env`, set `TL\_TIME\_SCALE` to `max(1, os.getloadavg()[0] / os.cpu_count())` and print it.
- **04** Put the ten most-red real tests in one xdist group (`pytest.mark.xdist_group`) with `--dist loadgroup` and a 60 s limit of their own.
- **05** Make `container_suite` not call `red()` when `suite-docker.py` already printed a saved-log line; return the path instead.
- **06** At the end of `flow.main`, keep the newest 20 `suite-*.log` and delete the rest (same `KEEP` as the green cache).
- **07** `tl prune` removes plugin cache dirs that are not installed, not pinned, not a `code_dir` of a live LoopState or manifest, and older than
  `keep_days`, after a dry-run week that only prints what it would remove.
- **10** Let `container_suite` return where it ran (parse the wrapper's one warning line or exit code) and put that word in `command`.
- **11** Delete the `unit` job from `test.yml`; keep `check`.
- **12** Add a nightly `schedule` job that runs `just test-live` and `uv run --script dev/race.py --seeds 1-2`; a red files a bead with the log.
- **13** Append `tests/contracts/test_wire.py` to the pytest line of the `rules` recipe.
- **14** Add `engine.wall_cap_min` (default 360) checked at every step boundary and lease poll; past it the run parks as `wall_cap` with the
  work kept (CRASHPARK's path).
- **15** Wrap the `suite-host.lock` wait in the engine's check with a `WaitWhat.SUITE_LOCK` start/add so it is waited, not spent.
- **17** `tl factory start` keeps a supervisor alive that re-spawns a lane that exited for `fails_to_stop`, `storm` or a crash, three times
  with 5, 15, 45 min backoff, and writes `exits.jsonl` rows; `low_disk` and `until` are final.
- **18** `host.json` gains `notify: [argv]`; the loop's `left()` and the ask raiser call it with one line of text as the last argument.
- **19** `host.json` gains `peers: [url]`; the dashboard's snapshot includes `peers[]` from each peer's `/api/snapshot` (2 s timeout, stale
  shown as stale).
- **20** Write the Trust Night checklist into `docs/cutover.md`: `tl pin <installed>` before, `tl pin --clear` after, `tl status` shows it.
- **21** Replace the 120 s clock in `loop/run.py:80` by "died before its first checkpoint write after the move" (the note already carries `step`).
- **22** Add `cores` to `CheckSpec` (default 1, `"all"` for a test runner) and a `cpu` resource with `limit = cpu_count` taken through the same
  lock table; the loop skips a pick while load1 > 2 x cpu_count.
- **25** Add the `TL_RELEASE_REEXEC=1` sentence to `dev/release.py`'s docstring and to `docs/cutover.md`.
- **26** Delete `TRAILER` or fill it from the session's model name.
- **28** `tl doctor` prints: free GB on the config dir's disk, load1 / cpu_count, plugin cache dirs and bytes, releases behind, bytes under
  `~/.codex/sessions` and `~/.claude/projects`.
- **29** Rename the worktree age to `loop.worktree_keep_days` and make `keep_days` the one run-data floor.
- **33** `tl status` adds one line: `runs/ 3.2 GB, +410 MB/day, 11 days to min_free_gb`.
- **34** Two owner verbs `factory_stop` and `factory_start` in `writes.py` that spawn `tl factory ...` and return its first line.
- **37** `status --json` gains `stores: [{name, bytes, oldest_at, rule}]` for live, history, agent-runs, overlay.

---

## What I think you are NOT thinking about

1. **Vendor CLIs update themselves under the factory.** Codex CLI, Claude Code and OpenCode are not pinned anywhere (`mise.toml` pins dev
   tools only); delegate parses their JSONL and stream-json by hand (`dg:adapters/harness/*`). A `brew`/`npm` auto-update at 02:00 changes a
   format mid-Night, and the first symptom is a classify miss that looks like a lane outage. Pin the three CLIs in `mise.toml` on both
   machines and have `tl doctor` print their versions.
2. **One subscription, two machines, two pictures.** Delegate's usage readings and out-marks live in `state.json` per machine
   (`dg:contracts/stores.py`). The devbox factory and the Mac factory both drain the same Codex 5-hour window, each believing it has the
   whole budget. The breaker sees half the refusals. Either one machine runs workers at night or the two `state.json`s are merged through
   the same medium as beads.
3. **The ISP and GitHub are single points.** Every `tl` call is `uv run --script` (`tl/adapters/childenv.py:122-125`); with a cold cache and
   no network there is no `tl`, no hook, no release, no hop fallback (installs come from the marketplace over GitHub), no land, no `bd sync`.
   Nothing pre-warms the uv cache for the next version before the hop, and `UV_OFFLINE` is set for Codex steps but not for `tl.py` itself.
4. **The beads database has one manual backup.** `~/.config/task-loop/beads-embeddeddolt-backup-20261101` is a hand copy; `refs/dolt/data`
   is pushed only after a land (`c4-system` flow a, step 17). A Dolt corruption between lands on the Mac loses the night's claims, notes
   and asks. A nightly `bd dolt push` chore costs one line.
5. **Thermal and power are part of "load 280".** A Mac at that load throttles; `caffeinate -i` does not stop throttling, lid sleep or a
   scheduled sleep, and no reading of temperature, battery or `pmset` reaches any log. The Night's wall-clock numbers (`write_cap_min`,
   `check_wall_min`) were tuned on a cool machine.
6. **Cost per night has no ceiling.** `budget_usd` is per bead and meaningless under subscriptions; `bead_token_cap` defaults to 0
   (`tl/contracts/config.py:201-207`); four lanes x unbounded beads x retries x reviews: the only ceilings are the vendor's rate limits,
   which delegate then treats as outages.
7. **The release machine is the dev machine.** Codex writers, the orchestrator, the release suite (eight workers x 2 GB), and occasional
   loops share one container with a cgroup limit; `cgroup_headroom_mb` (`tl/app/release/suite.py:51-61`) protects the suite from the
   container, not the container from the suite. The red-gate rate is partly this.
8. **Nobody reads 23 of the 30 days.** Retention is set for a forensic that has no tool: the dashboard shows 7 days, `tl report` has a window,
   but no verb answers "which version landed this bead" across hops without `grep`.

---

## Where I disagree with the existing documents

- **c4-system flow (b), Z05, Z21, rca "Release hops are a design question, not a defect".** The hop machinery is argued as mechanics
  (freeze, bundle, re-exec). The operational cause is cadence: 223 releases in five days. A between-bead-only hop still means ~24 version
  changes a night. Batch the releases (OPS-FABLE-31) and the hop design becomes a corner case rather than the center of flow (b).
- **Z22 "one `caffeinate -w` per child".** Wrong direction: one `caffeinate -s` (not `-i`) held by the supervisor that OPS-FABLE-17 proposes
  covers all lanes and the dashboard, and ends when the factory ends. N caffeinates is N more processes to reconcile.
- **extraction-synthesis "the 50% target is not a plan, 13% is".** Agreed on lines, but the document implies test volume is the lever for
  gate cost. It is not: 3205 tests run in 64 s here. Gate cost is three runs per change and a 58% red rate. Shrinking tests by extraction
  changes neither number.
- **c4-task-loop, Containers table, "Suite: one run; host lock".** It hides that the same suite runs as the engine's gate check, the release's
  suite and CI; and that the host lock serialises the engine's check behind the release while the check's wall clock keeps running
  (OPS-FABLE-15).
- **c4-system trust table, "Release to running code: three hop points, no negotiation".** The weaker point operationally is that no one can
  see which version each machine runs (OPS-FABLE-19) and nothing ever deletes a version (OPS-FABLE-07). A perfect negotiation over 224
  cached versions is still 1.8 GB and a 224-entry scan per move check.
- **README.md:73 "installed `caffeinate` prevents idle sleep while the loop lives".** For lane 1 only (`C4:tl/app/launch/factory.py:116-119`),
  idle sleep only, and the dashboard is not covered.
- **justfile:21 / CLAUDE.md "the 35-minute suite".** On the devbox it is 64 s. The Mac number is a platform artefact (endpoint scanner,
  `dev/suite-docker.py:5-8`) and possibly a one-worker artefact (OPS-FABLE-08); the document states it as the suite's property.
- **c4-task-loop Stores table: `releases/`, `suite-*.log` lifetime "long".** On a machine that releases but does not loop it is "forever":
  the only sweep runs at loop start (`tl/app/loop/loop.py:118-123`).
- **`tests/rules/test_no_os_services.py` and README "installs no OS service".** The rule is presented as a safety property. For a factory
  meant to run a night unattended on a laptop, it is the reason a two-strike stop at 01:00 is found at 08:00. Keep the rule for the devbox
  if you like; on the Mac it costs more than it protects.
- **rca-zoomout-three "Why the factory did not catch it: gates test the behaviour a slice added".** True, and incomplete: the gate also
  cannot catch what runs nowhere. `dev/race.py` and `tests/live` encode the invariants the night depends on and are not in any gate
  (OPS-FABLE-12); the C4 documents do not mention either.
