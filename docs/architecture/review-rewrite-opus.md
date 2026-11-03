# Lens 9: rewrite scan (Opus orchestrating 32 Haiku readers)

2026-11-02. task-loop main at e6c7f2a7 (`/home/iorlas/Workspaces/iorlas-task-loop`), delegate worktree UNITYD (`/home/iorlas/Workspaces/wt/UNITYD`).
Owner's question: "find cases where we will need to rewrite even a lot of stuff, it is ok, as long as we will decompose things."

**Method.** I had the Agent tool. I split the code into 32 module groups (25 task-loop, 7 delegate). One Haiku agent read each group in
full and returned a structured summary (responsibilities, state, deps, duplication, repeated shapes, smells, rewrite sketch). Agents ran
in batches of 5-6 (the session's 20-agent limit refused the first full fan-out). I then re-opened the load-bearing claims myself with
grep/sed. In this file:
- **(V)** = I re-opened it this session; the file:line is mine.
- **(H)** = a Haiku claim I did not re-open: treat it as unverified.
- Sizes are `wc -l` counts I ran, unless marked (H).

Baseline: `zoom-out-review.md` Z01-Z26 and R1-R5, epic tl-sqd3. Where a candidate overlaps one, I say "agrees with Zxx/Rx" and add only
what is new. Paths: `tl/` = `src/taskloop/`, `dash/` = `src/taskloop_dash/`, `dg:` = delegate `src/delegate/`.

---

## 0. The verdict in eight lines

1. The code is ~46.7k lines of task-loop source (with dash and static) plus 7.9k of delegate, 55.5k lines of tests in 327 test files (V), and
   1,183 commits since 2026-10-01 (V). It grew one bead at a time, and each bead added a new local shape instead of reusing one.
2. The biggest structural waste is **the same seven shapes written 30-100 times**, not one bad module (section 1.2). A rewrite that does
   not first fix the shapes will grow them back.
3. Only 3 call sites use the typed effect model (`plan_close`, `plan_land`) (V: `tl/app/run/closer.py:133`, `tl/app/land/sync.py:48`,
   `tl/app/run/ended.py:55`). The other ~90 app modules do their side effects inline through `host: Any`.
4. Run kinds are written as strings 62 times in `tl/app` (V: grep `"(FAULT|PAUSE|ASK|WAIT)_…"`), and turned into the enum at the last moment:
   `Kind[kind]` in `tl/app/run/blocked.py:32-35` (V). The type system is not used where the decisions are made.
5. `tl/app` declares 111 `Protocol` classes (V). 22 files in `app/land` alone have one (V). Most of them repeat `cfg`, `git`, `wt`, `log`,
   `blocked_for` (H, G05). That is about 1,000 lines of typing ceremony around a service locator (36 `host: Any` parameters (V), 38
   `cached_property` parts on `Engine` (V)).
6. The run's history is written 5-6 times in different shapes (log rows, trace, manifest, EndRec, events, checkpoint) (H, G17). The
   dashboard then re-derives the engine's decisions from those rows with its own rules (V: `dash/views/runfacts.py:129` `stuck_of` vs
   `tl/domain/stuck.py:14` `StuckWatch`; `dash/views/needs.py:48-55` vs `tl/app/loop/queue.py:224`).
7. Delegate and task-loop each re-implement the same machinery: the schema generator (V: `SCALARS` is identical at `tl/contracts/schema.py:16`
   and `dg:contracts/schema.py:15`), the codec, the stream_proc glue, the time parser, the read-only shell classifier, and the stop-reason
   permanence table, and those two now disagree (V: `tl/domain/lanes/pauses.py:23,39` makes `no_lane` and `crash` transient; delegate's
   `skills/delegate/contract.json:136-138,178-180` says `needs_owner`).
8. Recommended rewrite order: vocabulary, then substrate, then stores, then the fact log and read model, then the round primitive, then the
   run state machine, land, checks, loop. Each step runs behind the current Engine (strangler), so the factory never stops (section 2.0).

---

## 1. Module-group map

### 1.1 Groups, sizes, and what the Haiku reader found

Lines are `wc -l` (V). "Key finding" is the one claim per group that matters most for a rewrite; (V) where I re-opened it.

| G | Group | Lines | Role | Key finding |
|---|---|---:|---|---|
| G01 | `tl/app/run` core: engine, entry, run_once, stages, stage_run, steps, decide, state, context, layout | 2,189 | composition root, run lifecycle, cursor | `Engine` has 38 `cached_property` parts (V); two cursors (`stages.select_step` 79-102 vs `decide.resume_decision`) (H); Lease and checkpoint read built twice (`run_once.py:41-43`, `stages.py:106-111`) (H); dead `class Args` (V: `entry.py:50`, no other use) |
| G02 | `tl/app/run` workers: worker_call, lane_acts, requests, calls, waits, worker_identity, worker_recovery, budget, delegation | 1,435 | one AI call with retry; owner requests; waits/budget | `WorkerCall`↔`LaneActs` back-reference; engine fields mutated from inside (`worker_call.py:370-376`) (H); an interrupted call skips `calls.end`, so it gets no sessions row (`worker_call.py:268-272`) (H) |
| G03 | `tl/app/run` close: closer*, done_memo, outcomes, ended, blocked, stuck, running, summaries, reflect, ask_flow, review_glue | 1,277 | ordered close | three Kind classifiers (`outcomes.py:15-42`, `closer_settle.py:63,77`) (H); `CloserHost` ~25 members (H) |
| G04 | `tl/app/run` misc: resume, reload, records, trace, fields, shared, artifacts, console, shell, preflight, strays, bead_env | 1,126 | restore, hot reload, trace build, RunFields | `RunFields` ~75 attributes (H); `shared.py:50-54` read-replace with no lock (H); `reload.py:105` records "moved" before the hand-over can fail (H) |
| G05 | `tl/app/land` A: lander, gate, stack, stackgate, rebase, restart, recheck, verified | 1,241 | the land and land-stack | 22 land files declare Protocols (V); `blocked_for` re-declared in 5 Protocols (H); lock wrapper duplicated (`stack.py:177-189` vs `lander.py:121-123`) (H) |
| G06 | `tl/app/land` B: outbound, push, push_judge, tree, checkout, cleanup, fixer, forge, … | 1,596 | push, tree reset, PR, follow-ups | four git-error converters (`gitcall.py:14-19`, `cmds.py:36-76`) (H); `push_judge.py:9,74` authorizes with `green_result` (V; = Z01) |
| G07 | `tl/app/checks` | 1,786 | check rounds, cache, containers | memo built 3 ways; the delivery query uses `check_env()` and the round uses `bead_env`, both feeding the env digest of the key (`authorization.py:25`, `runner.py:41,129`, `cache.py:112,132`) (H): a possible key mismatch, see REWRITE-12 |
| G08 | `tl/app/loop` | 1,733 | the loop process: pick, take, run, settle | `LoopEnv` ~40 callables (H); parks read per bead per tick (H); `settle.py:65-66` matches `why` text (H) |
| G09 | `tl/app/launch, doctor, prune, track` | 1,730 | composition roots, dash/factory spawn, selftest | `.task-loop.json` read in ≥9 places (H); selftest ships `unittest.mock` in production code (`selftest.py:12,107`) (H) |
| G10 | `tl/app/release` + dev/release.py, dev/suite.py | 1,143 + 87 | release pipeline | not engine runtime; only `reexec`, `catalog`, `pins` are used at runtime (H) |
| G11 | `tl/app/slots` + slot contracts | 1,017 + 146 | slot leases, worktree reset, engine lock | global `LOCK` (`engine_lock.py:141`) read and written by 4 modules (H); "held by" text formatted 4 ways (H) |
| G12 | `tl/app/plan` + `tl/app/review` | 1,556 | planner, verifier | same skeleton (prompt, call, validate, send back once, record) in both (H) |
| G13 | `tl/app/wire` + `tl/app/reconcile` | 1,321 | edge wiring, sweep | `TASK = "task/"` branch prefix in ≥9 places (H); reconcile has its own Action model with `isinstance` dispatch, no ledger (H) |
| G14 | `tl/app/write` + `tl/app/report` | 1,492 | write/check/review rounds; `tl report`, reflect digest | `replan.md` written 4 times by hand (V: `write_round.py:105`, `check_round.py:66,92`, `review_round.py:186`); flow sentinels are strings (H) |
| G15 | `tl/app/asks`, `tl/app/look` + ask/answers contracts | 1,426 + 451 | owner verbs, looks, parks | `stick.decide` runs before the ledger write, so a retry can file a second factory bead (`intake.py:177-182`) (H); whole-metadata writes can drop a concurrent `owner_hold` (`looks.py:83-97`) (H) |
| G16 | `tl/contracts` ports, stores, dash, config | 2,043 | ports, stores, dash wire, profile | `Git` port has ~71 members, annotated in 62 files (H); `AskStore` state machine sits in contracts (V: `stores.py:252`) |
| G17 | `tl/contracts` delegate, log, paths, checks, run, checkpoint, locator, snapshots, trace, events | 2,253 | records, paths | `ConfigDir` builds ~61 paths (H); the same facts are stored in 5-6 records (H) |
| G18 | `tl/contracts` remaining 38 files | 2,303 | vocab, small records | decisions and IO in contracts (`fence.take`, `runlife.reconcile`, `parks`, `landed`, `adrs`) (H); 8 files with ≤2 importers (H) |
| G19 | `tl/adapters` git/proc/lock group (20 files) | 2,021 | git, processes, locks, signals | 5 git invocation paths, 3 lock entry points, 6 hand-written signal save/restore blocks (H) |
| G20 | `tl/adapters` bd/delegate/other (21 files) | 1,698 | bd, delegate, misc | `delegate_route.py` and `checks_argv.py` have zero importers (V); ~9 bd error-swallowing helpers (H) |
| G21 | `tl/domain` checks, lanes, land, look, write | 2,298 | check planning, lane policy, matchers | permanence table conflicts with delegate's contract (V); `lanes/netgate.py` has zero importers (V); 45 module-level regexes (H) |
| G22 | `tl/domain` review, prompts, plan, report | 1,827 | prompts, review routing, reflect clustering | prompts are f-strings and `%` strings mixed, no template files (H); 4 word-overlap rules (H) |
| G23 | `tl/domain` asks, beads, reconcile, root (effects, interpret, outcome, …) | 1,737 | effect model, outcome policy, ask specs | effects cover close and land only (V); `interpret`'s `apply` returns None, so an effect cannot feed a later decision (H) |
| G24 | `tl/cli`, `tl/hook`, `tl/stores`, `skills/task-loop/tl.py`, SKILL.md, `_vendor` | 1,078 + 223 + 653 + 460 + 674; vendor 6,297 | entry points; store bundle | two `RunLog` classes; three store layers (contracts/stores, stores/, call_state) (H); `cli/land.py` holds a whole land algorithm (H); hook catch-all (V: `tl/hook/main.py:22`; = Z03) |
| G25 | `dash/views` | 1,815 | read model assembly | re-derives stuck, passes, ready count, slot state, cost source (V for stuck and ready) |
| G26 | `dash` server root, api, readers, cli | 1,666 | HTTP, readers, caches | events and traces read by hand instead of `EventLog`/`TraceStore` (H); `loop_key` copied (H; = Z18) |
| G27 | `dash/static` | 2,809 | Preact page | client re-derives lane order, stuck/mute, columns, slot busy, tone thresholds (H) |
| G28 | `dg:contracts` | 1,839 | delegate wire, codec, schema, stores | live tag `"k"` vs task-loop `"kind"` (V: `dg:contracts/live.py:23`, `tl/contracts/wire.py:55`), patched by 2 dash shims (V: `dash/readers/world.py:54`, `dash/views/live_lines.py:24-25`) |
| G29 | `dg:app` run path: run, launch, supervisor, settle, lease, fleet, watch, publish, decide, answer | 1,807 | one `route.py run` | the Supervisor re-implements `stream_proc.run` (H); in-call canary, network retry and schema re-ask are invisible to task-loop, which then retries on top (H) |
| G30 | `dg:app` rest + cli + route.py | 1,094 + 242 + 12 | status, doctor, usage, onboarding | two auth-cache TTLs, two Claude probes (H); `status` writes state (= Z19) |
| G31 | `dg:adapters` (+harness) | 1,640 | CLI harnesses, procs, netprobe | three harnesses repeat one shape; parsers really differ (H); vendor-error regexes in 4 places (H) |
| G32 | `dg:domain` | 1,320 | router, holds, health, policy | `dwell.sticky`/`last` have no callers (V: only a docstring in `dg:app/watch.py:119` matches); read-only classifier duplicates task-loop's with different allowlists (H) |

Totals: task-loop src ~46.7k (with dash), vendor 6.3k, tests 55.5k; delegate src 7.9k (V).

### 1.2 Repeated shapes (what the readers found in several groups)

These are the real rewrite targets. Each one appears in many groups, so a local refactor of one module does not remove it.

| Id | Shape | Where (sample) | Count / evidence |
|---|---|---|---|
| RS1 | **Service locator**: a part takes `host: Any` (or `e`) and reads and writes any engine field | G01-G04, G12, G14, G15 | 36 `host: Any` in `tl/app` (V); 38 `cached_property` on `Engine` (V); RunFields ~75 fields (H) |
| RS2 | **Protocol-per-step**: each step re-declares the host members it touches, then a "host" Protocol sums them | G03, G05, G06, G07 | 111 `(Protocol)` classes in `tl/app`, 22 files in `app/land` (V); `CloseHost`/`LanderHost` are sums only (H) |
| RS3 | **Stringly vocabulary**: kinds, steps, flows, statuses, causes as strings, converted late | every app group | 62 kind literals in `tl/app` vs 13 files using `Kind.X` (V); `blocked_for(why, kind: str)` (V: `blocked.py:32`); flow `""/AGAIN/REPLAN/ACCEPT` (H) |
| RS4 | **Round skeleton**: build prompt, call a worker by role, parse, send back once, write `replan.md`, `steps.move`, bump counters | G12, G14, G15 (judge), G03 (reflect) | `replan.md` by hand 4 times (V); `rounds += 1` in `write_round.py:100`, `review_round.py:182` (V) |
| RS5 | **One fact, many records**: start/end pairs and outcome/cost/tokens repeated across log, trace, manifest, EndRec, events, checkpoint | G17, G04, G25 | three Tokens shapes, two Denial shapes, two RunState types (H) |
| RS6 | **Read-modify-write with no compare-and-set** | G15 (looks metadata), G04 (shared notes), G08 (parks), G11 (slot marks), locator (Z04) | (H) except where Z04 already verified |
| RS7 | **Same authority read in many places**: profile, task-branch prefix, repo key, delegate install, lease liveness | G06, G09, G13, G20 | profile ≥9 readers (H); `task/` prefix ≥9 (H); repo keys 4 (= Z18) |
| RS8 | **Several IO substrates**: git paths, process runners, locks, signal handlers, bd helpers | G19, G20, G29 | 5 git paths, 3 lock APIs, 6 signal blocks, ~9 bd swallowers (H) |
| RS9 | **Reader re-derives the writer's decisions** | G25, G27 | `stuck_of` vs `StuckWatch` (V); `ready_count` vs `rank_ready` (V); client tone/columns (H) |
| RS10 | **Same machinery in both repos** | G28 vs G16/G18; G29 vs G19; G32 vs G21 | schema `SCALARS` identical (V); live tag drift (V); permanence conflict (V); two stream_proc wrappers and two vendored copies (H) |
| RS11 | **Decide/apply exists only in pockets** | G23 (effects), G13 (reconcile Actions), G08 (verdict/settle) | effects have 3 callers (V); reconcile's Action model is a second, unkeyed one (H) |
| RS12 | **Prose regex as the protocol**: decisions taken by matching worker text or our own `why` text | G21, G22, G23, G03, G08 | 45 regexes in domain/checks+lanes+land+look+write, 28 in review/matchers, 23 in report/matchers (H); `why.startswith("paused: no lane")` (H) |

---

## 2. CONFIDENT rewrite candidates

### 2.0 Order that never breaks the running factory

Rules for every candidate below:
- **Strangler, never a big bang.** The new shape is built next to the old one and called from the existing `Engine`/loop. Each slice is
  one release through `dev/release.py`. The old path is deleted in the same bead that moves the last caller.
- **Records stay readable.** Any change to on-disk records adds a reader for the old version first (wire `V` gate), and deletes it only
  after the retention window (e.g. engine logs `logs_kept`).
- **Land and push are touched last, and alone.** One announced release per land-path slice (as Z01-Z03 already do).

Sequence: **01** (vocab) → **02** (substrate + dead code) → **03** (ports) → **04** (stores) → **05** (fact log) → **06** (read model) →
**07** (round primitive) → **08** (run state machine) → **09** (land) / **12** (checks) → **10** (loop) → **11** (lane policy + wire
across repos) → **13** (slots) → **14** (asks) → **15** (release out) → **16** (cli/tl) → **17** (delegate run path).
01 and 02 can run in parallel with wave 1 of ZOOMOUT. 04 needs Z04's CAS; 08 needs 04, 05, 07.

---

### REWRITE-01. One closed vocabulary, used where decisions are made

- **What is rewritten.** `tl/contracts/enums.py` (141), `kinds.py` (105), the free `Literal`s spread over `answers.py`, `dash.py`, `loop.py`,
  `needs.py`, `ledger.py` (H, G18); every `blocked_for(..., "FAULT_X")` call (62 sites, V); flow sentinels in `tl/app/write/state.py` (36) and
  `prepare.py` (H); step and cause strings in `steps.move(...)` (H).
- **New shape.** One `tl/contracts/vocab.py` with `StrEnum`s: `Kind`, `Step`, `Flow` (Continue/Again/Replan/Accept), `Cause`, `CheckStatus`,
  `SlotState`, `LoopExit`. `blocked_for(why, kind: Kind, ...)`. An import-linter or ruff rule bans the string forms in `app/`
  (e.g. a rule test: no `"FAULT_` literal outside `vocab.py`). Merge the duplicate names (`Cause` in `answers.py` vs `enums.py`, two
  `RunState`, two `CheckSpec`) (H).
- **Size.** In: ~250 vocab lines plus ~200 call sites. Out: about the same line count, minus ~150. The gain is type checking where the
  decision is taken, which every later rewrite needs.
- **Risk to the factory.** Low. A wrong mapping fails pyrefly or a test. Records keep the same string values (StrEnum).
- **Migration.** Make `Kind` a `StrEnum` first (it is `enum.Enum` now, H: `kinds.py:9`), so old strings still compare equal. Then move call
  sites per slice. Then turn on the rule.
- **First slice.** `blocked_for(kind: Kind)` and its 62 callers; the rule test bans `"(FAULT|PAUSE|ASK|WAIT)_` literals in `tl/app`.
- **Bead.** *REWRITE-VOCAB: one StrEnum vocabulary; blocked_for takes Kind* / acceptance: `grep -rE '"(FAULT|PAUSE|ASK|WAIT)_' src/taskloop/app`
  is empty and a rule test keeps it empty; `Kind[...]` lookup gone from `blocked.py`.

### REWRITE-02. One IO substrate: one runner, one git, one lock, one signal scope, one bd client; dead code out

Agrees with extraction #2 (git-porcelain) and #10 (process-lock) for the shelf part. New here: the bd and delegate clients, the signal
scope, and the dead-code batch.

- **What is rewritten.** `tl/adapters/git.py` 325 + `git_base.py` 150 + `git_ops.py` 96 + `markers.py` 17 (one class split over three files,
  plus a direct `subprocess.run` at `git.py:304`, H); `procs.py` 134 + `spawner.py` 91 + `runner.py` 184; `locks.py` 121 + `landlock.py` 92 +
  `contracts/guard.py` 15; `bd.py` 276 + `bdsafe.py` 22 + `beadtools.py` 52 + `bdcreate.py` 36 (`peek`/`attempt` written twice, H);
  `delegate.py` 222 + `delegate_route.py` 74 (zero importers, V); `checks_argv.py` 20 (zero importers, V); `tl/domain/lanes/netgate.py` 27
  (zero importers, V). Six hand-written signal save/restore blocks (`entry.py:301-310`, `closer.py:88-97`, `release/suite.py:148-158`,
  `cli/loop.py:120-125`, `landlock.py:75-92`, `halt.py:20-42`) (H).
- **New shape.** `adapters/proc.py`: `run(argv, env_policy, timeout, stop) -> Ran` over stream_proc, the only process starter.
  `adapters/git.py`: one `_run` (pinned env, timeout, error classification), typed results, one `GitError(kind)`. `adapters/lock.py`:
  `hold(path)`, the only lock API; paths only from `ConfigDir.lock(...)`. `adapters/signals.py`: one `deferred_signals()` context manager.
  `adapters/bd.py`: `BdClient.run(args) -> Result` with one default timeout (now unbounded, H: `bd.py:178-180`), typed `NotFound`/`Refused`/
  `Unavailable`, no swallowing inside the adapter; the "ignore if it fails" decision moves to callers with an explicit `.ok_or_none()`.
- **Size.** In: ~2,100 lines across ~20 adapter files. Out: ~1,300. Delete outright: ~140 lines of dead modules (V for three files).
- **Risk.** Medium. Git and bd are on every path. Mitigated by keeping method names on the port and swapping the implementation behind it.
- **Migration.** (1) Delete the three zero-importer modules (V). (2) Merge `bdsafe` into `beadtools` (pure move). (3) `git_base`/`git_ops`/`git`
  into one module behind the same `Git` port. (4) Signal scope. (5) Lock API (aliases first, then delete `landlock.os_lock` and `guard`).
- **First slice.** Delete `delegate_route.py`, `checks_argv.py`, `netgate.py`, and merge `bdsafe.py` into `beadtools.py`.
- **Bead.** *REWRITE-SUBSTRATE: one process runner, git, lock, signal scope and bd client* / acceptance: `grep -rn "import subprocess\|signal.signal("`
  under `tl/app tl/cli tl/adapters` hits only `adapters/proc.py` and `adapters/signals.py`; one lock entry point; the dead modules are gone.

### REWRITE-03. Narrow ports instead of the 71-member Git bag and the Protocol sums

Agrees with Z16/R5 in direction. New: the concrete split and the count (RS2).

- **What is rewritten.** `tl/contracts/ports.py` (511): `Git` (~71 members incl. `SlotGit`, H), `Beads` (16), `Sh` (0 users, H). The Protocol
  sums `CloserHost` (`tl/app/run/closer_host.py`, 100), `LanderHost` (`tl/app/land/lander_host.py`, 92), `land/parts.py` (54), `checks/host.py`
  CheckHost 22 members (H), plus the per-step Protocols (111 in app, V).
- **New shape.** Git split into `GitRefs`, `GitTree` (status, stage, commit), `GitWorktrees`, `GitRemote` (fetch, push), `GitRead` (log, show,
  diff). One error convention (raise `GitError`; no mixed `bool`/`None`/`GitOutcome`, H). Steps receive a frozen dataclass of the 2-4
  ports they use. No host Protocol sums.
- **Size.** In: ~511 + ~1,000 lines of Protocol declarations. Out: ~350 + ~200.
- **Risk.** Low at runtime (types only), high in churn: ~62 files annotate `Git` (H).
- **Migration.** Add the sub-ports as Protocols that `RealGit` already satisfies; change annotations file by file; delete the bag last.
- **First slice.** `app/land`: replace the 22 files' Protocols with one `LandPorts` dataclass (git refs, git remote, checks, log) and delete
  `lander_host.py` and `parts.py`.
- **Bead.** *REWRITE-PORTS: Git split into five sub-ports; land Protocol sums deleted* / acceptance: `app/land` declares ≤2 Protocols;
  `lander_host.py` and `land/parts.py` are gone; pyrefly clean.

### REWRITE-04. One store layer, above contracts, with CAS

Agrees with Z04 (CAS) and Z17 (effects out of contracts). New: the dashboard readers, `call_state`, and the two `RunLog`s are in scope, and
the 20 store subclasses become one table.

- **What is rewritten.** `tl/contracts/stores.py` 559 (`JsonStore`, `JsonlStore`, `AskStore` at :252 (V) with its state machine, 20 thin
  subclasses, H); `tl/stores/` 653 (`api`, `bundle`, `real`, `files`, `memory`, `runlog`, `books`, `call_state`); IO in contracts:
  `parks.py`, `landed.py`, `adrs.py`, `rotating.py`, `fence.take`, `runlife.reconcile`, `locator` writes (H); dash readers that bypass the stores:
  `dash/readers/records.py` 100, `dash/jsonl.py` 62, `dash/tails.py` 52 (H, G26).
- **New shape.** `tl/stores/`: `Doc[T]` (JSON, `revision`, `update(fn, expected_revision)` under a per-document lock), `Log[T]` (JSONL append,
  cursor, rotation), one registry table `{name: (path_fn, record_type, kind)}`; `fake_stores()` is the same table over memory. `AskStore`'s
  transitions become pure functions in `tl/domain/asks/` over `Ask`. The dashboard imports `stores` read-only accessors.
  `contracts/` keeps records only, enforced by a rule test (no `open`, `os.replace`, `subprocess`, `fcntl`; = ZOOMOUT-STORESLAYER).
- **Size.** In: ~1,600 (contracts/stores + stores/ + IO bits + dash readers). Out: ~800.
- **Risk.** Medium-high: every state file goes through it. Mitigated by keeping paths and record bytes identical; only the code that
  writes them moves.
- **Migration.** (1) Z04's `update(fn, expected_revision)` on `JsonStore` where it is now. (2) Move `JsonStore`/`JsonlStore` to `stores/` with
  re-exports. (3) Replace subclasses with registry rows. (4) Move `AskStore` logic to domain. (5) Dash readers switch to stores. (6) Delete
  re-exports.
- **First slice.** Fold `stores/call_state.py` (hand-rolled tmp+`os.replace`, no fake, H) into a `Doc` and give it a fake.
- **Bead.** *REWRITE-STORES: one store layer with CAS; contracts are records only* / acceptance: rule test passes (no IO under `contracts/`);
  one `RunLog` class; dash `readers/records.py` uses the store accessors; `fake_stores()` covers every store.

### REWRITE-05. The run log is the one history; the rest are projections

New relative to R1: R1 proposes SQLite for **authority**. This is about **history**, and it holds with either answer to Q-01.

- **What is rewritten.** The records that restate the same facts (H, G17): `RunTrace` (`contracts/trace.py`, 164) as a separately written
  record; `RunManifest` state fields (`contracts/run.py`), EndRec (`contracts/checkpoint.py:123-137`), the handoff mirror
  (`run.py:153-172`), pause/reexec files and `ReexecNote`/`NetPause`, the duplicate `engine-checks.rN.json` next to the `Checks` row; the
  writers `app/run/records.py` (157), `app/run/trace.py` (112), `closer_record.py` (88).
- **New shape.** `engine/<run>.jsonl` with a sequence number is the only append-only history of a run. `trace(run)`, `manifest_state(run)`,
  `end(run)` and the cross-run `events.jsonl` index are pure folds in `tl/domain/projection/`, computed at close and cached as files
  (so `tl report` and the dashboard stay fast). One `Tokens`, one `Cost`, one `Denial` shape (H: three Tokens shapes today).
- **Size.** In: ~1,000 lines of record types and writers. Out: ~500.
- **Risk.** Medium. `tl report`, reflect digest and the dashboard read traces. Keep writing the trace file, now produced by the fold, until
  every reader uses the fold.
- **Migration.** (1) Fold function that rebuilds today's `RunTrace` from a log; golden test against stored traces. (2) The closer writes the
  fold's output instead of building the trace by hand. (3) Pause/reexec become log rows. (4) Delete EndRec and the handoff mirror.
- **First slice.** `project_trace(log_rows) -> RunTrace`, plus a test that compares it with the last 50 real traces on the devbox.
- **Bead.** *REWRITE-FACTLOG: RunTrace is a projection of the engine log* / acceptance: `records.file_trace` builds no fields by hand; the
  projection equals the old trace on recorded runs; `Tokens` is defined once.

### REWRITE-06. The engine publishes the read model; the dashboard renders it

New. The baseline (Z08) is about dashboard **writes**; this is about dashboard **reads**.

- **What is rewritten.** `dash/views/passes.py` 234, `runfacts.py` 156, `phases.py` 98, the derivation parts of `needs.py` 160, `floor.py` 102,
  `queue.py` 31, `cost.py` 83 (H estimate ~600-800 lines, G25); client re-derivations in `dash/static/js` (`data.js`, `goals.js`, `floor.js`,
  `line.js`, `stage.js`, H estimate ~300 lines, G27).
- **New shape.** `tl/domain/projection/` (from REWRITE-05) also emits the views the page needs: passes with `PassEnd`, the open stuck
  episode, ready rows, slot state, lane order, tone. The engine records a `Pass` row (today none exists, H: `contracts/log.py`), so passes are
  not guessed from phase order. Both `tl status` and the dashboard call the same projection functions; the import-linter contract
  lets `taskloop_dash` import `taskloop.domain.projection` (pure) and nothing else of domain. The JS only renders and sorts nothing.
- **Size.** In: ~1,000 py + ~300 js. Out: ~400 py (moved into projection, shared) + ~100 js.
- **Risk.** Low for the factory (the dashboard is not on the delivery path), medium for owner trust (the page is how Denis sees the
  factory). Keep both computations for one release and log disagreements.
- **Migration.** stuck first (two rules today, V), then ready count (V), then passes, then slots.
- **First slice.** `dash/views/runfacts.py:129` `stuck_of` is replaced by `StuckWatch` from `tl/domain/stuck.py`, fed with log rows.
- **Bead.** *REWRITE-READMODEL: dashboard renders engine projections; no re-derived decisions* / acceptance: `stuck_of` and the
  `ready_count` fallback are deleted; the dashboard and `tl status` show the same stuck and ready values on one fixture world.

### REWRITE-07. One worker-stage primitive for plan, write, review, verify, look, reflect

New. This is RS4, the largest copy-paste in the app layer.

- **What is rewritten.** The skeletons of `tl/app/plan/planner.py` 234 + `sendback.py` 125 + `prompt.py` 124; `tl/app/review/verifier.py` 207 +
  `routing.py` 140; `tl/app/write/write_round.py` 134 + `check_round.py` 96 + `review_round.py` 195 + `stage_loop.py` 55 + `state.py` 36;
  `tl/app/look/judge.py` 197; `tl/app/run/reflect.py` 74. The one-shot booleans (`plan_decided`, `plan_assumed`, `cap_granted`, H), the
  `"found wrong:"` prefix channel (H), and the 4 hand writes of `replan.md` (V).
- **New shape.** `Stage(role, prompt_fn, answer_type, validators, router)`. `run_stage(ctx, stage) -> StageResult` where `StageResult` is
  `Continue | Again(feedback) | Replan(reason, Cause) | Accept(answer) | Blocked(Kind, spec)`. It owns: the worker call (through
  `WorkerCall`), one send-back on the same thread, the record and the `replan.md` write, the counter bump. Each node keeps only its
  prompt, its validators and its router.
- **Size.** In: ~2,200 lines. Out: ~1,300 (shared primitive ~250).
- **Risk.** Medium-high: these stages are the product. Golden tests on prompts already exist for write (H: `tests/domain/test_prompt_golden.py`);
  extend them to every node before moving.
- **Migration.** write round, then check round, then review round (one stage loop), then verify, then plan (plan has the most special cases:
  cap, assumptions, send-back), then look and reflect.
- **First slice.** `Flow` enum (from REWRITE-01) plus a `replan(ctx, reason, cause, text)` helper that replaces the four hand writes; the three
  write-stage rounds return `StageResult`.
- **Bead.** *REWRITE-STAGE: one worker-stage primitive; rounds return StageResult* / acceptance: `replan.md` is written in one function;
  `stage_loop.py` matches on `StageResult`; no string flow sentinels remain.

### REWRITE-08. The run as a state machine with a typed effect outbox (the new engine core)

Agrees with R5 and Z16 (engine without a locator). It goes beyond them: the effect model already exists for close and land (V: 3
callers) and is extended to the whole run, with effects that return results.

- **What is rewritten.** `tl/app/run/engine.py` 413, `fields.py` 97, `state.py` 243 (`carries_state`), `run_once.py` 245, `stages.py` 342,
  `steps.py` 78, `decide.py` 119, `resume.py` 191, `context.py` 87, `closer*.py` ~760, `outcomes.py` 69; `tl/domain/effects.py` 160,
  `interpret.py` 69, `outcome.py` 187. Total ~3,060.
- **New shape.** `RunState` (frozen record: bead, run, claim, checkpoint, stage cursor, counters). `next_step(state) -> Step` (one cursor;
  today two, H). `Step` functions from REWRITE-07 and the land/check use cases return `StepResult(transition, effects)`.
  `interpret(effects, ledger) -> results` (effects return a typed result, stored with the key in the checkpoint, so a resume replays
  results instead of re-running them). `RunOnce` becomes a 40-line loop: load, pick, run, commit. The composition root builds ports once
  and passes them to nobody else.
- **Size.** In: ~3,060 + the ~1,000 lines of host Protocols from REWRITE-03. Out: ~1,600.
- **Risk.** High. This is the engine. It is safe only after 01, 03, 04, 05 and 07, and only as a strangler: `Engine` keeps running and
  calls the new loop for one step at a time.
- **Migration.** (1) Effects return results (`interpret.apply -> Result`, H: returns None today). (2) Close fully on the new loop (it is
  already planned by `plan_close`). (3) Land after-effects (already `plan_land`). (4) The write stage (from 07). (5) Plan. (6) Reset/claim.
  (7) Delete `carries_state`, `RunFields`, the `cached_property` parts.
- **First slice.** `Closer` takes a typed `CloseInput` (done outcome, stats, branch, dry) instead of `CloserHost`; delete `closer_host.py`.
- **Bead.** *REWRITE-CORE: the run is a state machine over StepResult and a result-returning effect outbox* / acceptance: `carries_state`
  and `RunFields` are deleted; an import-linter contract forbids importing `Engine` in step modules; kill tests at every transition
  resume to the same next step.

### REWRITE-09. Land as one phase machine with one ports object

Agrees with R3 (one delivery judge) for the judge part. New: the land body itself.

- **What is rewritten.** `tl/app/land/` 2,837 lines in 30 files: `lander.py` 257 (step begun in two places, H), `gate.py` 177, `push.py` 109,
  `rebase.py` 144, `land_rebase.py` 41, `recheck.py` 72, `restart.py` 95, `verified.py` 76, `tree.py` 173, `checkout.py` 150, `cleanup.py` 120,
  `fixer.py` 134, `fix_outside.py` 74, `salvage.py` 64, `gitcall.py` 27, `cmds.py` 76, `parts.py` 54, `lander_host.py` 92, `state.py` 41.
- **New shape.** `LandPhase` enum (Outside, Fetch, Rebase, Gate, Push, Verify, Done). `land(ctx: LandPorts, state) -> LandResult` where each
  phase is a function returning the next phase or a `Problem(ProblemKind)`; one step-begin point; one git error type (from 02); the fix kind
  is an enum, not `"conflict"/"gate"/"verify"` (H). `stack.py` (218) and the engine share one lock helper, one stale-branch namer
  (written in 2 places, H), and one `.task-loop.json` loader (from 13 of RS7).
- **Size.** In: ~2,840. Out: ~1,700.
- **Risk.** High: this is delivery. Do it after Z01-Z03 have landed and after 02 and 03. One announced release per phase moved.
- **Migration.** (1) `LandPorts` (from 03). (2) Phase enum around the existing functions. (3) Merge the four git-error converters. (4) Move
  stack onto the shared helpers. (5) Delete `parts.py`, `lander_host.py`, `gitcall.py`.
- **First slice.** One `stale_branch_name(bead, clock)` and one `land_lock(repo)` helper used by `restart.py`, `tree.py`, `stack.py`, `engine.py`.
- **Bead.** *REWRITE-LAND: land is a phase machine over LandPorts* / acceptance: `app/land` has ≤15 files; one step-begin; procsim land tests
  unchanged and green.

### REWRITE-10. The loop as a pure pick and a pure settle

New relative to the baseline (Z22 covers only caffeinate and naming).

- **What is rewritten.** `tl/app/loop/loop.py` 369 + `core.py` 140 (a god object split by inheritance, H), `settle.py` 166, `take.py` 130,
  `queue.py` 239, `env.py` 90 (`LoopEnv` ~40 callables, H), and `tl/app/launch/loop.py` 317 (`build` 207-273, H).
- **New shape.** `Tick = snapshot(bd ready, parks, holds, busy areas, rests)` read once per tick (today parks are read per bead, H).
  `pick(tick, cfg) -> list[Candidate]` pure. `settle(verdict, counters) -> (counters, Continue | Sleep(s) | Exit(LoopExit))` pure. The slot
  is an optional object, not a `slots: bool` flag threaded through five calls (H). `LoopPorts` small and typed.
- **Size.** In: ~1,450. Out: ~900.
- **Risk.** Medium: the loop is the outer process; a bug stops the factory but does not corrupt delivery. Selftest covers it.
- **Migration.** `settle` pure first (it already almost is, H), then `pick`, then the snapshot, then `LoopEnv` split.
- **First slice.** `settle(verdict, counters)` returns an action value; exit reasons become `LoopExit`; delete `EXIT_REASONS` (no reader, H).
- **Bead.** *REWRITE-LOOP: pure pick and settle over a per-tick snapshot* / acceptance: one bd `ready` + one parks read per tick (counted in a
  test); `Loop` no longer inherits `Core`.

### REWRITE-11. One worker-run wire package and one reason table across the two repos

Agrees with extraction #5 (typed-json) and Z07 (stop authority), Z09 (contract list). New: the concrete drifts, two of them verified.

- **What is rewritten.** Delegate `dg:contracts/codec.py` 229, `schema.py` 104, `wire.py` 222, `live.py` 128, `stops.py` 40; task-loop
  `tl/contracts/schema.py` 147, `tl/contracts/delegate.py` 301, `tl/adapters/delegate_wire.py` 197; the permanence copy in
  `tl/domain/lanes/pauses.py` (103) and the permanence keying in `tl/domain/lanes/policy.py` (329); the two dash shims (V).
- **New shape.** A shelf package `worker_run` (records, one codec, one schema generator, the live-line tag and version, one argv builder,
  the reason table generated from one source with a test that the router's reasons are all listed; H: `only_family_unready` is missing
  from `contract.json`). Both apps vendor it at one tag. task-loop keeps only its loop-side backoff, keyed by reason name; permanence comes
  from the stop it receives.
- **Size.** In: ~2,000 across both repos. Out: ~1,000 (one copy).
- **Risk.** Medium. The contract is the boundary between two plugins released apart. Ship the package in delegate first with the old
  wire bytes; task-loop switches next; then fix the tag (`k` → `kind` with a dual reader) and the permanence conflict.
- **Migration.** (1) Fix the verified conflict now as a bug: `no_lane` and `crash` follow the contract's `needs_owner`
  (`pauses.py:23,39` vs `contract.json:136-138,178-180`, V). (2) Shared schema module (identical code today, V). (3) Records. (4) Live tag.
- **First slice.** The permanence conflict fix plus a test that every `pauses.TABLE` key's permanence equals the contract's.
- **Bead.** *REWRITE-WIRE: one worker-run package; reasons from one table* / acceptance: `tl/contracts/schema.py` and `dg:contracts/schema.py`
  are one vendored module; the two `"k"` shims are deleted; a test fails if a router reason is absent from the table.

### REWRITE-12. Checks: a pure round planner, a resolver chain, one CheckEnv

New. It also hides a possible correctness bug that needs a test first.

- **What is rewritten.** `tl/app/checks/executor.py` 256 (`_decide` 83-120, H), `cache.py` 268 (`RunMemo` 140 lines mixing key derivation,
  env hashing and IO, H), `runner.py` 184, `attempts.py` 128, `authorization.py` 34, `resources.py` 107, `lanes.py` 114.
- **New shape.** `plan_round(checks, tree, base, history) -> RoundPlan` pure (domain). `resolve(step) -> Skip | Admit | Reuse | Cached | Run`
  as an ordered chain over an injected store and runner. One `CheckEnv` value built once and used by all three memo sites. Statuses are
  `CheckStatus`. Unity-specific log handling (`PROJECT_LOG`, the `"analy"` heuristic, H: `executor.py:25,246`) moves into profile config.
- **Size.** In: ~1,100. Out: ~700.
- **Risk.** High: the gate decides delivery. The env question below must be answered before the move.
- **Migration.** (1) Test: does the delivery query (`check_env()`, TL_SLOT=check) compute the same key as the round (`bead_env`) for one
  tree? (H: `authorization.py:25` vs `runner.py:41,129`, env digest in the key at `cache.py:112,132`). If not, either delivery never finds
  the round's evidence (fail-closed, wasted reruns) or it finds evidence from a different env. (2) One `CheckEnv`. (3) Resolver chain.
  (4) Delete `repo_green`/`repo_green_result` (no callers, H).
- **First slice.** The key-equality test.
- **Bead.** *REWRITE-CHECKS: one CheckEnv; pure round plan; resolver chain* / acceptance: a test proves delivery and the round compute
  the same key for one tree; `executor._decide` is a list of resolvers.

### REWRITE-13. Slots as one aggregate; one profile reader; one branch-name module

New, apart from Z15 (lock location) and Z18 (repo keys).

- **What is rewritten.** `tl/app/slots/` 1,017 (`pool.py` 188, `reset.py` 199, `engine_lock.py` 141 with the global `LOCK`, `owned.py` 134,
  `marks.py` 52, `line.py` 48, `lease.py` 53, `verbs.py` 133, `env.py` 69), `tl/app/wire/slots.py` 301 (`slot_env` of 19 lambdas, H); every
  `.task-loop.json` reader (≥9, H); every `"task/"` literal (≥9, H).
- **New shape.** `Slot` aggregate (bead marks, worktree, engine lock) with `take(ticket) -> Lease | Busy(holder)` and `release(lease)`;
  `SlotMarks` with one formatter (four "held by" formats today, H); no module global. `tl/domain/profile.py`: `profile_at(git, rev)`, the only
  reader, used by loop, engine, push judge, doctor, check. `tl/contracts/branches.py`: `task_branch(bead)`, `wip_branch(...)`,
  `stale_branch(...)`.
- **Size.** In: ~1,500. Out: ~950.
- **Risk.** Medium: slots gate every run; one bad take blocks a lane.
- **Migration.** Profile reader first (also needed by Z02), then branch names, then the aggregate.
- **First slice.** `profile_at(git, rev)` replacing the readers in `push_judge.py`, `check.py`, `doctor/profiles.py`, `stackgate.py`.
- **Bead.** *REWRITE-SLOTS: one Slot aggregate; one profile reader; one branch-name module* / acceptance: `grep -rn '"task/' src/taskloop`
  hits only `contracts/branches.py`; `.task-loop.json` is opened in one module; `engine_lock.LOCK` is gone.

### REWRITE-14. Owner verbs as typed commands with intent before effect

New. The Haiku reader found two idempotence bugs worth a test each (H).

- **What is rewritten.** `tl/app/asks/intake.py` 206, `stick.py` 96, `looks.py` 129, `raiser.py` 90, `sweeps.py` 145, `parks.py` 66;
  `tl/app/look/owner_look.py` 143; `AskStore` transitions in `tl/contracts/stores.py:252-459` (V for the class start).
- **New shape.** One record per verb (`Answer`, `Hint`, `Hold`, `Waive`, `Override`, `Cause`, `Stick`, `Ack`, `Look`); `apply(cmd, ask) ->
  (ask', effects)` pure; one metadata port with `set/unset/json` and key-merge only (no whole-dict writes); one receipt helper; the ledger
  row is written before the effect, keyed, so a retry cannot file a second factory bead. One `Sweep(marker, every)` helper for the four
  throttled sweeps.
- **Size.** In: ~1,100. Out: ~650.
- **Risk.** Low-medium: owner actions are rare and visible; a regression is noticed quickly.
- **Migration.** Tests for the two suspected bugs (`intake.py:177-182` order; `looks.py:83-97` whole-metadata write), then the command
  records, then the dashboard writes (Z08) go through the same records.
- **First slice.** The two tests; fix whichever fails.
- **Bead.** *REWRITE-OWNERCMD: owner verbs are typed commands; ledger before effect* / acceptance: a retried `stick` files one factory bead;
  a `look` answer does not drop a concurrent `owner_hold`.

### REWRITE-15. Release leaves the engine

New (G10).

- **What is rewritten.** `tl/app/release/` 1,143: `flow.py` 186, `suite.py` 253, `publish.py` 95, `push.py` 49, `clone.py` 53, `shell.py` 72,
  `selfupdate.py` 37, `manifest.py` 38, `tidy.py` 60, `cache.py` 26 move to `dev/release/`. Runtime pieces stay: `reexec.py` 76 (to `app/run`,
  or deleted by R2), `catalog.py` 54 + `pins.py` 99 + `seams.py` 45 into one `app/plugins.py` that delegate resolution also uses (install
  lookup is written 4-5 times, H).
- **New shape.** `dev/release/` as named steps (gate, suite, bump, push, tag, publish, install), each `step(ctx) -> Result`; one lock
  helper; `dev/suite.py` and the release share one suite entry (two fallbacks today, H).
- **Size.** In: ~1,140 in src. Out: ~250 in src, ~700 in dev.
- **Risk.** Low for the factory (releases are run by the session, not by the loop), medium for the release path itself. Run one release
  through the moved code before deleting the old one.
- **Migration.** Move `tidy` (used by reconcile) and `Shell` (used by prune) out of release first, then move the rest.
- **First slice.** `app/plugins.py` with the one install lookup; `catalog`, `pins`, `seams`, `adapters/delegate.resolve` call it.
- **Bead.** *REWRITE-RELEASEOUT: release pipeline lives in dev/; one plugin-install lookup in src* / acceptance: `src/taskloop/app/release/`
  is gone; `installed_plugins.json` is parsed in one function.

### REWRITE-16. `tl.py` as one verb table; `cli/` parses and prints only

New (G24).

- **What is rewritten.** `skills/task-loop/tl.py` 460 (three lazy-load styles, dead `lazy`/`of_args`, 26 eager imports, docstring lists verbs
  that do not exist, H); `tl/cli/land.py` 45 and `land_stack.py` 89 (a run lifecycle written twice, H), `queue.py` 47 (mutates bd), `report.py`
  190 (reflect bookmark state), `wait.py` 91, `asks.py` 196 (`action_of` is a domain decision, H).
- **New shape.** `VERBS = {name: Verb(parser_fn, "module:func", audience)}`; one lazy import; `--help` generated from the table, so the
  docstring cannot drift. The direct-land and stack run lifecycle move into an app use case; `cli/` only parses and prints.
- **Size.** In: ~1,150. Out: ~800.
- **Risk.** Low. `tl actor` stops loading the app layer (H says it does today).
- **Migration.** Table first (no behaviour change), then move logic out of `cli/` file by file.
- **First slice.** The verb table with the existing handlers; delete `lazy`, `of_args`.
- **Bead.** *REWRITE-TLTABLE: one declarative verb table; cli without business logic* / acceptance: `tl --help` lists exactly the verbs in the
  table; `cli/land.py` and `cli/land_stack.py` call one app function.

### REWRITE-17. Delegate's run path over stream_proc with a typed Outcome and a side-effect-free decide

Agrees with Z19 (status writes nothing) and Z07's delegate half (one ladder). New: the supervisor and the in-call retry ladder.

- **What is rewritten.** `dg:app/supervisor.py` 258 (re-implements `stream_proc.run`, H), `launch.py` 260, `run.py` 278, `settle.py` 140,
  `decide.py` 177, `fleet.py` 163; the dict-key channel `hung_words`/`hung_kind`/`answered`/`started` (H).
- **New shape.** `decide(world) -> Decision` pure (writes returned as proposals; only `run` and owner verbs apply them). The run is a
  pipeline `lease → prepare → run(stream_proc with watcher callbacks) → classify → settle` with a typed `Outcome`. The in-call ladder
  (canary, network retry, schema re-ask) is an explicit list and is reported in `RunResult` (`attempts: [...]`), so task-loop can stop
  retrying what delegate already retried.
- **Size.** In: ~1,280. Out: ~850.
- **Risk.** Medium: every worker call goes through it. Delegate has its own tests and releases separately.
- **Migration.** `decide` pure first (= Z19), then `Outcome`, then the supervisor onto stream_proc, then `attempts` in the result.
- **First slice.** `RunResult.attempts` (additive field, task-loop ignores it), so the double-retry can be measured before anything else.
- **Bead.** *REWRITE-DGRUN: delegate run path on stream_proc; typed Outcome; attempts reported* / acceptance: `supervisor.py` has no own
  pump/timeout loop; one week of results shows how many task-loop retries followed an in-call delegate retry.

### REWRITE-18. Prompts as template files with goldens (small, but do it with REWRITE-07)

- **What is rewritten.** `tl/domain/prompts/` 435 (f-strings, `str.format` and `%` mixed, H), prompt prose inside logic modules
  (`review/findings.py`, `review/ledger.py:80-92`, `report/reflect.py:154-171`, H), numbers in prose that duplicate constants
  ("at most 8 per stage" vs `MAX_ANCHORS=8`, H).
- **New shape.** `skills/task-loop/prompts/*.md` with `string.Template` placeholders; one renderer; a golden per node; constants passed in.
- **Size.** In ~600, out ~350 py + the template files.
- **Risk.** Low with goldens; prompts change worker behaviour, so goldens must be byte-equal at the move.
- **First slice / bead.** *REWRITE-PROMPTS: prompts are template files with goldens* / acceptance: no prompt text longer than one line in
  `tl/domain/prompts/*.py`; every node has a golden.

---

## 3. UNSURE: yes/no questions for Denis

Each: the idea, what is rewritten, size, risk, my recommendation and why.

**Q-01. Authority in SQLite, or in CAS JSON files?**
Idea: R1 proposes one `factory.db` for jobs, attempts, reservations, waits, effects and loops. The alternative is REWRITE-04's CAS JSON
docs, with REWRITE-05's log for history. Rewritten: `locator.py`, `parks`, `loop/files.py`, `reexec`, slots marks, the effect ledger in
checkpoints (~1,200 lines). Risk: high (every state file), plus the dashboard and debugging with `cat` get worse. **Recommend yes, but
second:** do REWRITE-04 first, so the store layer is the only seam, and then SQLite is a backend swap behind `Doc`/`Log`. Without 04,
SQLite is a big bang.

**Q-02. Merge delegate into the task-loop repo as one plugin?** (= R4, ZOOMOUT-ONEPLUGIN.)
Idea: one repo, one version, one `_vendor`, one release; delegate stays its own package and skill. Rewritten: release pipeline, resolve and
pin logic, one vendor copy, the contract integer (~1,500 lines out, plus REWRITE-11 becomes an in-repo module). Risk: medium (history,
two CLAUDE.md, delegate's own users). **Recommend yes** if no one uses delegate without task-loop. Every cross-repo drift in this scan
(RS10) is a symptom of releasing apart.

**Q-03. Should delegate own all lane retries, and task-loop only wait for `retry_at`?**
Idea: today delegate retries in-call (canary, network, schema) and task-loop retries again by its own tables (`domain/lanes/retry.py`,
`policy.py`, `pauses.py`, 490 lines). Rewritten: `tl/domain/lanes/` down to ~150 lines (pin, caps, notes), `lane_acts.py` (201). Risk: medium;
some retries are engine-specific (`denied_secret` heredoc false positive, H: `denials.py`). **Recommend yes**, except for engine-made stops
(`producer: engine`, per Z07). Two retry layers multiply the cost of one failure.

**Q-04. Rewrite the 55.5k lines of tests at the new seams, deleting class-level tests as each rewrite lands?**
Idea: most tests are bound to `host` fakes and Protocol shapes that REWRITE-03/08 delete. Rewritten: ~327 test files over time. Risk:
high if done ahead; low if each rewrite bead moves its own tests to the new seam (transition tests, projection goldens, procsim). **Recommend
yes, per bead**, with a rule: a rewrite bead must not grow the test line count. No separate test-rewrite epic.

**Q-05. Replace prose-regex classification with structured worker answers where we control the schema?**
Idea: review findings, filing intent, gate proof, and "found wrong" are matched by ~50 regexes (H: `review/matchers.py` 28 patterns,
`report/matchers.py` 23). Add schema fields (kind enums) to the answers and delete the matchers that read our own workers' prose. Keep the
matchers that read vendor and tool output (checks, diagnostics, push). Rewritten: `domain/review/matchers.py` 223, parts of `findings.py`,
`answers.py`. Risk: medium; models fill enums worse than they write prose, so validation and send-back carry more. **Recommend yes, for
review only first**, measure send-back rates for a week.

**Q-06. Stop reading other tools' private state (OpenCode's sqlite, transcripts, delegate's history.jsonl)?**
Idea: `tl/adapters/opencode.py` reads `opencode.db`, `context_size.py` reads transcript tails, `app/report/planner.py:12,35` reads delegate's
`history.jsonl` (V). Delegate already knows context size and transcript refs; put them in `RunResult`, delete the readers. Rewritten:
~170 lines in task-loop, ~30 in delegate. Risk: low. CLAUDE.md already forbids it. **Recommend yes.**

**Q-07. Cut SKILL.md to the orchestrator procedure (~150 lines) and move the procedure into `tl` verbs?**
Idea: SKILL.md (674) mixes procedure, engine spec and reference; parts of the procedure (pick order, prune and lint steps, the triage table,
the stop sequence) could be one `tl next`/`tl stop` verb. It also contradicts itself on Touches (H: SKILL.md:348-351 vs :493-494).
Rewritten: SKILL.md, `docs/design`, a few verbs. Risk: medium; the session's behaviour changes with the text. **Recommend yes**, after
REWRITE-16 (so the verb table can render the reference part).

**Q-08. Drop the per-step Protocols entirely and use concrete dataclasses of ports?**
Idea: REWRITE-03 keeps a few Protocols for ports. This goes further: steps take a frozen dataclass of concrete port types; fakes subclass
or are the same classes over memory. Rewritten: the 111 Protocols in `tl/app` (V). Risk: low runtime, some loss of structural typing for
fakes. **Recommend yes**: the Protocols today describe the locator, not a boundary.

**Q-09. Share one read-only shell classifier between delegate and task-loop?**
Idea: `tl/domain/lanes/matchers.py` (118) and `dg:domain/policy/shell.py` (109) + `matchers.py` (137) classify read-only commands with
different allowlists and pipe rules (H). One shelf module. Risk: medium, it is a sandbox boundary; the stricter rule must win.
**Recommend yes, via shelf**, with task-loop's "no operators" as the default and delegate's pipes behind a flag.

**Q-10. Delete hot reload mid-bead (`reload.py`, `reexec.py`, TL_REEXEC)?** (= Z05/R2, FREEZEBUNDLE.)
I list it because REWRITE-08 is much smaller without it: `reload.py` (124), `release/reexec.py` (76), the hand-over in `engine_lock.py`
and `loop/run.py`. **Recommend yes**; a fix waits for the bead to finish.

**Q-11. Make the dashboard JS a pure renderer (no derivation, no 1 s global re-render)?**
Idea: after REWRITE-06 the page gets every derived field; replace the global mutable `ui` and the 1 s tick with a small store and
per-view subscriptions (H: `app.js:23-32`, `state.js:19-37`). Rewritten: ~2,800 lines of static, out ~1,800. Risk: low for the factory.
**Recommend yes, but after REWRITE-06**; doing it first just moves the derivation around.

**Q-12. Table-driven harnesses in delegate?**
Idea: codex, claude and opencode harnesses repeat one shape (H: `_s`/`_dict` x3, `ARG_KEYS` x2). Rewritten: `dg:adapters/harness/` 1,171. Risk:
medium. **Recommend no for the parsers, yes for the spec** (argv template, transcript locator, login probe, tool set as a record): the
event streams really differ, and a generic parser would be a worse parser.

**Q-13. Delete `tl report`'s planner section and the reflect digest's auto-filing, or keep them as a loop chore?**
Idea: `app/report/reflect.py` (247) schedules, locks, spawns, clusters and files beads; its lock is released before the spawn (H:
`reflect.py:236-240`). `planner.py` (64) reads delegate's private file (V). Rewritten: ~310 lines. Risk: low. **Recommend: delete planner.py,
keep reflect** as a pure `cluster(traces) -> list[BeadDraft]` plus a loop chore that files them; I cannot tell from code whether its beads
are useful (see 4).

**Q-14. msgspec in delegate too, for the shared wire package?**
Idea: REWRITE-11 needs one codec. task-loop uses msgspec (PEP 723 dep); delegate has a hand-written stdlib codec (229 lines). Risk: delegate
gains a dependency at a boundary that runs on every worker call. **Recommend yes** if delegate already runs under `uv run --script` (I did
not check its launcher); otherwise keep delegate's codec as the shared one and drop msgspec from the wire records only.

**Q-15. Remove the `look`/owner-look gallery path from the engine into its own slice package?**
Idea: `app/look` (694) + `app/asks/looks.py` (129) + `adapters/looks.py` (217) + `domain/look` hold Unity screenshot logic, gallery items as
plain dicts, and dashboard URL strings (H: `owner_look.py:73,126`). One `look/` package with its own record types. Risk: low. **Recommend
yes, low priority**; it is the most product-specific code in a generic engine.

---

## 4. What I could not learn

- **Runtime truth.** Nothing was run. The suspected bugs in REWRITE-12 (env key mismatch), REWRITE-14 (stick order, whole-metadata write),
  G02 (interrupted call without a sessions row) and G04 (`reload.py:105` order) are Haiku readings I did not re-open. Each needs one test
  before anyone believes it.
- **Which code paths actually run on Trust Night.** I cannot tell from source how often hot reload, `land-stack`, look rounds, reflect
  digest or the OpenCode lane fire. A week of engine logs, counted by step and Kind, would let you delete what never fires before rewriting it.
- **Churn per module.** I counted commits (1,183 since Oct 1) but did not map them to files. The modules with the most churn are the best
  rewrite candidates; `git log --stat` per directory would rank 01-18 better than my judgement.
- **Test coupling.** I know the test volume (55.5k lines, 327 files) but not how many tests construct `Engine` or a host fake. That number
  decides the true cost of REWRITE-03/08 and Q-04.
- **Haiku accuracy.** Haiku readers get line numbers wrong at a few percent. I re-opened about 25 claims; all held except one detail
  (G14 said `check_round.py:87` bumps `rounds +=`; my grep found the pattern only in `write_round.py:100` and `review_round.py:182`). Treat
  every (H) as a lead. Two process notes: one Haiku made and deleted a `/tmp` scratch file; one attempted a session tool call that was denied.
- **Delegate's launcher and dependencies** (Q-14), and whether anyone uses delegate without task-loop (Q-02).
- **Whether the reflect digest's filed beads were ever useful** (Q-13): that needs bd history, not code.
- **The dashboard JS line estimates** in REWRITE-06/Q-11 are Haiku estimates, not counts of removable lines.
