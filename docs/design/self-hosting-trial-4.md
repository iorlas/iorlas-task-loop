# Self-hosting trial 4: concurrency and recovery

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 against `main` at `8fe219905` (PR #736 merged). Linux only (OrbStack, aarch64), Codex, model `gpt-6.1-sol`,
effort `low`. Follow-up to [trial 1](self-hosting-trial.md) and [trial 2](self-hosting-trial-2.md) section 4. Vocabulary:
[glossary](../glossary.md). Tracker epic `tl-8bh9.14`. No factory code was changed. Other trials ran on the same machine at the
same time (load average 20 to 34), so every duration below is slow compared with trials 1 and 2.

**Result: the happy path holds with three slots and 23 tasks, and rounds survive kill, restart, a locked, read-only or
discarded `factory.db` and an unwritable artifacts directory. A person can not land under load (D1), a landing race is
misreported (D2), a short database lock loses a finished agent run (D3) and a discard leaves claimed tasks stuck (D4).**

## 1. Setup

`~/tl-trial4`, as in trial 2 section 1: a bare `remote.git` as `origin` (every `task/*` ref removed, `main` at
`8fe219905`), the person's checkout `repo`, a scratch tracker (`bd init -p t4`), `config.toml` with its own `db`,
`artifacts`, `slots_root` and `slot_count = 3`, three slots made with `git worktree add --detach` and adopted, the
repository's own `.task-loop.json`. Run only as `uv run --frozen --no-sync python -I -m taskloop --config ...` after `just
install`; mise trust through `MISE_TRUSTED_CONFIG_PATHS`. Rounds: `--every 15 --effort low --minutes 60`. Tasks: three that
each fill one adjacent line of one shared file, and 20 that each create one file `docs/t4/nNN.md` with one line, so the
agent work is tiny and the scheduler, checks and lands are what is measured. A fourth slot (`s4`) was added and removed
during the run. A process that had to be stopped was stopped by its recorded pid (`rounds started pid=` line or the
`entry_process` of `tl step list --json`), after reading `/proc/<pid>/cmdline`.

## 2. What was exercised and what happened

| Scenario | Result |
|---|---|
| 3 tasks at once, 3 slots, same file | All three planned, implemented and checked in parallel, no collision in the slots. Landing: first landed, the other two `refused:conflict` (adjacent lines), as it must. The recovery text is the dead end already filed as `tl-8bh9.14.30`, not refiled. |
| 20 tasks, distinct files | All 20 were planned, implemented and checked with three slots; 14 landed. The other 6 (t4-0vt, c0o, cw0, dnl, dp8, i7a) were claimed when the db was discarded and could not land: D4. Order is priority, then task id (`selection.py`): with the tracker's hash ids that is not creation order, as designed. Plan takes seconds, implement 1 to 5 min, checks 3 to 5 min with three at once on a loaded machine. |
| Two rounds at once (also started in the same instant) | The second answers `refused:rounds_running` with the holder's pid, exit 1. The `flock` lock works. |
| Three `tl step next` at once beside rounds | All answered `no_free_slot` or reported, nothing double-admitted. |
| Rounds killed with SIGKILL (confirmed pid), restarted | Restart logged `rounds started`, reported the running attempts and carried on; entries and agents survived. The stale lock file is harmless (kernel lock). Nothing in the log says the previous run died (D6). |
| SIGTERM | `rounds stopped abrupt` is logged. |
| SIGHUP (rounds without `nohup`) | Dies at once, no log line (D6). |
| Host restart simulation | A running attempt's `entry_boot` and `worker_boot` set to another boot id (my own write to the scratch db). Rounds answered `Entry: different_process`, hold `stuck:entry_lost`, worker `(not checked)`, then `unsettled:worker_alive`; nothing was signalled. The real entry then finished and lost the race: `conflict changed_admission`, `refused:not_captured`. Work stayed dirty in the slot, the hold finished after I emptied it. Safe. Note: `worker_gone` also asks `group_alive(pgid)` by number only, so after a real reboot an unrelated process group with the same id would keep `worker_alive` for ever. Theoretical, not filed. |
| Machine config changed (slot_count 3 to 2; 3 to 4) | Lowering changes nothing in the db (D7). A slot added with a new directory and `slot adopt` was used by the running rounds at once. A slot directory removed with `rm -rf` is skipped silently (D5). |
| Slot dirty by hand edit | An idle slot with a modified tracked file and an untracked file is never chosen, silently (D5). A slot left dirty by a held attempt is documented and worked. |
| `factory.db` locked (45 s exclusive) | Reads (`list`) work (WAL); rounds answered `unavailable:store`, waited 15 then 30 s and recovered. An entry did not: D3. |
| `factory.db` read-only (`chmod 444`, 40 s) | `list` works; rounds `unavailable:store`, `rounds wait seconds=15/30`, recovered cleanly, attempts survived. |
| `factory.db` discarded (moved aside) while three attempts ran | Entries died, nothing else. Every `tl step` answers `refused:database: No readable factory.db at this path; tl slot adopt creates it`. After `adopt` and a restart new tasks start, but see D4 (claimed tasks stuck, `branch_diverged` until each slot is detached, stale local `main`). |
| Artifacts directory unwritable (`chmod 555`, 45 to 50 s) | Rounds: `unavailable:log`, `start refused:input`, backoff, recovered with no hold. A land: D8. |
| Disk full | Not simulated: no safe quota in the scratch tree (no root, no tmpfs). The unwritable directory is the closest. |
| Long run | One rounds ran 30 min (13:01 to 13:31, two restarts before) and the next 15 min; RSS 43 to 58 MB then flat, open files 16 to 53 (13 to 28 on `factory.db`, limit 1 048 576), WAL 4 MB then checkpointed; `rounds.log` 28 KB for the whole 70-minute run (367 lines); an idle rounds writes nothing. No growth that matters; not run for hours. |
| `tl step list/show` while rounds write | 12 concurrent `list --json` while rounds and three entries wrote: 12 x exit 0, one key set, 0.4 s. Shapes are stable. |
| Many tasks | Rounds fill slots within a round. A running task logs a `report running` line each round (94 of the 367 lines of the whole run, 28 KB in 70 minutes); `round moves=N` counts these reports too, so a round that only waited reads as `moves=5`. Acceptable noise. |
| Concurrent lands | Lands are not serialised: see D1 and D2. 13 lands started together over a 10-minute window: 159 answers exit 3 (150 `no_free_slot`, 9 `target_moved`), 7 landed, 6 `refused:not_done` (the D4 tasks). |

## 3. Defects (one bead each, parent `tl-8bh9.14`)

| # | Sev | What | Bead |
|---|---|---|---|
| D1 | P1 | A hand `tl step land` starves while rounds runs: rounds refills every freed slot within seconds, the land needs a free slot to validate, 5 lands retried every 3 to 10 s got 6 to 39 `no_free_slot` or `slot_busy` refusals each over 10 minutes; only stopping rounds let them through | tl-8bh9.14.34 |
| D2 | P2 | Two lands pushing within a second: the loser is `refused:remote_rejected` ("by its own policy, not a race") on an origin with no hook or policy | tl-8bh9.14.35 |
| D3 | P2 | factory.db locked longer than the 1.5 s busy timeout while an implement entry ends: the finished work is lost as `stuck:uncollected` plus `held:slot_dirty`, `auto` removed | tl-8bh9.14.36 |
| D4 | P2 | After a db discard the 8 claimed tasks stay `IN_PROGRESS`, lease expired, not ready, never retaken; no message says so | tl-8bh9.14.37 |
| D5 | P3 | A removed or dirty idle slot is skipped silently; `no_free_slot` says "Every slot is held" | tl-8bh9.14.38 |
| D6 | P3 | SIGHUP (and SIGKILL) leave no log line; the restart does not say the previous run ended abnormally | tl-8bh9.14.39 |
| D7 | P3 | Lowering `slot_count` has no effect and `config show` reads as if it did; no way to retire a slot | tl-8bh9.14.40 |
| D8 | P3 | A land with unwritable artifacts says `unavailable:environment:files`, "fix it on the task branch or main" | tl-8bh9.14.41 |

Evidence in brief:

- **D1.** `L-*.tries` of the run: `try37 rc=3 ... unavailable:no_free_slot` for one task, `unavailable:slot_busy` ("Another land,
  entry or release holds the candidate's slot") for another whose parked slot rounds had reused. After `kill -TERM` of the rounds
  pid, four lands went through within three minutes. The help says rounds "fill it seconds after a slot frees"; that is the
  cause, not a coincidence.
- **D2.** t4-0vt and t4-b5a, `13:38:18Z` and `13:38:19Z`; `origin` pushed b5a; 0vt got `refused:remote_rejected`. The bare repo has
  no `hooks/` entry and no `receive.*` key. `land_push._refusal` maps every push result that is not `Pushed` or `RefRejected`,
  `Transient` or `HookRejected` to policy; a ref-lock failure on a concurrent push is none of those.
- **D3.** `artifacts/attempts/<t4-3pv implement>/entry.log`: `unavailable store publish=accepted then=pending:session_pending`;
  `diagnostics.txt` held a valid answer. Rounds then logged `hold pending abandon held:slot_dirty` and, after I ran `git clean`
  in the slot, `hold held stuck:uncollected`. `auto` re-added: retaken at plan.
- **D4.** `bd show t4-0vt`: `Lease: expires expired (heartbeat 13 mins ago)`; `bd ready` does not list it; `tl step release t4-0vt
  --abandon`: `refused:absent`. The factory's claim lease is 300 s (`claim_lease.py`). The same section of the guide as D4: after
  the discard each slot still sat at a task commit and every start refused `branch_diverged` until `git switch --detach main`
  in each slot, and the person's own `main` was nine land commits behind (the land prints `git pull --ff-only`).
- **D5.** `s4` removed: `tl step next` stopped `no_free_slot` with three reservations; recreating the directory and `slot adopt`
  made rounds use it in the next round. The hand-edited idle slot was skipped for 10 minutes without a word.
- **D6.** `SigIgn 0x1001006`, `SigCgt 0x4000` (SIGTERM only) for a rounds without `nohup`; `kill -HUP`: gone, log ends at the previous
  round. The documented behavior covers Ctrl-C and SIGTERM only.
- **D7.** `tl config show` with a two-slot copy of the config printed `slot_count = 2 (file)`; the db had `s1 s2 s3`.

## 4. Other observations (not filed)

- **Landing is not serialised and costs O(n) checks per lost race.** On one moving `main`, 13 lands started together took 10 minutes for 7 landings; each `target_moved` re-ran `just check` and
  `just test` (2 to 3 min each, three slots). With ten tasks ready this is a thundering herd; `merge-queue.md` is the design answer, not built. D1 makes it worse.
- **Lease between steps.** The claim lease is 300 s and "nothing renews it" between steps; tasks waited 5+ minutes at `Next:
  advance` for a slot under load. They were retaken without trouble here (same actor), but the tracker showed an expired lease
  on a live task.
- **`tl step list` never shrinks.** Landed and abandoned tasks stay in the list (and `--json`) for ever; a landed task still
  shows a `Slot:` that another task now holds. A dashboard needs a filter or a limit.
- **A network flake in `setup`** (`pyrefly` download timed out after 130 s) failed one entry (`unavailable environment:exit`); rounds
  relaunched it and `setup` ran again, no hold. Good.
- **Restart with an unfinished session** (rounds only killed): attempts and agents carried on; this is the path that works.
  SIGTERM of the entry itself is trial 2 F2.
- **Recovery after `held:slot_dirty`** worked exactly as the guide says (empty the slot, `auto` back, retaken at plan).
- My own slip: `pkill` by name once, refused by the sandbox before it ran; nothing was killed by name.

## 5. Not covered

Disk full proper, runs of hours, macOS, a real reboot (the boot-id change was written by hand), a push race inside Git itself with
a deterministic reproduction for D2, two rounds on two different backlogs on one db, a rejected verdict and `needs_owner`.

## 6. Verdict

Several slots do what they should. The hand land is the weak point under concurrency: it can not get a slot while rounds runs
(D1), it races other lands blind (observations) and misreports the push race (D2). Recovery from every crash I could cause with an
intact database is clean; a short lock (D3) and a deliberate discard (D4) are the two ways found to lose or strand work. Fix D1 and
D4 before an unattended run with more than one slot.
