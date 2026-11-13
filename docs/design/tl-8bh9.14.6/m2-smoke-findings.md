# M2 live smoke: findings (2026-11-11)

Status: **evidence**. Dated findings, measurements and their limits, retained with the original commands and
environment. This is not a current setup runbook; use the [README](../../../README.md) for implemented commands.

**Result: passed, with three runbook corrections.** Rounds from a runner worktree took tasks of this repository through
plan, implement and the check step on a scratch remote, tracker and factory.db (schema v12). Every expectation of
[live-smoke.md](live-smoke.md) held once its commands were corrected; no factory bug (wrong state, stuck slot, wrong
word, crash) was seen. Run by an agent the owner authorized ("work autonomously; smoke runs by agents are authorized").
Finding 1 is a design gap for the owner, not a check-step bug.

## Setup

- Factory and code under test: `4e004864c7c89396617a14b8a70780e9a8968242` (S6e), runner `~/tl-smoke/m2/runner`
  (`just install`, non-editable). Scratch `~/tl-smoke/m2` (state, artifacts, slots, remote.git, repo, tracker); removed
  after the run. Nothing pushed anywhere but `~/tl-smoke/m2/remote.git`.
- `codex-cli 0.167.0`, model `gpt-6.1-sol`, effort `low`, `--minutes 90`; `auth.json` checked with `test -f` only.
  `bd 1.3.1`, mise `2026.5.12`, Linux arm64 (OrbStack). `UV_OFFLINE` unset in the rounds' shell (count 0).
- mise trust: `mise settings add trusted_config_paths "$M2"` before `just install` (it appended
  `/home/iorlas/tl-smoke/m2`); the file was restored byte for byte afterwards (sha256 `baf490e4...` before and after).
- `TL config show`: every value under `$M2`, source `file`; `round_seconds = 60 (default)`. `TL slot adopt`: first
  `s1 not_listed /home/iorlas/tl-smoke/m2/slots/05e9e410c805/s1` (exit 1), then `s1 adopted ...` (exit 0); `.t/s1` 49
  bytes; `codex sandbox -- true` from the slot exit 0; `PRAGMA user_version` 12.
- `TL profile show --at HEAD` after `P base`: setup `just bootstrap`; checks `check`, `test`, `report`, `slow`; required
  `check`, `test`; target `main`. `P failing` adds `offline-only` (required); `P orphan` adds `orphan`.

## Tasks

| task | profile at main | what it covered | checks attempts |
|---|---|---|---|
| A `m2-cn2` | base | section 2: plan, implement, checks pass, `Next: done` | 1 passed |
| A2 `m2-v0m` | base | section 3: interrupt rounds during the block, restart | 1 passed |
| B `m2-jm2` | failing | section 4 (failed required, hand re-runs, argv marker), section 5 (abandon) | 3 failed, then abandoned |
| C `m2-dp8` | orphan, timeout variant | section 6 as first written: `timed_out`, not `lingering` | 1 passed |
| C2 `m2-z3t` | orphan with `setsid` | plan section 17 step 7's second variant: also `timed_out` | 1 passed |
| C3 `m2-0qu` | orphan, corrected (`sleep 600 & true`) | section 6: `lingering`, held, person stops, release; section 3's harder variant on its re-run | 2 failed `orphan:lingering` |

Each implement agent added one test file only (`tests/steps/test_round_log.py`, `test_round_log_ident.py`,
`test_exit_codes.py`, `test_step_guide_checks.py`, ...) and reported `just check` and `just test` passing in its
sandbox. Plan about 35 s, implement 60 to 100 s, a checks block about 90 s (setup about 10 s, `check` 1 s, `test` 17 to
21 s with `2026 passed`, `slow` 60 s).

## Section 2: A passes (pass)

`rounds.log`: `plan start started`, `implement advance started`, `implement report running`, `check advance started
47b59cbd...`, `check report running 47b59cbd...`, then `round moves=0`. No `failed`, `skip`, `refused` or `stuck` line.
While the block ran: `Step: check`, `Attempt: 47b59cbd... (run 1)`, `Entry: running (pid 1867764 ...)`, `Check: check
passed, exit 0, 1 s`, `Check: test unfinished, process group 1868656`. `ps -g 1868656`: `just test` with pid = pgid =
sid 1868656; the entry's own sid is 1867764 (`python -I -m taskloop.check_entry ...`); the check's cwd (`readlink
/proc/<pid>/cwd`, `lsof` is not installed) is the slot. After the block, exactly the runbook's lines:

```
Step: check
Attempt: 47b59cbd9ada459e8c8ee5e34adf0193 (run 1)
Earlier: 00d6874f5ebd417ba660cbceadc84910 advanced
Slot: s1
Phase: concluded
Commit: 399eef1d1adf073ab8186c640a53e79f4a7abe87
Required: check, test (main at 6804b0adf24a265a388a4abf26dc9a5f1b0d60d3)
Profile: 07565a6c... at X
Setup: run 1 passed at 399eef1d...; log .../setup-1.log
Check: check passed, exit 0, 1 s; log .../check-1-check.log
Check: test passed, exit 0, 21 s; log .../check-1-test.log
Check: report passed, exit 0, 0 s; log .../check-1-report.log (not required)
Check: slow passed, exit 0, 60 s; log .../check-1-slow.log (not required)
Result: collected passed
Succeeded: yes
Released: 2026-11-11 19:48:36 UTC, slot parked at 6804b0adf...; claim kept
Next: done
```

(`tl step show` also prints a second `Earlier:` line for the plan attempt.) `check-1-check.log`: `All checks passed!`,
`0 errors`, `Contracts: 8 kept, 0 broken.`, `exit 0`; `check-1-test.log` ends `2026 passed in 20.50s`, `exit 0`.
`check-1-report.log` ends `exit 0`, `untracked: m2-report.txt` (also listed in the `slow` log). The slot was still
released: `status --porcelain=v1 --ignored=no` empty, HEAD D, `.t/s1` empty. `TL step list`: `m2-cn2 m2 check 1 s1
concluded gone collected passed done`. `bd show`: `IN_PROGRESS`, assignee `taskloop`. Entry log: `collected passed
claim=held release=released`.

## Section 3: interrupted rounds and the restart (pass, both variants)

- **Simple (A2).** One SIGINT to the verified rounds pid while `Check: slow unfinished`: `Rounds stopped: interrupted.
  Launched steps keep running; ...`, `rounds.log` `rounds stopped interrupted`; the checks entry (pid 1885780,
  `taskloop.check_entry ... m2 m2-v0m`) kept running. Restarted rounds: `m2-v0m check report running 1ec44239...`,
  then `round moves=0`; result block 1's (`check-1-*.log`), `Attempt: ... (run 1)`, `Next: done`.
- **Harder (C3's hand re-run, run 2).** Rounds stopped by SIGINT; `TL step start m2-0qu` re-ran the checks
  (`676d7e16...`, run 2); while `slow` ran, `kill -TERM` to the verified entry pid 1971180; `slow` (pgid 1975941, its own
  session) kept running. Rounds restarted: `m2-0qu check relaunch relaunched 676d7e16...`; entry log `unavailable
  checks:running claim=held`; `TL step show`: `Refused: checks:running (1 in a row)`, `Next: start`. The next round
  (slow ended) relaunched again (no new line: the identical line is not repeated); factory.db: block 1 `slow`
  `interrupted`, block 2 `check`, `test`, `report`, `slow` passed and `orphan` lingering; `Setup: run 2`, logs
  `check-2-*.log`; the result is block 2's. Not `stuck:checks_refused` (one counted refusal, then a conclusion).

## Section 4: a failing required check (pass; word `undefined`, see finding 1)

B's X was cut from the slot's D, the base profile, so `offline-only` was not defined at X:

```
2026-11-11T19:59:51Z m2 m2-jm2 check advance started 12182bd2e68b42e9afd9b47f2e5ee06c
2026-11-11T20:01:21Z m2 m2-jm2 check report failed:offline-only:undefined 12182bd2e68b42e9afd9b47f2e5ee06c
```

- `TL step show`: `Required: check, test, offline-only (main at c117f1963...)`, `Check: offline-only undefined
  (required by main, not defined at X)`, `Result: collected failed:offline-only:undefined`, `Succeeded: no`, `Released:
  ...; claim kept`, `Next: done`. The other checks ran and passed.
- Four more rounds (20:01 to 20:06): no second checks attempt (factory.db one row, run 1), no new `rounds.log` line for
  B; `bd show`: `IN_PROGRESS`, `taskloop`. Other work unaffected: the round admitted and finished C, C2, C3 afterwards.
- By hand, `TL step start m2-jm2 ...`: `Attempt: ff7da353... (run 2)`, `Earlier: 12182bd2... re-run`, then `7c6976e7...
  advanced`; still `failed:offline-only:undefined` (logged once for the new attempt).
- **argv marker.** Main's `test` argv changed to `["sh", "-c", "just test"]` (committed and pushed), then a third hand
  re-run: `Check: test passed, exit 0, 19 s; log .../check-1-test.log (argv differs from main)`; `Required:` names the
  new main; the block ran X's `just test`.
- The real `offline-only failed, exit 1` on the host was not reached (it needs another task cut from a slot at the
  failing main; skipped to save agent tokens). `failed:orphan:lingering` covers a failed non-required check below.

## Section 5: abandon after the checks (pass)

`TL step release m2-jm2 --abandon`: first `released: attempt 25fb692b...` (the checks attempt, `Claim kept`), then
`released: attempt 7c6976e7...` (implement) `Claim returned to the tracker`, `Abandoned: tl step start m2-jm2 admits a
fresh attempt`. `bd show`: `OPEN`, no assignee. factory.db: only the latest checks attempt `abandoned=1`. Next round:
`m2-jm2 implement skip abandoned 7c6976e7...`; `TL step list`: `Next: start`; never re-advanced. With rounds stopped,
`TL step start m2-jm2` by hand then admitted a **plan** attempt (`Step: plan`, `Earlier: 7c6976e7... abandoned`, claim
taken again) once the slot was back at the branch's D (finding 1: at a newer slot commit it refused `branch_diverged`).
The plan agent answered `unchanged` (`collected reused`); B was abandoned again.

## Section 6: `lingering` (pass after correction; first `timed_out`)

- **As written** (`sh -c 'sleep 600 & sleep 600'`, timeout 5, task C): `Check: orphan timed_out, 5 s, process group
  1945413 (not required)`, log `timed out`; nothing left (`pgrep sleep` showed no `sleep 600`); the block went on;
  `Result: collected passed`, released, `Next: done`. **C2** (`setsid sleep 600 & sleep 600`): the same, `timed_out`,
  nothing left. Finding 3.
- **Corrected** (`sh -c 'sleep 600 & true'`, task C3): `Check: orphan lingering, exit 0, 5 s, process group 1970668
  (not required)`, log `exit 0`, `lingering`; `Result: collected failed:orphan:lingering`, no `Released:` line,
  `Next: release`; entry log `collected failed:orphan:lingering claim=held release=held:check_running`; `rounds.log`
  `m2-0qu check report release f6b808ac...` once. `TL step release` before the stop: `unsettled:check_running` (exit 3,
  nothing changed). `ps -g 1970668`: one `sleep 600`, owner iorlas, cwd the slot; `kill -TERM` to that pid; then `TL
  step release`: `Slot s1 parked at 9980a01c6...`, `Reservation of s1 removed`, `Claim kept`; `Next: done` with the
  failed result; slot clean at D. Then `P base`.

## Findings

1. **A task branch starts from the free slot's HEAD, never from `main` (design gap, not a check-step bug).** `prepare.py`
   cuts `task/<id>` from D and never fetches; nothing moves a free slot, so after `P failing` B's X still had the base
   profile and `offline-only` was `undefined`, not `failed`. Every task in a loop is cut from the commit the slot was
   adopted (or last moved by hand) at, however far `main` moved. The runbook now detaches the free slot at the new
   `main` in `P`. Owner question: should admission (or the release's park) bring a free slot to the target, or is moving
   slots the person's job until land exists? A moved slot also makes `tl step start` of an abandoned task whose branch
   lacks the new D refuse `branch_diverged` (seen with B).
2. **Repeated `skip abandoned` lines.** `m2-jm2 plan skip abandoned 06a670a2...` was written five times: the quiet set
   is the previous round's, and a round with no free slot does not reach admission, so each slot release repeats it.
   The runbook's "an identical line is never repeated" holds only between consecutive rounds. Cosmetic.
3. **A timeout never yields `lingering` here.** `stream_proc.tree.stop_tree` notes descendants (including `setsid`
   ones) from the process table before the stop and kills them by pid, so both orphan variants end `timed_out` with no
   survivor. `lingering` comes from a check that exits leaving its group alive. Plan section 17 step 7's `setsid` case
   and section 19's "survivors for a setsid child" are answered: no survivor, `timed_out`.
4. **No `round moves=0` after a failure.** The closing line's quiet key is the stopped word only (`round._Trail.close`),
   so after `round moves=1` (B's failure) the later quiet rounds' closing lines were suppressed and `rounds.log` stayed
   silent, unlike after a pass (`round moves=1 stopped=no_free_slot`, then `round moves=0`). Cosmetic.
5. **`unsettled:check_running` guide.** `tl step release` printed, between the correct `check_running` sentences, the
   agent attempt's guide for `unsettled` (slot files, `tl step verify`, `worker_alive`, `staged`), which does not apply
   to a checks attempt.
6. `check` takes about 1 s on this machine (cached ruff/pyrefly/import-linter; log file times agree). `lsof` is not
   installed on this host: `readlink /proc/<pid>/cwd` served.

## Resolutions (2026-11-11, after the smoke)

1. Fixed: a new task branch is cut at the plan attempt from the local `main`'s tip (no fetch; `target` without a local
   `main`); an existing branch is resumed as it is; D stays the park point and must be in the branch
   ([.15 section 17](../tl-8bh9.4.3.1.15/plan.md), decided there, open to veto). The runbook's `P` no longer moves the
   slot. `failed:offline-only:undefined` itself was the plan's `undefined` rule as designed (plan section 7): a name
   `main` requires that X's profile lacks.
2. Fixed: a round that never reads the ready rows (no free slot, a stop) carries the previous round's admission skip
   keys (`attempted`, `abandoned`, `assigned`, `ancestry`) into its `written`, so `skip abandoned` is written once.
3. As designed (recorded above and in the runbook).
4. Fixed: the closing line's quiet key is its whole text (`moves=<n>` and the stopped word), so the first round with
   no move after one with moves writes `round moves=0`, whatever the stopped word.
5. Fixed: `tl step release` of a checks attempt marks its refusal (`Failed.checks`), and the guides come from
   `guide(word, checks=True)`: `unsettled` has a checks text (a process of the checks attempt holds the slot).

## Runbook corrections made with this file

1. Section 1: X descends from the free slot's D; `P` also detaches the free slot at the new `main`.
2. Section 6: the orphan check is `sh -c 'sleep 600 & true'` (timeout 30): an exit leaving the group alive is
   `lingering`; a timeout stop takes the tree, `setsid` included. (A first edit, `sleep 600 &` inside the guard's
   braces, was a shell syntax error, caught by `profile show` before any task used it.)
3. Section 6: `readlink /proc/<pid>/cwd` where `lsof` is missing.

## Cleanup

Rounds stopped by SIGINT each time (exit 0); every survivor stopped by verified pid; no process with cwd or argv under
`~/tl-smoke/m2` left. The runner worktree removed from the source repository and the slot worktree from the scratch
repository (`git worktree remove --force`), then `~/tl-smoke/m2` removed (other `~/tl-smoke` content untouched);
`~/.config/mise/config.toml` restored to its prior content (same sha256). No `m2-*` ref in the source repository.
