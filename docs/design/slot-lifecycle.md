# Slot lifecycle: one owner for prepare, verify and cleanup

Status: DRAFT for discussion, 2026-11-07. Nothing here is built. Sections marked (scan) wait for the entity scans; claims from them are checked against the code before they stay.

Verified against origin/main at `d9c56c4a` (2026-11-07). Many beads will change this code (C-PIPELINE, C-THIN, D-LANES, merge queue, tl-eip4), so every file:line below is a pointer, not a fact: re-verify a claim against the tree before building on it. Scan results come from Haiku agents; only the claims marked "checked" were read by hand.

## 0. The problem

The same slot job is done in several places, and stages ask git for facts the engine already holds.

- 20 stage-side asks for the work tree's branch, in 15 files (`git.branch(wt)`), each a private safety check or a copy of `e.branch`.
- `land/tree.py` and `slots/reset.py` both reset the tree: fetch, save work, check out the task branch, free the branch, leave the slot. Two wip-commit formats.
- Two "run setup only when the input hash changed" paths (`slots/reset.py`, `checks/linux.py`).
- The engine lock and the slot lease record one fact, "who holds this slot", twice.
- Free disk is read in three places; a rebase-in-progress probe in four.
- `gitmemo` (adapter) exists only because of the repeated git asks.

History: `app/slots` was a move out of the old `tl.py` (2026-10-28), and later pieces (fence, aside, watchdog) followed incidents. It was patched per failure, not designed as a lifecycle.

## 1. Principles (owner)

1. **Stages are blind.** A stage gets facts (`wt`, `branch`, `bead`) and ports. It never checks or sets up the environment. Its own git work (commit, diff, rebase for land) stays.
2. **The slot owns the environment.** Every slot has a state machine. Before a stage: prepare. After it: verify and clean up.
3. **Fail first, fail fast.** A fault keeps the slot and the stage retries; no storm mechanism, no extra monitoring (tl-eip4).
4. **One path per fact.** One owner record for who holds a slot; one reader per measurement; no re-check of what the slot already knows.

## 2. Slot state machine (draft)

```
absent -> created -> setup -> free -> leased(bead) -> preparing -> ready -> running(stage)
                                  ^                                            |
                                  |                       verifying <----------+
                                  +-- cleaned <-- (ok) ---+--(fault)--> retry stage on the same slot
broken (setup or reset failed): set aside, probed later (today: slots/aside.py)
removed: worktree and scratch deleted by the slot
```

Open: whether `preparing` and `verifying` are states or steps inside `running`.

### 2.1 Observe, converge, check (owner direction, 2026-11-07)

State is what is on disk, git and bd, read once by one function (`observe_slot`). It is never stored as a state name.

1. Before a stage: `observe_slot` gives the actual state; `desired(bead)` gives the wanted one (task branch checked out, no rebase, leftovers committed with a warning, setup done for its inputs, lease ours, run folders present). The prepare step converges the difference, one fix per difference.
2. The stage runs, blind.
3. After the stage: `observe_slot` again. Any deviation not on the allowed list (HEAD off the branch, an added worktree) fails the bead with FAULT_ENGINE and the difference in the log.

`app/reconcile` already has this shape for beads, leases and trees (observe -> diff -> apply). The slot should reuse it and not add a second one. Limits: converging never wipes; the only fix for unsaved work is the leftovers commit. `observe_slot` reads few facts (branch, HEAD, status, lock row), because every file read costs time on the Mac.

## 3. Prepare (before every stage)

Composed of independent parts, run in this order. Each part is one small function with one test.

| part | job | today's home |
|---|---|---|
| lease | the slot is ours; one holder record | `slots/lease.py`, `marks.py`, `engine_lock.py` (merge) |
| rebase | abort a rebase left by a crash | 4 copies |
| branch | `task/<bead>` exists and is checked out; if another worktree holds it, detach it there | `slots/reset.py check_out/free_branch`, `land/tree.py` (merge) |
| leftovers | uncommitted work is committed, and the log gets a WARNING | `keep_work`, `Tree.wip` (merge to one) |
| setup | the repo's own `slots.setup` argv, skipped when `setup_inputs` hash is unchanged | `slots/reset.py setup`, `checks/linux.py` (merge) |
| command env | the `TL_*` names every command gets | `run/bead_env.py`, `checks/step_env.py` |
| run folders | run dir outside the work tree, `.task/<bead>/` inside | `run/layout.py` |

Setup commands come only from the repo's `.task-loop.json` (argv list). The OS and repo differences live there, not in the engine.

## 4. Verify and clean up (after every stage)

| part | job | today |
|---|---|---|
| on branch | HEAD is on the task branch (detached only mid-rebase); else FAULT_ENGINE, bead logged with the reason | `workers/strays.py` (rename), once per worker call |
| leftovers | commit if any, with a warning | `pipeline/closing_branch.py` |
| leave | slot detached at base when the bead ends | `Tree.leave_slot` and `slots/reset.py leave_slot` (merge) |
| remove | worktree and its scratch removed when the slot is removed | `wire/slots.py`, `land/cleanup.py`, `release/tidy.py`, `prune/slotstate.py` |

Open: keep the added-worktree check (a worker runs `git worktree add`)? Open: a deny rule in the PreToolUse hook for `git checkout/switch` in a task tree, as the only guard, or beside the check.

## 5. What leaves the stages

- All `git.branch(wt)` asks except the prepare and verify steps; stages read `branch` from the run facts.
- `adapters/gitmemo.py` (proposed): its only purpose is to make the repeated asks cheap.
- Free-disk waits and readers (`loop/waits.py` wait on disk, the three `disk_usage` readers): a full disk is a fault like any other, retried later. Doctor's days-to-full report is a separate question.
- `engine_busy` (proposed): replaced by the lease's holder.
- The storm adapter, domain rule, loop wait and knobs (tl-eip4).

## 6. Process model (scan, to settle before the lease merge)

The owner's chain is slot -> stage -> delegate -> job. The code has three process levels (loop scan, Haiku, not cross-checked):

```
tl loop            (own session, state row in factory.db; re-execs in place on upgrade)
  `- run-task      (one process per bead, own session; loop/run.py:74 -> adapters/spawner.py start_held)
       `- worker call   (in-process: delegate.api.run on a thread, no child for the router)
            `- vendor CLI worker   (any_agent supervisor, own session)
```

So "one slot, one stage, one delegate" holds inside `run-task`, but the loop and `run-task` are two processes, and hand-run `tl slot reset|release|run-task` makes a third writer. That is why the engine lock names a pid. The merge of the engine lock into the slot lease needs one rule for pid liveness: today it is decided separately in `loop/files.py`, `Ticket.alive` (kernel), `slots/engine_lock.py` and `delegate/app/lease.py`.

Other doubles from the scan: dead-claim release is applied by `launch/loop_ops.py`, `run/entry.py` and `reconcile/leases.py`; a worker call has four wall-time clamps; a bd heartbeat (`slots/lease.py`) and a delegate heartbeat (`delegate/app/lease.py`) beat for the same run.

## 7. Entity lifecycles (scan)

Entities to document, each with: stored where, states, creator, mutators, destroyer, duplicate sources. Slice reports pending.

| entity | slice | status |
|---|---|---|
| slot, worktree, task branch, lease, fence, marks, aside | slot scan | pending |
| run, run folder, checkpoint, steps, logs, traces | run scan | in (Haiku, not cross-checked), see section 8 |
| bead, claim, ask, pause/wait, fault kinds, reconcile | bead scan | in (Haiku, not cross-checked), see 7.1 |
| loop, ticket line, run-task, worker call, delegate job | loop scan | pending |
| land, merge queue, gate, release | land scan | pending |
| every persisted state family and its deletion rule | state scan | in (Haiku, not cross-checked), see 7.2 |

### 7.1 Wait and retry mechanisms today (bead scan)

Eleven ways to wait, each with its own trigger and its own place for the wake time:

| mechanism | trigger | wake stored in |
|---|---|---|
| disk/RAM wait | low resource | loop state file |
| storm (tl-eip4 removes it) | same fingerprint on 2 beads in 30 min | file; `clear_storm` has no caller (checked) |
| role gate | role unusable | memory |
| transient park | transient pause | park table `retry_at` |
| rest | fault or 3 pauses | rest JSON and counters |
| network | network pause | memory |
| no lane | every bead waiting | memory |
| ask park | no answer in 3 days | ask row |
| deferred intake | daily budget | bead status |
| slot aside | quick failures | memory |
| lease | live run | bd `lease_expires_at` |

"Three tries" has three separate budgets (`fault_retries`, pause `max_attempts`, `lane_poll`). `kernel/kinds.py` has 27 outcome kinds while the `outcome.py` docstring says 23.

Direction (draft): under "a fault keeps the slot and the stage retries", the slot state machine carries one retry record (attempt, next try). Disk/RAM wait, storm, rest and aside collapse into it; network, lane and ask keep their own wake because the cause is outside the slot.

Doubles named by the scan: a stopped bead is put back to open in `closing_settle.py` and `loop/run.py`; the park gate is evaluated in `loop/stages.py` and `run/entry.py`; three modules reopen a blocked bead on an answer.

### 7.2 Persisted state (state scan)

Files that the repo's own rule ("factory.db is for state") puts in the DB: run plan and check results (`runs/<run>/*.json`), `storm/`, `shared/<repo>.json` (flaky notes), `loop.pid` and `dash.pid`, ask sweep markers, `slots/<key>.setup` (the setup mark). Everything else in the scan is a log, an evidence file or the DB already.

Held twice: loop exit (`factory.log` and `exits.jsonl`); owner asks (bead comments and the `ask_ledger` table, which the sqlite plan says to drop); usage (`lanes_doc` and `usage-history.jsonl`); run end (`run` row, manifest blob, `traces.jsonl`, `timed`, `engine.jsonl`, `events.jsonl`, bd `landed_*`); loop pid (file and lease row). `Stores.flakes` and `SharedNotesStore` have no caller.

No deletion rule: `wait` rows (and they block run pruning), `died-*` loop rows (the retention rule targets files nothing writes), engine lock rows, `followup`, `storm/`, `shared/`, setup marks, `profile-changes.jsonl`, `decisions/uses.jsonl`, `artifacts/`.

Raw readers beside the store: `storm.py` parses `traces.jsonl` itself; `hook/prepush.py:77` reads `kv repos` by SQL.

## 8. Pruning (open)

What a run leaves behind and its deletion rule today (run scan, Haiku, not cross-checked):

| left behind | deleted by |
|---|---|
| factory.db run, attempt, step rows | `tl prune`, past kept days (max(keep_days 14, 30)) |
| factory.db checkpoint | dropped by resume, standalone, restart; no prune rule |
| factory.db wait rows | no rule found |
| `runs/<run>/` folder | prune, past kept days and bead closed |
| engine log, stderr, live/ | prune, past keep_days |
| traces.jsonl rows | prune, past keep_days and not LANDED |
| `<cfg>/artifacts/` | no rule found |
| `.task/<bead>/` in the worktree | no rule found |
| land and check scratch dirs | 1 day |

Four prune modules (`layout.py`, `prune/runs.py`, `prune/traces.py`, `prune/retention.py`) apply three different protection rules. Run-scan doubles: the Close record and the trace row are each written by `closing_record`/`journal` and again by `finish_projection`; the terminal state is written in four places; `replan.md` in four. `RunState` is defined twice (`tlkernel/checkpoint.py:72`, `tlkernel/run.py:167`). `resume.py:172` re-reads branch and head that the checkpoint already stores.

Moving files at the end of a slot does not remove run folders or logs: the dashboard and resume read them. One age rule in one place stays needed. Questions: which files are the slot's (deleted with it) and which the run's (kept by age)?

## 9. Decisions recorded

| id | decision | by | status |
|---|---|---|---|
| D1 | Remove storm; fault holds the slot, stage retries | owner 2026-11-07 | filed tl-eip4 |
| D2 | Stages are blind to the environment | owner | agreed |
| D3 | Slot owns prepare, verify, cleanup as a lifecycle | owner | agreed |
| D4 | Wip commit is a workflow step that warns when it finds work | owner | agreed in discussion |
| D5 | Setup sequence lives in the repo's `.task-loop.json` | owner | agreed |
| D6 | Remove free-disk handling | owner | agreed in discussion |
| D7 | Worktree removal belongs to the slot | owner | agreed |
| D8 | Remove gitmemo; stages read `branch` from the run | proposed | open |
| D9 | One holder record (lease) replaces the engine lock | proposed | open, needs section 6 |
| D10 | Remove the whole migration system (section 13): layout and key migration, DB schema steps, config old shapes, aliases, silent skips. Only the current version is read; an old one is refused loudly | owner 2026-11-07 | agreed, not filed |
| D11 | Remove quarantine (`quarantine_versions`, `quarantine_if_needed`): an old DB is refused, not moved aside | owner 2026-11-07, read from "quarantine, all this stuff, just" | agreed in discussion; answers question 7 |
| D12 | Ids: each id kind gets one module that makes and parses it (section 12); no id is removed | proposed | open |
| D13 | Rebase is removed from the factory: a branch is updated by merging main in, landing stays squash (one commit per bead). All rebase code goes (section 14.6). Reason: landing squashes, so the branch's private history is discarded and rebase buys nothing; merge needs no force push and has no rebase-in-progress state | owner 2026-11-07, read from "decide that right now" | agreed in discussion; in-slot case follows the same rule; no bead filed |
| D14 | Remove the base-red check ("was this check already red on the untouched base"): a red check is red, the writer fixes it in the same slot. All its code, records and words go (section 14.8) | owner 2026-11-07 | agreed in discussion; no bead filed |
| D15 | Glossary words: `pass` replaces `receipt`; the reduced vocabulary of 15.11 is the direction | owner 2026-11-07 ("Yes, pass") | `pass` agreed; the rest of the list is the proposal the owner reacted to with "all, but reduce num of words" |

## 10a. `app/reconcile`: keep, shrink or drop

What it is (~830 lines, `app/reconcile` + `domain/reconcile`, added 2026-10-30, `e7a41f1a`): `observe` reads bd, branches, worktrees and leases as typed facts; a pure `diff` turns them into actions; `apply` runs each action against the oid or lease generation it was observed at. It exists because processes die and leave orphans: a dead claim, a slot nobody holds, a landed branch, a build tree.

Callers: `run/entry.py`, `loop/loop.py`, `launch/loop_ops.py` (release dead claims); `prune/verb.py` (tidy); `land/queue_recover.py`; `doctor`, `report/card`, `asks/owner_verbs`.

Parts and a first verdict (draft, `diff.py` not read in full):

| part | job | verdict |
|---|---|---|
| `leases.release_dead` | give back claims whose lease ended with no live run | keep, as the one place; today three modules call the rule (`loop`, `entry`, `loop_ops`) |
| `sweep` + `apply` | prune's tidy of build trees, release branches, landed task branches | keep the idea; the slot-owned parts (its worktree, its scratch) move to the slot lifecycle |
| `lost` + `commits` | `tl lost`: a report of commits no run will bring home | candidate to drop: a diagnostic, and the owner's rule is no extra monitoring |
| `loopwatch` | the "absent loop" finding | candidate to drop: same reason |

With the slot's observe-converge-check, most of the lease and tree repairs are done at the next prepare. `reconcile` shrinks to the cross-process ones: a run died and its claim must be given back.

## 10b. Adapters (in progress)

One row per adapter in `src/taskloop/adapters` (42 files, about 3,900 lines). Verdicts are drafts. Done so far:

| adapter | job | verdict |
|---|---|---|
| `storm.py` | one self-expiring file per repo for the failure-wave breaker | delete (tl-eip4) |
| `gitmemo.py` | cache of read-only git answers, vouched by file signatures | delete once stages stop asking git (section 5) |

Git family (scan, Haiku, not cross-checked; the scan said "keep, rename" for gitmemo, the owner direction above overrides):

| adapter | job | callers | verdict |
|---|---|---|---|
| `git.py` (RealGit) | the one real implementation of the Git port | 1 in src (`wire/real.py`) | keep; the name says a technology, `real_git.py` |
| `git_base.py` | runs git, turns stderr into typed errors | 4 | merge with `git_pool.py`: two classifiers do one job |
| `git_ops.py` (LandGit) | counts, commit, push, rebase writes | 1 (`git.py`) | merge into `git.py`: a three-level class chain (GitBase, LandGit, RealGit) for one implementation |
| `git_pool.py` | maps porcelain exceptions to slot errors | 2 | merge with `git_base.py` |
| `gitrepo.py` | reads `.git` files with no git process | 15 | keep; it answers path questions at no process cost |
| `base_tree.py` | temporary detached worktree for the gate and checks | 3 | keep; goes with the slot's worktree duty (one maker of worktrees); no direct test |
| `treehash.py` | tree id the worktree would commit; ignore rules | 3 | keep; split the ignore helpers out |
| `repourl.py` | one repo key: origin URL, else common dir | 5 | keep |
| `slotcheck.py` | detects `core.worktree`/`core.bare` redirecting a slot | 1 (`run/parts_run`) | keep as a prepare check; its own `_MEMO` goes with gitmemo |

Memo layers: three (gitmemo, the vendored porcelain `real_cache`, `slotcheck._MEMO`). Deleting gitmemo and `_MEMO` leaves one. Tests: `base_tree` has no direct test; `gitmemo` and `slotcheck` only through `tests/adapters/real/test_git_memo.py`.

bd, checks and delegate family (scan, Haiku, not cross-checked):

| adapter | job | callers | verdict |
|---|---|---|---|
| `bd.py` | the one place that starts `bd`; implements the kernel `Beads` port | 5 | keep |
| `bdids.py` | tracker prefix of an id, ids named in prose | 2 | merge into kernel `ids.py` (id parsing is split across two layers) |
| `bdcreate.py` | create a bead; on bd's "missing section" refusal add filler and retry once | 2 | not an adapter: a retry policy; move into `land/followups.py` |
| `beadtools.py` | `bd_store()` factory, `must()`, re-exports of kernel `bdsafe` | 21 | rename `bead_store.py`; drop the re-exports (two import paths for one job) |
| `delegate.py` | `DelegateRoute`: calls the delegate library | 1 (`stores/delegate.py`) | keep; `stores/delegate.py` is a pass-through to check |
| `delegate_wire.py` | decodes delegate's JSON into a result; builds stop records | 2 | rename `delegate_answer.py`; `app/workers` imports it although the port says no app module imports the adapter |
| `check_files.py` | tree listing, ignored files, file digest, `repo_key()` | 15 | split: `repo_key` duplicates kernel `ids.loop_key`; the rest is cache inputs |
| `check_net.py` | argv prefix that removes a check's network | 1 | keep; rename `netisolate.py` |
| `check_probe.py` | which words resolve on PATH, justfile recipes | 3 | keep; rename `path_probe.py` |
| `suiteout.py` | parses pytest output into a failure report | 1 | not an adapter (pure text): move to `app/release/` |
| `looks.py` | visual shot table: parse, argv, collect, downscale | 6 | rename `shot_table.py`; app/look holds part of the same job |

No direct test: `delegate`, `check_files`, `suiteout`, `bdcreate` (indirect only).

Migration, identity and misc (scan, Haiku, not cross-checked):

| adapter | job | callers | verdict |
|---|---|---|---|
| `key_migrate.py`, `layout_migrate.py`, `layout_paths.py` (~290 lines) | one-time move of old config layout and old repo keys | `ident.py` runs the gate on every `tl` verb | delete: the no-compat rule says old data is discarded. The scan saw the old dirs gone on this machine; the Mac factory is not checked. Also `tlkernel/factorymigrate.py` is a fifth migration. |
| `ident.py` | config dir, hostname, `Identity`, plugin root and version | 32 in src | keep, shrink: it imports `layout_migrate`, so an identity module depends on a migration; `PLUGIN_ROOT` is an ambient global |
| `links.py` | URLs from added diff lines; opens them, blocks private hosts | 1 (`review/link_check`) | keep; the only host-side network use; review its `carries_data` heuristic |
| `profile_at.py` | reads `.task-loop.json` at a commit or in the tree | 6 | keep |
| `markers.py` | lists conflict markers with `git grep` | engine argv, `land/fixer` | rename `conflict_markers.py`; three more marker checks live in the vendored `git_porcelain` |
| `factory.py` | `caffeinate` for a pid on macOS | 1 | rename `keepawake.py`; `app/launch/factory.py` aliases it to avoid a clash |

Process and OS family (scan, Haiku, not cross-checked):

| adapter | job | callers | verdict |
|---|---|---|---|
| `procs.py` | start, wait for and stop child process trees | 11 adapters | keep; `src/delegate` has a second `procs.py` for the same job |
| `spawner.py` | the real `Spawner` port | 1 | keep |
| `pidcheck.py` | is a pid alive, and is it the same process | 3 | merge into `procs.py`; kernel `locks.pid_alive` is identical |
| `halt.py` | SIGTERM sets a stop flag, stop at safe points | 3 | keep; move `RUN_SLOT` out; signals are handled in four places |
| `deadline.py` | run-wide budget clamping child and wait timeouts | 7 | keep |
| `threadflag.py` | a bool attribute separate per thread | 2 | rename `per_thread.py`; no test |
| `ram.py` | macOS `vm_stat` text into free MB | 1 (`loop_ops.available_mb`, feeds `loop/waits.py` min_ram_mb wait) | delete only if the RAM wait goes; the owner decided disk, not RAM (open); the Linux path returns None |
| `locks.py` | named cross-process locks with holder files | 10 | keep |
| `landlock.py` | repo land lock per origin, `tl land-lock` | 9 | rename `land_lock.py` (collides with the Linux Landlock name); move `canonical_remote` to `repourl.py` |
| `clock.py` | `SystemClock` | 2 | keep |
| `childenv.py` | every child's environment | 16 | keep |
| `runner.py` | `ApiRunner`: the delegate call on a thread with a wall limit | 1 | merge into `agent.py` (same thread and cancel pattern); no own test |
| `agent.py` | `ApiAgent` thread wrapper, live-file readers | 4 | keep |

Overlaps named by this scan: pid liveness (5 implementations: `pidcheck`, kernel `locks.pid_alive`, kernel `Lock.alive`, delegate `lease.orphan`, direct `proc_start` calls); process stop (`procs.stop_tree`, `loop_ops.stop_tree`, `landlock.run_locked`, delegate `kill_tree` and `reap`); wall limits (`deadline`, `ApiRunner`'s timer, delegate `timeout_s`, `BACKSTOP_S`); two `procs.py`; signal handlers in four places.

Cross-check of the delete and merge verdicts against callers (2026-11-07, read by hand with grep; callers, not behaviour):

| verdict | result |
|---|---|
| delete `storm` | holds (callers: `closing_decide`, `launch/loop`, tests) |
| delete `gitmemo` | holds, with one move: `doctor/profiles.py` imports only `ref_files` (the list of files a ref question reads), not the cache, so that helper moves to the doctor or goes; `git.py:256` only has a comment about it |
| delete the migration trio | holds, and it removes three touch points: the gate in `ident.layout_stop` (called at `tl.py:495` on every verb), the `tl layout migrate` verb in `track/verbs.py`, and the old-layout message in `wire/doctor.py`. `tlkernel/factorymigrate.py` is the DB schema step list (versioned upgrades of factory.db), a different thing; the scan wrongly counted it as a fifth layout migration |
| delete `ram` | conditional, see its row |
| merge `pidcheck` | holds, direction corrected: the kernel is the lower layer, so the adapter goes and callers use `tlkernel.locks.pid_alive`; the two differ only by input type (`pidcheck` takes `object` and adds `proc_start`) |
| merge `git_ops` into `git.py` | holds: one subclass, one user |
| merge `git_pool` with `git_base` | partly: the two classifiers take different inputs (`classify` reads stderr text, `pool_error` reads porcelain exceptions), so it is one file `git_errors.py`, not one function; `app/land/push_evidence.py` imports `git_base.push_error_line`, an app-to-adapter-internal import to fix |
| merge `runner` into `agent.py` | weak: `ApiRunner` has one user (`adapters/delegate.py`); moving it next to `delegate.py` is as good |
| `bdids`, `bdcreate`, `suiteout` leave adapters | holds: 2, 2 and 1 callers, all in the app |

Totals across the four scans (42 adapters): delete 6 (`storm`, `gitmemo`, `key_migrate`, `layout_migrate`, `layout_paths`, `ram`); merge 7 (`git_ops`, `git_pool`, `bdids`, `bdcreate`, `pidcheck`, `runner`, `suiteout` out of adapters); rename about 15; the rest stay.

## 10. Open questions

1. Deny rule, after-check, or both for a moved branch?
2. Keep the added-worktree check?
3. States vs steps for preparing and verifying.
4. Where the package lives: `app/slots` grown, or a new stage package under `packages/` (docs/design/stage-packages.md).
5. Order of work: duplicates merged first, or the new lifecycle first?
6. RAM wait: drop with the disk wait? (`ram.py` depends on it.)
7. `quarantine_versions={1}` in `factorydb.py` moves an old DB aside and makes a fresh one; the owner rule says refuse loudly. Which wins?

## 11. Entity-centric map (six scans, Haiku, docstrings and names only, not cross-checked)

Test: a module is entity-centric when all its behavior is one entity's lifecycle. Primary-entity counts by layer (the entity list had no "review" or "plan"; the scans folded them into check-gate and worker-call):

| entity | domain, stores, cli, hook | kernel | app | reading |
|---|---|---|---|---|
| check-gate | 27 | 9 | 40 | big, and mostly consistent (rules in domain, runs in `app/checks`) |
| worker-call | 13 | 4 | 26 | per-stage prompts in seven packages, by design |
| land-queue | 14 | 4 | 10 | rules in domain; but `app/land` (45 modules) mixes branch (11), queue (8), checks (8), bead (4) |
| run | 9 | 12 | 22 | |
| bead | 8 | 7 | 23 | verbs in `asks`, `loop`, `track`, `wire`, `launch`, `reconcile` |
| ask | 8 | 9 | 17 | |
| slot | 4 | 2 | 16 | plus 10 kernel modules touch it (`slots`, `slottable`, `worktrees`, `worktreerows`, `fence`, `locks`, `events`, `reconcile`, `needs`, `dash`) |
| claim-lease | 1 | 4 | 6 | touched by 7 kernel modules |
| worktree-branch | 5 | 4 | 19 | in `land`, `pipeline/closing_branch`, `workers/strays`, `write/newfiles`, `slots`, `reconcile`, `release/tidy` |
| identity-id | 0 | 2 | 2 | no owner; see section 12 |
| release | 0 | 0 | 14 | no domain rules and no kernel records; `dev/release.py` beside it |

Findings:
- **Packages named by a verb or a metaphor, not an entity:** `launch` (serves loop, checks, dashboard, selftest), `wire` (repo config, asks, lanes, hook, handoff, slots), `track` (bead verbs, run queries), `doctor`, `prune`, `reconcile`, `report`. Each cuts across entities. These are the scattered behaviors.
- **27 app modules marked "no entity"** are the host, parts and ports Protocols per package (`run/parts_*`, `closing_host`, `lander_host`, `*/host.py`). They carry check and worker behavior behind a wiring label.
- **Most-mixed modules:** `run/engine` (seven entities), `pipeline/run`, `land/lander`, `pipeline/closing`, `run/entry`, `wire/slots`, `prune/verb`, `report/card`, `release/flow`, `launch/loop`, `loop/take`, `reconcile/observe`, `track/verbs`.
- **Intended spread:** checkpoint state in seven packages follows the stage-isolation design (each stage owns its state), not a defect.
- **Kernel I/O:** the kernel scan counted ~17 modules with OS or file calls and ~15 with sqlite against a "records only" rule. That rule is written for each stage package's `contracts/` in CLAUDE.md, not for the kernel. Not treated as a finding until checked.

Direction (draft): packages follow entities (`slots`, `runs`, `beads`, `asks`, `loops`, `lands`, `checks`, `releases`, `config`, `identity`); the verb packages dissolve into them. Not decided.

## 12. Identifiers (id scan, Haiku; four claims checked by hand: yes)

One kind of id, one place that makes and parses it. Today (checked items marked):

| id | duplicates | owner |
|---|---|---|
| task branch `task/<bead>` | `TASK = "task/"` in 4 modules (checked) and ~12 inline spellings (checked); `run/target.py` takes a bead from a branch without validating | `tlkernel/ids.py` |
| stale branch `-stale-<ts>[-N]` | made in `land/restart.py` and `land/tree.py`; the `-2` suffix is not matched by the stripper, so `reconcile/commits.py` may read a stale branch as a bead | `ids.py` |
| repo key | `slots/owned.key_of` is a copy of `ids.loop_key` (checked); `check_files.repo_key` a third; the vendored `git_porcelain` hashes `common_dir[:12]` | `ids.py`, one function |
| repo url | raw origin hashed for storm, review lock, release clone; canonical form for the land lock | one `remote_key(url)` |
| worktree key | `sha1(realpath)[:8]` in `owned.py`, `sha1(raw)[:12]` in `reset.py` | `paths.py` |
| bead id | `is_bead_id`, the `WireBead` regex, the `bdids` prose regex each define the charset | `ids.py` |
| run id | `RunId.parse` raises, `RunId.of` returns None, dash uses plain strings; delegate uses `uuid4` | `ids.py` |
| actor / session | `ACTOR_PREFIX` used once (checked); `"tl-"` literal in 5 places (checked); `wire/slots.py:310` rebuilds an actor from a `loop-` folder name | `identity.py` |
| pid + start token | five wrappers over `stream_proc`; `Ticket.alive` ignores the start token | new `tlkernel/proc.py` |
| fence generation | two writers: `fence.take` and `slots/marks.py` | `fence.py` |
| slot name from bead title | `b.title.split()[-1]` in 4 places | `app/slots` |
| attempt folder | `rpartition` in two places, `removeprefix` in three | `paths.py` |

`identity-id` has no primary module in the app or domain; its code is `ident.py`, `ids.py` and callers. This is why ids are scattered.

## 13. Removing migrations (owner direction: only the current version is read; an old one fails loudly)

Scan (Haiku, not cross-checked; three spot checks: the config tables, `factorymigrate` and the delegate legacy data dir exist as described):

| group | what goes | note |
|---|---|---|
| layout and key migration | `layout_migrate.py` (172), `key_migrate.py` (102), `layout_paths.py` (14); the gate `ident.layout_stop` run on every verb; the `tl layout` verb; the doctor warning; `wire/doctor.legacy_line` | tests: `test_layout_migrate`, `test_key_migrate`, `test_legacy_sessions` |
| landed-before-record fallback | `reconcile/commits.legacy_lands`, the `legacy` arg of `lands_of`, `observe.py` git-log branch, `lifecycle/matchers.land_bead`, `loop_ops._landed_on_base` fallback | keep the record only |
| DB schema steps | `tlkernel/factorymigrate.py` (27), `steps=` in `factorydb.py`, `factoryparts.add_park`, `discard_old_pin`, `dbparts._upgrade` | the version check stays and becomes a refusal |
| vendored `sqlite_store` | `migrate.upgrade`, quarantine | vendored from the shelf: change upstream (`dev/vendor.json`) |
| config old shapes | in `tlkernel/config.py`: `RETIRED_ENGINE/CHECK` (silently accepted keys), `RENAMED_*`, `GONE_ENGINE`, `renamed_keys`, `retired_keys`, `say_retired` | renamed and gone keys already fail loudly; retired keys are the silent ones; the rule "unknown field is refused" covers all |
| other old shapes | `checkpoint.py` `forbid_unknown_fields=False`; `answers.py` `LEGACY_KINDS`; `gateplan` aliases `id`/`why`; `tl check` alias `gate`; `ident.py` fallbacks for old Claude Code env names; `envvars.NOT_VARIABLES` entries; ask orphans (`asks/sweeps.reask_orphans`, `askstore.orphans`) | |
| dash silent skips | `readers/dbruns.read_kept` serves the last good read on a foreign schema; `readers/records.py` skips rows of another version | show the error instead |
| delegate library | `RETIRED_SETTINGS`, `RETIRED_STATE`, `LEGACY_DATA` + `adopt_legacy`, `doctor` alias `init` | `src/delegate` is a library in this repo; the same rule applies |

Must stay (refusals, not compat): `wire.load` `StaleRecord`, `docstore` `ForeignVersion`, the schema version check, `tl rollback`, `reload_fallback`, delegate capability handshakes, the fixed-path shim used by dev checkouts.

Open: `quarantine_versions={1}` (silent move-aside of a v1 DB) conflicts with the loud-refusal rule; see question 7.

Size: the three layout files and `factorymigrate` are ~315 lines; the rest is small branches across about 30 sites. Re-verify every line number: the open beads will move them.

## 14. Vision (owner direction in discussion; nothing here is decided)

### 14.1 Mechanisms live in libraries, the task loop holds policy

The shelf libraries (git_porcelain, stream_proc, process_lock, sqlite_store, beads_client, ...) own mechanisms and their fakes. This repo imports them and holds only the rules of the factory. An adapter that wraps a library to add a mechanism is a sign the mechanism belongs in the library.

Git as the worked case (git scan, grep counts, not cross-checked):

- `adapters/git.py` + `git_base` + `git_ops` + `git_pool` + `gitmemo` (about 650 lines) sit over `git_porcelain` (7,466 lines, with its own real implementation, its own fake `testing.py`/`fake*.py`, and its own error types). The adapter calls the library in about 70 places and runs raw `git` in about 30.
- A `Git` Protocol exists so the implementation can be swapped. No swap is planned, so callers import `git_porcelain` directly and the Protocol, the adapter and the wrappers go.
- The library already offers `merge_base`, `is_ancestor`, `rebase_onto`, `abort_rebase`, `rebasing`, `grep_tracked`, `diff`, `dirty`, `remote_url`, `branch`, `stage`, `record`. The adapter still runs raw `merge-base`, `rebase`, `grep`, `diff`. Why is not in the code; to be answered per call: a missing flag, a different return type, or history.
- The library lacks: `rev-parse` (verify, absolute git dir, toplevel, common dir), `symbolic-ref`, `config` reads, `status --porcelain -z`, `check-ignore`, `ls-files`, `show rev:path`, `for-each-ref`, `commit -m`, path-list `add`. Each is added to the library in the shelf, with its fake behavior, or dropped if the caller goes away.
- Memo: dropped (stages stop asking; section 5). Pin (`GIT_DIR`/`GIT_WORK_TREE` from the checkout's `.git`, written because a stray `core.worktree` once pointed every slot at another folder): kept only if the slot lifecycle cannot prevent that; `slotcheck` already detects it.
- Error types: `SlotGitError` and its subclasses move from `tlkernel/slots.py` into the library, so no code maps one set of errors onto another.
- One fake: the library's. `tests/support/gitsim` (1,811 lines), `fakegit.py` and `fake_slot_git.py` go once the library's fake covers what they cover (to check).
- Cost: about 45 test files use the repo's fakes. Library changes go through the shelf's gate.

### 14.2 Entities own behavior

Packages are named by the entity they serve (slot, run, bead, ask, loop, land, check, release, config, identity). The verb packages (`launch`, `wire`, `track`, `doctor`, `prune`, `reconcile`, `report`) dissolve into them. Each entity has one lifecycle document (create, states, mutators, destroyer) and one owner module per id it uses (section 12).

### 14.3 The slot is the unit of work

A slot has a lifecycle: observe, converge to the wanted state, run a blind stage, observe again, fail on a deviation, retry on the same slot (sections 2 and 2.1). The stage gets facts, never the environment. The waits collapse into one retry record plus the waits whose cause is outside the slot (section 7.1).

### 14.4 One path for state

State is in factory.db, once. Logs stay files. A format has one version; an older one is refused loudly; there is no migration, no quarantine, no silent skip (section 13). The seven files that should be rows (section 7.2) become rows or go.

### 14.5 What goes

storm, gitmemo, the git wrappers, the migration system, the verb packages' cross-cutting repairs, the extra waits, the duplicate id handling. The order and the beads come after the vision is agreed.

### 14.6 Integration strategy: merge main in, squash on land (what is already decided, and what code disagrees)

`docs/design/merge-queue.md` (decided by the owner, 2026-11-07) says: branches are updated by merging main in (plain pushes, no force); landing stays squash, one commit per bead. The code and `SKILL.md` still rebase: before each stage after the first, when the base moved (SKILL.md line 106); and at land, "fetch, rebase, gate, push" (line 107); a rebase conflict goes to a fix round.

If merge replaces rebase, these go (grep counts, not cross-checked; 42 files mention rebase):

- `app/land/rebase.py` (144), `land_rebase.py` (42), `salvage.py` (64) and the rebase halves of `restart.py`, `fixer.py`, `fix_outside.py`.
- The stage-time "rebase when the base moved" step.
- Every "is a rebase running / abort it" probe: four copies in the slot code (`reset.keep_work`, `reset.check_ready`, `closing_branch`, `workers/strays`), the detached-HEAD allowance in the strays check, and `rebasing` / `abort_rebase` / `rebase_onto` / `finish_rebase` in the git port.
- The "rebase" step of the slot prepare table (section 3) disappears; a merge conflict is a normal state of the tree, handled by one fix round.

What stays: one squashed commit per bead at land (`reset --soft base`, one commit); the wip commit step.

Open: does "merge main in" apply to the slot's branch between stages, or only to the PR branch in the queue? The merge-queue note speaks of PR branches. The in-slot case is not settled in that note.

### 14.7 The pin belongs to slot initialization

Today every git call carries `GIT_DIR` and `GIT_WORK_TREE`, computed from the checkout's `.git`, because a stray `core.worktree` once redirected every slot. Direction: the slot's prepare step checks the slot's git config once (no `core.worktree`, no `core.bare`; `adapters/slotcheck.py` already detects both) and fails the bead on a deviation. The verify step reads it again. The per-call pin (`adapters/gitrepo.pinned_env`, the `pinned` flag in `git_base`) goes. If the library needs the pin for its own calls, it takes the checkout path and does it inside.

### 14.8 The base-red check goes (footprint, grep, not cross-checked)

A check that fails is a failure the writer fixes in the same slot. The extra run on the base commit goes with everything that serves it:

- `app/checks/base.py` (`BaseCheck`) and its construction in `checks/runner.py` (two sites), the `base` argument of `Attempts`, `Outcome.base_red`.
- `RunMemo.base_was_red`, `set_base_red`, `base_key` in `checks/cache.py`; `BaseRedRecord` and the `base_red` document set (`stores/bundle.py`, `stores/real.py`, `tlkernel/checks.py`, `tlkernel/receiptrows.py`); the `'base_red'` kind in the `check_pass` table constraint (`checks/store.py`). A schema change: an old factory.db is refused (D10, no migration).
- `CheckResult.base_red`, `CheckRun.base_red`, the `failed` filter that skips base-red results (`tlkernel/checks.py`), the `executor.py` branches, the evidence text "red on the untouched base too" (`checks/evidence.py`, two sites), the writer brief text (`write/briefing.base_red_text`, `write/host`, `write/check_round`).
- The config key `engine.base_red`; the kinds `FAULT_BASE_RED` (`tlkernel/kinds.py`, `domain/lanes/pause_reasons.py`, `pipeline/trace.py`); the paragraph in `SKILL.md`.
- In `adapters/base_tree.py`: the `base_tree` helper. `clean_tree` stays for the gate when `gate_tree` is `clean` and for `tl check --staged`; it moves to the library as the temp-worktree helper.
- Tests: `test_check_spawn`, `test_evidence`, `test_identity`, `test_runkey`, `test_receiptrows`, `test_factorymigrate`, `test_pause_released`, the contract samples and golden files.

Not removed: `report/mainstate` (detects a red main for the report), which is a separate matter.

### 14.9 `app/report` (direction, not decided)

About 1,090 lines: `app/report` (8 files, ~700), `domain/report/reflect.py` (172), `cli/report.py` (202). Three separate things share the folder (grep and docstrings, not cross-checked):

| thing | what it does | users |
|---|---|---|
| scorecard (`card`, `inputs`, `landphases`, `mainstate`, `planner`, `window`) | `tl report`: a window's runs, lands, land-phase timings, planner cost per bead, and whether main is red (a revert landed since the window began, or the last release gate failed) | `tl report`, the dashboard (`launch/dash_ports` calls `score_of`), `wire/doctor` (`repo_traces`) |
| reflect digest (`app/report/reflect`, `domain/report/reflect`, `pipeline/reflect*`) | each run ends with one cheap read-only AI call that says what went well and badly (`reflect: true` by default); once a day the loop starts `tl reflect digest`, which clusters recurring causes and files one bead per cause | the loop (`loop_ops`), the dashboard's beads |
| `tl lost` | lists commits on task branches no run will bring home | `cli/report` |

Against the rules: the scorecard, `mainstate` and the planner table are monitoring ("no extra monitoring"); `tl lost` is the diagnostic from section 10a. The reflect digest is an automation that costs an AI call per run and files beads by itself; whether it earns its cost is not measured. If it goes, `pipeline/reflect.py`, `reflect_prompt.py` and the `reflect` config key go with it, and so does the daily start in `loop_ops`.

What the dashboard needs from the scorecard (`score_of`) decides how much of the first row can go. Not checked.

## 15. Work items (bead-ready)

How to read this section. Each item is one future bead. `Status`: **agreed** = the owner said it in this discussion; **direction** = proposed here or asked by the owner, not concluded; **check** = a claim that must be verified against the tree before work starts (every file:line in this document comes from grep or Haiku scans and will move when the open beads land). Items name scope by file; counts are grep counts. `Needs` lists items that must land first. Nothing here is filed except `tl-eip4`. Section numbers refer to this file.

### Epic A. Remove what the owner does not want

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| A1 | Remove storm | filed as `tl-eip4`. A fault holds the slot and the stage retries. Delete `adapters/storm.py`, `domain/storm.py`, the check in `pipeline/closing_decide.py`, the wait in `launch/loop.py`, knobs `storm_window_s` and `storm_beads`, the `POLICY` `.storm` flag, the notify trigger in `docs/design/notify.md`, and their tests | `grep -ri storm` over src, tests, docs/design finds nothing live | none | agreed, filed |
| A2 | Remove the base-red check | section 14.8 (D14): `checks/base.py`, `BaseRedRecord` and its document set and table kind, `CheckResult.base_red`, `CheckRun.base_red`, `executor.py` branches, evidence and brief text, `FAULT_BASE_RED`, config `engine.base_red`, SKILL.md paragraph, `base_tree` helper, about 10 test files | no `base_red` left; old factory.db refused | A5 (schema refusal) | agreed |
| A3 | Remove the migration system | section 13 (D10, D11): layout and key migration (`layout_migrate`, `key_migrate`, `layout_paths`, `ident.layout_stop`, `tl layout`, doctor message, `legacy_line`), landed-before-record fallbacks, DB schema steps and quarantine (`factorymigrate`, `quarantine_versions`, `dbparts._upgrade`, `add_park`, `discard_old_pin`), config retired/renamed/gone tables, `checkpoint forbid_unknown_fields=False`, `LEGACY_KINDS`, `gateplan` aliases, `tl check` alias `gate`, Claude env fallbacks in `ident.py`, ask orphans, dash silent skips, delegate `RETIRED_*`, `LEGACY_DATA`, `doctor` alias `init`. Vendored `sqlite_store`: change upstream in the shelf | an old format fails loudly; no step list, no quarantine | none | agreed |
| A4 | Remove rebase | section 14.6 (D13): `app/land/rebase.py`, `land_rebase.py`, `salvage.py`, the rebase halves of `restart`, `fixer`, `fix_outside`; the stage-time "rebase when the base moved" step; the four rebase-running probes; `rebasing`, `abort_rebase`, `rebase_onto`, `finish_rebase` in the git port; SKILL.md lines 106 to 108 and 298. Branches are updated by merging main in; land stays squash | `grep -ri rebase` finds nothing live | none | agreed |
| A5 | Refuse old DB loudly | the schema version check becomes the only path: an older or newer factory.db is refused with a clear message, no move-aside | a v1 DB is refused, not renamed | A3 | agreed |
| A6 | Remove the disk wait | free-disk handling: `loop/waits.py` disk branch, `launch/loop.py free_bytes`, `doctor/disk.py` sampling decision open (doctor forecast is a report, not a wait) | no wait on disk; a full disk is a fault retried later | E1 | agreed (RAM wait: open, see Q1) |
| A7 | Remove gitmemo | `adapters/gitmemo.py`; move `ref_files` out of it for `doctor/profiles.py` or drop that use; `slotcheck._MEMO` | no memo layer left | C1, B3 | agreed (the owner called the memo unnecessary) |
| A8 | Remove the reflect chain | footprint is wider than the digest (section 15.3): the per-run reflection touches about 35 files in the kernel and taskloop (trace field `reflection`, `Reflector`, the close path, the bead comment "Reflect (engine)") plus ~10 test files. Two tiers: (a) digest only, about 10 files (`app/report/reflect.py`, `domain/report/reflect.py`, `cli/report.py`, the daily start in `loop_ops.py`, `loop/env.py`, `tl.py` lines 30, 236, 460, `.importlinter`, SKILL.md line 489); (b) the whole chain. Owner: remove entirely if the code is small; it is not small, so tier choice is Q8 | no daily digest (tier a) or no reflection at all (tier b) | none | agreed in principle; tier open |
| A9 | Remove deadline.py | the run-wide budget (`adapters/deadline.py`, `DeadlineExpired`, 7 callers: waits, lifecycle, lander, spawner, runner, procs, halt). Per-check `wall_min` stays. Timeouts get a design later | no `deadline` import | none | agreed ("remove it entirely for now") |
| A10 | Remove `tl lost` and the commit observer | `app/reconcile/lost.py`, `commits.py`, `domain/reconcile/lost.py`, `cli/report.py lost` | decided with Q3 | none | direction (see Q3) |
| A11 | Scorecard and `mainstate` | the dashboard renders ten fields of the scorecard: since, beads, landed, landed_no_ask, asks, lost, crashes, retries, kinds, main_red (`static/js/app.js:104-107`); it does not render `m2_pass`. `landphases.py` (feeds `land`), `planner.py` (feeds `tokens`) and `window.py` serve only `tl report`, not the dashboard: removable now. `mainstate` feeds `main_red` and `lost` feeds the dashboard: decide with Q3 and Q4. `mainstate` is a guess (a commit titled Revert, or a failed release gate): replace by a real query or drop | see Q4 | none | direction |
| A12 | Remove the profile-change approval | owner 2026-11-07: "I change it with an AI agent, so the task-loop json file is always good; ditch unnecessary code." No approval of any kind. Footprint in 15.7 (corrected after a Haiku map: `trustroots.py` and `authorization.py` mostly stay) | no `profile_change`, `diff_sha`, `--profile-change`, `profile-changes.jsonl` | none | agreed; footprint from Haiku, not cross-checked |

### Epic B. Git moves into the library (`git_porcelain` in the shelf)

Principle (section 14.1): mechanisms and their fakes live in the shelf library; this repo holds policy. Callers import `git_porcelain.api`; the `Git` Protocol is not needed because no swap is planned.

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| B1 | Align git_porcelain with what the engine needs | section 15.4: of about 36 raw calls, 8 have an equivalent method, about 20 exist but differ (return type, flags, error behavior, hooks default, no index codes, no `--stat`, grep fixed-string only), and about 8 are missing (`init --bare`, `clone`, `rev-parse --verify`, `--show-toplevel`, the staged-diff family, `checkout-index`, `config --show-origin` origin). Per call: add the missing, and for each "differs" decide whether the library changes or the caller adapts. Library changes go through the shelf gate | the adapter runs no raw git | none | agreed in direction; scope larger than first said |
| B2 | Move error types into the library | `SlotGitError`, `BranchPinned`, `DirtyTree`, `RefRace`, `IndexLocked`, `GitReadFailure`, `NotARepo`, `MissingRevision`, `MissingRemote`, `NotAWorktree` from `tlkernel/slots.py` into the library; delete `git_base.classify`, `read_failure`, `git_pool` translators | one error set | B1 | direction |
| B3 | One fake | use the library's fake (`FakeRepo`, `FakeWorktree`, `FakePlumbing`, `testing.py`). Today: `fakegit` is imported by 26 test files, `gitsim` by 5, `fake_slot_git` by 1, the library fake by 6. Lacking in the library fake: per-call fault injection by argv or by op name with a times count, call recording (`seen`, `ran`, `calls`), `Unsupported` guard, `rev_parse`/`show`/`read_tree`/`write_tree`. Add those to the library fake, then move about 32 test files; delete `tests/support/gitsim` (1,811 lines), `fakegit.py`, `fake_slot_git.py` | one fake, one contract suite | B1, B2 | agreed (the owner: use the library's fake) |
| B4 | Delete the adapter chain and the Git Protocol | `adapters/git.py`, `git_base.py`, `git_ops.py`, `git_pool.py`, `tlkernel/gitport.py`, `app/wire/real.py` Git construction; callers import the library | no `adapters/git*` | B1, B2, B3, A4 | agreed (direction) |
| B5 | One repo key | three keys exist for "the repo": library `identity().key` = `sha1(common_dir)[:12]` (no caller in src), `loop_key` = folder name + `sha1(realpath)[:8]` (path based), `lock_key` = `sha1(canonical origin url)[:12]` (origin based). They coincide only when there is no origin. Choose the meaning (the clone's path versus the remote's name; locks need the remote's name, slot files need the path), give each one function in the ids module, delete `repourl.py` | one function per meaning | E1 | direction; Q9 |
| B6 | `treehash.py` becomes `Worktree.snapshot` | `tree_of` already wraps `snapshot`; drop `state_of` with the memo; compare the ignore matching (`ignore_rules`, `ignored_by`) with the library's `ignore_rules.py` and delete the duplicate | `treehash.py` deleted | A7, check: ignore overlap | direction |
| B7 | Temp worktree helper in the library | `clean_tree` as a `with` helper in `git_porcelain`; used by the gate (when `gate_tree` is `clean`) and by `tl check --staged`. Decide Q2 first | `base_tree.py` deleted | A2, Q2 | agreed (the owner prefers it in the library) |
| B8 | Pin to slot initialization | the slot's prepare step checks git config once (no `core.worktree`, no `core.bare`; `slotcheck` already detects both), verify reads it again; delete `pinned_env`, the `pinned` flag, `gitrepo` pin code | no per-call `GIT_DIR` and `GIT_WORK_TREE` | D1 | agreed |
| B9 | `gitrepo.py` shrinks | `common_of`, `repo_root`, `same_dir`, `git_dirs`: into the library or the ids module; 15 callers | file gone | B1, B8 | direction |

### Epic C. Process and OS code moves into the shelf

The kernel should hold records, not OS calls. `packages/kernel/ruff.toml` bans `subprocess`, `socket` and `threading` in tlkernel ("contracts never spawns a process"; `procport.py` carries one `noqa`); sqlite is not banned anywhere (about 12 tlkernel files import it), and no rule says "records only" for the kernel (Haiku check). The scan's count of about 17 modules with OS, file or process calls and about 15 using sqlite is therefore a design question (does the kernel hold persistence?), not a rule violation. Delegate encapsulates the harness workers; it does not own the factory's own processes, locks and run manifests, which need pid and start-token liveness.

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| C1 | One pid-liveness function in the shelf | five wrappers exist: `adapters/pidcheck.py`, `tlkernel/locks.pid_alive`, `Lock.alive`, `Ticket.alive` (ignores the start token), delegate `app/lease.orphan`, plus direct `proc_start` calls in `locator.py` and `attemptrows.py`. All call `stream_proc.alive` and `proc_start`. Delete the wrappers; callers import the library | one definition | none | agreed ("move it all into shelf and ditch it from the kernel") |
| C2 | Merge procs into stream_proc | `adapters/procs.py` (108 lines: spawn, wait, stop a tree; `PidHandle` for a foreign pid) and `src/delegate/adapters/procs.py` do the same job over the same library. Move both into `stream_proc` in the shelf; delete both files | one process library | none | direction (owner asked "why not merge it into stream_proc") |
| C3 | Spawner into the library | `adapters/spawner.py` (97 lines) is `stream_proc` held spawn plus `childenv.tool_env`. Offer a `Spawner(env_builder)` in the library; this repo passes its env policy. Kernel `procport.py` and the `procsim` fake change | `spawner.py` deleted | C2, C5 | direction; difficulty low to medium (one adapter, one port, one fake) |
| C4 | Halt as a standalone stop library | `adapters/halt.py`: SIGTERM sets a flag, work ends at its next safe point; a deferred stop; `nap`. Signals are handled in four places (`halt.py`, `cli/loop.py`, `landlock.run_locked`, `pipeline/closing.py` and `run/entry.py` set `SIG_IGN`). Trace the whole design first (Haiku trace requested), then one library: `StopFlag`, install, checkpoint, nap, defer | one owner of "please stop" | trace result | direction (owner: "trace how it is organized; probably move to shelf") |
| C5 | Child environment | `adapters/childenv.py` (201 lines): the generic part is already the shelf package `child_env` (virtualenv scrub, `without_venv`); this file holds our policy: an allowlist of names, registered `TL_*` names, the hand-over variables, `core.hooksPath` through `GIT_CONFIG_COUNT`. The env of a command is part of slot preparation (`run/bead_env.py`, `checks/step_env.py` build the `TL_*` names). Move the policy into the slot lifecycle's "command env" part (section 3); keep generic scrub in `child_env` | one builder, owned by the slot env | D1 | direction |
| C6 | Land lock and `os_lock` | `adapters/landlock.py` holds `os_lock` (generic), `canonical_remote` (generic string rule), `lock_key`, `land_lock_path`, `run_locked` (`tl land-lock`, with its own signal handling). Move `os_lock` next to `process_lock` in the shelf; `canonical_remote` into the repo-identity function (B5); rename the rest `land_lock`. Whether the lock stays cross-process depends on the process model (Q5) | no `landlock.py` | B5, Q5 | agreed to move to shelf; process question open |
| C7 | Clock | `adapters/clock.py` (11 lines, `SystemClock`: `now`, `monotonic`) satisfies the kernel `Clock` port. The vendored `any_clock` is NOT a substitute: it is `PhaseClock`, a phase stopwatch (used only by `pipeline/budget.py`), with no `now` or `monotonic` (Haiku check, 2026-11-07). Options: keep `SystemClock` as is, or add a plain clock to the shelf | decide | none | check resolved: first claim was wrong; direction open |
| C8 | Thread flag | `adapters/threadflag.py` (23 lines): a per-thread bool so `killed` and `wall_hit` say how the calling thread's last command ended, because several gate lanes run at once. The side channel is the smell: return `killed` and `wall_hit` in the command's result and delete the class. If a thread library is wanted, build it from halt (C4) | file gone | C4 | direction |
| C9 | Agent and runner | `adapters/agent.py` (`ApiAgent`: `delegate.api.run` on a thread, `api.cancel`, live-file readers) and `adapters/runner.py` (`ApiRunner`: the delegate call seam, wall limit, live file) share one thread-and-cancel pattern. Both wrap `src/delegate` which is a library in this repo: the code moves into `src/delegate` (as the engine-side client) or into the shelf `any_agent`; this repo uses it. Wall limits: with A9 the extra limits go (`BACKSTOP_S`, the runner timer, delegate `timeout_s` stay in the library) | two files deleted | A9, C4 | direction |
| C10 | Locks and leases | `adapters/locks.py` (127 lines on the shelf `process_lock`): keep what is project policy, move the rest (`hold_path`, wait polling) into the shelf next to `process_lock`; reconcile with `any_lease`. Heartbeat: `slots/lease.py` (bd lease) and delegate `app/lease.keep_alive` beat for the same run | one heartbeat | D3 | direction, check |

### Epic D. The slot lifecycle (sections 2 to 5, 14.3)

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| D1 | `observe_slot` and `desired(bead)` | one function reads branch, HEAD, status, lock/lease row (few reads: each file read costs ~20 ms on the Mac) and returns facts; `slot_state` derives from it. Replace the four derivations (`slot_view`, `free_reason`, `slot_liveness`, `observe`, the watchdog) | one derivation | none | agreed (direction: state derived from disk, git, bd) |
| D2 | Prepare and verify around every stage | before: converge (rebase abort goes with A4; branch: free it from another worktree, check out or create `task/<bead>`; leftovers committed with a warning; setup by the repo's `.task-loop.json` `slots.setup` unless `setup_inputs` unchanged; command env; run folders). After: observe; a deviation not on the allowed list fails with `FAULT_ENGINE` and the difference in the log | stages never ask git for the branch | D1 | agreed |
| D3 | One holder record | the engine lock (`slots/engine_lock.py`, `lockrows`) and the slot lease record "who holds this slot" twice. One lease with one pid-liveness rule (C1). Needs the process tree (section 6): loop, then `run-task`, then worker call, plus hand-run `tl slot` | `engine_busy` gone | C1, D1 | direction (the owner did not follow why two processes exist; section 6 explains) |
| D4 | One tree-reset path | `land/tree.py` and `slots/reset.py` both fetch, save work, check out the task branch, free the branch, leave the slot; two wip-commit formats; `leave_slot` twice; `keep branch aside` twice (`tree.py`, `restart.py`). `land/tree.py` calls the slot; one wip function | one reset | D2 | agreed |
| D5 | Slot owns worktree removal and scratch | `wire/slots.py`, `land/cleanup.py`, `release/tidy.py` remove worktrees; `prune/slotstate.py` removes slot scratch. One remover, in the slot | one remover | D4 | agreed |
| D6 | Replace 20 branch asks | `git.branch(wt)` in 15 files: stages read `branch` from the run facts; two asks per stage remain (D2) | no stage asks git for the branch | D2 | agreed |
| D7 | Retry record | a fault keeps the slot and retries the stage: one record (attempt, next try) replaces rest, aside, storm and the disk/RAM wait; network, lane and ask keep their own wake. Collapse "three tries" budgets (`fault_retries`, pause `max_attempts`, `lane_poll`) | one retry rule for faults | D1 | agreed (principle), design open |
| D8 | Aside and marks | `aside_*` keys are not in `HELD_KEYS`: a released slot keeps its aside state. Fix with D1 | checked | D1 | check |
| D9 | Added-worktree check | decide whether to keep the check that a worker did not run `git worktree add` inside the slot (Q6) | | D2 | open |

### Epic E. Ids and identity (section 12)

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| E1 | One module per id kind | `tlkernel/ids.py` owns bead id, task branch `task_branch(bead)` / `bead_of(branch)`, stale branch (with its `-N` suffix), wip branch, run id (one parse policy), repo key (delete `owned.key_of`, `check_files.repo_key`), `remote_key(url)` (raw versus canonical), worktree key (`owned.py` 8 hex versus `reset.py` 12 hex), attempt folder names, slot name from the bead title (4 copies). `identity.py` owns actor naming and `"tl-"`. No id is removed | `TASK = "task/"` defined once; no inline `"task/"` | none | direction (the owner read "ids" as removal; it is consolidation) |
| E2 | Fence generation single writer | `fence.take` and `slots/marks.py` both bump | one writer | D3 | check |
| E3 | `ident.py` shrinks | drop `layout_stop`, `PLUGIN_ROOT` global; keep config dir, hostname, `Identity` | no import of migration | A3 | direction |

### Epic F. State has one path (sections 7.2, 8)

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| F1 | Files that should be rows | `runs/<run>/plan.json`, `engine-checks*.json`, `shared/<repo>.json` (flaky notes; `Stores.flakes` and `SharedNotesStore` have no caller: delete), `loop.pid`, `dash.pid`, ask sweep markers, `slots/<key>.setup` (the setup mark goes with D2). `storm/` goes with A1 | none left | none | direction (the repo rule is stated) |
| F2 | Deletion rules for what has none | `wait` rows (never deleted, and they block run pruning: a bug today), `died-*` loop rows, engine lock rows, `followup`, `profile-changes.jsonl`, `decisions/uses.jsonl`, `artifacts/` store, `.task/<bead>/`, the checkpoint (dropped only by resume paths) | each family has a rule | none | direction |
| F3 | One prune rule | four modules (`run/layout.py`, `prune/runs.py`, `prune/traces.py`, `prune/retention.py`) apply three protection rules; one age rule with the slot's own scratch removed by the slot (D5) | one rule | D5 | direction |
| F4 | Duplicated records | loop exit in `factory.log` and `exits.jsonl`; `ask_ledger` table versus bead comments (the sqlite plan says drop the table); usage in `lanes_doc` and `usage-history.jsonl`; run end in six places; `Close` and trace written by `closing_record`/`journal` and again by `finish_projection`; `RunState` defined twice (`tlkernel/checkpoint.py`, `tlkernel/run.py`); terminal state written in four places | one writer per fact | none | direction |
| F5 | Single readers | `storm.py` parses `traces.jsonl` itself (goes with A1); `hook/prepush.py:77` reads `kv repos` by SQL; `kv durations` raw SQL in migrations (goes with A3); `host.json` read by four modules | one reader each | A1, A3 | direction |

### Epic G. Packages follow entities (section 11)

| id | title | goal and scope | done when | needs | status |
|---|---|---|---|---|---|
| G1 | Dissolve the verb packages | `launch`, `wire`, `track`, `doctor`, `prune`, `reconcile`, `report` move into the entity they serve (slot, run, bead, ask, loop, land, check, release, config, identity). Order after the rest, because the other epics delete much of what they hold | no verb package | A, B, C, D | direction |
| G2 | Split `app/land` | 45 modules mix branch (11), merge queue (8), checks (8), bead (4). Branch work goes to the slot, checks to `checks`, the queue stays | `land` is the queue and the push only | A4, D4 | direction |
| G3 | Release gets a home | 14 app modules and `dev/release.py`, no domain rules, no kernel records | domain and kernel records for release | none | direction |
| G4 | Merge the duplicated land helpers | squash of wip commits (`commit.py`, `rebase.py`), keep-old-branch-aside, record-the-land in four modules, stale-tree checks in `gate.py`/`push.py`/`treecheck.py`, three land locks (`lander`, `stack`, `release/push`), force-with-lease push in two, detached worktree make/remove in four places | one each | A4 | direction |
| G5 | Reconcile shrinks | keep `release_dead` as the one place (called today from `loop/loop.py`, `run/entry.py`, `launch/loop_ops.py`); tidy of build trees and landed branches via one sweep; drop `lost` and `loopwatch` (A10) | section 10a | D1, A10 | direction |
| G6 | Reflection and other later stages | a separate package, state and stage after the factory is simpler (A8) | | A8 | later |

### Epic H. Adapter hygiene (section 10b)

| id | title | scope | needs | status |
|---|---|---|---|---|
| H1 | Move non-adapters out | `bdids` to the ids module (E1); `bdcreate` (a retry policy: add filler sections on bd's lint refusal) to `land/followups.py`; `suiteout.py` (pytest output parsing) to `app/release/` | E1 | direction |
| H2 | Rename by purpose | `landlock` to `land_lock`, `factory` to `keepawake`, `looks` to `shot_table`, `markers` to `conflict_markers`, `check_files` to `cache_inputs`, `check_net` to `netisolate`, `check_probe` to `path_probe`, `beadtools` to `bead_store` (drop its re-exports of kernel `bdsafe`), `delegate_wire` to `delegate_answer` | | direction |
| H3 | Fix layering leaks | `app/workers` imports `delegate_wire` although the port says no app module imports the adapter; `app/land/push_evidence.py` imports `git_base.push_error_line`; `adapters/ident.py` imports a migration | A3, B4 | direction |
| H4 | Duplicates across layers | `check_files.repo_key` versus `ids.loop_key` (E1); `markers.py` versus three marker checks in the vendored `git_porcelain`; `tlkernel/gitfacts` versus library types | | check |
| H5 | `links.py` | keep; review the `carries_data` heuristic (the exfil findings SEC-OPUS-30, SEC-FABLE-16). It is the only host-side network use | | direction |
| H6 | Tests missing | no direct test for `base_tree` (goes with A2), `delegate`, `check_files`, `suiteout`, `bdcreate`, `threadflag`, `ident`, `markers` | | check |

### Questions that block items

1. **Q1 RAM wait.** Drop it with the disk wait (`ram.py` and `loop/waits.py` RAM branch go)? Blocks A6.
2. **Q2 Gate tree.** Run the gate in the slot (`gate_tree: slot`, already supported with a guard) so the gate half of `clean_tree` goes, or keep `clean`? Blocks B7.
3. **Q3 `tl lost`.** It lists commits on `task/<bead>` and `wip/*` branches that are not on the base, classed landed, reclaimed, superseded, pending, unknown or lost (a closed bead with no land after, or a dead session's wip branch). It is a read-only diagnostic of stranded work. With wip commits as a workflow step and squash landing, does it still earn its code? Blocks A10.
4. **Q4 Scorecard.** `tl report` (runs, lands, land timings, planner cost, mainstate) is monitoring. The dashboard reads `score_of`. Drop, or keep a reduced card fed by real queries only? Blocks A11.
5. **Q5 One process.** The owner asked why cross-process locks exist if one process runs all slots. Today the loop starts one `run-task` process per bead, hand-run `tl` verbs and `dev/release.py` are further processes, and the land lock serializes all of them. If the target is one process with a thread per slot, the land lock becomes an in-process mutex and the engine lock merge (D3) gets simpler. Needs the halt trace and a decision. Blocks C6 and D3.
6. **Q6 Added-worktree check.** Keep the check in D2's verify (a worker runs `git worktree add`)? Blocks D9.
8. **Q8 Reflection.** Remove only the daily digest (about 10 files) or the whole chain including the per-run reflection record and the close's bead comment "Reflect (engine)" (about 35 files plus tests)? Blocks A8.
9. **Q9 Repo key.** One name for a repo. Two options: (a) the remote's canonical name (works across clones; a second clone of the same remote on the machine would share its config folder, slots and loop state), (b) the common git dir (one clone only; then the release must push from the same clone). Which rule: one clone per remote on a machine? Blocks B5, C6 and E1.
7. **Q7 Order.** Delete first (epic A, then B and C), then build the slot lifecycle (D), then rename packages (G)? Or the slot lifecycle first? The draft's order puts A first, because deleted code needs no migration and shrinks D.

### 15.1 Halt trace (C4; Haiku, not cross-checked)

Core is coherent, the edges are patches: one run-level `Event` (`halt.RUN_HALT`) polled at safe points (`app/run/plumbing.py` `halt_point`, `nap`, `adapters/runner.py`, `pipeline/run.py`); the loop has two inputs merged in `loop/core.stop_mode` (an in-process signal Event and a DB command row).

Patches found:
- Nine signal-handler sites with five semantics: `halt.py` (two), `pipeline/closing.py` and `run/entry.py` (both `SIG_IGN`), `cli/loop.py`, `landlock.py` (no main-thread guard), and three in vendored code (`stream_proc/hold.py`, `any_lease/__main__.py`, `any_agent/supervisor.py` which raises `SystemExit` from a handler, against `halt.py`'s own rule).
- An owner stop is injected as a SIGTERM equivalent and relabelled after the fact (`lifecycle.py:165`); a deadline is a second stop path with another outcome (`OWNER_PARK`).
- A deferred stop is consumed at three sites and silently dropped at two (`run/entry.py:426`, `pipeline/lifecycle.py:244`).
- The text "failed: stopped (SIGTERM)" is a literal at five sites.

Proposed library API (shelf, standalone): `StopFlag` set with a reason (owner, signal, budget stay distinct); `install(flag, signals)` context manager with the main-thread check and restore; `checkpoint(flag)` raising a typed `Stopped`; `nap(flag, secs)`; `defer(flag)` yielding a must-consume token; `ignore()` for the close. Process-tree stop and spawn-hold stay in `stream_proc`. With A9 (no deadline) the second stop path disappears.

Not traced: `loop/loop.py` body, the owner POST path (`tl park|stop|note`), `after`-mode at `loop.py:177`, the exit reason of the loop.

## 16. Names (owner dislikes `app` and `report`)

The owner does not understand what `app` is and dislikes `report` ("what kind of Excel or PDF report at the end of a system"). `app` today is the layer between `domain` (pure rules) and `adapters`/`cli`: the code that runs the factory. A layer name that says nothing hides the entities inside it (section 11). Direction, to be settled with the package split (G1):
- Drop `app` as a name. Packages sit at the top level named by entity (`slots`, `runs`, `beads`, `asks`, `loops`, `lands`, `checks`, `releases`, `config`, `identity`); rules (what is `domain/` today) and I/O sit inside each entity's package, as the stage-package charter already says (`packages/<stage>/{src,tests}`).
- `report` is three things (14.9): the scorecard (a monitoring view: name it for what it shows, or remove it, A11), the reflect digest (a later stage called "reflection" or "evolution", A8) and `tl lost` (a diagnostic about stranded work, A10). The word `report` goes with them.
- The same test for the other names in section 11: `launch` (start things), `wire` (connect things), `track` (bead verbs), `doctor`, `prune`, `reconcile`. Each is a verb or a metaphor; each moves into the entity it serves.

Work item G7: agree a naming rule (entity names, no layer names, no verbs) before G1 starts, because renaming twice costs two sets of import changes and two sets of test moves.

### 15.2 Footprints for A6 (disk and RAM) and A9 (deadline) (Haiku, not cross-checked)

**A9 deadline.** The only run-wide budget is `engine.run_deadline_min` = 45 (`tlkernel/config.py:267`), installed at `pipeline/lifecycle.py:159`; expiry becomes `OWNER_PARK` ("run deadline exceeded; branch and checkpoint kept"). Every other caller keeps its own timeout, so removing the module drops only the run-wide clamp. What bounds each caller without it: `pipeline/waits.py` its 300 s lock wait; `land/lander.py` the check `wall_min`; `adapters/spawner.py` and `procs.py` the caller's timeout; `adapters/runner.py` the delegate wall (`timeout_s` plus `BACKSTOP_S` 120). `halt.nap` has no caller in `src/` (`slots/line.py` has its own `nap`). Goes with it: the config key, `tests/adapters/test_deadline.py`, `tests/support/fake_deadline.py`, parts of `test_lifecycle`, `run/test_liveness`, `land/test_liveness`. Consequence to accept: a run can last as long as its per-call limits allow; nothing caps the whole run.

**A6 disk and RAM.**
- Waits (the loop pauses): `loop/waits.py` (disk `min_free_gb` 5, RAM `min_ram_mb` 1024), fed by `launch/loop.py` `free_bytes` and `loop_ops.available_mb` (`vm_stat`, parsed by `adapters/ram.py`). `LoopWait` reasons `low_disk` and `low_ram`; `EXIT_REASONS` lists `low_disk`.
- Reports (no wait): `doctor/disk.py` hourly sample (`loop_ops.py:72`), kv rows `disk.free.*` (`diskrows.py`), `tl doctor --disk`. There is no RAM report. The dashboard shows neither.
- If only the waits go: `waits.py` branches, `env.py` fields, `launch/loop.py:176-177`, `loop_ops.py:129-135`, `ram.py`, keys `loop.min_free_gb` and `loop.min_ram_mb`, README lines 101 to 103, SKILL.md lines 503 to 505, `test_waits`, `test_loop_disk`, `test_ram`, parts of `test_exits` and `test_loop`, golden and sample records.
- If all goes: also `doctor/disk.py`, `diskrows.py`, the hourly call, `--disk`, `test_disk`, `test_diskrows`.
- Q1 now has two parts: waits (disk agreed, RAM open) and the doctor report (open).

### 15.3 Reflection footprint, scorecard feeds (Haiku check, not cross-checked)

- The `reflection` field is `RunTrace.reflection` (`tlkernel/trace.py:157`). It is written by `Reflector.reflect_run` (`pipeline/reflect.py`), set at `closing_record.py:90` and `standalone.py:388`, persisted as a `traces.jsonl` row (`journal.py:283`). Readers: the close path (`closing_notes.py`, `outcomes.py`: the bead comment "Reflect (engine)"), `standalone.py` (stops at the previous reflection), and the digest. The dashboard, doctor and the report card do not read it.
- Deleting it breaks, in the kernel: `trace.py`, `answers.py`, `enums.py`, `config.py` (key `reflect`, read only at `pipeline/reflect.py:89`; `launch/selftest.py` sets it false), `snapshots.py`, `rowstores.py`, `docrows.py`, `factorydb.py`, `factoryparts.py`; in taskloop about 20 pipeline, run, domain and cli files; about 10 test files. So a full removal is a sweep, not a delete.
- Scorecard feeds: `card.py` builds `Score` from `inputs.repo_traces`, `_bead_rows`, `landed_of`, `bead_status`, crash counting, `reconcile/lost.py` and `mainstate`. `landphases` and `planner` feed the CLI card only.
- Q8 (blocks A8): remove only the daily digest and the AI call it needs the notes for, or the whole chain including the bead comment "Reflect (engine)" the close writes today?

### 15.4 Git library coverage per call (Haiku, not cross-checked)

- **Equivalent** (8): `branch`, `symbolic_ref`, `for_each_ref` (`Repo.refs`), `is_ancestor`, `remote_url`, `stage_literal`, `config_get`, `amend`.
- **Exists but differs** (about 20): `merge_base` (Sha or None), `ls_tree` (recursive only), `status` (no index or work codes), `check_ignore` (no excludesFile), `git_dir` (Path), `rebase` (library validates the base and adds `--end-of-options`, `core.editor=true`), `commit_*` (hooks off by default), `stage` (no `-A`, glob pathspecs), `show` (`Tree.read` returns bytes or None), `ls_files` (no pathspec), `grep` (fixed string, forced `-w`, paths only), `config_entries` (no origin), `common_dir` (via `identity()`, an extra remote call), `diff` (no `--stat`, adds `--no-renames`), `count`, `diff_entries` (kinds A/M/D only), `try_commit`.
- **Missing** (about 8): `init --bare`, `clone`, `rev-parse --verify`, `rev-parse --show-toplevel` (`identity().root` is the main checkout, not this worktree), `diff --cached` and the staged-paths family, `checkout-index`, `diff -w --quiet`.
- Fakes: see B3.
- Keys: see B5. Q9: which meaning does each key serve?
- Consequence: B1 is not "add a dozen methods". It is an API alignment of about 28 calls, so B4 (delete the adapter chain) is the largest item in epic B.

### 15.5 Owner direction on git and repo names (2026-11-07, in discussion)

- Git: move all of it into the shelf library. For the about 20 calls where the library behaves differently, reassess each: the library's behavior wins by default (`None` for absent, not an empty string; typed errors), callers adapt, and the library changes only where a caller truly needs something it lacks. A Haiku reassessment per call is in progress; its table replaces B1's "per call decide".
- Fakes: one fake, the library's, merged from `gitsim`, `fakegit` and `fake_slot_git`; simple. No second and third fake (B3).
- Repo name: one repository name, one function (B5).
- Why the land lock is keyed by the remote today (answer to "why not just one repo"): the lock must be shared by every process that pushes to the base. Slots are worktrees of one clone, so they share a common git dir. But `dev/release.py` works in its own separate clone (`<config>/release/`, CLAUDE.md) and pushes to the same remote, and sessions can push from other clones. Those clones have different paths and different common dirs, so only the remote's name is the same for all of them. If every pusher used the one clone (the release also goes through the slot or the PR path), the key could be the common dir, and `canonical_remote` and the origin hash would go. Q9 asks this.

### 15.6 Per-call verdicts for the differing git methods (Haiku, grep and reading, not cross-checked; replaces "decide per call" in B1)

**Library wins, callers adapt** (14): `merge_base` (Sha or None; callers test truthiness), `git_dir` and `common_dir` (Path; two callers wrap "" in `Path` today and get "." : `land/tree.py:111`, `land/stack.py:325`), `rebase` (callers use only ok and output), `commit_tracked`, `commit_staged` (map "nothing to record" to an error in the caller), `try_commit` (a small wrapper for the hooks flag and the "commit refused (hooks)" text), `stage`, `show` (bytes or None; callers decode), `count` (drop the silent 0 on bad output), `diff` (render `--stat` once from `Diff.changes`), `_paths` (superset of rename sides is fine), `grep` (drop; use `grep_tracked`).

**Library changes** (what to add): (1) keep the index and work status codes in `parse_status` and expose rows, which also gives `staged`, `staged_paths` and the index check; (2) path-scoped `ls_tree` that returns the kind (blob, tree) for `plan/adrsync`; (3) diff options: ignore-space (`-w`), exact renames as `R` with the old path, kind `T`, and a changes-only mode; (4) `check_ignore` with an excludes file, `ls_files` with a pathspec, `config_entries` with the origin and an unpinned mode, all promoted to the `Repo` protocol; (5) index export (`checkout-index --prefix`) for `tl check --staged`.

**Dropped with A12:** `profile_diff` existed only for the profile-change approval hash (`diff_sha`); the owner removes that approval.

**Drop:** `_space_changes` (a workaround for old git, used only by `diff_entries`).

**Absent as "" or False (change to None or a typed error):** `merge_base` (`trustroots.py:31` reports absence as a read fault), `git_dir`, `common_dir`, `toplevel`, `branch` when detached, `rev_parse` (about 90 raw call sites), `config_get`, `remove_worktree` (False hides absent versus refused), `count`.

**Also found:** (a) `src/delegate/adapters/git.py` is a second git layer inside the delegate library; (b) `adapters/markers.py`, `hook/prepush.py` and the `merge-tree`/`commit-tree` calls in `land/queue_refs.py` bypass the adapter and call git directly. Both must reach the library too (new items B10, B11).

| id | title | scope | needs | status |
|---|---|---|---|---|
| B10 | Delegate's git layer | `src/delegate/adapters/git.py` onto the same library | B4 | check |
| B11 | Direct git callers | `markers.py`, `hook/prepush.py` (the hook must stay stdlib-only: `python3`, no imports of ours; check whether it can use the library), `queue_refs.py` merge-tree, commit-tree, update-ref (add to the library) | B1 | check |

### 15.7 Footprint of A12 (Haiku map, not cross-checked)

**Delete:** `app/land/profile_change.py`; `stores/profile_changes.py` and `tlkernel/profile_changes.py` with their entries in `tlkernel/paths.py`, `stores/bundle.py`, `stores/real.py`, `tests/support/memstores.py`, contract samples and golden records; the `owner_approved`/`ProfileChanged` branch in `app/land/push_judge.py` (keep the base-commit read); the `profile_change` parameter and `audit_profile` in `app/land/stack.py`; `--profile-change` in `cli/land_stack.py`; the refusals and the `--policy-commit` argv in `app/land/stackgate.py`; `tl.py:305` `--policy-commit` and `launch/check.py` `policy_of` (the `policy` parameter has no other caller); `profile_diff` in `adapters/git_ops.py` and `tlkernel/gitport.py`.

**Edit, not delete:** `app/asks/trustroots.py`: remove `.task-loop.json` from `FILES` only (the file also guards `AGENTS.md`, `CLAUDE.md`, `mise.toml`, `.claude/`, `.codex/`, `githooks/` against review-prompt injection). `app/wire/setup_apply.py` `open_pr` (the profile PR) has no approval logic; it is the only path that puts a first profile on base, so drop it only together with the PR bootstrap.

**Stays:** `adapters/profile_at.py` (readers: `authorization.py`, `push_judge`, `stackgate`, `wire/slots.py`, `doctor/profiles.py`, `launch/check.py`); `app/checks/authorization.py` (46 lines, no approval logic: the judged-tree profile reader for `cli/green`, `release/gate`, `launch/check`, `push_judge`, `stackgate`); `hook/prepush.py` (forwards stdin to `tl judge-push`, fails closed); `owner_author` in config (owner-comment trust, not approval).

**Docs:** README lines 64 to 66 and 68 to 76; SKILL.md lines 221 to 227 and 344 to 346; `docs/glossary.md` 17 to 18; `docs/design/topology.md` 58, 63. Security docs: SEC-FABLE-04 becomes accepted risk; SEC-FABLE-02, SEC-OPUS-23, SEC-OPUS-43 touch the same path; ledger M-001 keeps the base read and drops the refusal.

**What it prevented (per the docs, for the record):** a worker editing `.task-loop.json` on its task branch to weaken gate checks, add host argv checks or widen `writer_exec_allow`, then landing it. The base-commit read stays, so a branch's own edit still cannot judge its own push.

**Tests:** delete `tests/land/test_profile_owner.py`, `tests/stores/test_profile_changes.py`; edit parts of `test_push_judge`, `test_stack`, `test_queue_land`, `test_queue_gate`, `test_stackgate_policy`, `real/test_push_policy`, `hook/real/test_prepush`, `adapters/test_git_read_failures`, and the `.task-loop.json` cases in `tests/asks/test_trustroots.py`, `tests/write/test_trustroots.py`, `tests/run/test_trustroot_reviewers.py`. Keep `tests/adapters/test_profile_at.py`, `tests/hook/test_prepush.py`.

### 15.8 One profile reader (direction, from the owner's question "why have profile_at.py at all")

`adapters/profile_at.py` (47 lines) opens `.task-loop.json` at a commit or in a working tree. Commit-reading exists so the gate and the push judge read the base's profile, not the branch's: that guard goes with A12 (the owner trusts the file). Without it every reader needs only the file in a checkout: the slot's working tree during a run (it holds main merged in, D13), and the repo's main checkout for the loop, `wire/slots.py` (slot count), `doctor` and `launch/check`. So the reader becomes `config.load_file(path)` in the kernel config module (about 10 lines: read, parse an object, `config.load`), and `adapters/profile_at.py`, `raw_at`, the `show`/`ls_tree` fallback and the base-commit reads in `push_judge`, `stackgate` and `wire/slots.py` go.

Work item A13 (needs A12): replace `profile_at` by `config.load_file`; callers read the file in the checkout they run in. Check before work starts: `push_judge` and `tl judge-push` run from a pre-push hook and judge a tip commit; confirm they have a checkout to read, or what they read when the pushing checkout is not the task's. Status: direction.

Also: `app/checks/authorization.py` is the check-receipt query (profile of the judged tree, then the stored receipts of the required checks); rename `check_receipts` (H2). Check definitions live only in the `checks` section of the profile; passes live in `factory.db` table `check_pass` keyed by run key, tree and base.

### 15.9 Glossary alignment (`docs/glossary.md`, "one canonical name per concept")

- **receipt** is defined: "the stored green result of one check under its RunKey, kept with who made it and where its output is. A failure is never a receipt." So `check_receipts` is the glossary's word. But `tlkernel/receipts.py` uses "receipt" for a different thing (owner-command receipts: the answer kept per idempotency key so a retried click does not act twice). One word, two concepts: rename the second (H9), for example "reply record" or "idempotent reply".
- **repo** is defined as "a registered git repository ..., known by its canonical name (origin `owner/name`; folder name when there is no remote). One home clone per machine." This answers Q9 in favor of the remote's canonical name, with the folder name as the fallback; the "one home clone per machine" rule is already written. The release clone is the exception that needs the remote's name (15.5).
- Entries that change with this document (a glossary edit per item, because the glossary says a word in the "Not" column is not used): **profile** ("as committed on the base branch": A13 reads the working tree), **owner** ("profile-change approval": A12), **trust root** (lists `.task-loop.json`: A12), **stage** ("one folder under `src/taskloop/app/`": section 16), **step**/**Step** (`reflect` is a step: A8), **gate**, **land-stack** ("serial core replaced by the merge queue").
- H8: update the glossary with every item that lands; the doc header says it was audited on 2026-11-07, so each change is a same-day edit.

### 15.10 A glossary derived from GitHub's words (owner question, direction only)

Idea: where a concept matches a GitHub one, use GitHub's word, so a newcomer already knows it; keep our own word only where the meaning differs. The mapping below is from general knowledge of GitHub and GitHub Actions vocabulary, not checked against GitHub's docs; each row needs a meaning check before a rename (the glossary says a word in "Not" is banned, and a rename is a hard cut).

| ours today | GitHub word | match |
|---|---|---|
| land | merge | the PR modes already say merge; `land` adds a word |
| merge queue | merge queue | same word, already used |
| gate | required status checks (branch protection) | the same idea: checks that must be green before merge |
| check | check run (a status check) | one named command with a conclusion |
| receipt | a check run with conclusion `success` | our receipt is keyed by tree and base like a check run on a commit |
| RunKey | cache key | the same idea as `actions/cache` keys |
| bead | issue | already planned to become `task`; GitHub's is `issue` |
| ask | a review request / a comment that blocks | partial |
| artifact | artifact | same word |
| step | step (inside a job) | differs: ours is an engine phase (write, checks, review), GitHub's is one command |
| stage | job | differs: ours is a code folder per phase |
| run | workflow run | close: one engine pass over one bead |
| loop, slot | runner (self-hosted), workspace | differs: a slot is a persistent worktree, a runner is a machine |
| worker | (none; "agent") | keep ours |
| profile | workflow file / repository settings | differs: ours is one JSON file for the repo |
| trust root | CODEOWNERS / protected paths | gone with A12 and maybe trustroots |

Work item H10 (needs the owner's pick of rows): rewrite `docs/glossary.md` with the chosen GitHub words, one hard-cut rename per word. Order after G1, so a word is renamed once together with its package.

### 15.11 Reduced vocabulary (owner: adopt GitHub's words, fewer words; "check" not "check run"; "task" not "issue")

Proposed set, one word per concept; everything not listed stops being a glossary term (or is internal and not named in docs):

| word | replaces | note |
|---|---|---|
| factory | factory | one install, one `factory.db` |
| repo | repo | canonical name = origin `owner/name`, folder name without a remote |
| task | bead | the owner's pick; `bd` stays the backend behind a port |
| slot | slot | a persistent worktree |
| run | run | one engine pass over one task |
| step | step, stage | one phase (plan, write, checks, review, merge); the word `stage` goes, a step's code folder is also called a step |
| check | check, check run, gate | one named command with a verdict; `gate` becomes "required checks" |
| pass | receipt, `PassRecord` | the stored green result of a check for a tree and base; the code already says `check_pass` and `PassRecord`; a failure is never a pass. The word `receipt` is freed (also from the owner-command meaning, H9) |
| merge | land | `merge queue` stays |
| ask | ask | a question to the owner that parks a task |
| worker | worker | one model call |
| profile | profile | `.task-loop.json` |

Dropped as terms: `loop` (a process, not a concept; "the factory runs tasks"), `RunKey` (say "check key"), `Carry` (a pass reused when only the base moved: "reuse"), `facts`, `Asked`, `role`, `trust root`, `land-stack`, `piece`, `epic`. Decided by the owner (2026-11-07): `pass` replaces `receipt`.
