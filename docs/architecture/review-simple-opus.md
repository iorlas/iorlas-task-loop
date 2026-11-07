# Review lens 6: radical simplification (SIMPLE-OPUS)

Question: if we rewrote task-loop (and the delegate seam) from scratch, knowing what the last 15 days taught, what is the
30%-size design? Reviewer: Claude Opus, 2026-11-02. Static reading plus `wc`, `git log` and a read of the devbox's live
`~/.config/task-loop`; nothing run.

Code base read: the task-loop main checkout `/home/iorlas/Workspaces/iorlas-task-loop` at 0.23.293 (all `file:line` below are from that
checkout unless prefixed `dg:` = `/home/iorlas/Workspaces/wt/UNITYD/src/delegate/`). The C4 worktree is 0.23.299 and about 250 lines
larger; line numbers there differ (for example `caffeinate` is `app/launch/factory.py:51` here, `:116-119` in the C4 docs). Paths:
`tl/` = `src/taskloop/`, `dash/` = `src/taskloop_dash/`.

Note: the brief lists `docs/review/volume-delete.md` and `volume-tests.md` in the C4 worktree. Neither file exists
(`ls /home/iorlas/Workspaces/wt/C4/docs/review/`). I worked from the other documents.

---

## 0. The numbers this lens starts from (all measured with `wc -l`)

| Part | Lines now |
|---|---:|
| `src/taskloop` (engine, loop, land, checks, contracts...) | 40,917 |
| `src/taskloop_dash` Python | 3,481 |
| dashboard static JS/HTML | 2,329 |
| `skills/task-loop/tl.py` | 460 |
| `skills/task-loop/_vendor` (shelf copies; `git_porcelain` alone is 4,511) | 6,297 |
| `tests/` | 55,552 |
| `dev/*.py` | 1,425 |
| `.importlinter` | 484 |
| `SKILL.md` (loaded into every orchestrating session) | 674 |
| **task-loop total code** | **~110,900** |
| delegate `src` / `tests` / `skills/delegate/contract.json` | 7,909 / 7,739 / 1,759 |
| **both apps** | **~128,000** |

Facts that change the picture:

- **Age.** First commit 2026-10-18; 1,183 commits since; 377 of them are release commits (`git log --format=%s`, subjects starting
  with a version). About 100k lines written in 15 days. The size is not the residue of years of requirements; it is two weeks of
  review-driven slices, each adding a guard.
- **Who uses the engine.** 1,131 of 1,183 task-loop commits carry `Co-Authored-By` (sessions plus Codex, outside the engine). The
  devbox's live config dir holds 26 run manifests and 26 traces in total, every one `landed`; the 18 engine logs present are all
  `mode: stage:check` runs inside `release/<hash>` (the release's check runner), not bead runs. The engine's real customer is the
  Mac lifesim factory. The people building task-loop do not run its full path on their own repo.
- **Profiles in use.** task-loop's own `.task-loop.json` sets 4 keys and one check, `python3 dev/suite-docker.py`. lifesim (origin/main)
  sets 15 `engine` keys and 23 checks, all `in: host`, 5 of them `needs: ["unity"]`. The profile schema has 128 annotated fields
  (`grep -c` on `tl/contracts/config.py`).
- **The outcome taxonomy already collapses.** 25 `Kind`s (`tl/contracts/kinds.py:9-30`) map to exactly three actions, `RETRY | ASK | HOLD`
  (`kinds.py:46-49`, `fault_of` `:81-90`). Everything else in the 8-column `Rule` table (`tl/domain/outcome.py:41-49`) is display and
  heuristics.
- **Delegate already says what to do with a stop.** `dg:contracts/stops.py:28-40` returns `{reason, scope, permanence, retry: {kind, at}}`.
  task-loop's `domain/lanes/` (1,491 lines) decides it again.

Extraction (`extraction-synthesis.md`) reaches 13% by moving lines to shelf. This lens says the 70% that matters is not movable: it is
deletable, because it guards features, writers and hops that should not exist.

---

## 1. The 30% design

One sentence: **a bead is a job, a job is a directory with one writer, liveness is a held flock, and bd plus git are the only
shared state.**

### 1.1 Stores (three authorities, one cache)

| Store | What it holds | Writers | Replaces today |
|---|---|---|---|
| **bd** | queue (`bd ready --label auto`), bead status, claim (assignee), owner questions and answers (comments), hold (label `hold`), needs-owner (label `needs-owner` + status `blocked`) | engine (its own bead only), owner (`bd`, dashboard answer) | `asks/`, `ask-ledger.jsonl`, `parks/`, `pauses/` (owner kind), `decisions/` ADRs, `followups/` (follow-ups are just `bd create`), owner-request files |
| **git** | code, `task/<bead>` branches, main | engine (land), workers (commit in their worktree only, no push) | `landed/` (the land commit on main is the receipt: `git log --grep "Bead: X" origin/main`) |
| **job dir** `C/jobs/<repo-id>/<bead>/` | `job.json` (step, round, plan, bundle, retry_at, attempts, spend), `log.jsonl` (append-only), `calls/<call-id>.json` (raw worker answers = the memo), `checks/` (logs) | **only the process holding `job.lock`** (flock in the same dir). Nobody else ever writes in it. | `runs/<run>/manifest.json`, `checkpoints/`, `B.call.json`, `reexec/`, `pauses/`, `engine/<run>.jsonl`, `runs/*/plan.json`, `done.json`, `handoff.json`, `.task/engine.lock`, `.task/engine.take`, the fence generation in bd metadata |
| **check cache** `C/results/<repo-id>/<sha256(tree, check spec, profile commit)>.json` | write-once, content-addressed pass records | any check runner (idempotent: same key, same content) | `results/` + `base-red/` + `check-durations/` + the execution-identity fingerprinting of CHECKIDENT |

Plus the loop's own `C/loop/<repo-id>/loop.json` (one writer: the loop, liveness = `loop.lock`) and the owner's `C/host.json`.
That is it. No manifest has a second writer, so no CAS, no `mark_lost`, no `died-<pid>.json` renaming: "lost" is computed on read
(`job.lock` is free and `job.json.step` is not terminal). SQLite is not needed because the multi-writer problem is deleted, not managed.

### 1.2 Modules (target ~9.5k lines of `src`, from 40.9k)

| Module | Lines (target) | Job |
|---|---:|---|
| `tl/cli.py` | 500 | 8 verbs (below), argparse, nothing else |
| `tl/profile.py` | 250 | ~25 knobs, read **only** from the base commit (`git show origin/main:.task-loop.json`) |
| `tl/job.py` | 400 | `Job` record, `job.json` load/save, `log.jsonl` append, `job.lock`, "lost" derivation |
| `tl/engine/steps.py` + one file per step | 2,600 | `plan`, `write`, `check`, `review`, `land`, `close`: each `step(job, ports) -> Transition` |
| `tl/engine/run.py` | 200 | the loop over steps: load job, pick step, call it, apply transition, save; close-out always runs |
| `tl/worker.py` | 350 | `call(role, brief, schema, cwd, call_id) -> Answer | Stop`; delegate's `stop` passed through untouched |
| `tl/checks.py` | 700 | run argv on host in the worktree, timeouts, `needs:` resource flocks, cache by content key |
| `tl/land.py` | 600 | land lock, fetch, rebase, gate, `git push` (or one PR mode), `bd close`, `bd sync` |
| `tl/loop.py` | 600 | one process per repo per host supervising N slots; pick, claim, spawn `tl run`, reap, exec-upgrade between jobs |
| `tl/slots.py` | 300 | a slot = persistent worktree + `slots/N.lock` flock + setup stamp by inputs hash |
| `tl/bd.py`, `tl/git.py`, `tl/proc.py` | 900 | three adapters, real CLIs, typed faults |
| `tl/prompts/` | 900 | keep today's `domain/prompts` (870) nearly as is: that is the product |
| `tl/hook.py` | 100 | PreToolUse `pkill`/`killall` rule only |
| `tl/status.py` | 300 | text status from job dirs + loop.json + bd |
| dashboard (`dash/`) | 1,500 py + 1,200 JS | read-only over job dirs, loop.json, `bd list --json`; one write: answer (spawns `tl answer`) |

Vendor: `atomic_io`, `process_lock`, `stream_proc` only (~1,130 lines); `git_porcelain` (4,511), `jsonl_log` (425), `child_env`, `static_page_check`
are not needed by this shape. Tests: ~13k (scenario tests through `tl run` with a scripted delegate and real git in a tmp dir, plus
unit tests of the pure transition table). Delegate: ~5.5k src (it is the healthier half; see 1.6).

### 1.3 The few verbs

```
tl loop start|stop|status [--slots N]   # the factory: one supervisor per repo per host
tl run BEAD [--slot S]                   # one job, foreground; what the loop spawns
tl check [--gate] [REV]                  # run the profile's checks on a tree (also the release's gate)
tl answer BEAD TEXT                      # bd comment + unblock; the dashboard calls exactly this
tl status [BEAD] [--json]
tl doctor                                # lanes, bd, git remote, disk, stale locks: read-only
tl dash [ensure|stop]
tl prune [--dry-run]
```

Everything else is `bd` directly (`bd ready`, `bd update --claim`, `bd label add X hold`, `bd comments`). Today's 47 verbs
(`skills/task-loop/tl.py:405-448`) include `claim`, `land`, `close`, `block`, `queue`, `lint`, `slot ...`, `worktree(s)`, `land-lock`,
`land-stack`, `ask/answer/hint/hold/override/park/note`, `wait`, `trace`, `report`, `lost`, `reflect`, `handoff`, `actor`,
`register`, `lanes`, `usage`, `pin`, `rollback`, `cutover`, `selftest`, `green`, `judge-push`, `hooks`, `gate`, `next`, `stop`.

### 1.4 The engine as a transition table

```
Transition = Next(step) | Retry(at, why) | Ask(question) | Hold | Landed(sha)
plan   -> Next(write)            | Ask(plan question) | Retry(stop.retry.at)
write  -> Next(check)            | Retry | Ask
check  -> Next(review) if green  | Next(write, red brief) while round < max_rounds | Ask(same red N times)
review -> Next(land) if accepted | Next(write, findings) while round < max_rounds | Ask
land   -> Landed(sha)            | Next(write, conflict/red brief) once | Ask
close  -> (always runs) bd close / bd update --status blocked + comment / leave open with retry_at
```

Six steps instead of twelve (`tl/contracts/enums.py:5-17`: `RESET, PLAN, REPLAN, WRITE, CHECKS, REVIEW, VERIFY, LOOK, GATE, LAND, CLOSE,
REFLECT`). `REPLAN` is `plan` with round > 0, `VERIFY` and `LOOK` are `review` with more attachments (screenshots are check artifacts),
`GATE` is inside `land`, `RESET` is slot preparation, `REFLECT` is deleted. Five transitions replace 25 kinds; the human-readable
"why" is a string field, not a type.

Worker stop mapping, the whole table (replaces `domain/lanes/` 1,491 lines and the four stop deciders of Z07):

```
stop.permanence == "transient"   -> Retry(stop.retry.at or now + loop.retry_s)
stop.permanence == "needs_owner" -> Ask(stop.reason + stop.fix)
anything else / no stop / bad JSON -> Retry(now + loop.retry_s), counted; 3 in a row on one bead -> Ask
```

### 1.5 Upgrades, pushes, the dashboard

- **Bundle per job.** `tl run` records its own plugin dir and delegate dir in `job.json` at admission and uses them for the whole job.
  The loop execs into the newest installed version only between jobs. A resumed job whose bundle dir was garbage-collected becomes
  `Ask("bundle gone; tl run --rebundle")`. This is R2, done by deletion: no safe point, no hand-over note, no crash fallback.
- **No pre-push judge.** The engine is the only process that pushes, and it gates the exact tree in the same process under the land
  lock right before `git push`. Workers cannot push (delegate sets `GIT_CONFIG_*` push refusal, Z24). The release script calls
  `tl check --gate` itself. Nothing is left for a second judge to judge.
- **Dashboard.** Read-only. One POST: answer, which spawns `tl answer BEAD TEXT --expect <comment-id>`. No engine import at runtime.

### 1.6 Delegate in this shape

Delegate is closer to right-sized (7.9k). Cuts: `agent_runs` (Z10), the status poll's config writes (Z19), `statusline`/`cockpit`
folded into `status`, and `contract.json` from 1,759 lines to the reasons table task-loop actually reads (scope, permanence, retry).
Ship both skills in **one plugin with one version** (R4). Then the contract integer, `resolve` / `find_route`, the `run_args`
negotiation (Z12), `pinned.json`'s delegate key and the vendor drift (Z23) all go: the two halves can no longer disagree.
Keep the subprocess boundary: it is what makes a worker killable as a process group.

### 1.7 Size of the result

| Part | Target |
|---|---:|
| task-loop src + dashboard + vendor + dev | ~15,800 |
| task-loop tests | ~13,000 |
| delegate src + tests + contract | ~10,800 |
| **total** | **~39,600 (31% of ~128,000)** |

---

## Top 10 by importance

1. **SIMPLE-OPUS-01** One writer per job directory, liveness by flock: deletes the whole multi-writer class (Z04, A.F11, PIDIDENT) instead of adding CAS.
2. **SIMPLE-OPUS-02** Outcomes are five transitions over three actions; delete 25 kinds as types and task-loop's own stop policy (`domain/lanes`, 1,491 lines).
3. **SIMPLE-OPUS-03** Delete the pre-push judge and git-hook dispatchers; the engine gates in-process before its own push, workers cannot push.
4. **SIMPLE-OPUS-04** Bundle per job, upgrade only between jobs: delete `reload.py`, `reexec.py`, hand-over env, crash fallback, selftest gate.
5. **SIMPLE-OPUS-05** bd is the inbox: asks, parks, holds, notes, ADRs and follow-ups become bd comments and labels (asks slice 1,892 lines -> ~300).
6. **SIMPLE-OPUS-06** Slots are flocks, not bd beads: delete slot beads, fence generations in bd metadata, lease heartbeats.
7. **SIMPLE-OPUS-07** Rewrite the engine beside the old one (~3k lines, six steps) behind a per-repo profile switch; do not refactor `app/run` (6,028 lines, 51 files).
8. **SIMPLE-OPUS-08** Profile from 128 knobs to ~25, read only from the base commit; every other knob becomes a constant.
9. **SIMPLE-OPUS-09** A net-negative ratchet: total lines may only shrink; each slice deletes at least what it adds.
10. **SIMPLE-OPUS-10** Phase 0 usage census on the Mac before any deletion (verbs, knobs, kinds, steps actually used over 7 days).

---

## Idea ledger

Severity is "how much the current shape costs" (P0 worst). Verdicts: ✅ do, ❌ refuse, ❓ untested (what would test it).
**LOW-CONF** marks ideas I hold with low confidence or that go against the documents on purpose.

| id | idea | evidence (file:line) | kind | sev | effort | verdict | reason |
|---|---|---|---|---|---|---|---|
| SIMPLE-OPUS-01 | One writer per job dir `C/jobs/<repo>/<bead>/`; the holder of `job.lock` is the only writer; "lost" is derived on read (lock free + step not terminal), never written | get-then-put with no lock in every `RunLocator` method `tl/contracts/locator.py:104-151`; `JsonStore` atomic but unlocked `tl/contracts/stores.py:80-121`; `LoopFiles.live()` renames other loops' files `tl/app/loop/files.py:49-61`; reconcile writes manifests `tl/contracts/runlife.py:64` | delete writers | P1 | M | ✅ | Z04's CAS keeps six writers and makes them polite. Removing five of them removes the race, `mark_lost`, `died-*.json`, and pid identity in one move. |
| SIMPLE-OPUS-02 | Engine outcomes = `Next / Retry(at) / Ask / Hold / Landed`; `Kind` becomes a display string; delete the 8-column `Rule` table | 25 kinds `tl/contracts/kinds.py:9-30` map to 3 actions `:46-49`, `:81-90`; `Rule(bd, loop, trace, makes_ask, resolver, label, storm, retries)` `tl/domain/outcome.py:41-49`; `CUT` "no production code raises it" `kinds.py:13` still has a rule `outcome.py:68` | taxonomy collapse | P2 | M | ✅ | The machine already acts on three values. The other 22 distinctions are prose that every new feature must extend in five places. |
| SIMPLE-OPUS-03 | Delete task-loop's stop policy; map delegate's `stop.permanence` / `retry.at` directly (table in 1.4) | `dg:contracts/stops.py:28-40` already returns permanence and retry time; task-loop re-decides in `tl/domain/lanes/policy.py` (329), `pauses.py` (103), `retry.py` (58), `matchers.py` (118); `domain/lanes/` = 1,491 lines | duplicated authority | P2 | M | ✅ | Agrees with Z07 and goes further: not "one table in task-loop", but no table beyond the three-line mapping. |
| SIMPLE-OPUS-04 | Delete the pre-push judge, `judge-push`, `green`, the 14 git-hook dispatchers and the `core.hooksPath` injection | 14 dispatchers `tl/app/doctor/install.py:49-50`, written per session `:59-80`; injected into every child `tl/adapters/childenv.py:56-64`; judge `tl/app/land/push_judge.py` (107), `tl/app/launch/push_judge.py` (21), `tl/hook/prepush.py` (75), `tl/cli/green.py` (40); the hook does not see pushes outside tl's children (`tl/cli/hooks.py:1-3` per c4) | delete feature | P1 | S | ✅ | The only pushers under it are the engine (which just gated the same tree), the release (which runs the suite), and workers (who must not push at all: Z24). Z01, Z02, Z03, Z14 are four P1/P2 fixes to a judge that judges its own caller. Delete instead of fixing. |
| SIMPLE-OPUS-05 | Bundle per job; loop moves only between jobs; delete safe-point exec | `Reload.safe_point` / `switch` exec at step boundaries `tl/app/run/reload.py:68-124`; `tl/app/release/reexec.py` (76); `tl/app/loop/versions.py:1-6` "Nothing is tested before a move: a move that breaks soon after goes back"; `reload_fallback` knob `tl/contracts/config.py:152` | delete feature | P1 | M | ✅ | Agrees with Z05/R2/I.F01; stronger: no FREEZEBUNDLE "later". Deletes ~600 lines (reload 124, reexec 76, versions 100, pins 99 shrunk, selftest 269) and incidents 2, 3, 9, 10. Cost: a fix waits up to one bead. |
| SIMPLE-OPUS-06 | bd is the inbox: ask = `bd update --status blocked` + comment `Q:`; answer = comment `A:` + unblock; hold = label; note = comment; follow-up = `bd create`; ADR = bd decision bead or a repo doc | asks slice: `app/asks` + `domain/asks` + `contracts/ask.py`, `answers.py` (335), `ledger.py`, `cli/asks.py` (196), `app/run/ask_flow.py` = 1,892 lines; ADR store `tl/contracts/adrs.py` (86); sweeps that park unanswered asks after 3 days `tl/app/asks/sweeps.py:1-2`; repeat detection `tl/domain/asks/similar.py` | delete store | P2 | M | ✅ | Every owner act already lands in bd as a comment or label anyway (dashboard writes through `BdStore`, c4 `dash_ports`). A second inbox with its own lock per bead, ledger and sweeps duplicates the tracker. Keeps ~300 lines: ask text lint and the Q/A comment format. |
| SIMPLE-OPUS-07 | Slots are `slots/N.lock` flocks and a setup stamp; no slot beads, no fence generation in bd metadata, no lease heartbeat | slot = "a worktree plus its bd bead, which is the lease" `tl/app/slots/pool.py:1-2`; found by `BeadQuery(label="slot")` `:115`; generation bump is a read then an update `tl/contracts/fence.py:71-78`; "a bd outage fences nothing" `:88`; lease kept alive because setup outlasts a 5-min bd lease `tl/app/slots/lease.py:1-2` | delete mechanism | P1 | M | ✅ | A flock is held exactly as long as the process lives: no heartbeat, no expiry, no fail-open on bd outage, no slot beads in `bd list`, no Dolt sync of machine-local leases. Slots (1,447 lines incl. `wire/slots.py`) -> ~300. |
| SIMPLE-OPUS-08 | Claim once, in the loop; `tl run` verifies assignee == loop actor and never re-claims | double claim by two processes under one actor (c4 item 8: `launch/loop.py:164-170`, `run/entry.py:387-396` in C4 numbering; unverified in this checkout's numbering) | duplicated authority | P2 | S | ✅ | With the job lock as the fence, bd's assignee is the only claim and needs no generation. |
| SIMPLE-OPUS-09 | Rewrite the engine as six step functions (~3k lines) beside the old one, switched per repo by `engine.v2: true`; delete `app/run` when lifesim has run 50 beads on v2 | `app/run` = 6,028 lines in 51 files; 38 `cached_property` parts built over the engine `tl/app/run/engine.py:186-215`; `RunOnce(host: Any)` `tl/app/run/run_once.py:35-37` | rewrite | P1 | L | ✅ | Z16/R5 estimate L for a refactor of the locator. Codex wrote 100k lines in 15 days; writing 3k fresh against a golden trace set is cheaper than unwinding 38 mutual attributes, and the old engine keeps running the Mac until the switch. |
| SIMPLE-OPUS-10 | Profile: ~25 knobs; every other field becomes a constant in `profile.py`; read only from the base commit | 128 annotated fields `tl/contracts/config.py`; `CheckSpec` alone has 21 (`:88-111`); lifesim sets 15 engine keys, task-loop sets 4 (`.task-loop.json`) | delete config | P2 | M | ✅ | Every knob is an untested combination and a field in the dashboard and docs. Keep: checks (id, argv, stage/gate, timeout, needs, inputs), slots (count, setup, setup_inputs), land, pick_label, worker_rules, planner_notes, visual_paths, max_rounds, budget_min, resources. |
| SIMPLE-OPUS-11 | Delete container execution from the engine: a check that wants Docker calls Docker in its own argv | `where: host|container` `tl/contracts/config.py:105`; `app/checks/execution.py` (64), `adapters/container_run.py` (93), `app/checks/container.py` (47); task-loop's own gate is `python3 dev/suite-docker.py` (`.task-loop.json`), i.e. the repo already does it in argv; lifesim: all 23 checks `in: host` | delete feature | P2 | S | ✅ | Removes the "host receipt certifies a container requirement" class (CHECKIDENT, M05, LF02) at the root: one executor per check means the cache key is (tree, spec), nothing else. |
| SIMPLE-OPUS-12 | Check cache key = sha256(tree, check spec, base profile commit), write-once; delete `green_result`, `authorization`, base-red, durations, execution fingerprints | `cache.py` (268), `authorization.py` (34), `base.py` (47), `gateplan.py` (106), `evidence.py` (124); "this ID-only query must never authorize delivery" (`cache.py:263-265` per c4) | simplify | P1 | M | ✅ | Identity bugs exist because there are several identities. One content key and one executor leave nothing to confuse. |
| SIMPLE-OPUS-13 | Land = one path: lock, fetch, rebase, gate, push, bd close, bd sync; conflict or red goes back to `write` once, then Ask | `salvage.py` (64), `fix_outside.py` (74), `fixer.py` (134), `recheck.py` (72), `restart.py` (95), `verified.py` (76), `land_optimistic_tries` `config.py:173`; land slice 2,878 lines in 29 files | delete recovery paths | P2 | M | ✅ | Five recovery strategies for "main moved or the rebase is red" each with its own tests (land tests 4,807). One retry through the normal write step covers them; the rest is Ask. Target ~600 lines. |
| SIMPLE-OPUS-14 | Pick one delivery mode per repo: direct push, or PR + merge (`land-stack`); not both as engine features | `land-stack` = `stack.py` (218) + `stackgate.py` + `forge.py` + `contracts/forge.py` = 416; lifesim origin/main is full of `Merge pull request #30x from yoselabs/task/...` (who opens them: unverified) while the engine default is `git push origin HEAD:main` (`config.py:172`) | delete duplicate path | P2 | S | ❓ | Test: count, on the Mac, how lifesim beads reached main last week (engine push vs land-stack vs a human merge). Keep the one that carried most; make the other a profile value of the same land function. |
| SIMPLE-OPUS-15 | One loop process per repo per host supervising N slots; delete factory lanes, placeholder state, per-lane logs, per-lane caffeinate | factory spawns N loop processes and writes their state for them (c4 item 5); `caffeinate` only on one child `tl/app/launch/factory.py:51`; `launch/factory.py` + `adapters/factory.py` + `app/launch/loop.py` (317) + `app/loop/` (1,733) | delete mechanism | P2 | M | ✅ | Disagrees with Z22 (rename lanes): no lanes, no rename. One supervisor, one `caffeinate -w <loop pid>`, one `loop.json`, one log. N slots are N children of one parent. |
| SIMPLE-OPUS-16 | Dashboard read-only plus one write (answer via `tl answer`); delete `look`, `stick`, `cause`, `ack`, `prune`, `park`, `stop`, `note` POSTs and the runtime import of engine ports | nine verbs `dash/api/writes.py:113-166`; factory beads filed by folder name `tl/app/launch/dash_ports.py:57-63`; `dash_ports.py` (154), `contracts/dash.py` (562) | delete feature | P2 | M | ✅ | Agrees with Z08, stronger. Stop and park are `bd label add hold` from the phone's terminal or a second POST later if the census shows use. |
| SIMPLE-OPUS-17 | Delete `reflect` and `reflect digest` | `tl/app/run/reflect.py:1` "one cheap read-only call at the close"; `tl/app/report/reflect.py` (247); `engine.reflect` default true `config.py:181`; no `reflect-digest.json` on the devbox | delete feature | P3 | S | ❓ | Test: on the Mac, list beads filed from a reflect digest in the last 14 days and whether any landed. If fewer than 3, delete (321 src lines plus a worker call per bead). |
| SIMPLE-OPUS-18 | Delete `tl report`, `lost`, `trace`, `handoff`, `wait` as separate verbs; `tl status BEAD --json` covers them | `report` slice 604 + `cli/report.py` 190 + `domain/report` (`matchers.py` 182); `handoff` PreCompact writer (c4 `hook/session.py:88-96`) | delete verbs | P3 | S | ✅ | The orchestrating session reads JSON; five read verbs over the same files is five renderings to keep in sync. |
| SIMPLE-OPUS-19 | Delete the heuristics that the transition table makes moot: storm detector, stuck watch, waits segments, done memo, worker recovery digests, shared notes, net detector in the loop, area busy, epic order, host affinity | `domain/storm.py` (46) + `adapters/storm.py` (59); `app/run/stuck.py` (38); `waits.py` (146); `done_memo.py` (58); `worker_recovery.py` (93); `shared.py` (108); `loop/net.py` (37); `loop/hosts.py` (14); `LoopConfig` 23 timing knobs `config.py:130-155` | delete heuristics | P2 | M | ✅ | Each was a fix for one incident. With `Retry(at)` per bead and an Ask after three empty answers, the loop does not need a second opinion on storms or stuckness. Keep `budget_min` (a hard wall), drop dollars and token caps unless the census shows a hit. |
| SIMPLE-OPUS-20 | The worker memo is `calls/<call-id>.json` in the job dir, written before the answer is consumed | `done_memo.py:1` "Answers a run already took, indexed by call coordinates and semantic execution digest"; `worker_recovery.py:1`; CALLMEMO (D.F12) | simplify | P2 | S | ✅ | The call id is deterministic (job, step, round); the file either exists or not. No semantic digest. |
| SIMPLE-OPUS-21 | One plugin, one version, both skills; keep delegate's subprocess boundary but delete version negotiation | contract int compare and two lookups (Z12, Z13); `contract.json` 1,759 lines, 22 reasons (`skills/delegate/contract.json`); two vendor sets at different tags (Z23) | packaging | P2 | M | ✅ | Owner already decided "everyone installs both". Negotiation code exists only to survive a state that one version makes impossible. |
| SIMPLE-OPUS-22 | Delete `git_porcelain` and the git simulator; one `git.py` adapter over real git; tests use real git in tmp repos | vendor `git_porcelain` = 4,511 lines; `tests/support/fakegit.py`, `fake_slot_git.py`, `narrow_hosts.py` (777); the logic-test guard fails any test that runs real git (`tests/conftest.py:58` limits and guards, CLAUDE.md) | delete abstraction | P2 | M | ✅ LOW-CONF | Disagrees with extraction #2 (converge git-porcelain, "critical" risk, 3.3-4.3k lines). A tmp-repo git call costs milliseconds; the simulator costs thousands of lines and can disagree with git. Low confidence only on suite wall time; measure. |
| SIMPLE-OPUS-23 | Tests ~13k: golden scenario traces (plan, write, red, fix, review, land, conflict, ask, retry, kill-and-resume) through `tl run` with a scripted delegate; unit tests only for the transition table and prompt rendering | tests 55,552 (1.36x src); `tests/support` 6,297 lines of fakes; `engine_case.py` (765), `narrow_hosts.py` (777); `test_stages_visual.py` (717) | delete tests with features | P2 | L | ✅ | Most tests guard host-object shapes that the rewrite deletes. Scenario traces survive the rewrite and are the migration's acceptance test. |
| SIMPLE-OPUS-24 | `.importlinter` from 484 lines and 18 slice contracts to 4 layers; `tests/rules` (1,804) to a size cap and the hook-is-light rule | `.importlinter` 484; `tests/rules` 1,804; per-slice forbidden lists (c4 `:141-503`) | delete rules | P3 | S | ✅ | The rules hold and prove little (zoom-out line 10). Twelve modules need no acyclicity proof per slice. |
| SIMPLE-OPUS-25 | `SKILL.md` from 674 to ~150 lines: the eight verbs, the bd conventions, the delegate table | `skills/task-loop/SKILL.md` 674 lines; `tl slot` mentioned 16 times | prompt cost | P2 | S | ✅ | Loaded into every orchestrating session. Every verb named there is a verb a session may call wrongly. |
| SIMPLE-OPUS-26 | Net-negative ratchet: `tests/rules` records total lines of `src`+`tests`; a commit may not raise it unless the bead carries `grow-ok` from the owner | `KNOWN_OVERSIZE` ratchet exists only per file (`tests/rules/rules_ratchet.json`, CLAUDE.md); 100k lines in 15 days (`git log`) | process | P1 | S | ✅ | Every review (this one included) produces beads; every bead adds a guard. Without a total-size ratchet the deletions below regrow in a month. |
| SIMPLE-OPUS-27 | Phase-0 usage census: count per day on the Mac which verbs run, which profile knobs differ from default, which Kinds close beads, which steps execute, which dashboard POSTs fire | `events.jsonl` exists as the sink (c4 stores table); devbox has 26 runs total so devbox data cannot decide | measurement | P1 | S | ✅ | Decisions 14, 17, 19, 33, 34 depend on it. One week of data turns "is X worth it" into a lookup. |
| SIMPLE-OPUS-28 | Fold `look` into `review`: screenshots are check artifacts (`keep:` globs), the reviewer gets them as attachments; delete the separate look step, judge, gallery and owner-look bead | look slice 1,019 lines (`app/look/*` 694, `adapters/looks.py` 217, `contracts/gallery.py`); `test_stages_visual.py` 717; lifesim uses `visual_paths` and `shot_table` | merge feature | P2 | M | ❓ | Test: on 10 recent lifesim visual beads, does a reviewer with the shots attached reach the same verdict as the look judge? If yes, merge. |
| SIMPLE-OPUS-29 | Release machinery out of the shipped package: `app/release` flow/suite/clone/publish/push to `dev/`, and a cap of one release per hour | `app/release` = 1,143 lines inside `src` (shipped, `MANIFEST.sha256`); 377 release commits in 15 days; devbox `releases/` holds 356 suite logs, 209 MB; `release/` clone 45 MB | move + ops | P2 | S | ✅ | Release code in the product is code every install carries and every import rule must place. 20+ releases a day spends suite time and makes every Mac loop move. |
| SIMPLE-OPUS-30 | SQLite execution store (R1) | zoom-out R1 | store | P2 | L | ❌ LOW-CONF | Refuse for the 30% design: one-writer job dirs remove the reason. SQLite adds a schema-migration surface, a reader lock interplay with the dashboard, and a second format next to bd. Low confidence: if the census shows cross-job queries are frequent (dashboard, status), revisit. |
| SIMPLE-OPUS-31 | Replace slots with a fresh `git worktree add` per bead | `lease.py:1-2` says lifesim slot setup takes 5-12 min | delete mechanism | P2 | S | ❌ | Refuse: Unity's Library and NuGet restore make a fresh tree too slow. Slots stay; only their lease mechanism changes (SIMPLE-OPUS-07). |
| SIMPLE-OPUS-32 | Make delegate an in-process library | `dg:` supervisor kills a process group (`dg:app/supervisor.py:1-2`) | packaging | P3 | M | ❌ | The subprocess is the kill boundary and the crash boundary. One plugin (21) captures the version win without it. |
| SIMPLE-OPUS-33 | Delete the loop; the orchestrating Claude session is the loop (`/loop` + `tl run`) | SKILL.md already teaches the session to drive beads; loop slice + launch = 2,129 lines | delete feature | P2 | M | ❓ LOW-CONF | Test: one Trust Night with a session-driven loop on two slots; compare beads landed and owner interventions. My bet: the unattended overnight run needs a process that does not compact or hit a session limit, so this fails. |
| SIMPLE-OPUS-34 | Delete the engine's review step for beads whose gate is strong; sample reviews instead | `review: on|off|sampled` already exists `config.py:217-218`; review slice 1,632 lines | delete feature | P2 | S | ❓ LOW-CONF | Test: over 30 lifesim beads, count review findings that the gate would not have caught and that the owner agreed with. Below 10%: default to `sampled`. |
| SIMPLE-OPUS-35 | Let GitHub's merge queue be the land lock and queue, with a self-hosted runner on the Mac running the gate | land lock `adapters/landlock.py`; land slice 2,878 | outsource | P1 | L | ❓ LOW-CONF | Contrarian. Would delete land lock, rebase loop, outbound and push race code. Test: one week on lifesim with branch protection + merge queue; measure time-to-main. Risk: Unity runner availability on a sleeping Mac. |
| SIMPLE-OPUS-36 | Drop msgspec; records are dataclasses with a 50-line strict loader | `msgspec-in-contracts-only` contract; the hot hook cannot import it (CLAUDE.md); `contracts/` 7,293 lines | dependency | P3 | M | ❓ LOW-CONF | Test: port `job.json` and the log line to dataclasses and compare load time and error messages. msgspec may well be worth it; the question is whether its type ceremony drove the 7k-line contracts layer. |
| SIMPLE-OPUS-37 | Devbox does not run a factory; delete multi-host features (host affinity `needs:<res>`, `host.json` resources for picking, cross-machine claim handling) | devbox: 26 runs, all release check runs or a few landed beads; `app/loop/hosts.py:1` host affinity; Z06 | scope | P2 | S | ❓ | Test: owner states whether devbox will ever loop lifesim. If not, one host per repo is a rule in `host.json`, not code. |
| SIMPLE-OPUS-38 | Delete `selftest` as the gate for an install move | `tl/app/launch/selftest.py:1` "A newer install must pass it before a loop moves to it" (163 + 106 beads helper) vs `versions.py:1-6` "Nothing is tested before a move" | dead/contradictory | P3 | S | ✅ | The two docstrings contradict each other; with moves only between jobs and the release suite already green, selftest is a third test of the same build. |
| SIMPLE-OPUS-39 | Dead code now: `Stores.loop_state`, `Kind.CUT` and its rule, `contracts/dash.py` types used only by the dashboard living in engine contracts | `tl/stores/bundle.py:27`, `stores/real.py:21`, `stores/memory.py:217` (nothing reads `loop/<key>.json`, c4); `kinds.py:13`, `outcome.py:68` | dead code | P3 | S | ✅ | Free deletions to start the ratchet. |
| SIMPLE-OPUS-40 | The config dir is also a junk drawer: a 137 MB bd backup, 209 MB of suite logs, 45 MB release clone; `prune` covers runs only | devbox `du` of `~/.config/task-loop`; `tl/app/prune/runs.py:1` "three sweeps ... check-round logs, run folders, engine logs" | ops | P3 | S | ✅ | Disk-free gate (`min_free_gb` `config.py:154`) stops the loop; the release's own logs are what fill the disk. |

### First step for each ✅

- **01** Add `job.lock` + `job.json` to the current engine as a mirror written at every step (dual write), and make `tl status` read lost-ness from the lock instead of the manifest.
- **02** Add `action` (`retry|ask|hold|landed`) and `retry_at` to the run end record and have the loop read only those two fields.
- **03** Replace the call sites of `domain/lanes/policy` in `worker_call` with the three-line permanence mapping behind a profile flag, and compare decisions on recorded Mac answers.
- **04** Land Z24 (delegate push refusal) first, then stop writing `core.hooksPath` in `childenv.hooks_vars` and delete the dispatchers in the same release.
- **05** Set the loop's default to `hop: between-jobs` (skip `safe_point`), run a week, then delete `reload.py` and `reexec.py`.
- **06** Make the engine raise an ask as `bd update --status blocked` + a `Q:` comment in addition to the ask file, and switch the dashboard's ask list to read bd.
- **07** Take a `slots/N.lock` flock alongside the slot bead for one release; then stop creating slot beads.
- **08** Make `run-task` verify the assignee instead of claiming when `TASK_LOOP_LOOP_PID` is set.
- **09** Write the golden scenario traces from 10 recorded Mac runs before writing any v2 engine code.
- **10** Emit a census event for every profile key that differs from its default; after a week, move unused keys to constants.
- **11** Change `where: container` checks to fail the profile load with "call docker in argv", after checking no profile on either machine uses it.
- **12** Compute the content key alongside today's key and log disagreements for a week; then authorize by the content key only.
- **13** Count which of salvage, restart, recheck, fix_outside, fixer fired on the Mac in 14 days; delete the ones with zero.
- **15** Make `tl factory start --lanes N` start one loop with `--slots N` and one `caffeinate`.
- **16** Remove the eight non-answer POST verbs from the page (keep the API one release), then from the server.
- **18** Make `tl status BEAD --json` include everything `report`, `trace`, `lost` print; then delete those verbs from SKILL.md.
- **19** Delete storm and stuck (their outputs are already only warnings in the log), measure for a week.
- **20** Name the call memo by `(job, step, round)` and write it before consuming the answer.
- **21** One release of a combined plugin repo that ships both skills at one version, with the delegate skill unchanged.
- **22** Port one slice's tests (slots) to tmp-repo real git and record the wall time.
- **23** Freeze the old suite (no new tests in `tests/run`, `tests/land`), add new tests only as scenario traces.
- **24** Rewrite `.importlinter` to the four layers when v2 lands; delete the slice contracts with the slices.
- **25** Cut SKILL.md to the verbs the census shows sessions actually call.
- **26** Add the total-lines number to `rules_ratchet.json` and fail `just check` when it grows.
- **27** Add `trail.event("census", ...)` at verb dispatch, profile load, step start and close.
- **29** Move `app/release/{flow,suite,clone,publish,push,manifest,cache,seams,shell,tidy}.py` under `dev/` with no behaviour change.
- **38** Delete the selftest call from the install-move path; keep `tl selftest` as a dev command one release, then delete it.
- **39** Delete `Stores.loop_state` and `Kind.CUT` in one commit.
- **40** Add `releases/` (keep 20 newest) and the release clone to `tl prune`.

---

## 2. What to delete, in one table (this checkout, `wc -l`)

| Delete | Files | Lines | Replaced by |
|---|---|---:|---|
| mid-bead hop | `app/run/reload.py`, `app/release/reexec.py`, `app/loop/versions.py`, `app/release/selfupdate.py`, `app/release/catalog.py`, `app/release/pins.py` | 490 | bundle in `job.json`, exec between jobs (~60) |
| selftest | `app/launch/selftest.py`, `selftest_beads.py` | 269 | release suite |
| pre-push judge + hooks | `land/push_judge.py`, `launch/push_judge.py`, `hook/prepush.py`, `cli/green.py`, dispatcher part of `doctor/install.py`, `childenv.hooks_vars` | ~300 | in-process gate before push |
| stop policy | `domain/lanes/*` | 1,491 | 3-line mapping |
| outcome taxonomy | `contracts/kinds.py`, `domain/outcome.py` | 292 | `Transition` (~60) |
| inbox | asks slice (`app/asks`, `domain/asks`, `contracts/ask.py`, `answers.py`, `ledger.py`, `cli/asks.py`, `run/ask_flow.py`), `contracts/adrs.py` | 1,978 | bd comments/labels (~300) |
| slot leases | `app/slots/*`, `wire/slots.py`, `contracts/slots.py`, `domain/slot_env.py`, `contracts/fence.py` | 1,558 | flock slots (~300) |
| run records and reconcile | `app/reconcile`, `domain/reconcile`, `contracts/reconcile.py`, `runlife.py`, `locator.py` | 1,165 | lock-derived liveness (~100) |
| checks identity, container, lanes, base-red, fixer, keep | `app/checks/*` + `domain/checks` + check contracts and adapters | 3,427 | `checks.py` (~700) |
| land recovery paths, stack | `app/land/*`, `domain/land` | 2,878 | `land.py` (~600) |
| look as a step | `app/look`, `adapters/looks.py`, `domain/look`, `contracts/gallery.py` | 1,019 | attachments to review (~150) |
| reflect, report | `app/report`, `app/run/reflect.py`, `cli/report.py`, `domain/report` | 1,222 | `tl status --json` |
| heuristics | budget, stuck, storm (2), strays, done_memo, waits | 497 | `Retry(at)`, memo by call id |
| release in src | `app/release` flow/suite/clone/publish/push/manifest/cache/seams/shell/tidy | 877 | `dev/` (~400) |
| dashboard engine side | `launch/dash.py`, `launch/dash_ports.py`, `contracts/dash.py`, `dashcost.py`, `dashruns.py` | 1,022 | read-only readers (~400) |
| engine host | `app/run/*` (51 files) | 6,028 | `engine/` (~2,800) |
| contracts layer | `contracts/*` (56 files) | 7,293 | `job.py`, `profile.py`, record types (~1,200) |
| vendor not needed | `git_porcelain`, `jsonl_log`, `child_env`, `static_page_check` | 5,165 | real git adapter (~300) |
| test fakes | `tests/support/*` | 6,297 | scripted delegate + tmp repos (~1,000) |
| rules | `.importlinter`, `tests/rules/*` | 2,288 | 4 layers + size ratchet (~300) |

These overlap (for example `app/run` and the inbox); the target in 1.7 is computed from the design, not by subtracting this table.

---

## 3. Features not worth their weight

Judged by lines carried versus evidence of use. Where I cannot see the Mac, I say so and the census (27) decides.

| Feature | Weight | Evidence of value | Call |
|---|---|---|---|
| Mid-bead upgrade hop | ~760 lines + 4 incidents | none beyond "a fix arrives one bead sooner" | delete |
| Pre-push delivery judge | ~300 lines + 4 open P1/P2 findings | judges the engine's own push after the engine judged it | delete |
| Second inbox (asks/ledger/sweeps/ADRs) | ~2,000 lines | duplicates bd comments | delete |
| bd-backed slot leases + fences | ~1,500 lines | flock does the same with no failure modes | delete |
| Reflect + digest | ~320 lines + 1 call per bead | none on devbox; Mac unverified | census, likely delete |
| Visual look step | ~1,000 lines + 717-line test | real for lifesim | merge into review, not delete |
| Container checks | ~200 lines + an identity class of bugs | no profile uses it; task-loop calls Docker in argv | delete |
| 25 outcome kinds | ~300 lines + every switch on them | 3 actions | collapse |
| Storm, stuck, net, area, epic order, host affinity | ~600 lines + 20 knobs | incident patches | delete, re-add only on census |
| Dashboard's 8 non-answer writes | ~400 lines + the engine import at runtime | unknown (Mac) | census, likely delete |
| `land-stack` next to push | 416 lines | lifesim has many PR merges (who: unverified) | keep one mode |
| 47 verbs | `tl.py` table + SKILL.md 674 lines | sessions call ~10 | 8 verbs |

---

## 4. Migration that never breaks the running factory

Principles: the Mac lifesim factory keeps running the old path until the new one has carried real beads; every phase is one release,
reversible by `tl pin`; no phase lands during a Trust Night; each phase deletes in the same release in which it switches (or the
next one), so the system never carries both for long.

| Phase | What | Gate to the next phase | Reversible by |
|---|---|---|---|
| 0. Census (1 week) | SIMPLE-OPUS-27: events for verbs, knobs, kinds, steps, POSTs on the Mac; total-lines ratchet (26) | a census table in `docs/architecture/` | n/a (read only) |
| 1. Free deletions (2 days) | dead code (39), selftest gate (38), release out of `src` (29), prune of releases (40), zero-use knobs and verbs from the census | suite green, Mac loop moves once | `tl pin` |
| 2. Push path by deletion (1 week) | delegate push refusal (Z24) released and verified on both lanes; then delete the pre-push judge and dispatchers (04) | one Mac night with no `judge-push` and every land green | pin; dispatchers are regenerated by the old version on SessionStart |
| 3. No mid-bead hop (1 week) | loop default `between-jobs`; record bundle in job (05) | a release lands mid-Trust-Night with no bead affected | flag off |
| 4. One writer per job (2 weeks) | dual-write job dir (01, 20); dashboard and `tl status` read it; then stop writing manifests, checkpoints, parks, pauses, reexec | old readers have none left (grep), kill tests at each step resume correctly | stop dual-write later; old files still written until the switch |
| 5. Slots and claims (1 week) | flock slots alongside slot beads (07), single claim (08), then drop slot beads | a week with no slot fault on the Mac | flag |
| 6. bd inbox (1 week) | asks as bd comments alongside ask files (06), dashboard reads bd; then stop writing ask files | every open ask on the Mac visible from bd alone | flag |
| 7. Engine v2 (3-4 weeks) | golden traces from Mac runs (09, 23); v2 engine and loop (15) behind `engine.v2: true`; run on task-loop's own repo on devbox first (this also fixes "nobody dogfoods"), then lifesim one slot, then all slots | 50 lifesim beads on v2 with landed rate and owner-intervention rate no worse than the old engine's last 50 | profile flag per repo |
| 8. Delete the old engine | `app/run`, old land, old checks, old tests, `.importlinter` slices, vendor `git_porcelain` (22, 24) | suite green, size near target | git revert of one commit + pin |
| 9. One plugin (21) | combined repo and release | both skills load on both machines | marketplace keeps the last two-plugin versions |

Order rationale: phases 1-3 delete without needing the new store and remove the P1s that the zoom-out wave 1 would otherwise fix in
place. Phase 4 is the keystone; 5 and 6 depend on it for the lock-as-liveness rule. Phase 7 is a rewrite but not a big bang: per
repo, per slot, behind a flag, with the old engine still installed.

---

## What I think you are NOT thinking about

1. **The size is a velocity artifact, and the review process is the generator.** 100k lines in 15 days, 377 releases. Every review
   (architecture, dataflow, six encapsulation lenses, five extraction lenses, zoom-out, now this round) files beads, and every bead
   adds a guard plus tests. Without a total-size ratchet (26) and a rule "a hardening slice must delete what it replaces", this
   review round will make the code larger. The epic tl-sqd3 has 31 children; I count at most four of them that delete code.
2. **Nobody who builds task-loop runs it on task-loop.** 1,131 of 1,183 commits were authored by sessions with Codex outside the
   engine; the devbox's own engine has 26 runs, and its recent engine logs are only release check runs. All design pressure comes
   from Mac incident reports, read second-hand. The engine v2 should run task-loop's own beads first (phase 7) so that its builders
   feel its friction daily.
3. **Fixing an authority you should delete costs twice.** Z01, Z02, Z03 and Z14 fix the pre-push judge; Z04 adds CAS to six
   writers; Z22 renames lanes; FENCE hardens a bd-metadata fence. Each is a slice, a release, a test file. Each disappears if the
   thing it fixes is deleted (03, 01, 15, 07). Rank by "can this be deleted" before "how cheap is the fix".
4. **Tests are the main obstacle to simplification, not the safety net for it.** 55k test lines, 1.36x the source, 6.3k lines of
   fakes shaped like the engine's host object. A rewrite that must keep them green is impossible; a rewrite that discards them needs
   a replacement acceptance set first. That set is golden traces of real Mac runs. Nobody has recorded them yet.
5. **The orchestrator pays for every verb.** SKILL.md is 674 lines loaded into each orchestrating session; 47 verbs; CLAUDE.md on top.
   That is token cost per session and a wrong-verb risk per call, and it grows with every feature. A verb count budget belongs next
   to the line budget.
6. **bd is used as a lock service and a database, which it is not.** Slot beads, fence generations in metadata and lease
   heartbeats run through a Dolt database that syncs across machines. Machine-local, process-lifetime facts belong in flocks; bd
   should hold only facts a human would want in a tracker.
7. **The config dir is filling up with the release ritual, not the factory.** On the devbox: 209 MB of suite logs in `releases/`, a 45
   MB release clone, a 137 MB bd backup; the factory's own data is under 2 MB. `min_free_gb` stops the loop on a full disk; the loop
   would stop because of release logs.
8. **The two-machine design may be unnecessary.** If the devbox never loops lifesim, every multi-host concern (Z06 claim sync, host
   affinity, `needs:` routing at pick, the Mac-update gap Z21 partly) becomes a one-line rule. Ask the owner before building any of it.
9. **A rewrite is cheap here and refactors are expensive.** The usual "never rewrite" rule assumes writing is the bottleneck. Here Codex
   writes thousands of lines a day; the bottleneck is review and Mac verification. A refactor of `app/run` needs review of every
   intermediate state; a v2 beside v1 needs review of one small thing plus a comparison of traces.

---

## Where I disagree with the existing documents

1. **zoom-out Z01, Z02, Z03, Z14 (wave 1, release 1):** fix-in-place of the pre-push judge. I would delete the judge (03). The only
   pushes under `core.hooksPath` are tl's children, the engine gates before its own push, and workers must not push at all.
2. **zoom-out Z04 (CAS) as step one of R1:** it hardens multiple writers. Delete the writers: one writer per job dir and liveness
   from the flock (01). CAS is needed only where two writers must stay; after the redesign none must.
3. **zoom-out R1 (SQLite store):** refused (30). The store problem is a writer problem, and SQLite does not remove writers.
4. **zoom-out Z22 (rename factory lanes to loops):** delete the factory lanes instead (15).
5. **zoom-out Z05 / encapsulation FREEZEBUNDLE as an open owner decision:** the evidence (four incidents, a docstring that says moves
   are untested, `versions.py:1-6`) is enough; recommend delete now.
6. **zoom-out Z07:** right diagnosis, too small a cure. "One task-loop table mapping (producer, reason) to a Park" keeps the table; the
   design needs only delegate's permanence and retry time (02, 03).
7. **zoom-out Z16/R5 (engine without service locator, effort L as a refactor):** do it as a rewrite beside the old engine (09).
8. **extraction-synthesis "13% is the plan":** extraction moves lines, it does not remove concepts, and shelf copies drift (Z23).
   Deletion is the lever: ~70% of the code guards features, writers and hops that should not exist.
9. **extraction #2, git-porcelain convergence (3.3-4.3k lines, critical):** converge to nothing. Delete the porcelain and the simulator
   and test against real git (22).
10. **c4-task-loop's Stores table:** it lists 40-odd file families and their writer sets as given facts. It should have asked which
    families have a reason to exist. Under this design there are four (job dir, loop dir, check cache, host.json) plus bd and git.
11. **c4-task-loop "hard to draw" items 1-17:** they are framed as smells to fix. At least 1, 2, 3, 4, 5, 7, 8, 9, 15, 16 and 17 vanish by
    deletion rather than fix. The C4 documents are accurate and too kind: they document the factory's shape without challenging it.
12. **encapsulation synthesis rule "absence and fault are different types":** correct, and expensive to apply across 40 file families.
    It costs nothing when there are four stores and one writer each.
13. **The review brief's inputs:** `review/volume-delete.md` and `review/volume-tests.md` do not exist in the C4 worktree. If a volume
    lens was planned, its absence means the deletion question has had less attention than extraction (five lenses) and
    encapsulation (six).
