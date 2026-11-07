# Test tiers: keep the behavioral tests, stop paying for all of them on every PR

Epic: tl-wnup (TESTSPEED). Status: design, docs only. The existing "devbox canary" (`app/release/canary.py`, an acknowledgement for the Mac pin) is another thing and keeps its name. Terms: docs/glossary.md ("Tests" section). Related: docs/design/merge-queue.md (flakes
section 7, repair section 2.1), dev/affected.py, `src/taskloop/app/land/carry.py`, `dev/release.py`.

## 1. The problem and the answer in five lines

Denis wants the behavioral tests (the ones that run the real thing) as the only proof that it works, and fears their cost: one small edit
selects many of them on every PR. Measured (section 2): a leaf change selects 87 test files, a hub change 481 of the 4,839-test suite's 563 test files, and 89% of all
tests; the real tests are 35% of the tests of a sample run and 66% of its summed wall time.

1. **T1, every PR**: unit + contract tests, selected by closure. Seconds.
2. **T2, every PR**: behavioral tests selected by closure *and distance* (section 4), skipped by receipt when their closure bytes are unchanged.
3. **T3, off the PR path**: the full behavioral suite on `main` by an idle slot (main sweep) and on every release candidate; a red T3 blocks the
   release, never an unrelated PR.
4. A hub change does not run the whole behavioral suite on its PR; it runs the behavioral tests *near* the hub, and T3 covers the rest.
5. A regression in the far part can sit on main until the next main sweep (section 6). We accept that, and shorten it with a bisect and an
   automatic repair bead.

## 2. Measurements (2026-11-07, this checkout at origin/main b83678e8, Linux box, 14 CPUs)

Nothing here changed code. "Not measured" marks what the rules forbid an agent to run (`just test-full`, `just test-live`: CLAUDE.md) or what
the logs do not hold.

**Tests per layer** (`pytest --collect-only -m ""`, 4,839 tests; layers by path as in tests/conftest.py):

| layer | what it touches | tests | share |
|---|---|---|---|
| unit (`tests/<slice>/`, domain, stores, dash, cli, hook, contracts) | fakes, memory, `workdir` | 3,645 | 75% |
| rules (`tests/rules`, always selected) | reads the whole tree | 283 | 6% |
| real (`tests/<slice>/real/`, `tests/ports`, `tests/adapters`) | a real git, process, socket | 882 | 18% |
| e2e (`tests/e2e`) | a whole flow | 29 | 0.6% |
| delegate (`tests/delegate`, real processes, minutes) | not collected unless the change touches delegate | not counted | |
| live (`tests/live`) | explicit-only, a person | not counted | |

Contract suites (tests/contracts 293, tests/ports 167) are inside unit and real. The lead's draft calls real + e2e (+ delegate, live) the
**behavioral** layer: 911 collectable tests, plus the delegate and live ones.

**Time per layer** (sample run, not the suite): the 87 files `dev/affected.py` picks for a change to `app/prune/retention.py`, run as
`pytest -n 4 -p testtimes` (the same plugin `just test` loads), 717 tests, green, 66.6 s wall:

| layer | tests in sample | CPU s | wall s (summed over workers) | slowest test CPU s |
|---|---|---|---|---|
| unit | 159 | 3.5 | 30.6 | 0.39 |
| rules | 305 (incl. subtests) | 39.2 | 47.7 | 7.07 |
| real | 253 | 29.1 | 152.0 | 0.96 |
| e2e | 0 | n/a | n/a | n/a |

Real tests cost 5x their CPU in wall (git and process waits), the unit tests 9x on a loaded box. Whole suite wall time: **not measured**
(forbidden to run). The comment in `dev/runtests.py` says a wide selection takes about 15 min in 4 workers; the epic's goal is 5 min.

**What the selection picks** (`dev/affected.py --changed PATH`, test functions counted from `--collect-only`):

| change | test files | tests | of which real | of which e2e | share of all tests |
|---|---|---|---|---|---|
| docs only (this PR) | tests/rules only | 283 | 0 | 0 | 6% |
| leaf: `app/prune/retention.py` | 87 | 717 | 253 | 0 | 15% |
| `app/land/carry.py` | 61 | not counted | | | |
| `app/land/engine.py` | 94 | 738 | 33 | 0 | 15% |
| `app/run/engine.py` | 180 | 1,700 | 287 | 0 | 35% |
| `contracts/paths.py` (a hub) | 481 | 4,330 | 728 | 28 | 89% |

The task said "engine.py selected 179 tests"; the figure here is files (180) for `app/run/engine.py`, 1,700 test functions.
Even a leaf selects 15%: 283 are `tests/rules` (always) and the loop and slot tests reach prune.

**The gate and Carry** (factory.db `timed` and `check_pass` tables, this machine, 2026-11-06 18:40 to 2026-11-07 00:54):

| measure | value |
|---|---|
| land gate runs of the `suite` check (`just gate`) | 167 |
| seconds: median / p90 / max / mean | 65 / 122 / 212 / 66 |
| runs under 5 s (a receipt hit, or an empty selection) | 9 (5%) |
| runs 5 to 30 s / 30 to 120 s / over 120 s | 45 / 95 / 18 |
| stored receipts (`check_pass`) | 16, all `pass` |
| how many gates Carry skipped | **not measured**: `origin` is empty in all 16 receipts and no counter logs a carry. 8 of the 16 have no seconds; whether those are carried is unverified |

Reading: today's gate costs one minute at the median, so the pain is not the median PR. It is the hub PR (the tail over 120 s, 11% of
runs) and the growth of the suite. The 5% of runs under 5 s show receipts work, but 95% of gates run tests.
The measurements the next beads must add: seconds per layer in every run record (nothing stores them today), and a Carry counter.

## 3. What "release" means for tests

Today `dev/release.py` (read, not changed): takes the release lock, resets its own clone to origin/main, runs `just check` and the profile's
suite (`just test`, affected-only), commits the version bump, pushes, tags `v<version>`, installs the plugin, then the devbox canary decides
`devbox-ok`. Releases have no minimum interval, so *every landing can be a release*.

For test purposes:

- **Release candidate**: the tree `dev/release.py` is about to bump, that is origin/main's tip *before* the version-bump commit (the release
  already caches its gate by "pre-bump tree"). It is a tree, named by its tree hash, not a branch.
- **Release**: a release candidate that passed T3 (the full behavioral suite on that tree) *and* the existing `just check` + `just test`, then
  got the bump commit, the tag `v<version>` and the install. Nothing else is a release: a landing is not one (glossary: land is not release).
- A T3 receipt for the tree hash of the candidate, made by the main sweep, counts. So when the main sweep already ran that exact tree, the
  release spends no time; when main moved since, the release runs T3 itself, but only for the behavioral tests whose closure bytes changed
  since the last green T3 receipt (the same Carry rule).

## 4. The tiers

| tier | when | what | selected by | skipped by | budget (from the epic) | on red |
|---|---|---|---|---|---|---|
| T1 | every PR, every round and the gate | unit + contract + rules | closure of changed files (`affected.py`) | receipt on the closure bytes | seconds; 120 s CPU one worker | PR fails |
| T2 | every PR, at the gate | behavioral (real + e2e) | closure, **limited to distance**, plus every changed or new behavioral test | receipt (the Carry rule) | part of the same 120 s CPU | PR fails |
| T3 main sweep | after each landing, by an idle slot, newest main tip, at most one running | the whole behavioral suite, all tests that a person does not need to start (not live) | none: everything | receipt on the tree: a tree already green is not rerun | 5 min wall, 4 workers | auto bead, bisect, repair |
| T3 release | the release candidate | same as the main sweep | none | the main sweep receipt on that tree | the same | the release stops; no tag |

The lead's draft against the measurements:

- **T1 holds.** The unit layer is 75% of tests and 3.5 s of CPU in the sample. The always-selected rules cost 39 s CPU, which is most of
  the T1 budget; they are already a bead's target (tl-wnup.8 closed at 10 s on its own measure, the sample shows 39 s with 283 tests, so
  that target is not met on this box; flagged, not filed: the box is not the measuring host).
- **T2 as drafted does not hold for hubs.** "Closure of changed code" selects 728 real and 28 e2e tests for `contracts/paths.py`, and the
  receipt cannot help: a changed file is a changed closure for each of them. So a closure-selected and receipt-cached T2 saves nothing exactly
  where the fear is. The fix, and the one change to the draft: T2 limits the closure by **distance**: a behavioral test runs on the PR when
  it (a) is added or changed by the PR, (b) imports a changed file directly, (c) sits in the slice folder of a changed file, or (d) is one
  of the wiring tests (one per consumer, per the "contract, then consumers" rule) and the e2e flows. The rest of the closure goes to T3. The
  distance cut is a new rule of `affected.py`; the number it would select for the six changes above is measured by the first bead before
  any threshold is set (I could not measure it: the tool has no such mode and code is out of scope).
- **A PR that adds or changes a behavioral test runs that test**: kept as drafted, rule (a) above; it is already how `affected.py` treats a
  changed test file ("a changed test file selects itself").
- **T3 on main by an idle slot and on the release candidate: kept.** The refinement is the receipt: the main sweep tests *trees*, not commits,
  so a run on a tip equal in tree to an earlier green run costs nothing, and the release reuses the main sweep's receipt.

## 5. Red T3: no PR is blocked, the owner is not asked

A red main sweep or release T3 is a failure of main, not of a PR, so it does not enter the merge queue's PR verdicts. Flow (mirrors the repair
flow of merge-queue section 2.1, which handles a tree mismatch the same way):

1. Retry the failing tests once; then run them on the previous green T3 tree (merge-queue section 7 steps 1 and 2). Same failure on the old
   tree: not a new regression (a flake or an old red); it is a flake row and no bisect.
2. Otherwise **bisect** the range between the last green T3 tree and the red tip by halving, running only the failing tests per step (the
   suite is not rerun). The first bad commit names the PR.
3. File a **bead automatically** (label `auto`, title with the test ids and the first bad commit, evidence attached, parent: the PR's bead),
   and **dispatch the repair** as the merge-queue repair flow does: an agent, default a revert PR of the first bad commit, which goes through
   T1 and T2 like any PR; a human only after two failed repairs.
4. **The release is blocked** while the newest T3 on the candidate is red: `dev/release.py` refuses with the failing ids. PRs keep landing
   (they gate on T1 and T2 only); the block is on the release, not on main.

## 6. The cost of a late T3, and the mitigation

A regression that only T3 can see (far from the change, in a test the distance cut left out) lands on main and stays there until the next
main sweep finishes: the interval is *queue time of the idle slot + T3 wall time*, at most 5 min of run once started. While it sits, PRs
rebased on it carry the bug and the release is blocked, but nothing breaks that was not already in the code.

Mitigations, in order of cost:

1. The main sweep runs after every landing when a slot is idle, newest tip only (an older tip is dropped), so the window is typically one T3
   run, not a day. The measured landing rate is the data to size it: 167 gates in 6.2 hours on this machine (a busy day).
2. The bisect (section 5) finds the commit in `log2(range)` steps over the failing tests alone.
3. The release stays blocked, so a bad tree is never installed.
4. The distance cut is conservative by design: the hub PR still runs the nearest behavioral tests, and the wiring tests per consumer.
5. If the main sweep finds that far-away regressions are common, the distance setting shrinks toward the full closure. The main sweep counts
   them: "T3-only reds per month" is the number that tells whether T2's cut is too tight (bead: record it).

## 7. Alternatives, with a verdict

| alternative | cost | what it gives | verdict |
|---|---|---|---|
| All behavioral tests on every PR | a hub PR pays 4,330 tests; the whole suite is about 15 min in 4 workers and grows | no regression ever reaches main | **refuse**: it is the cost Denis fears, and the epic's 5-minute rule forbids it |
| Behavioral only at release | releases have no minimum interval, so the interval is unbounded; one red blocks everything just built | cheap PRs | **refuse**: a regression is found long after, by the release, with many commits to bisect; no signal on the PR at all |
| Nightly only | up to 24 h of main with an unseen regression, and an agent factory lands dozens of PRs a day | cheap, simple | **refuse as the only layer; accept as a floor**: the main sweep is the nightly made continuous. If the idle slot never idles, a time-based run (one a day) guarantees the interval |
| Closure-selected T2 only, no T3 | the far-away regression is never found until it breaks something else | cheapest | **refuse**: the distance cut needs T3 behind it |
| **Tiers T1, T2 (cut by distance), T3 main sweep + release** | T2 a few tens of seconds more per PR; one idle slot of CPU continuously | behavioral proof on every PR near the change, on main in full, on every release | **do** |

## 8. Flakes: how this meets merge-queue section 7

A behavioral test is where flakes live (real processes, sockets, git). Flakes are handled by the same policy as the queue, in the same
place, not by a second one:

- **T2 on a PR**: retry once, then the clean-main check, then blame the PR (merge-queue section 7 steps 1 to 3). One flake score log.
- **T3 on main**: the same retry-and-previous-tree check is step 1 of section 5 above. A test that fails on retry-pass or on the old tree is
  a flake row and *never* a main sweep alarm and *never* a release block by itself; only a failure that also fails twice on the new tree and
  passes on the old one blocks.
- **No quarantine** (merge-queue decision 8). T3 gives a flake more runs, so the score reaches the "more than 3 rows a week" threshold
  sooner and the engine files the fix bead (merge-queue section 16, slice q) sooner: that is the point, and the bead is the owner of the test.
- A flaky test cannot hide in T3, because T3 runs every behavioral test, and cannot stall PRs, because a T3 red never enters a PR verdict.

## 9. Order of work

Beads under tl-wnup: **tl-wnup.10** seconds per layer and Carry hits in the run record (first: measure); **tl-wnup.11** the distance cut in
`dev/affected.py` (needs .10); **tl-wnup.12** the main sweep runner (needs .10); **tl-wnup.13** the release candidate T3 gate in the release
flow (needs .10, .12); **tl-wnup.14** automatic bead, bisect and repair on a red sweep (needs .12 and the MQUEUE beads tl-7s2f.7, flake
policy, and tl-7s2f.15, recovery flow).

## Unverified

- Whole-suite wall time and Carry's skip rate (section 2).
- How many tests the distance cut selects for each change (no tool yet; the first bead measures it).
- Whether an idle slot exists often enough for the main sweep to run after every landing; the slot-use data lives with the MQUEUE work.
- `tests/rules` at 39 s CPU here against tl-wnup.8's 10 s target: a different box, not re-measured on the target host.
