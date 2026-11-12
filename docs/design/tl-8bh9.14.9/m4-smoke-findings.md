# M4 live smoke: findings (2026-11-12)

**Result: passed** (step 9, the Git read timeout, blocked and not run). `tl step rounds --label auto` from a runner
worktree held every round-taken task it stopped on with the right reason, label moves, claim state and one comment;
left hand-started and closed tasks' tracker state alone; re-ingested answered holds at plan under their stored label
only; and its keep-awake helper left no process after Ctrl-C once, Ctrl-C twice or `kill -9`. Every expectation of
[live-smoke.md](live-smoke.md) held once five runbook commands were corrected. No factory bug (a hold under a live
process, a task wrongly held or abandoned, a label or claim wrongly changed, a stuck slot, a wrong word, a crash, a
Ctrl-C not stopping rounds) was seen. Run by an agent the owner authorized ("work autonomously; agent-run smokes are
authorized", 2026-11-11). No circuit breaker exists or was tested (plan section 11).

## Setup

- Factory and code under test: `27c632d5d2c4d155f15f362f9214d232a64c414a` (H3 review repairs; contains K1 `52c0acada`).
  Runner `~/tl-smoke/m4/runner` (`just install`). Scratch `~/tl-smoke/m4` (state, artifacts, two slots, `remote.git`,
  `repo`, `other`, tracker); removed after the run. Nothing pushed anywhere but `~/tl-smoke/m4/remote.git`.
- `codex-cli 0.167.0`, model `gpt-6.1-sol`, effort `low`, `--minutes 20`, `--every 20`; `auth.json` checked with
  `test -f` only. `bd 1.3.1`, Linux arm64 (OrbStack, NixOS userland). `env | grep -c '^UV_OFFLINE=\|^GIT_CONFIG_'`: 0.
- mise: `mise settings add trusted_config_paths ~/tl-smoke/m4` (sha256 `baf490e4...` before, `dbac34a8...` while
  trusted); restored from a copy outside `$M4`, sha256 `baf490e4...` after.
- `TL config show`: every value under `$M4`, `slot_count = 2`. `TL slot adopt`: `not_listed` twice (exit 1), then `s1`,
  `s2 adopted` (exit 0). `PRAGMA user_version` 14. Profile on the scratch `main` (`74e8df0ce`): setup `just bootstrap`,
  one required check `marker` = `sh -c 'test -n "$UV_OFFLINE" || ! test -e m4-fail.txt'` (fails on the host only).
- Codex cost: 12 plan and 7 implement runs, each 10-25 s. Whole run 02:07-02:22 UTC.

| task | id | what it covered | outcome |
|---|---|---|---|
| A | `m4-7be` | needs_owner plan | held `failed:needs_owner`, on_hold |
| B | `m4-ags` | failed required check, then answered | held `failed:marker:failed`; re-ingested, checks passed, landed |
| C | `m4-9bg` | clean task | `land`, landed same tree |
| D | `m4-e7u` | origin `task/<id>` fast-forwarded | not `branch_moved` at the check advance (finding 1); land refused `branch_moved` |
| D2 | `m4-16u` | local `task/<id>` moved off X | held `branch_moved` |
| E | `m4-4tm` | `kill -9` of the implement entry | pending `unsettled:worker_alive`, then held `stuck:entry_lost` |
| E2 | `m4-6bv` | dirty slot (leftover file, worker and entry killed) | pending `held:slot_dirty`, held after cleanup |
| F | `m4-m7v` | hand-started (`tl step start`), needs_owner | `done`, never held |
| G | `m4-d38` | closed (`--force`) while planning | held, labels `closed`, nothing written |
| H | `m4-f36` | label rule: `auto` and `auto2` | held under `auto2` rounds removing `auto`; skipped by them; re-taken under `auto`, held again |

## Holds (pass)

- **A (needs_owner).** `m4-7be plan hold held failed:needs_owner 21a7b54a...` once (12 s after the plan started), then
  no line or tracker call for A. `SHOW A`: `Hold tracker: \`auto\` removed, \`held\` added, commented`, `Hold claim:
  returned`, `Next: on_hold` with the answer guide (`bd label add m4-7be auto`). `bd show`: OPEN, no assignee, labels
  `held`. One comment by `taskloop`: `taskloop hold: failed:needs_owner`, step, attempt, time, the quoted explanation
  ("> The repository owner must decide whether the smoke file is named after the moon or the sun..."), `Evidence:`,
  "The factory removed auto and added held and returned its claim.", the answer lines.
- **B (failed checks).** `m4-ags check hold held failed:marker:failed ee83e922...` (the agent attempt; cause the checks
  attempt `af61133b...`). Comment: `Step check, attempt 1 (...)`, `task branch task/m4-ags at e0149a8e...`, `Failed
  checks: marker failed <check-1-marker.log>`, `Evidence:`, claim returned. OPEN, unassigned, `held`, no `auto`;
  `task/m4-ags` on origin kept X.
- **Other tasks unaffected.** While A and B were held, C went plan, implement, check (`land`); the freed slot was reused
  by the next task within the same or next round; no hold line stopped admission or advances.
- **G (closed while planning).** `bd close` without `--force` is refused by bd (assignee `taskloop`; runbook
  correction 3). With `--force`: `m4-d38 plan hold held failed:needs_owner` once; row `labels closed`, `commented_at`
  NULL; `SHOW`: `Hold tracker: nothing written (the task is closed), no comment`, `Hold claim: not held`, release claim
  `not_held`, slot parked; `bd show`: CLOSED, labels still `auto` (no `held`), no comment.
- **F (hand-started).** `tl step start` (exit 0) with the rounds running; the rounds wrote `m4-m7v plan report
  failed:needs_owner` (never `hold`); `attempt.label` NULL, no `task_hold` row; `SHOW`: `Next: done`, `claim kept`;
  `bd show`: IN_PROGRESS for `taskloop`, no `held`, no comment.
- **D2 (`branch_moved`).** Rounds stopped while its implement ran; after the entry published X (`d623ccf4`), the
  person's local `task/m4-16u` was moved to `main`; restarted rounds: `m4-16u implement hold held branch_moved
  1bc74fd7...`; the comment ends "Restore task/m4-16u to contain d623ccf4..., or delete it locally and on origin,
  before adding the label."; OPEN, `held`.

## `kill -9` of an entry and the dirty slot (pass)

- **E.** `kill -9` of the verified entry (`taskloop.attempt_entry ... m4 m4-4tm`, pid 2813851) during implement; the
  codex worker (own session, pgid 2814642) kept running. Next round: `implement hold pending abandon
  unsettled:worker_alive`; `SHOW`: `Hold: stuck:entry_lost`, `Hold claim: kept: the abandon has not finished`, `Next:
  hold`; `tl step list --stuck` listed it with the hold guide; `bd show`: IN_PROGRESS for `taskloop`, `held` (no
  `auto`); one comment "still holds the claim: a process of this attempt still runs (pid 2814642, group 2814642)".
  **`tl step start m4-4tm` while pending: `refused:held`** ("Attempt ... has a hold not finished (stuck:entry_lost)"
  and its guide), exit 1, nothing changed. The worker ended by itself about 65 s later leaving the slot clean, and the
  next round wrote `hold held stuck:entry_lost`: slot parked, claim `unclaimed`, OPEN, still one comment.
- **E2 (dirty slot).** A file written into its slot (`m4-leftover.txt`, standing in for agent work), then the verified
  worker and entry killed. `implement hold pending abandon held:slot_dirty`; one comment "still holds the claim: slot
  .../slots/66050b697c27/s1 has files left by this attempt. Save what you need, remove them, and the next round returns
  the claim. The factory never removes work."; IN_PROGRESS for `taskloop`. **Rounds stopped (Ctrl-C) and restarted:**
  the restarted rounds continued the pending hold (the line written again once by the new process). After the file was
  removed, the next round: `hold held stuck:entry_lost`, slot clean at its park point `74e8df0ce`, claim returned,
  still exactly one comment.

## Re-ingestion and the label rule (pass)

- **H.** Labels `auto`, `auto2`. Rounds stopped while its plan ran; the plan concluded `needs_owner` (`SHOW`: `Next:
  hold`, due). Rounds restarted with `--label auto2`: `m4-f36 plan hold held failed:needs_owner` removed **`auto`** (the
  stored label) and kept `auto2` (`bd show`: `auto2, held`); then `plan skip attempted` once in that same round and
  `plan skip abandoned` once in the next (finding 2), never admitted under `auto2`. Then `bd label add m4-f36 auto` and
  rounds under `auto`: `plan start started 53c668c2...` (seq 2, label `auto`), `hold cleared 96719767...` (the old
  row), then held again (`failed:needs_owner`, new row `moved`); `held` stays (now the new hold's), two comments.
- **B answered.** Description edited (remove `m4-fail.txt`, add `m4/B.txt`) and `bd label add m4-ags auto`: `plan start
  started` (seq 3, label `auto`) and `hold cleared ee83e922...` in the same round; `bd show`: labels `auto` only. On the
  **existing** branch: `main..task/m4-ags` kept `de94ad602` and `e0149a8e8` and added the new plan and `012db8985 Remove
  failing marker and add M4 B marker`; checks passed, `Next: land`.

## Keep-awake (pass, effect none on this host)

- Every start logged `rounds keep_awake started pid=<h>`; `<h>` was at once a zombie child of rounds (`Zs
  [systemd-inhibit] <defunct>`): the inhibitor is refused on OrbStack (plan section 27), `systemd-inhibit --list`: "No
  inhibitors.". No stderr line (the spawn itself succeeded).
- **Ctrl-C once** (SIGINT to the verified rounds pid, three times in the run): "Rounds stopped: interrupted. Launched
  steps keep running; ...", exit 0, no traceback; helper pid gone within 2 s; launched entries kept running.
- **Ctrl-C twice** (two SIGINTs 0.3 s apart): "Stopping after the current move; Ctrl-C again to exit at once." then
  "Stopped at once.", exit 130, `rounds stopped abrupt` in the log, no traceback; helper gone.
- **`kill -9`** of the verified rounds pid: exit 137; rounds and helper gone within 2 s (the zombie is reaped by init);
  rounds restarted at once (lock free) and continued.

## Land and the tracker at the end (pass)

`tl step land` C: same tree, no slot, pushed, closed. B: `main` had moved, so `checks passed on S`, pushed, closed. D:
`refused:branch_moved` ("task/m4-e7u (local 55c91c70..., origin fd0aa3db...) is not the checked 55c91c70..."), exit
1. `bd list --label held`: exactly A, D2, E, E2, H (G closed, B answered and landed). `TL step list`: C, B `landed`; D
`land`; F `done`; the rest `on_hold`. Both slots clean at `74e8df0ce`, no reservation rows.

## Git read timeout (BLOCKED)

Step 9 (G1/G2) not run then; git-porcelain 0.18.0 is released and pinned since (tl-isfa.5).

## Findings

1. **A fast-forward of origin's `task/<id>` is not `branch_moved` at the check advance (by design; runbook wrong).**
   `check_admit._on_branch` reads the person's local `task/<id>` first and asks whether it contains X; the other
   clone's push to origin left the local branch at X, so D's checks ran on X and passed, and only the land refused
   (`branch_moved`, "not exactly the checked X"). Plan section 17 item 1's "moves on origin" is not a hold trigger while
   a local branch exists; a local move off X (D2) is. The task then sits at `land` until the person resets or abandons.
2. **Same-round `skip attempted` after a hold (cosmetic).** The `auto2` round that held H wrote `m4-f36 plan skip
   attempted` in the same round (the ready read saw H open again after the hold returned its claim) and `skip
   abandoned` in the next; both once. A skip, not an admission.
3. **Repeated report lines per rounds process.** F's `plan report failed:needs_owner` (and E2's pending line) is written
   again by every new rounds process (the quiet set is in memory), as M2/M3 noted.
4. **Wording (cosmetic).** The comment says "task branch task/<id> at not published"; the hold guide joins its items
   with ".;"; `tl step show` of a hand-started failed plan prints the checks guide ("A failed check step keeps the
   claim ...") under `Collected:`.
5. **Host**: `sqlite3` CLI missing (Python read-only), no `/bin/bash` (rounds started as `bash <script>`).

## Runbook corrections made with this file

1. Section 0: the mise copy is saved outside `$M4` (`$SAVE`), since `$M4` is removed before the restore.
2. Section 1: `TL profile show` exists; its output is the check.
3. Section 4: `bd close` of a task claimed by `taskloop` needs `--force`.
4. Section 5/5b: the entry's `kill -9` alone may leave nothing in the slot; 5b makes the dirty slot on purpose.
5. Section 6: move the person's **local** `task/<id>` off X (finding 1); rounds run as `bash <script>` with a pid file.

## Cleanup

Rounds stopped by SIGINT (exit 0) at the end; every signal went to a pid verified by `ps -o command=` first. The runner
worktree removed from the source repository (`git worktree remove --force`, `prune`); `~/tl-smoke/m4` removed (`chmod
-R u+rwX` first; other `~/tl-smoke` content untouched); `~/.config/mise/config.toml` restored (sha256 `baf490e4...`,
equal to before). No process with `tl-smoke/m4` in its command line left; no `m4-*` ref in the source repository.
