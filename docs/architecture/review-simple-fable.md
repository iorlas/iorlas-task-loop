# Review, lens 6: radical simplification (SIMPLE-FABLE)

Read 2026-11-02 against task-loop 0.23.299 (`/home/iorlas/Workspaces/wt/C4`, HEAD `d4dd972b`) and delegate 0.55.0 (`/home/iorlas/Workspaces/wt/UNITYD`,
HEAD `ebe839c`). Static reading; nothing run. Paths: `tl/` = `src/taskloop/`, `dash/` = `src/taskloop_dash/`, `dg:` = `src/delegate/`.
Every number is a `wc -l` of this session; every `file:line` was opened. "(unverified)" marks what I could not settle.

The question of this lens: if we rewrote it tomorrow with everything we now know, what is the 30%-size design? Then: what of today's
code is that design's deletion list, which features do not pay their weight, and how to get there without stopping Trust Night.

---

## 0. The denominator, measured

| Thing | Lines | Files |
|---|---:|---:|
| task-loop `src/taskloop` + `src/taskloop_dash` (py) | 44,682 | 491 |
| of which `contracts/` | 7,294 | |
| of which `app/run/` | 6,071 | |
| of which `domain/` | 5,852 | |
| of which `adapters/` | 3,733 | |
| of which `taskloop_dash/` (py) | 3,518 | |
| dashboard static (html, js, css) | 2,811 | |
| `skills/task-loop/tl.py` + `SKILL.md` | 460 + 674 | |
| vendored shelf copies (`skills/task-loop/_vendor`) | 6,297 | |
| `dev/*.py` | 1,425 | |
| task-loop tests | 56,195 | 461 |
| of which `tests/support/` | 6,842 | |
| delegate `src/delegate` | 7,909 | |
| delegate vendor | 1,832 | |
| delegate tests | 7,739 | |
| `.importlinter` | 484 lines, 26 contracts | |
| `tl.py` verbs | 47 (`skills/task-loop/tl.py:405-448`) | |

Production code of the factory (both apps, vendor included, dashboard page included): about **64,000 lines**. Tests: about **64,000**.
The 30% design below is **~19,000 lines of production code and ~20,000 of tests**. The honest claim is 30-35%, not 20%: the domain
really is wide (plan, write, check, review, land, close, lanes, slots, a page) and the vendored git layer does not shrink by wishing.

Also measured, because it explains the shape: 383 of the 1,198 commits are version bumps (`git log --format=%s | grep -c '^0\.'`), with 59, 40 and
69 releases on 2026-10-28, -29 and -30. The code that lets a bead survive a release mid-run (section 3, D4) exists to serve that cadence.

---

## 1. Top 10 by importance

1. **SIMPLE-FABLE-01** One SQLite authority (`factory.db`) with four tables replaces 40-odd file families and every get-then-put race; files keep only evidence.
2. **SIMPLE-FABLE-02** The engine is six step functions over `(inputs, ports) -> Transition`; the 38-part `Engine` service locator, `carries_state`, `host: Any` and `tests/support/narrow_hosts.py` go.
3. **SIMPLE-FABLE-03** Delete the mid-bead version hop (reload, reexec, pins, bad-versions, fall_back): a release waits for the bead; the loop moves between beads only.
4. **SIMPLE-FABLE-04** 47 verbs become 12; the dashboard's nine POST verbs spawn `tl VERB`; `bd` stays the owner's tool for beads.
5. **SIMPLE-FABLE-05** Delete the features that are products of their own: look/pictures, reflect digest, land-stack, the M2 scorecard, shared flaky notes, ADRs, handoff.
6. **SIMPLE-FABLE-06** One delivery judge, one profile reader (base commit), one repo key, one delegate lookup: four "one"s that remove ~1,500 lines and three P1s.
7. **SIMPLE-FABLE-07** Slots become `git worktree` dirs named by lane; the lease is the `attempt` row; `.task/engine.lock`, tickets, slot beads, `Owned` records go.
8. **SIMPLE-FABLE-08** The Git port shrinks from 72 methods to ~25 by making the engine stop doing git porcelain itself (commit/rebase/salvage/restart/recheck collapse into one `land` step with one fix round).
9. **SIMPLE-FABLE-09** One plugin, one release, one vendor set; delegate stays a subprocess for the sandbox line, not for distribution.
10. **SIMPLE-FABLE-10** Raise the 400-SLOC file cap to 800 and cut the file count by two thirds: Codex writes every line, and 491 files averaging 91 lines is the wrong shape for a model that reads files, not graphs.

---

## 2. The 30% design, concretely

### 2.1 Modules (one package `taskloop`, no `app/` slices, no layer contracts beyond three)

| Module | Job | Lines (target) | Replaces today |
|---|---|---:|---|
| `records.py` | msgspec records: `Job`, `Attempt`, `Plan`/`Stage`, `CheckKey`/`Pass`, `Ask`, `Profile`, `Stop`, `Outcome` | 900 | `contracts/` 7,294 (`config.py` 411 with 13 record classes and 139 fields at `contracts/config.py:16-247`; `dash.py` 562; `log.py` 358; `answers.py` 335; `delegate.py` 301) |
| `db.py` | `factory.db` (stdlib sqlite3, WAL, `BEGIN IMMEDIATE`), `commit(expected_rev, row, effects)` | 400 | `contracts/stores.py` 559, `locator.py` 178, `parks.py` 46, `loop.py` 122, `runlife.py` 73, `fence.py` 111, `stores/` 653, `app/loop/files.py` 134 |
| `ports.py` | `Beads`, `Git` (≤25 methods), `Delegate`, `Spawner`, `Clock` | 250 | `contracts/ports.py` 511 (Git alone has 72 methods, `ports.py:141-376`) |
| `bd.py`, `git.py`, `delegate.py`, `procs.py` | the four adapters, over vendored `git_porcelain`, `stream_proc`, `process_lock` | 900 | `adapters/` 3,733 |
| `profile.py` | `.task-loop.json` read once, at the base commit, by everyone | 250 | `app/wire/slots.py` 301 (profile), `app/land/push_judge.py:49-58` (a second reader), `app/checks/authorization.py` (a third) |
| `steps.py` | `plan`, `write`, `check`, `review`, `land`, `close`: `step(inputs, ports) -> Transition` | 1,800 | `app/run/` 6,071, `app/write/` 881, `app/plan/` 945, `app/review/` 611, `app/land/` 2,846 |
| `policy.py` | the stop table `(scope, permanence, retry) -> Action` and `POLICY[Kind]` | 350 | `domain/lanes/policy.py` 329 (keep most), `domain/outcome.py` 188 (keep), `domain/lanes/pauses.py` 104, `retry.py` 58, `app/run/lane_acts.py` 201 |
| `prompts.py` | the brief texts, one per step | 500 | `domain/prompts/` (8 files), `domain/plan/brief.py` 182, `domain/brief.py` 120 |
| `checks.py` | registry, plan, executor, full-key evidence, container run | 700 | `app/checks/` 1,890, `domain/checks/` (16 files), `adapters/container_run.py` 93 |
| `judge.py` | `judge(repo, tips, base) -> Allowed | Refused | Unavailable`: the one delivery authority | 150 | `app/land/push_judge.py` 107, `stackgate.py` 69, `app/land/gate.py` 178, `cli/green.py` 40, `checks/cache.py:255-272` |
| `loop.py` | pick, admit (bundle), spawn `tl run`, settle; N lanes = N processes of this one module | 500 | `app/loop/` 1,733, `app/launch/loop.py` 317, `app/launch/factory.py` 134, `cli/loop*.py` 181, `cli/factory.py` 107 |
| `cli.py` | 12 verbs, argparse, one `Ctx` | 300 | `tl.py` 460 + `cli/` 1,110 + `app/wire/` 865 + `app/track/` 287 |
| `hook.py` | pretool (pkill guard) and the pre-push client, stdlib only | 120 | `hook/` 223 (keep the shape) |
| `dash/serve.py` + `dash/page.html` | reads `factory.db` read-only, serves one page, `POST /api/<verb>` spawns `tl <verb>` | 600 + 2,000 | `taskloop_dash/` 3,518 py + 2,811 static, `app/launch/dash_ports.py` 154, `app/launch/dash.py` 222 |
| vendor | `git_porcelain` 4,511, `stream_proc` 804, `jsonl_log` 425, `process_lock` 237, `atomic_io` 91, `child_env` 93 | 6,200 | the same, at one tag set, prepended to `sys.path` |
| delegate | `route.py run|status|contract|net`, router, lease, launch, supervise, classify, settle, three harnesses | 4,500 | `dg:` 7,909 |

Sum: about **19,500** production lines including vendor (today 64,000). Without vendor: ~13,000 (today ~56,000).

### 2.2 Stores

One authority, one evidence tree, and nothing else under `~/.config/task-loop`:

```
factory.db          SQLite, WAL. Tables:
  job      (id, repo, bead, bundle_tl, bundle_dg, profile_commit, state, rev)
  attempt  (id, job, host, pid, start_id, heartbeat, step, stage, plan_json, outcome_kind, outcome_text, rev)
  effect   (job, key, state, result)            the close's outbox: bd close, bd sync, comment, follow-up, branch delete
  pass     (repo, check_key, tree, base, plan_digest, result, run)   the delivery evidence, full key
  ask      (bead, id, kind, text, status, answer, t)
  loop     (id, repo, host, pid, start_id, lane, state, command)
runs/<run>/         logs, raw answers, check outputs, screenshots: evidence, never authority
locks/              flock files (land-<url>, suite-host); holder hint in the db row
host.json           what this machine has (unchanged)
bin/tl, githooks/   the shim and the 14 dispatchers (unchanged, written atomically)
```

What this deletes, by file family (`tl/contracts/paths.py:22-234` names 40 of them): `runs/R/manifest.json`, `owner-request.json`,
`checkpoints/B.json`, `B.call.json`, `parks/`, `pauses/`, `reexec/`, `landed/`, `followups/`, `loop/K.<pid>.json`, `K.command.json`,
`K-rest.json`, `K.jsonl`, `loop/K/exits.jsonl`, `died-<pid>.json`, `slots/K/*.json`, `seq`, `*.setup`, `slot-state/`, `worktrees/K/`,
`events.jsonl`, `traces.jsonl`, `sessions/`, `repos.json`, `shared/`, `pinned.json`, `bad-versions.json`, `releases/`, `reflect-*.json`,
`handoff/`, `decisions/`, `asks/`, `ask-ledger.jsonl`, `snapshots/`, `usage-history.jsonl`, `dash.json`, `dash.pid`, `cache/beads-*.json`,
`check-durations/`, `results/` (becomes the `pass` table). The `.task/engine.lock` and `.task/engine.take` in the writer's tree
(`paths.py:276-281`) go with them: the `attempt` row with `(host, pid, start_id)` is the lock.

Why SQLite and not "a locked JsonStore": the zoom-out review's Z04 proposes `JsonStore.update(fn, expected_revision)` under a per-document
flock as a first step. That keeps 40 families and adds a lock to each. One table with a `rev` column is less code than one locked store
per family, and the dashboard's "join everything" views (`dash/views/` 1,815 lines of hand joins over JSONL and JSON) become SQL.

### 2.3 The few verbs

```
tl run BEAD [--worktree W] [--lane N]   one bead, this process (the loop's child; also a person's foreground run)
tl loop [--lanes N] [--until T]         N processes of loop.py; replaces loop, factory start/status/stop/logs, next, cutover
tl stop [--lane N]                      a loop command row
tl status [--json]                      one query over factory.db (+ route.py status --json); replaces status, lanes, usage, lost, wait, trace, report, queue
tl answer BEAD TEXT | tl park BEAD | tl note RUN TEXT    the owner's three writes; replaces ask, answer, hint, hold, override, park, note
tl check [--gate]                       the registry on this tree; replaces check, gate, green
tl judge-push                           the pre-push client
tl prune                                old runs/, merged branches
tl doctor                               profile + install sanity
tl dash [ensure|stop]
```

Twelve. The 35 deleted verbs and where their job goes: `actor`, `bd`, `register`, `claim`, `land`, `close`, `block`, `queue`, `lint`,
`slot`, `worktree`, `worktrees`, `land-lock`, `land-stack` -> `bd` and `git` directly (the person has them; the engine never needed
the verb); `trace`, `report`, `lost`, `wait`, `handoff`, `reflect` -> `tl status --json` and the page; `pin`, `rollback`, `cutover`
-> deleted with the hop (D4); `hooks` -> the shim writer runs inside `tl doctor`; `selftest` -> `tests/e2e`; `next`, `factory` -> `loop`;
`usage`, `lanes` -> the dashboard asks delegate itself.

### 2.4 The engine as steps

```python
def plan(i: Inputs, p: Ports) -> Transition      # Planned(plan) | Ask(spec) | Stop(kind)
def write(i, p) -> Transition                    # Written(tree) | Replan(why) | Ask | Stop
def check(i, p) -> Transition                    # Green(passes) | Red(fix_brief) | Stop
def review(i, p) -> Transition                   # Accepted | SendBack(items) | Ask | Stop
def land(i, p) -> Transition                     # Landed(sha) | Conflict(fix_brief) | Refused(judge) | Stop
def close(i, p) -> Transition                    # Closed(effects applied) | Stop
```

`loop.run_attempt` is thirty lines: load the `attempt` row, pick the step from `(step, stage)`, call it, `db.commit(rev, transition,
effects)`, repeat. A stop is a `Kind` and the `POLICY` table (`tl/domain/outcome.py:64-92`, keep as is) says what the close does. The
lane policy (`tl/domain/lanes/policy.py:1-40`, keep) decides retry/wait/reroute inside `write`/`review` where the delegate call is made.

What this removes: the `Engine` with 38 `cached_property` parts built over itself (`tl/app/run/engine.py:190-250`), `carries_state`
installing writable aliases of every `RunState` field (`tl/app/run/state.py:45-103`), 36 `host: Any` parameters across `src/taskloop`
(grep), `RunOnce` (`tl/app/run/run_once.py:35-63`) and `run_stages`/`one_stage`/`select_step` (`tl/app/run/stages.py:44-160`: two
step-selection paths, one for the loop, one for `--stage`), and the test shape they force: `tests/support/narrow_hosts.py` (778 lines of
typed fakes "of what a slice reads of the engine", `narrow_hosts.py:1-3`) and `tests/support/engine_case.py` (765).

---

## 3. What to delete from today's code

Grouped by the reason the lines exist. `wc` is of this session. Tests named are the ones whose assertions break; counts of test lines
are by file where a slice has its own folder, else "(grep-wide)".

### D1. Features that are products of their own (not worth their weight)

| Feature | Files (lines) | Why it does not pay |
|---|---|---|
| **Look / pictures / owner-look** | `tl/app/look/shots.py` 239, `judge.py` 197, `owner_look.py` 143, `keep.py` 115; `tl/app/asks/looks.py` 129; `tl/domain/look/matchers.py` 25; `tl/domain/review/visual.py` 83; `tl/contracts/gallery.py` 83; `dash/api/looks.py` 76; `Step.LOOK` in `tl/contracts/enums.py:13`; `look_rounds`, `look_max_px`, `visual_paths` in `tl/contracts/config.py:200,224-225`; tests `tests/look/` 421 | **1,090 lines** for a stage that is a check with `keep` globs: a check that produces PNGs under `runs/<run>/` and a reviewer brief that lists them. The "look judge" is a reviewer call with pictures. The render-again rule in `run_once.py:91-94` and the owner-look bead (`run_once.py:108-109`) are an epic-level product feature that belongs in lifesim's own tooling, not in the factory. |
| **Reflect digest** | `tl/app/report/reflect.py` 247, `tl/domain/report/reflect.py` 172, `tl/app/run/reflect.py` 74, `tl/domain/prompts/reflect.py` 19, `Step.REFLECT` (`enums.py:17`), `reflect: bool` (`config.py:181`), the daily chore (`tl/app/launch/loop.py:159`), `reflect-digest.json`/`reflect-view.json` (`paths.py:221-225`) | **512 lines** + a reviewer-lane call per bead to write "what went badly" into a digest nobody has shown drives a fix. A close comment on the bead carries the same text for free. |
| **land-stack** | `tl/app/land/stack.py` 218, `forge.py` 70, `stackgate.py` 69, `tl/cli/land_stack.py` 89, `tl/contracts/forge.py` 59; tests mentioning it 3,332 lines (grep-wide, over-counts) | **505 lines** to deliver human PRs through the engine's judge. It is the only `gh` user (`c4-task-loop.md` Level 1 table). The person pushes a PR with `gh`; the pre-push judge still runs. |
| **M2 scorecard, traces, lost, report** | `tl/app/report/card.py` 207, `inputs.py` 66, `planner.py` 64, `window.py` 20; `tl/cli/report.py` 190; `tl/domain/report/matchers.py` 182; `tl/contracts/trace.py` 164; `tl/app/run/trace.py` 113; `traces.jsonl` | **1,006 lines** of a second event model (`RunTrace` v2) beside `events.jsonl` (`tl/contracts/events.py` 150, `tl/app/track/trail.py` 81) and the engine log (`tl/contracts/log.py` 358). Three logs of one run. With `attempt` rows the scorecard is a SELECT. `report/planner.py` reads delegate's `history.jsonl` by path (Z09). |
| **Shared flaky notes** | `tl/app/run/shared.py` 108 (`shared.py:1,15`: "the tests known to be flaky", 14-day memory), keyed by a fourth repo key (`c4-task-loop.md` item 6) | A flaky test is a bead with a label, or a `retry: 1` in the registry (`SKILL.md:52`). 108 lines and a file family for a cache of prose. |
| **ADRs / decisions** | `tl/contracts/adrs.py` 86, `tl/app/plan/decisions.py` 43, `dash/views/learning.py` 87, `decisions/K/` (`paths.py:76-91`) | Decisions are beads or a doc in the repo. A store the dashboard "sticks" into is a second tracker. |
| **Session handoff** | `tl/app/write/handoff.py` 122 (writer handoff: keep as a brief paragraph), `tl/app/wire/handoff.py` 22, `tl/hook/session.py` 48, `docs/contracts/handoff-v1.md` 55, `handoff/K.md` | The orchestrating Claude session's compaction handoff is Claude's problem and the skill's; the engine ships a hook for it. |
| **Asks as a subsystem** | `tl/app/asks/` 732, `tl/domain/asks/` 183, `tl/contracts/ask.py` 116, `ledger.py` 69, `tl/cli/asks.py` 196, `tl/app/run/ask_flow.py` 65, seven verbs (`tl.py:424`) | **~1,360 lines** for "the bead is blocked with a question; the owner answers". The 30% design: an `ask` row + a bd comment + `status=blocked`. The sweeps (`tl/app/asks/sweeps.py` 145: close orphans, park after three days) are one SQL and one loop chore. `stick.py` (96, "what the owner turns an answered ask into", dash-spec 5.3) is product surface for a page one person uses. |
| **Waits / stuck tick** | `tl/app/run/waits.py` 146 (a `WaitsHost` Protocol with 12 members, `waits.py:36-62`), `tl/app/run/stuck.py` 38, `tl/domain/stuck.py` 71 | Wait time as "its own segment never counted in budget_min" (`waits.py:1`) is one column on `attempt`; the stuck rule reads the engine's own log back (`stuck.py:1`) to decide the engine is stuck: the heartbeat row's `step` and `t` say the same. |
| **Delegate status mirroring** | `tl/contracts/snapshots.py` 171, `usage.py` 63, `delegate_status.py` 54, `tl/app/wire/lanes.py` 77, `wire/usage.py` 26, `snapshots/`, `usage-history.jsonl`; the 20-minute chore (`launch/loop.py:155`) that also mutates delegate's config (Z19) | **391 lines** copying `route.py status --json` into task-loop's folder so the page can read it. The page runs `route.py status --cheap` itself. |

D1 total: about **5,300 lines** of `src`, plus their tests (look 421, report 840, asks 2,037, and grep-wide shares of land and run).

### D2. The engine's mechanism that only exists because of the host object

| What | Where | Lines |
|---|---|---:|
| `Engine` service locator, aliases, forwarders | `tl/app/run/engine.py` 413 (`:103` `@carries_state`, `:190-250` 38 parts, `:95-100` `land_with_engine`/`close_with_engine`), `state.py` 243 (`:45-103`), `fields.py` 97, `closer_host.py` 100, `lander_host.py` 92, `checks/host.py` 145, `review_glue.py` 27 | ~1,100 |
| Two step cursors | `tl/app/run/stages.py` 350 (`:44-61` continuous vs `one_stage`, `:83-106` `select_step`/`checkpoint_next`, `:162-257` `record_stage`), `run_once.py` 262 | 612 -> ~150 |
| Call identity, recovery, memo, strays | `tl/app/run/worker_identity.py` 107, `worker_recovery.py` 93, `done_memo.py` 58, `strays.py` 26, `tl/stores/call_state.py` 134, `calls.py` 117, `worker_request.py` 58 | 593 -> one `call` column on `attempt` (key, state, answer path): ~80 |
| Closer in six files | `closer.py` 184, `closer_branch.py` 95, `closer_decide.py` 74, `closer_notes.py` 129, `closer_record.py` 88, `closer_settle.py` 89, `tl/domain/effects.py` 160 | 819 -> the `effect` table and one `close` step: ~250 |
| Resume | `tl/app/run/resume.py` 191, `app/land/salvage.py` 64, `restart.py` 95, `recheck.py` 72, `fix_outside.py` 79, `fixer.py` 134, `land_rebase.py` 41, `rebase.py` 144 | 820 -> a `land` step: fetch, rebase, one fix round, judge, push, else `Conflict` -> replan: ~200 |
| Owner requests | `tl/app/run/requests.py` 169, `tl/contracts/requests.py` 25, `owner-request.json` + lock | 194 -> the `loop.command`/`attempt.command` column |
| Test harness of the above | `tests/support/narrow_hosts.py` 778, `engine_case.py` 765, `fake_route.py` 267 | 1,810 -> ~500 |

D2 total: about **4,100 lines** of `src` and ~1,300 of `tests/support`.

### D3. Slots, locks, worktrees, claims: four mechanisms for "one lane works in one directory"

`tl/app/slots/` 1,017 (`pool.py` 188 "a slot is a worktree plus its bd bead, which is the lease", `reset.py` 199, `owned.py` 134,
`verbs.py` 133, `engine_lock.py` 141, `lease.py` 53, `line.py` 48, `marks.py` 52, `env.py` 69), `tl/app/wire/slots.py` 301,
`tl/contracts/slots.py` 100, `worktrees.py` 17, `tl/domain/slot_env.py` 29, `tl/adapters/slotcheck.py` 54, `landlock.py` 92,
`locks.py` 121, `tl/contracts/locks.py` 70, `guard.py` 15, `fence.py` 111; tests `tests/slots/` 2,062.

**~2,200 lines.** In the 30% design a lane is `worktrees/<repo>/<lane-N>` made with `git worktree add` once; the lane's process owns it
while its `loop` row is live; the bead is claimed in bd once (not twice: `c4-task-loop.md` item 8, `tl/app/launch/loop.py:164-170` then
`tl/app/run/entry.py:387-396`); the fence is `attempt.rev`. The slot bead in bd ("the lease"), the ticket files, the `.setup` stamp,
`slot-state/` and the `Owned` record are five more records of one fact. Target ~300 lines.

### D4. The mid-bead version hop and its safety net

`tl/app/run/reload.py` 124 (`safe_point` at `:68-88`, `switch` at `:102-124`), `tl/app/release/reexec.py` 76, `tl/app/loop/versions.py` 100,
`release/pins.py` 99, `catalog.py` 54, `selfupdate.py` 37, `cache.py` 26; `Loop.fall_back`/`exec_to` (`tl/app/loop/loop.py:123-144`),
`maybe_move` (`loop.py:209`), `TL_REEXEC` handling in `engine_lock.py`, `reexec/B.json`, `runs/R/reexec.json`, `pinned.json`,
`bad-versions.json`; 20 call sites of `safe_point`/`reexec.` in `src/taskloop` (grep); tests mentioning reexec/Reload 1,692 lines (grep-wide).

**~600 lines of src and the incident class A.F04/A.F06 (zoom-out Z05).** The 30% design admits a job with `(bundle_tl, bundle_dg)` and
runs it on that pair until the close; the loop re-reads `installed_plugins.json` between beads only. A fix released during a bead
waits one bead. With 69 releases in a day (2026-10-30) that is the only sane rule anyway: the hop machinery is what made 69 releases a
day feel safe, and it is the second-largest source of incidents in the dataflow review.

### D5. Release and suite inside the plugin

`tl/app/release/` 1,143 minus D4's 316 = `suite.py` 253, `flow.py` 186, `publish.py` 95, `shell.py` 72, `tidy.py` 60, `clone.py` 53,
`push.py` 49, `manifest.py` 38, `seams.py` 45 (keep), `dev/release.py` 48, `dev/suite.py` 39, `dev/suite-docker.py` 99, `releases/`,
`suite-green.json`; tests `tests/release/` 845.

**~800 lines.** A release is `dev/release.py`: a 150-line PEP 723 script with its own clone, `just check`, bump, push under one flock,
tag, marketplace bump, `claude plugin update`. It does not need `taskloop.app` and should not ship in the plugin (every install carries
its own release pipeline today). The "run origin/main's release code" exec dance (`selfupdate.py:1`) is only needed because releases
are so frequent that the checkout lags; see D4.

### D6. Duplicated authorities (the zoom-out's R-A root cause, as deletions)

| Fact | Readers today | Keep one |
|---|---|---|
| Delivery verdict | `push_judge.py:71-75` via `green_result` ("must never authorize delivery", `tl/app/checks/cache.py:263-265`), `stackgate.py:36`, `land/gate.py`, `cli/green.py` | `judge.py` (`judge()`); `green_result`/`is_green` (`cache.py:255-272`) deleted |
| Profile | base commit (`wire/slots.py:42-68`), working tree (`push_judge.py:49-58`), judged tree (`checks/authorization.py:17-19`) | `profile.py` at the base commit; a candidate changing `.task-loop.json` is judged by the base |
| Repo key | `ids.loop_key`, `ids.repo_key`, `check_files.repo_key`, `shared.py:29` | one `RepoId` |
| Delegate path | `adapters/delegate.py:88-113` resolve, `:116-129` find_route | one |
| Stop reason | delegate's four sites, task-loop's synthesized stops (`adapters/delegate.py:197-205`) and four permanence re-derivations (A.F07) | delegate's `classify`; the engine maps `(producer, reason)` once in `policy.py` |
| Loop state | factory placeholder + child + renaming reader (`tl/app/launch/factory.py:67-70`, `app/loop/files.py:59-61`) + dashboard's own glob | the `loop` row |

### D7. Contracts, layers and rules that police the deleted shape

`.importlinter` 484 lines, 26 contracts, of which per-slice forbidden lists `:141-503` exist only because there are 18 app slices; `tests/rules/`
1,786 lines (ratchets for oversize, env, git, type; `test_state_writers.py:1-3` enforces "a state file is a Rec on a Doc" across 40
families; `test_tree_writer.py`, `test_stage_entry.py`, `test_runstate_rule.py` police the host object). With 14 modules the layer rule
is three lines (`records`/`ports` import nothing of ours; `steps`/`loop`/`cli` import adapters only through `ports`). Keep the 80-line
function cap and `test_pep723.py`; raise the file cap to 800 (SIMPLE-FABLE-10).

### D8. The dashboard

`dash/views/` 1,815 py (hand joins over JSONL and JSON), `dash/readers/` (own glob of loop files, own `loop_key` copy at
`readers/loops.py:7-9`), `contracts/dash.py` 562 (a typed snapshot of everything), `api/writes.py` 168 (nine verbs through engine ports
loaded by name, `tl/app/launch/dash.py:147`), static 2,811. **~6,300 lines for one viewer on a phone.** The 30% page: one `serve.py`
(~600) that SELECTs from `factory.db` (`mode=ro`), tails `runs/<run>/*.jsonl` for the live view, proxies `route.py status --cheap`,
and `POST /api/<verb>` = `subprocess.run(["tl", verb, ...])`; one `page.html` (~2,000: the present one minus the look gallery, learning,
ledger and needs views).

### D9. Delegate

| Delete | Lines | Why |
|---|---:|---|
| `dg:app/cockpit.py` | 239 | `cockpit.py:1-2`: one row per lane with the pick `next worker` would make; `status --json` already carries the rows, the text rendering belongs in the skill or the page |
| `dg:app/doctor.py`, `app/onboard.py` | 123 + 94 | `doctor.py:2`: "nothing here installs, logs in or decides": a table the README can be |
| `dg:adapters/agent_runs.py` | 58 | no consumer (Z10); deletes other producers' files (`c4-delegate.md` item 13) |
| `dg:app/codex_policy.py` + `--exec-allow` parser branch | 37 + ~30 | Z11 ❌ as designed; the engine-run-command alternative lives in task-loop |
| `dg:domain/routing/dwell.py` + `prev` writes | 22 + ~10 | `sticky` has no caller (`c4-delegate.md` item 1); `min_dwell_minutes` changes nothing |
| `dg:adapters/statusline.py` + `capture-limits` | 30 + ~15 | writes into Claude Code's own state dir |
| `dg:contracts/status.py` 239 + `app/status.py` 115 | 354 -> ~120 | one `Status` record with lanes and windows; the snapshot cache (`status-snapshot.json`) goes when `status --cheap` is the only poll |
| `dg:domain/health/ledger.py` 176 + `history.jsonl` fold | 176 -> 60 | contrarian, see SIMPLE-FABLE-27: task-loop's lane policy already pauses a lane on the same facts |
| `dg:adapters/harness/opencode.py` 325 + `opencode_sandbox.py` 99 | 424 | ❓ Mac-only lanes (Grok, DeepSeek free, Z.ai); keep only if their landed-bead share justifies 20% of delegate |

Delegate target: ~4,500 of 7,909.

### D10. Sum of the deletion list

| Group | src lines out (approx.) |
|---|---:|
| D1 products of their own | 5,300 |
| D2 host-object mechanism | 4,100 |
| D3 slots/locks/claims | 1,900 |
| D4 mid-bead hop | 600 |
| D5 release in the plugin | 800 |
| D6 duplicated authorities | 1,500 |
| D7 rules and contracts policing the old shape | 1,400 (`.importlinter` + `tests/rules` share) |
| D8 dashboard | 4,300 (py + static) |
| D9 delegate | 3,400 |
| contracts/ records collapse (13 config classes, 3 log models, dash snapshot) | 4,500 |
| adapters collapse (Git 72 -> 25 methods; `git.py` 325, `git_base.py` 150, `git_ops.py` 96, `gitmemo.py` 100, `treehash.py` 104, `gitrepo.py` 91) | 1,500 |
| domain matchers (`domain/*/matchers.py`: 11 files, ~1,250 lines of regexes behind the "re only in matchers" rule) | 700 |
| **Total** | **~30,000 of ~56,000 non-vendor** |

Plus the vendored copies stay (6,300 + 1,800 -> one set of ~6,300). Net: ~64,000 -> ~20,000. Tests follow the code: the per-slice
folders of deleted slices (look, report, asks, slots, release, land-stack share of land, dash views) are ~12,000 lines; the harness
(`tests/support`) halves; what remains is ~20,000.

---

## 4. Migration path that never breaks the running factory

Rule for every phase: the Mac's Trust Night runs the released version it has; nothing in a phase changes a running bead; each phase is
released alone and the next starts after one night of Trust Night at the new version with the landed/parked counts within noise of
the night before (the parity metric: `tl status --json` today, the `attempt` table later).

**Phase 0, a week: stop the bleeding without changing shape.** Z01, Z02, Z03, Z14 (push path), Z13 (one delegate lookup), Z19
(delegate status writes nothing). Freeze: no new slice, no new verb, no new file family. Set a release budget: at most two releases
a day; this is what makes D4 deletable later.

**Phase 1, strangler on state (SIMPLE-FABLE-01).** Add `db.py` and `factory.db` behind `Stores` (`tl/stores/bundle.py:19-36` is the one
seam every store goes through). Write-through: every `JsonStore.write` of a manifest, park, landed, loop state, ask, pass also writes
a row; readers switch family by family (loop state first: it has the renaming-reader bug; then manifests: the beat/mark_lost race;
then parks; then passes). A rule test counts files written per family and may only shrink (the ratchet pattern already in
`tests/rules/rules_ratchet.json`). A family's JSON writer is deleted when its reader count is zero. Reversible at every step: the db
is additive until the last reader moves.

**Phase 2, delete products (D1, D5, D4) behind profile flags, one release each.** Order: reflect (`config.py:181` already a flag), land-stack
(no engine path uses it), the M2 report (replace with `tl status --json` first, delete after a week nobody runs `tl report`), look
(lifesim's profile sets `visual_paths`; replace by a `keep`-glob check and a reviewer brief that names the files; run both for a week on
Trust Night; delete), release code out of the plugin (dev/release.py becomes self-contained first, then `app/release` goes), the hop
(set the loop to move between beads only; after a week with no mid-bead hop, delete reload/reexec/pins; `tl rollback` becomes
`claude plugin install <version>`).

**Phase 3, the engine as steps (SIMPLE-FABLE-02).** One step at a time, leaf first: `close` (its effects are already a list,
`tl/domain/effects.py:1`), then `land`, `check`, `review`, `write`, `plan`. For each: write `step(inputs, ports)` beside the part,
have the `Engine` call it (the engine becomes a thin adapter that builds `Inputs` from its fields), move the part's tests to the
function, delete the part. When six steps exist, `RunOnce.go` becomes `run_attempt` and `Engine` is a dataclass of the fields the
steps read. `narrow_hosts.py` dies with the last host Protocol.

**Phase 4, verbs and page (SIMPLE-FABLE-04, D8).** The dashboard's `writes.py` spawns `tl` for each verb (no behaviour change for the
owner); `dash_ports.py` and the runtime import of engine code go. Then the verb table: each deleted verb prints its replacement for
one release ("use `bd close`"), then is removed. The page's views become SQL over `factory.db` one view at a time; the look, learning,
ledger and needs views go with their features.

**Phase 5, slots (D3).** Replace the slot bead and tickets by `loop.lane` + `attempt` ownership; keep `git worktree` dirs where they are
(`.slots/`), so a running Mac factory finds its trees untouched. The engine lock file moves out of `.task/` first (Z15), then is
replaced by the row.

**Phase 6, one plugin (SIMPLE-FABLE-09).** After phases 1-5 the delegate contract is the only seam left; ship both skills from one
repo at one version with one vendor set. The subprocess boundary stays (env scrub, sandbox, process group), the distribution boundary goes.

Expected duration at Codex speed with one orchestrating session and the release budget: 6-8 weeks of calendar, since every phase is
gated on one Trust Night of parity. Fast is not the point; never stopping the factory is.

---

## 5. Idea ledger

Kinds: DEL = delete, MRG = merge into one, RPL = replace, KEEP = keep as is, CON = contrarian/low-confidence. Severity is the cost of
not doing it (P0 = the factory is wrong today). Effort S/M/L.

| id | idea | evidence (file:line) | kind | sev | effort | verdict | reason |
|---|---|---|---|---|---|---|---|
| SIMPLE-FABLE-01 | One SQLite authority `factory.db` (job, attempt, effect, pass, ask, loop); files keep evidence only | `tl/contracts/paths.py:22-234` (40 families); `tl/contracts/locator.py:104-178` (every method get-then-put); `tl/stores/bundle.py:19-36` (the seam) | RPL | P1 | L | ✅ | removes Z04's whole race class and the hand joins in `dash/views/` (1,815); stdlib only; Mac and devbox both have sqlite3 |
| SIMPLE-FABLE-02 | Engine = six step functions returning `Transition`; delete `Engine` locator, `carries_state`, `host: Any` | `tl/app/run/engine.py:103,190-250`; `state.py:45-103`; 36 `host: Any` (grep); `tests/support/narrow_hosts.py:1-3` (778 lines of fakes of the host) | RPL | P2 | L | ✅ | the host object is why every part needs a typed fake and why two step cursors exist (`stages.py:44-61`, `:83-106`) |
| SIMPLE-FABLE-03 | Delete the mid-bead hop: reload, reexec, pins, bad-versions, fall_back; the loop moves between beads only | `tl/app/run/reload.py:68-124`; `tl/app/loop/loop.py:123-144`; `tl/app/release/{reexec,pins,catalog,selfupdate}.py` (76+99+54+37); 20 call sites | DEL | P1 | M | ✅ | A.F04/A.F06 incidents; stronger than Z05's freeze: nothing to freeze if there is no hop. Cost: a fix waits one bead |
| SIMPLE-FABLE-04 | 47 verbs -> 12; deleted verbs print their replacement for one release | `skills/task-loop/tl.py:405-448` | DEL | P3 | M | ✅ | 35 verbs are bd/git wrappers, report readers or hop controls; the skill (`SKILL.md`, 674 lines) shrinks with them |
| SIMPLE-FABLE-05 | Delete look/pictures/owner-look as a stage; a visual check is a check with `keep` globs plus a reviewer brief that names the files | `tl/app/look/*` (694), `run_once.py:91-94,108-109`, `enums.py:13`, `config.py:200,224-225` | DEL | P3 | M | ✅ | 1,090 lines for a reviewer call with attachments; lifesim's taste judgement belongs to lifesim |
| SIMPLE-FABLE-06 | Delete reflect (step, digest, chore, prompt, two state files) | `tl/app/report/reflect.py` 247, `domain/report/reflect.py` 172, `app/run/reflect.py` 74, `launch/loop.py:159`, `config.py:181` | DEL | P3 | S | ✅ | one more lane call per bead to write prose into a digest; a close comment is the same text |
| SIMPLE-FABLE-07 | Delete land-stack, forge, stackgate | `tl/app/land/stack.py:1` ("deliver an existing PR"), `forge.py` 70, `stackgate.py` 69, `cli/land_stack.py` 89, `contracts/forge.py` 59 | DEL | P3 | S | ✅ | the only `gh` user; a person's PR goes through `gh` and the same pre-push judge |
| SIMPLE-FABLE-08 | Delete the M2 scorecard, traces.jsonl, `tl report/lost/trace`; `tl status --json` over the db | `tl/app/report/{card,inputs,planner,window}.py` (357), `cli/report.py` 190, `contracts/trace.py` 164, `app/run/trace.py` 113, `app/report/planner.py:12,35` (reads delegate's history by path) | DEL | P3 | M | ✅ | three logs of one run (`events.jsonl`, `traces.jsonl`, `engine/*.jsonl`); the scorecard is a SELECT once rows exist |
| SIMPLE-FABLE-09 | One plugin, one release, one vendor set; delegate stays a subprocess | `dev/vendor.json` (task-loop stream-proc v0.2.2; delegate v0.2.1 per Z23), `tl/adapters/delegate.py:88-129` (two lookups), `c4-system.md` C8/C9 | MRG | P2 | M | ✅ | agrees with R4 and goes further: no contract-integer skew logic at all once both ship together |
| SIMPLE-FABLE-10 | Raise the file cap to 800 SLOC; target ≤150 files; keep the 80-line function cap | 491 files / 44,682 lines = 91 per file; `CLAUDE.md` caps; `tests/rules/rules_ratchet.json` | CON | P3 | S | ✅ | Codex writes every line and reads files, not import graphs; 18 slices x 10 files is a navigation tax, not a design |
| SIMPLE-FABLE-11 | Asks become one `ask` row + a bd comment + blocked status; delete the asks slice, ledger, sweeps as a subsystem, `stick.py` | `tl/app/asks/` 732, `domain/asks/` 183, `contracts/ask.py` 116, `ledger.py` 69, `cli/asks.py` 196, `tl.py:424` (seven verbs) | RPL | P3 | M | ✅ | 1,360 lines for "blocked with a question"; the sweeps are one SQL and one chore |
| SIMPLE-FABLE-12 | Slots = worktree dirs per lane; lease = `attempt` row; delete slot beads, tickets, `.setup` stamps, `Owned`, `engine.lock` | `tl/app/slots/pool.py:1` ("its bd bead, which is the lease"), `engine_lock.py` 141, `wire/slots.py` 301, `paths.py:165-181,276-281`; double claim `launch/loop.py:164-170` + `run/entry.py:387-396` | RPL | P2 | M | ✅ | five records of one fact; the lock lives in the writer's tree (Z15); the claim is taken twice (item 8) |
| SIMPLE-FABLE-13 | Collapse the land path to one step with one fix round: delete salvage, restart, recheck, fix_outside, land_rebase as separate parts | `tl/app/land/salvage.py:1`, `restart.py:1`, `recheck.py:1`, `fix_outside.py:1`, `fixer.py:1`, `rebase.py` 144, `run_once.py:150-186` (the prepare ladder) | MRG | P2 | M | ✅ | 820 lines of ladders for "rebase; if conflict, one writer round; if still red, replan"; each rung is a place a P1 hid (Z01/Z02 live here) |
| SIMPLE-FABLE-14 | Git port ≤25 methods; the engine stops doing porcelain (no treehash, gitmemo, git_ops of its own) | `tl/contracts/ports.py:141-376` (72 `def`), `adapters/git.py` 325, `git_base.py` 150, `git_ops.py` 96, `gitmemo.py` 100, `treehash.py` 104, `gitrepo.py` 91 | MRG | P3 | M | ✅ | extraction #2 (git-porcelain convergence) only pays if the port is small first |
| SIMPLE-FABLE-15 | Release = `dev/release.py` self-contained (150 lines); delete `app/release/{suite,flow,publish,clone,push,tidy,shell,manifest}` from the plugin | `tl/app/release/` 1,143; `selfupdate.py:1` (exec origin/main's release code) | DEL | P3 | S | ✅ | every install ships a release pipeline it never runs; the self-update dance exists for the release cadence |
| SIMPLE-FABLE-16 | Delete the per-slice import-linter lists and three of four ratchets; keep three layer lines, the function cap, pep723 | `.importlinter` 484 lines / 26 contracts (`:141-503` per-slice); `tests/rules/` 1,786 | DEL | P3 | S | ✅ | the rules police the shape being deleted; `c4-task-loop.md` Level 3: "the import rules hold and prove little" |
| SIMPLE-FABLE-17 | Dashboard: `serve.py` over `factory.db` ro + `POST` spawns `tl`; delete views, readers, dash contracts, `dash_ports` | `dash/views/` 1,815, `contracts/dash.py` 562, `api/writes.py` 168, `tl/app/launch/dash.py:147` (runtime import), `dash_ports.py:57-63` (hard-coded repo name) | RPL | P2 | M | ✅ | Z08 done by deletion; the page keeps its HTML minus four views |
| SIMPLE-FABLE-18 | Delete delegate status mirroring (`snapshots/`, `usage-history.jsonl`, `tl lanes`, `tl usage`, the 20-minute chore) | `tl/contracts/snapshots.py` 171, `usage.py` 63, `delegate_status.py` 54, `wire/lanes.py` 77, `wire/usage.py` 26, `launch/loop.py:155` | DEL | P3 | S | ✅ | the page calls `route.py status --cheap` itself; the chore is what triggers Z19 |
| SIMPLE-FABLE-19 | Delete `shared.py` flaky notes, ADR store, session handoff hook, `wait`, `waits.py`, stuck tick | `tl/app/run/shared.py:1,15`, `contracts/adrs.py` 86, `hook/session.py` 48, `run/waits.py:1,36-62`, `stuck.py:1`, `domain/stuck.py:1` | DEL | P3 | S | ✅ | each is a second record of a fact bd, git or the heartbeat row already has |
| SIMPLE-FABLE-20 | One delivery judge `judge()`; delete `green_result`/`is_green`, the judge's own profile reader, stackgate | `tl/app/land/push_judge.py:49-58,71-75`; `checks/cache.py:255-272`; `stackgate.py:36`; `checks/authorization.py:17-19` | MRG | P1 | S | ✅ | agrees with Z01/Z02/R3; here it is the first phase, not wave 1 of a fix list |
| SIMPLE-FABLE-21 | Delete delegate `cockpit`, `doctor`, `onboard`, `agent_runs`, `dwell`, `statusline`, `codex_policy` | `dg:app/cockpit.py:1-2`, `doctor.py:1-2`, `adapters/agent_runs.py:1-5`, `domain/routing/dwell.py:14` (no caller), `app/codex_policy.py` 37 | DEL | P3 | S | ✅ | 600 lines of owner UI, dead memory and an unmerged escape hatch |
| SIMPLE-FABLE-22 | Delegate `status` is one record (`lanes[]`, `windows[]`, `next`); delete the snapshot cache and `contracts/status.py`'s 239 lines | `dg:contracts/status.py` 239, `app/status.py` 115, `status-snapshot.json` (`c4-delegate.md` Stores) | MRG | P3 | S | ✅ | one poller (the page), one shape |
| SIMPLE-FABLE-23 | `records.py`: 13 config classes with 139 fields become one `Profile` with ≤40 fields; drop `look_*`, `reflect`, `review_budget_min`-class knobs | `tl/contracts/config.py:16-247` (13 classes), `SKILL.md:23-80` (the profile table) | MRG | P3 | M | ✅ | every knob is a branch; the ones that go with D1 features go first |
| SIMPLE-FABLE-24 | Release budget: at most two releases a day, announced; the hop deletion depends on it | 59/40/69 releases on 2026-10-28/29/30 (git log); 383 of 1,198 commits are bumps | CON | P2 | S | ✅ | a factory that ships 69 times a day needs mid-run hops; one that ships twice does not. Process, not code |
| SIMPLE-FABLE-25 | Delete the PreToolUse hook; keep only the pre-push dispatcher | `tl/hook/rules.py:19-48` (denies `pkill`/`killall` only), `hooks/hooks.json` PreToolUse 3 s on every Bash call, `hook/main.py:22-23` fail-open | CON | P3 | S | ❓ what tests it: count how often the hook denied in the last month (`events.jsonl` has no row for it: unverified); if zero, delete | a 3-second hook per Bash call for one rule a `settings.json` deny list can hold |
| SIMPLE-FABLE-26 | Delete checkpoints: resume = `attempt.step/stage` + the wip commits on the branch (`wip_push` after every stage) | `tl/app/run/run_once.py:178-186` (`wip_push` then `checkpoints.save`), `contracts/checkpoint.py` 180, `state.py:106-129` | CON | P3 | M | ❓ test: replay a month of resumes from the branch alone in a trial cell; if the plan can be re-read from `runs/<run>/plan.json` and the stage from the wip commit count, the checkpoint is redundant | the checkpoint and the branch record the same cursor twice |
| SIMPLE-FABLE-27 | Delete delegate's health breaker (bench ladder, canary, history fold); the engine's lane policy already pauses the lane on the same facts | `dg:domain/health/ledger.py:1-13`; `tl/domain/lanes/policy.py:1-12` (Retry/Wait/Reroute/Yield over scope+permanence) | CON | P3 | M | ❓ test: count benches that prevented a stop the engine would not have handled; if the breaker only ever benched after a `rate_limited` the engine already paused on, delete | two breakers over one stream of stops (Z07's sibling) |
| SIMPLE-FABLE-28 | Delete the OpenCode harness and sandbox-exec profile (Mac-only lanes) | `dg:adapters/harness/opencode.py` 325, `opencode_sandbox.py` 99, `app/launch.py:144-146` (refuses on Linux) | CON | P3 | S | ❓ test: landed beads by family in the last 30 nights; if xai/deepseek/zai together < 10%, delete | 20% of delegate for lanes that may not pay; ask the data |
| SIMPLE-FABLE-29 | Delete the planner step: the writer plans its own stages from the acceptance text | `tl/app/plan/` 945, `domain/plan/` 298, `prompts/plan.py` 119, `run_once.py:160-163` | CON | P2 | M | ❌ refuse | plan send-back (`plan/sendback.py`) is where bad plans die before a write; the clean-land rate in `docs/design/stages.md` was bought here (unverified against current data) |
| SIMPLE-FABLE-30 | Replace msgspec with dataclasses + json to drop the uv dependency from `tl.py` | `tl.py:68-71` (exits without msgspec), `tests/rules/test_pep723.py` | CON | P3 | L | ❌ refuse | msgspec's strict validation is what makes `JsonStore.read` tell Torn from Present (`contracts/stores.py:90-102`); dropping it buys one fewer dependency for a class of silent bugs |
| SIMPLE-FABLE-31 | The devbox does not run the factory; it runs releases and orchestrating sessions only | `c4-system.md` Level 1 (devbox: Codex lane only; no Unity; no browser), Z06 (two Dolt DBs, one remote) | CON | P2 | S | ❓ owner decision; test: list beads landed from devbox loops in 30 days | half the multi-machine findings (Z06, Z21, C6) vanish if one machine loops |
| SIMPLE-FABLE-32 | Delete events.jsonl and the `track` slice; the `effect` and `attempt` rows are the index | `tl/app/track/trail.py` 81, `verbs.py` 206, `contracts/events.py` 150 | DEL | P3 | S | ✅ | the "cross-repo index of claims, stages, slots and lands" (`events.py` docstring) is a table |
| SIMPLE-FABLE-33 | Delete `reconcile/observe/diff/facts` (816 lines) except the lost-run sweep; `tl prune` = old runs + `git worktree prune` + merged branches | `tl/app/reconcile/observe.py` 201, `commits.py` 92, `domain/reconcile/diff.py` 115, `facts.py` 176, `lost.py` 69 | DEL | P3 | S | ✅ | a typed observe/diff/apply of worktrees and branches for a janitor; with ownership in the db, tidy is a SELECT and two git commands |
| SIMPLE-FABLE-34 | Delete the check "lanes" (parallel step groups) and `resources` leases until a measured need; one check at a time, `needs:` as a host label only | `tl/app/checks/lanes.py:1`, `resources.py:1`, `config.py:340` (unverified line; per c4), `c4-system.md` flow (e) unity leases | CON | P3 | S | ❓ test: check-round wall time with and without lanes over a Trust Night | a third meaning of "lane" (Z22) and a second scheduler |
| SIMPLE-FABLE-35 | Worker-call: one `call` column (key, state, answer path) on `attempt`; delete worker_identity, worker_recovery, done_memo, call_state, strays | `tl/app/run/worker_identity.py:1`, `worker_recovery.py:1`, `done_memo.py` 58, `stores/call_state.py` 134, `strays.py` 26, `worker_call.py:1-8` | MRG | P3 | M | ✅ | five files to remember "this step's call is in flight / answered" across a kill |
| SIMPLE-FABLE-36 | The skill shrinks to ~150 lines: identity, the profile table, the 12 verbs, the workers table | `skills/task-loop/SKILL.md` 674 lines, sections at `:320-670`; read in full at every compaction (`SKILL.md:16`) | DEL | P3 | S | ✅ | the orchestrating session re-reads 674 lines after every compaction; most of it describes verbs and flows deleted above |
| SIMPLE-FABLE-37 | Delete the `domain/*/matchers.py` regex-file convention; regexes live beside their one user | 11 `matchers.py` files (`tl/domain/report/matchers.py` 182, `review/matchers.py` 223, `checks/matchers.py` 168, ...) | CON | P3 | S | ✅ | the "re only in matchers" rule (`CLAUDE.md`) moved regexes away from their meaning; with 14 modules it has no purpose |

Verdict count: 29 ✅, 6 ❓, 2 ❌. Contrarian/low-confidence: 10 (10, 24-31, 34, 37).

### First step of every ✅ idea (one sentence each)

- **01** Add `db.py` with the `loop` table and make `LoopFiles.write/read/live` (`tl/app/loop/files.py`) write-through to it behind a rule-test ratchet on JSON writes per family.
- **02** Write `steps.close(inputs, ports)` beside `Closer` using `domain/effects.plan_close` as its body, call it from `closer_over`, move `tests/run/test_closer*` to it, delete `closer_*.py`.
- **03** Make `Reload.safe_point` a no-op behind `loop.hop_mid_bead: false` in the profile for one week on Trust Night, then delete the module.
- **04** Make each of the 35 deleted verbs print its replacement and exit 2 in one release; delete them in the next.
- **05** Add a `keep: ["**/*.png"]` check for lifesim's visual paths and a reviewer brief line that lists kept files; run beside `look` for one night; delete `app/look`.
- **06** Set `reflect: false` as the default in `EngineConfig`; delete the step, the chore and the two files one release later.
- **07** Delete `cli/land_stack.py`, `app/land/{stack,forge,stackgate}.py`, `contracts/forge.py` and their tests in one release; note "use gh" in the changelog.
- **08** Add `tl status --json` rows for landed/parked/failed per day over `runs/`; a week later delete `app/report`, `cli/report.py`, `contracts/trace.py`.
- **09** Move `skills/delegate` into the task-loop repo under one `plugin.json` and one `dev/vendor.json`; delegate's tests run in the same suite.
- **10** Change the cap to 800 in `tests/rules/gate_rules.py` and merge the six `closer_*.py` files into one as the first proof.
- **11** Add the `ask` table; make `AskStore` write-through; move `tl ask/answer` onto it; delete `asks/` sweeps as a chore of `loop.py`.
- **12** Move `.task/engine.lock` to `C/locks/` (Z15), then replace it by the `attempt(host,pid,start_id)` row; delete slot beads last.
- **13** Merge `salvage`, `restart`, `recheck`, `fix_outside`, `land_rebase` into `Lander.finish` with one `Conflict -> fix round -> replan` branch.
- **14** List every `Git` method's callers; delete the ones with one caller by inlining the git call, then re-cut the Protocol.
- **15** Make `dev/release.py` import nothing from `taskloop.app.release`; delete that package when the suite passes.
- **16** Delete `.importlinter:141-503` and replace with one contract: `records, ports` import nothing from `taskloop`.
- **17** Change `dash/api/writes.py` to `subprocess.run([shim, verb, ...])` and delete the `--ports` runtime import in `cli/dash.py`.
- **18** Delete `tl lanes`/`tl usage` and the chore; make the page call `route.py status --cheap`.
- **19** Delete `app/run/shared.py` and `contracts/adrs.py` with their dashboard views in one release.
- **20** `PushJudge.green` calls `authorization.results` with the executed key and reads the profile at `base_for(tip)`; delete `green_result`.
- **21** Delete the seven delegate modules and `--exec-allow`'s parser branch; `route.py doctor` prints the README's table.
- **22** Collapse `contracts/status.py` to one `Status` record and delete `status-snapshot.json`.
- **23** Delete `VisualConfig`, `ReviewSkipConfig`'s look fields, `reflect`, `look_*` from `config.py` with ideas 05/06.
- **24** Write the budget into `dev/release.py`: refuse a third release in a UTC day without `--force`.
- **32** Replace `trail.event` calls by `db.effect`/`attempt` writes as phase 1 reaches each family; delete `events.jsonl` last.
- **33** Delete `observe/diff/facts` and make `tl prune` call `git worktree prune` and delete merged `task/*` branches by `git branch --merged`.
- **35** Add `attempt.call_key/call_state/answer_path` columns and move `CallState` onto them.
- **36** Rewrite `SKILL.md` around the 12 verbs after idea 04 lands.
- **37** Move each regex to its single user as its module is rewritten in phase 3.

---

## 6. What I think you are NOT thinking about

1. **The release cadence is the architecture.** 69 releases on one day; 383 bump commits of 1,198. The mid-bead hop, `bad-versions`,
   `fall_back`, `selfupdate`, the shim-points-at-last-writer problem (Z14) and the delegate re-resolve per call (Z13) are all consequences of
   shipping many times per bead. No review so far names the cadence as a cause. A budget of two releases a day deletes more code than any
   refactor and costs nothing but patience.

2. **Tests outnumber code and the harness is the engine's shadow.** 56,195 test lines for 44,682 of code; `tests/support` is 6,842, and
   `narrow_hosts.py` (778) plus `engine_case.py` (765) exist to fake the host object. The "volume-tests" review (not present in this tree:
   `docs/review/volume-tests.md` was named by the brief but is not there) would have shown this: the 30% design cuts tests more than code,
   and that is where Codex's time goes today (every slice touches the harness).

3. **bd is already a database with metadata; half the file families duplicate it.** Parks, landed, asks, slot leases, claims, follow-up
   outboxes: each is "the bead's state, as the engine sees it", kept beside bd because bd calls are subprocesses. The 30% design puts
   that in `factory.db`; a braver design puts it in bd metadata (one authority, synced by Dolt, visible from both machines, which also
   answers Z06). I did not pick it because bd's subprocess cost per write is unmeasured; measure it.

4. **The dashboard is a 6,300-line product for one viewer.** Nobody asked whether the page should exist as code in this repo. The
   `tl status --json` document plus a static HTML that polls it is a day of work and 2,000 lines; the "learning", "ledger", "needs",
   "look" views are features of features.

5. **Codex is the only writer, and the file shape fights it.** 491 files, 18 slices, 26 import contracts, 11 `matchers.py` files, 36
   `host: Any` parameters. Every one of those is a place Codex must look before it can change anything. A design for a model writer has
   few, long, self-contained files and one obvious place per fact. The 400-SLOC cap and the "re only in matchers" rule optimise for a
   human linter, not for the writer you have.

6. **The devbox may not need to loop at all.** It has no Unity, no browser, Codex only; the Mac has everything. If only the Mac loops,
   Z06 (two Dolt DBs), Z21 (release delivery to the Mac), C6, and the `host.json` affinity machinery (`needs:` labels, `PAUSE_MOVED`,
   `move_host` at `engine.py:272-278`) are not needed.

7. **The profile is a programming language with 139 fields.** `contracts/config.py` has 13 record classes; `SKILL.md` spends 60 lines
   describing it; `tl doctor` exists to lint it. Each field is a branch in the engine. A profile of ≤40 fields is a deletion target in its own
   right, and the fields that go with D1 features (`look_*`, `reflect`, `visual_paths`, `review_budget_min`) go first.

8. **Three event models of one run.** `events.jsonl` (`Event`, 150 lines of union), `traces.jsonl` (`RunTrace` v2, 164), `engine/<run>.jsonl`
   (`EngineLog`, 358). Reports read one, the dashboard another, `tl trace` the third. One `attempt` row plus one engine log is enough.

9. **The "one plugin" question has a sharper form: should delegate exist as a separate codebase at all?** The router (tiers, picker, holds,
   health) is 1,278 lines of domain; the harnesses 760; the rest is supervision and state. If task-loop is the only unattended caller and
   the orchestrator's `/delegate` skill is the only attended one, a single package with a `worker` module and a `route` CLI entry is
   simpler than a contract integer. I kept the subprocess (sandbox, env scrub) but not the repo split.

10. **Nothing measures whether a feature pays.** No row says "look caught a defect", "reflect produced a fix", "salvage saved a branch",
    "the mid-bead hop delivered a fix that mattered". Every ❓ above is testable from `runs/` and `traces.jsonl` in an afternoon; the
    factory has the data and no query.

---

## 7. Where I disagree with the existing documents

- **Extraction synthesis, "the honest number" (`extraction-synthesis.md:8-27`).** 13% is the ceiling of *extraction*, and the lenses were
  right to refuse more. But the brief's goal is volume, and deletion reaches 40-50% without moving a line to shelf. The synthesis treats
  "domain code (land/gate/close, lanes, slots, runs, routing)" as the fixed denominator; half of that domain is mechanism around a host
  object and files, not domain.

- **Zoom-out R1 (`zoom-out-review.md:367-381`).** Agrees on SQLite; disagrees on the table set. `reservation` and `wait` are columns of
  `attempt`, not tables; `effect` is right; `loop` is right. And R1 is placed in wave 3 behind owner decisions; here it is phase 1, because the
  strangler (write-through behind `Stores`) is reversible and every later deletion is easier once rows exist.

- **Zoom-out Z04 (`:67-80`) and Z05 (`:82-94`).** Z04 proposes locking 40 families; the simpler move is to not have 40 families. Z05 proposes
  freezing the bundle so the mid-bead hop is safe; the simpler move is no mid-bead hop. Both are "fix the mechanism" where "delete the
  mechanism" is cheaper and removes the same incidents.

- **Review synthesis's 14 slices (`docs/review/synthesis.md:12-27`).** HOPSAFE (7), PIDIDENT (13), CALLMEMO (10), PAUSEEPISODE (9),
  DELEGATECAP (12), FOLLOWOUTBOX (3), SETTLE (8) are fixes to code this review deletes or replaces by a row with a `rev`. Doing them first
  is work that is then thrown away. Do PROFILEREAD (1), GATEIDENT (2), FENCE (5) and GATESELECT; skip the rest into the phases above.

- **c4-task-loop Level 3 "Engine is the composition root" (`c4-task-loop.md:316`).** It is a service locator; the document's own item 10
  says so. The component table lists 15 components with "Depends on"; the real dependency is "everything, via `self.e`". The diagram is
  kinder than the code.

- **c4-system's trust table calls the dashboard "no auth, bind is the access rule" a weak point.** True, but the deeper problem is that the
  page is a writer with engine code loaded at runtime; a page that only spawns `tl` has the same tailnet exposure with one tenth of the
  attack surface and no engine import. The fix is deletion (SIMPLE-FABLE-17), not authentication.

- **RCA root cause R-C "the trust line is the sandbox, then punched through" (`rca-zoomout-three.md:16`).** Agree, and one more hole:
  the hop. An engine that execs into a directory it found in `installed_plugins.json` mid-bead runs code chosen by whatever last wrote that
  file. That is a version-authority hole beside the sandbox holes, and R-C does not list it.

- **The brief's "aggressive volume reduction and extraction to shelf, even at the cost of refactoring."** Extraction is the smaller lever
  and it is being pulled first (phase-2 list in `extraction-synthesis.md:31-45`). git-porcelain convergence (3,300-4,266 lines, "critical" risk)
  only pays once the Git port is 25 methods (SIMPLE-FABLE-14); doing it on the 72-method port moves the problem to shelf.

- **`docs/design/stages.md` (211 lines, "Verdict", "Denominator", "clean-land rate")** is the one document that measures a feature's value
  by beads moved. Every ❓ in the ledger should be answered the way that document answers: by the clean-land rate over a Trust Night, not by
  argument. None of the four architecture documents cites it (unverified: grep of the C4 docs for "stages.md" finds only
  `shared.py`'s docstring reference).
