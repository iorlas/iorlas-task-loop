# M3 live smoke: findings (2026-11-12)

**Result: passed.** Rounds from a runner worktree took eight tasks of this repository through plan, implement and the
check step; the person's `tl step land` then landed six of them on a scratch bare remote as one squash commit each,
validated S in a slot whenever `main` had moved, pushed never forced from the person's checkout, and closed each task in
the scratch tracker; two were abandoned. Every expectation of [live-smoke.md](live-smoke.md) held except the multi-URL
push guard (blocked, not run). No factory bug (wrong state, a push to anything but the scratch remote's `main`, stuck
slot, wrong word, crash, a task closed or landed wrongly) was seen. Run by an agent the owner authorized ("work
autonomously; agent-run smokes are authorized", 2026-11-11). The findings below are wording and runbook points.

## Setup

- Factory and code under test: `ececcf8d3d28edcfb5a9ca3a65f6fd6236e6b44d` (L5 and its review repairs; the precondition
  `merge-base --is-ancestor d1aca1601` and `git grep '"abandoning"'` passed). Runner `~/tl-smoke/m3/runner` (`just
  install`). Scratch `~/tl-smoke/m3` (state, artifacts, two slots, `remote.git`, `repo`, `other`, `elsewhere.git`,
  tracker); removed after the run. Nothing pushed anywhere but `~/tl-smoke/m3/remote.git` (and the person's hand pushes
  of the runbook to the same remote); `elsewhere.git` stayed at its clone point.
- `codex-cli 0.167.0`, model `gpt-6.1-sol`, effort `low`, `--minutes 90`; `auth.json` checked with `test -f` only.
  `bd 1.3.1`, mise `2026.5.12`, Git 2.54.0, Linux arm64 (OrbStack). `env | grep -c '^UV_OFFLINE=\|^GIT_CONFIG_'`: 0.
- mise trust: `mise settings add trusted_config_paths "$M3"` appended `/home/iorlas/tl-smoke/m3`; the file was restored
  byte for byte afterwards (sha256 `baf490e4...` before and after; `99ba6c14...` while trusted).
- `TL config show`: every value under `$M3`, `slot_count = 2`, `round_seconds = 60 (default)`. `TL slot adopt`: first
  `s1`/`s2 not_listed .../slots/7129e0b85916/s{1,2}` (exit 1), then both `adopted` (exit 0); `.t/s1` 49 bytes;
  `PRAGMA user_version` 13. `P base` as M2's (profile at `f4c4934f6`, O for every task): checks `check`, `test`,
  `report`, `slow`; required `check`, `test`.
- `sqlite3` is not installed on this host: factory.db was read with Python's `sqlite3` module in read-only URI mode
  (`file:...?mode=ro`); `lsof` is missing too.

## Section 1: eight tasks to `Next: land` (pass)

Rounds 23:39:04 to 23:52:55 UTC (two slots, two tasks at a time; about 14 minutes for eight). `rounds.log`: for each
task `plan start started`, `implement advance started`, `check advance started`, `check report running`, then `round
moves=0`; no `failed`, `refused`, `stuck` or `skip` line. `TL step list`: all eight `check 1 ... concluded gone collected
passed land`. One SIGINT to the verified rounds pid: `Rounds stopped: interrupted.`. Each implement agent added one test
file (`tests/steps/test_m3_<letter>.py`) and the plan file only.

| task | id | section | outcome |
|---|---|---|---|
| A | `m3-l8c` | 2, 3, 10 | summary, same-tree land, `already_landed`, abandon refused `landed` |
| B | `m3-o53` | 4 | `push_barred`, `push_url`, then validated in s1 and landed |
| C | `m3-791` | 5 | Ctrl-C, `kill -9`, `checks:running`, block 3 landed |
| D | `m3-sgm` | 6 | `target_moved`, candidate 2 landed |
| E | `m3-dlp` | 7.1-7.3 | `remote_rejected`, abandon refused `landing`, `--withdraw`, abandoned |
| F | `m3-3r5` | 7.4 | `remote_rejected` (in s2, concurrently with E in s1), lost answer `already_pushed` |
| G | `m3-cms` | 8 | hand land: `no_change`, `--no-change`, `already_landed` |
| H | `m3-pcr` | 9 | `conflict` naming its path, abandoned |

## Section 2: the summary changes nothing (pass)

`LAND A --summary`, exit 0: `Checks: e524da9c... passed at X 4795ae13... (main at f4c4934f6...)`, `Check: check
passed`, `Check: test passed`, `Required at origin main f4c4934f6...: same`, `Origin main: f4c4934f6...; same tree as X,
no checks`, `Message:` with `Test one module's words (A) (m3-l8c)`, `Squashed from task/m3-l8c at 4795ae13...:` and both
branch subjects, `Task:`, `Plan: docs/design/m3-l8c/plan.md`, `Checked: ...`, then `Diff: git diff f4c4934f6..4795ae13`
and `Nothing was recorded, reserved, pushed or closed`. Afterwards `land_candidate` count 0, origin's `main` unchanged,
`bd show`: `IN_PROGRESS`, assignee `taskloop`; `PERSON` equal. `--json`: `status summary`, `state same_tree`, `again
false`.

## Section 3: the same tree lands with no slot (pass)

`LAND A`, exit 0, **1 s**: `pushed: m3-l8c (backlog m3) on origin main; S pushed to origin's main by this land`,
`Candidate 1 (3bebcfd0...): S 5c988f076... onto origin main at f4c4934f6...; same tree as X, no checks`, `Pushed: origin
main at 5c988f076...`, `Closed: closed`, `Tracker: closed locally, not synced (bd dolt push shares it)`, `Next: git pull
--ff-only ...`. Candidate row: slot NULL, `same_tree`, `pushed`, `closed`.

- S `5c988f076`: exactly one parent, `f4c4934f6` (O); S's tree and X's tree both `dae0a2bd7...`; author and committer
  `iorlas <dt0xff@gmail.com>` (the person); the message is section 9's, no co-author trailer (none in any landed S).
- `bd show`: `CLOSED`, reason `Landed 5c988f07... on main (task/m3-l8c at 4795ae13...)`. `TL step show` ends with the
  `Land:`, `Land required: check, test (origin main at f4c4934f6...; same as the checks)`, `Land result: same_tree`,
  `Pushed: ..., 2026-11-11 23:53:27 UTC`, `Closed: ... (closed)`, `Tracker:` lines and `Next: landed` with its guide.
  `TL step list`: `landed`.
- **The person's checkout untouched**: `PERSON` (HEAD, `refs/heads/main` `f4c4934f6`, index sha256 `16009841...`) equal
  before and after this land, and still equal after every later land (sections 4 to 9); only `refs/remotes/origin/main`
  moved (`status -sb`: `behind 1`); stash empty.
- Rerun: `already_landed: ... landed before this call: nothing called`, exit 0; origin's `main` and `bd show` unchanged;
  still one candidate row.
- No `bd dolt push` ran: the scratch tracker has no remote (`No remotes configured.` at the end).

## Section 4: refusals, then a moved `main` validates S in a slot (pass)

- Push bar (`GIT_CONFIG_*` `pushInsteadOf`): `refused:push_barred`, exit 1. `pushurl` to `elsewhere.git`:
  `refused:push_url` ("Nothing was pushed"), exit 1; candidate count, origin's `main`, `elsewhere.git`'s `main` and `bd
  show B` unchanged after each; `pushurl` unset (`remote -v` both lines `remote.git`).
- **Multi-URL push guard: BLOCKED, not run** (needs git-porcelain 0.17.0; plan section 27.1 item 4).
- `LAND B` (98 s): while it ran, `Land: candidate 1 (b171d4d9...) onto origin main at 5c988f076...: a2003926...; merged
  onto a moved main, checks run again`, `Land slot: s1, held`, `Land process: running (pid 2493913, started 25206531)`,
  `Land check:` lines (`slow unfinished, process group 2499341`), `Land result: pending`, `Next: land`. Then `pushed:
  ...`, `Candidate 1 ...; checks passed on S`, `Pushed:`, `Closed: closed`, `Tracker:` line, exit 0. `TL step show`:
  `Land slot: s1, released 23:55:29 UTC, parked at f4c4934f6`, four `Land check: ... passed, exit 0` with
  `check-1-<name>.log`, `Land result: passed`, `Next: landed`. Slot s1: `status --porcelain=v1 --ignored=no` empty, HEAD
  `f4c4934f6` (D), `.t/s1` empty.
- Origin's `main` `a2003926`, one parent `5c988f076` (S_A), its tree holds `test_m3_A.py` and `test_m3_B.py`.
- **Cost**: same tree 1 s, no slot; moved `main` 97 to 100 s per land (setup, `check` 1 s, `test` 26 to 28 s, `slow`
  60 s) and a slot for that time.

## Section 5: interrupts (pass)

1. **Ctrl-C** (SIGINT to the verified `tl step land m3-791` pid 2499851, SigCgt includes SIGINT) while `Land check: slow
   unfinished, process group 2505282`: the land ended with a Python `KeyboardInterrupt` traceback, exit 130 (finding 1).
   **The check tree was stopped as the review predicted**: `ps -g 2505282` (the `sh -c` and `sleep 60`, pid = pgid =
   sid) printed nothing right after. `TL step show`: `Land process: gone (pid 2499851, ...)`, `Land result: pending`,
   `Next: land`.
2. Rerun: block 1's `slow` became `interrupted` and block 2 ran (`check-2-*.log`). During its `slow`
   (pgid 2510785), `kill -9` of the verified land pid 2505361 (`.../runner/.venv/bin/tl --config ... step land m3-791
   ...`). The check kept running in its own session (`ps -g`: `sh -c` and `sleep 60`, sid 2510785).
3. Rerun while it ran: `tl step land: unavailable:checks:running` with the checks guide and the rerun line, exit 3, 0 s;
   `Land result: pending`; the land process became the rerun's pid. After `slow` ended, `LAND C` (99 s): block 3 whole,
   `pushed:`, `Closed: closed`. factory.db: block 1 and 2 `slow` `interrupted` (no rc), block 3 all `passed`. Slot clean
   at D.

## Section 6: `target_moved` (pass)

While D's block ran (`slow unfinished`), the other clone pushed `772328b24 someone else lands`. The land: `tl step land:
unavailable:target_moved` ("Nothing was pushed"), exit 3, 97 s; origin's `main` the hand commit. `TL step show`: `Land
superseded: moved`, `Land result: passed`, slot released, `Next: land`. Rerun (98 s): `Candidate 2 (3a130a46...): S
c192e766 onto origin main at 772328b24; checks passed on S`, pushed, closed; S's one parent is the hand commit. Rows:
candidate 1 `passed moved`, candidate 2 `passed pushed closed`.

## Section 7: `remote_rejected`, `landing`, `--withdraw`, a lost answer (pass)

1. With the scratch `pre-receive` hook refusing `main`, E (s1) and F (s2) landed concurrently: both validated (100 s),
   then `tl step land: refused:remote_rejected`, exit 1. **A remote `pre-receive` refusal is classified
   `remote_rejected`, not `unavailable git`.** `TL step show E`: `Land result: passed`, no `Pushed:`, `Next: land`.
2. `TL step release E --abandon`: `refused:landing` with its guide, exit 1; `TL step show` byte-identical before and
   after; `bd show`: `IN_PROGRESS`.
3. `LAND E --withdraw`: `withdrawn: m3-dlp ...; candidate 1 (a268a2ea...) superseded, S cfd3b412... was not on origin's
   main`, exit 0; `Land superseded: withdrawn`. The abandon then went through (the checks attempt `Claim kept`, then the
   implement attempt `Claim returned to the tracker`); `bd show`: `OPEN`, no assignee.
4. **Lost answer**: hook removed; F's S `f6796440` pushed by hand from the person's checkout. `LAND F`: `already_pushed:
   ... origin's main was found to hold S: recorded, not pushed again`, `Closed: closed`, exit 0; origin's `main` still
   `f6796440`. The `kill -9` of a land after its push and before its record was not attempted: the window is a few
   milliseconds and cannot be hit reliably; the hand push is the runbook's stand-in (plan section 12's row, tested).

## Section 8: a hand land (pass)

The other clone squash-merged `task/m3-cms` and pushed `f41378572 hand land m3-cms`. `LAND G`: `refused:no_change` with
its guide, exit 1, no candidate. `LAND G --no-change`: `no_change: ... recorded with no push`, `Candidate 1 ...; no
change, no checks`, `Closed: closed`; origin's `main` unchanged; `bd show`: `closed`, reason `Already on main at
f41378572...`; `TL step show`: `Land result: no_change`, `Delivered: no change, origin main at f41378572 already held it`.
Rerun: `already_landed`.

## Section 9: a conflict (pass)

H's X adds `docs/design/m3-pcr/plan.md` and `tests/steps/test_m3_H.py`; the other clone committed a different
`tests/steps/test_m3_H.py` and pushed. `LAND H`: `refused:conflict`, `X does not merge onto origin's main at 3c198283...
(1 paths: tests/steps/test_m3_H.py). Nothing was recorded.`, exit 1; H's candidate count 0. The abandon went through
(`OPEN`).

## Sections 10 and 11 (pass)

- `TL step release A --abandon`: `refused:landed` with its guide, exit 1; nothing changed (8 rows, the same `rev` sum).
  `LAND A --summary --withdraw`: usage error, exit 2.
- `git pull --ff-only` in `$M3/repo` fast-forwarded `f4c4934f6..3c198283e`. `TL step list`: A, B, C, D, F, G `landed`;
  E and H `implement ... collected verified start`. Rounds restarted: `m3-dlp implement skip abandoned` and `m3-pcr
  implement skip abandoned` once each, `round moves=2`, then nothing for three minutes (nothing for the landed tasks);
  stopped by SIGINT.
- Afterwards: both slots clean at D, `.t/` empty, no `reservation` rows; origin's branches other than `main` and the
  eight `task/*` equal the source repository's; no process under `~/tl-smoke/m3`.

## Findings

1. **Ctrl-C prints a raw traceback (low).** A land interrupted by SIGINT ends with Python's `KeyboardInterrupt`
   traceback through `stream_proc.runner._wait` and exit 130, not a line saying the land stopped and a rerun resumes.
   State is right (the tree stopped, the candidate pending, the rerun reconciles). A `KeyboardInterrupt` handler in
   `cli_step._land` (or `cli.main`) printing "interrupted: rerun `tl step land`" would match the rounds' message.
2. **`Land process: ... started 25206531` (cosmetic).** The stored process start is printed as raw clock ticks
   (`show_render` land lines), where the agent's `Entry:` line reads as a time.
3. **Repeated refusal text (cosmetic).** `target_moved` and `remote_rejected` print a detail line and a guide line that
   say nearly the same sentence twice.
4. **`refused:landed` detail on a closed task (wording).** `tl step release --abandon` of a landed and closed task says
   "rerun `tl step land` to finish the close", though nothing is left to close; the guide after it says so correctly.
5. **Tracker lease shown `expired`.** `bd show` of a task at `Next: land` reads `Lease: expires expired (heartbeat 5 mins
   ago)` once rounds stopped; the close (`if_assignee taskloop`) still succeeded for every task. Recorded for plan
   section 23's open item ("`bd close` with `if_assignee` against a lapsed lease"): it works on bd 1.3.1.
6. **Rounds after abandoned skips write no `round moves=0`.** After `round moves=2` (the two `skip abandoned` lines)
   later quiet rounds wrote nothing for three minutes. Cosmetic, as M2 finding 4.
7. Host: `sqlite3` and `lsof` are not installed; Python's read-only `sqlite3` and `/proc` served.

## Runbook corrections made with this file

1. Section 0: where the `sqlite3` CLI is missing, a read-only Python equivalent.
2. Section 5 step 1: Ctrl-C ends the land with a traceback and exit 130 (finding 1).
3. Section 7 step 4: a bare remote has no reflog unless `core.logAllRefUpdates` is set before the push; `rev-parse main`
   is the check.

## Cleanup

Rounds stopped by SIGINT both times (exit 0); the two land processes stopped were verified by command line first; no
process with argv under `~/tl-smoke/m3` left. The runner worktree removed from the source repository (`git worktree
remove --force`, then `prune`), then `~/tl-smoke/m3` removed (`chmod -R u+rwX` first; other `~/tl-smoke` content
untouched); `~/.config/mise/config.toml` restored (same sha256). No `m3-*` ref in the source repository.
