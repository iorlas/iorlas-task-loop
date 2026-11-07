# Zoom-out review: what the three diagrams say about the factory

Read from `c4-system.md` (combined), `c4-task-loop.md`, `c4-delegate.md`, and the reviews in `docs/review/` (A = architecture.md,
D = dataflow.md, encapsulation lenses M/C/F/L/LF/I, extraction lenses and synthesis, dashboard-backend = DB). 2026-11-01, task-loop
0.23.299 in this worktree, delegate 0.55.0 in `/home/iorlas/Workspaces/wt/UNITYD` (IN-FLIGHT `--exec-allow` included). Static reading; nothing
run. Every file:line below was opened again for this review unless marked **(unverified)**. Path prefixes as in `c4-system.md`
(`tl/`, `dash/`, `dg:`). Extraction candidates and existing slices are named by id, not repeated.

---

## 1. The shape, in ten lines

1. Two plugins that are always installed together and released apart, joined by a subprocess contract that both sides bypass.
2. The center of gravity is not the engine but `~/.config/task-loop`: 40-odd file families, a dozen with more than one writer, no transaction.
3. Authority is duplicated on every axis that matters: two delivery judges, three profile readers, two stop-reason deciders, two claim takers.
4. The trust line is drawn at the sandbox, and then pierced on purpose: the engine lock in the writer's tree, `--exec-allow`, Codex escalations.
5. Fail-open survives at the edges that were just hardened (hook catch-all, push profile, fence on bd outage).
6. Two machines run the factory, but the design is single-machine: bd claims, locks, caffeinate, resource leases are all host-local.
7. A release reaches running code through three independent hop points, none of which negotiates with the others.
8. The dashboard is drawn as a reader and wired as a writer with the engine's own ports loaded at runtime.
9. Delegate is a clean pure-core router wrapped in an app layer whose "read" verbs write the owner's config.
10. The import rules hold and prove little: effects live in the bottom layer of both apps and the engine is a service locator.

---

## 2. Findings

Order: findings two or more inputs agree on come first (Z01-Z09), then single-source and new ones. Each has: evidence, kind, severity,
proposal, verdict, effort, order.

### Z01. Two delivery judges, and the one on the engine's own push uses the evidence it says must never authorize

- **Evidence:** `tl/app/land/push_judge.py:71-75` calls `green_result`; `tl/app/checks/cache.py:263-265` "Historical display evidence;
  this ID-only query must never authorize delivery". `land-stack` uses the full key (`tl/app/land/stackgate.py:36`). Agreed by c4-task-loop
  item 1, M04, LF01/LF02. CHECKIDENT (0.23.293, "gate evidence is keyed by the full check identity") left this call in place: identical
  in the main checkout.
- **Kind:** duplicated responsibility; doc-code mismatch. **Severity: P1** (the pre-push is the path every engine push goes through,
  `tl/adapters/childenv.py:56-64`).
- **Proposal:** `PushJudge.green` calls `authorization.results` with the executed `CheckKey`, exactly as `stackgate` does; then delete
  `green_result`'s boolean wrapper (`cache.py:255`) or rename it `display_green` and ban it from `land/` with an import-linter contract.
- **Verdict:** ✅ do. A one-call fix that closes CHECKIDENT. Test: a host receipt for a container-required check must not let a push pass.
- **Effort:** S. **Order:** first; Z02 touches the same file.

### Z02. The push judge reads the candidate's own profile, and an empty gate means "allow"

- **Evidence:** `push_profile` reads `<repo>/.task-loop.json` from the working tree (`tl/app/land/push_judge.py:49-58`);
  `if not tips or not cfg.gate_checks: ALLOWED` (`:103-104`). Loop and engine read the profile committed on the base
  (`tl/app/wire/slots.py:42-68`); delivery authorization reads the judged tree's copy (`tl/app/checks/authorization.py:17-19`).
  Agreed by c4-task-loop item 2, LF03 (slice GATESELECT, not done), A.F05, D.F10.
- **Kind:** security-boundary weakness; state with several readers of one authority. **Severity: P1.** A writer that commits
  `"gate_checks": []` in its candidate controls the judge of its own push.
- **Proposal:** the judge resolves the profile at the base it judges against (`base_for(tip)`) through the same reader as the loop, never
  the working tree; a candidate that changes `.task-loop.json` is judged by the base's gate, and the change itself needs the owner label.
- **Verdict:** ✅ do (this is GATESELECT; do it now, with Z01). **Effort:** S. **Order:** after Z01, before Z05.

### Z03. The githook path still fails open on any exception it did not expect

- **Evidence:** `tl/hook/main.py:12-23` wraps the `githook` branch, including `importlib.import_module("taskloop.hook.prepush")`, in
  `except Exception: return 0`; `prepush.entry` catches only `(OSError, ValueError, SubprocessError)` (`tl/hook/prepush.py:22`), `githook`
  the same (`:67`). An `ImportError` (broken install, partial cache dir) or a `TypeError` returns 0 = push allowed, against
  `prepush.py:1-2`. Agreed by c4-task-loop item 17 and L02 (HOOKPUSH, 0.23.292, did not move this catch).
- **Kind:** security-boundary weakness; doc-code mismatch. **Severity: P1.**
- **Proposal:** dispatch `githook` before the `try`; inside `githook`, `except BaseException: return 1` when `name == "pre-push"`. Keep
  exit 0 on failure only for `pretool`, `session-start`, `precompact`.
- **Verdict:** ✅ do. Test: make `taskloop.hook.prepush` unimportable and assert exit 1. **Effort:** S. **Order:** independent; wave 1.

### Z04. Run manifests, parks, loop state and landed receipts each have several writers and no compare-and-set

- **Evidence:** every `RunLocator` method is get-then-put with no lock (`tl/contracts/locator.py:104-177`), written by the engine and by
  `mark_lost` from loop start, `tl wait`, `tl doctor`, `tl report` and the owner-request gate reachable from the dashboard (c4-task-loop
  item 4). Parks: engine close and loop profile-ahead read-modify-write through an unlocked `JsonStore` (`tl/app/loop/take.py:81-86`,
  `tl/contracts/parks.py:42-46`). Loop state: factory placeholder plus child plus a renaming reader (`tl/app/loop/factory.py:67-70`,
  `tl/app/loop/files.py:59-61`). Landed: engine and `tl land` (`tl/cli/land.py:31`). Agreed by c4-task-loop items 4, 5, 9; A state table;
  A.F11; D "Lost run"; I "Storage".
- **Kind:** state with several writers. **Severity: P1** (a `beat` racing `mark_lost` buries a live run; a stale park wake wins).
- **Proposal:** give `JsonStore` a `revision` field and `update(fn, expected_revision)` under a per-document flock (the vendored
  `process_lock` already exists); move `mark_lost` behind the same lock with "only if heartbeat unchanged". This is the first step of R1,
  not the end state.
- **Verdict:** ✅ do. Test: two processes `beat` and `mark_lost` interleaved at the get/put gap (procsim). **Effort:** M.
  **Order:** before R1 and Z16; independent of Z01-Z03.

### Z05. A release reaches running work through three hop points that never agree on a bundle

- **Evidence:** loop `maybe_move` between beads (`tl/app/loop/versions.py:1-6`, `tl/app/loop/loop.py:353-369`), engine `safe_point` inside a
  bead (`tl/app/run/reload.py:68-119`), delegate re-resolved before every call (`tl/app/run/delegation.py:11-27`). The handover records
  counters and versions, not a schema range (A.F04); the loop's "pid stays" comment is false under `uv run` (A.F06); a contract-3 pair can
  disagree on flags (A.F08, F01). I.F01 calls the mid-bead hop the wrong product feature; the encapsulation synthesis parks it as
  FREEZEBUNDLE, an owner decision; summary HOPSAFE repairs it instead.
- **Kind:** missing seam (no admitted bundle); hard-to-draw smell (flow b has three unsynchronized arrows). **Severity: P1.**
- **Proposal:** admit each job with `(engine_dir, delegate_dir, profile_commit)` written into the manifest; every engine call and every
  delegate call of that job uses those dirs; only the loop moves, and only between jobs. Keep `pin`/`rollback`/`bad-versions`.
- **Verdict:** ❓ owner decision, recommended ✅. What would test it: a week of Trust Night logs counting hops that happened mid-bead and
  the failures attributed to them (incidents 2, 3, 9, 10 per A and D). If mid-bead hops delivered nothing a between-bead move would not, delete.
- **Effort:** M (freeze) then S (delete reload). **Order:** after Z12 (so the frozen pair is checked once at admission). See R2.

### Z06. bd claims are exclusive per machine, not per factory

- **Evidence:** the only Dolt traffic of the app is `bd sync` after a land and in `land-stack` (`tl/app/land/outbound.py:134-152`,
  `tl/app/land/stack.py:217`); no pull happens before `bd ready` or the claim (grep of `tl/app`). The land already handles "another machine
  ran this bead" for task branches (`outbound.py:126-128`). The Mac dashboard files factory beads into the registered repo named
  `iorlas-task-loop` (`tl/app/launch/dash_ports.py:57-63`) while devbox sessions work that same repo's beads. D notes "another claim can
  invalidate" the queue; A.F03 treats the claim as the ownership token. bd's own background sync, if any: **(unverified)**.
- **Kind:** missing seam; state with several writers (two Dolt DBs, one remote). **Severity: P1** if both machines ever loop on one repo,
  P2 otherwise (duplicate work, Dolt merge conflicts that block a landed bead with FAULT_LAND).
- **Proposal:** declare repo ownership per machine (`host.json` gains `repos: [...]`; the loop refuses to start on a repo another host owns,
  read from a committed `factory.json` or a bd label); for shared repos, `bd sync` before the claim and immediately after, and treat a claim
  conflict after sync as a lost claim.
- **Verdict:** ❓ untested. Test: two clones with one Dolt remote, claim the same bead on both, `bd sync` both; observe whether bd refuses
  or merges two assignees. **Effort:** M. **Order:** test first; interacts with FENCE (A.F03): a fence that fails open on bd outage is worse
  across machines.

### Z07. Nobody owns the stop reason

- **Evidence:** delegate decides a reason in four places (`dg:adapters/harness/classify.py:29-74`, `dg:app/settle.py:64-70`,
  `dg:app/launch.py:247-251`, `dg:app/run.py:188-257`) while calling `classify` "the one outcome ladder" (`classify.py:1`). task-loop
  synthesizes its own stop with its own scope and permanence (`tl/adapters/delegate.py:197-205`), rewrites a reviewer timeout to a lane
  overrun (D, Delegate boundary), and decides permanence again in `domain/lanes/policy.py`, `domain/lanes/pauses.py`, `app/asks/parks.py`,
  `app/loop/settle.py` (A.F07). Agreed by c4-delegate item 7, A.F07, LF10, L08, D.
- **Kind:** duplicated responsibility (across the app boundary). **Severity: P2** (owner-required stops retried on a timer: A.F07).
- **Proposal:** delegate's `RunResult.stop` is the cause and is never rewritten downstream; task-loop's synthesized stops carry
  `producer: "engine"`; one task-loop table maps `(producer, reason)` to one durable `Park` wake; delete the role/timer fallback in
  `settle.py:94`. Delegate merges its four sites into `classify` plus one `Settle` input.
- **Verdict:** ✅ do. **Effort:** M (two repos). **Order:** after Z04 (Park writes must be safe first); before R1.

### Z08. The dashboard is a writer that every document calls a reader

- **Evidence:** nine POST verbs (`dash/api/writes.py:73-168`); the process imports `taskloop.app.launch.dash_ports` by name at runtime
  (`tl/app/launch/dash.py:147`), which reaches `Intake`, owner requests and through them `runlife.reconcile` (`tl/app/run/requests.py:45-50`);
  the answer port still carries no ask id (`tl/app/launch/dash_ports.py:50-54`); factory beads go to a repo found by folder name
  (`:57-63`). `CLAUDE.md` and `README.md:65` say read-only. The browser checks now exist (`dash/http.py:40-52`; DB F09 is fixed), but any
  tailnet peer gets every write. Agreed by c4-task-loop item 11, A.F09, L10, DB F04/F05.
- **Kind:** doc-code mismatch; coupling; security-boundary weakness (tailnet). **Severity: P2.**
- **Proposal:** the dashboard executes owner commands by spawning `tl <verb> --expect <id>` (the same writer surface as the CLI) and
  imports no engine code; GET handlers get read-only query objects (L10's `DashQueries`). Carry the ask id; replace `FACTORY_REPO` by a
  `repos.json` role. Say "read-mostly, nine owner verbs" in the docs.
- **Verdict:** ✅ do. **Effort:** M. **Order:** after Z04 (commands then go through locked transitions).

### Z09. "Only the contract is shared" is false in both directions

- **Evidence:** task-loop calls `contract --json` (`tl/adapters/delegate_route.py:49`) and `net` (`tl/adapters/delegate.py:164`), reads
  delegate's `contract.json` (`:93`, `:104`) and its `history.jsonl` by a hard-coded path (`tl/app/report/planner.py:12`, `:35`, new here),
  runs `route.py` under its own `sys.executable` (`:140`, `:164`, `:194`). Delegate's OpenCode read steps may read task-loop's `runs/`
  (`dg:adapters/harness/opencode_sandbox.py:22-24`), against its own `docs/dev/integrations.md:151`. Agreed by c4-task-loop
  (mismatches), c4-delegate items 9 and 12.
- **Kind:** coupling; doc-code mismatch. **Severity: P2.**
- **Proposal:** write the actual list into worker-run v3: `contract --json`, `run`, `status --json`, `status --claude-usage`, `net`; delete
  the `contract.json` file read (use `contract --json`, already called); move the planner report onto a `status --history` field or delete
  the report; delegate drops `readable_outside`.
- **Verdict:** ✅ do. **Effort:** S. **Order:** before Z12 (the capability check reads `contract --json`).

### Z10. agent-runs v1 is a public contract with no consumer and no spec

- **Evidence:** delegate writes `~/.config/agent-runs/` "for the dashboard" and calls it public (delegate `README.md:46`,
  `docs/dev/integrations.md:10-12`), and deletes any producer's file older than 7 days (`dg:adapters/agent_runs.py:38-44`). task-loop has no
  reader (grep of `src/`: only a test fixture path in `tests/adapters/test_opencode.py:97`) and `docs/contracts/` holds no agent-runs spec.
- **Kind:** doc-code mismatch; dead seam. **Severity: P3.**
- **Proposal:** delete `adapters/agent_runs.py` and its calls; delegate's own doc says this breaks nothing (`docs/dev/integrations.md:147`).
- **Verdict:** ✅ do. **Effort:** S. **Order:** any time; removes delegate code before extraction B2 counts it.

### Z11. IN-FLIGHT `--exec-allow` lets the writer run its own edited code outside the sandbox with no reviewer

- **Evidence:** `prefix_rule(..., decision="allow")` with `--ignore-rules` dropped (`dg:app/codex_policy.py:11-14`, `dg:app/decide.py:93-100`);
  first-token blocklist without `nice`, `timeout`, `command`, `uv`, `npx`, `make`, `just` itself (`dg:cli/parser.py:66`); engine-only
  conflict checks only `prefix[1]` (`:46`), so `["just","-f","x","slow"]` passes; the overlay symlinks the real `auth.json` and is never
  cleaned (`codex_policy.py:28-36`). Delegate's constitution: "A fixed-command whitelist does not bound a build tool that runs repo code"
  (`docs/dev/constitution.md:24`). c4-delegate items 4 and 5. task-loop sends no `--exec-allow` yet (grep).
- **Kind:** security-boundary weakness. **Severity: P1** once a caller uses it.
- **Proposal:** do not let the writer escape. The engine already runs checks on the host after each write (`tl/app/write/check_round.py:1`);
  add a structured "run this declared engine command" request in the writer's answer, run it in the check round, feed the result to
  the next write. If an escape is kept, it must be Mac-only, a declared profile list (not caller argv), and still model-reviewed.
- **Verdict:** ❌ refuse as designed: it re-opens the exact hole the constitution names, to save one write round. **Effort:** M for the
  engine-side alternative. **Order:** before any task-loop caller is written.

### Z12. Flag compatibility is not checked though delegate already advertises it

- **Evidence:** `resolve` compares only the contract integer (`tl/adapters/delegate.py:105-113`); `contract --json` returns
  `{contract, reasons, run_args}` (`dg:cli/verbs.py:89-92`); a flag an older parser does not know `sys.exit`s with text
  (`dg:cli/parser.py:58-69`), which task-loop turns into a synthesized stop. A.F08, F01, slice DELEGATECAP.
- **Kind:** missing seam. **Severity: P2.**
- **Proposal:** at resolve, read `run_args` and refuse (owner pause, machine scope) any request flag not listed; record the admitted pair in
  the manifest (feeds Z05).
- **Verdict:** ✅ do. **Effort:** S. **Order:** after Z09, before Z05.

### Z13. Delegate is found by two rules and may change between calls of one job

- **Evidence:** `resolve` = explicit, pin, `installed_plugins.json`, else refuse (`tl/adapters/delegate.py:88-113`); `find_route` adds a
  newest-in-cache fallback (`:116-129`); which callers use which: **(unverified)**. D "Plugin update mid-run": a route kept after a refused
  new install may point at a removed dir.
- **Kind:** duplicated responsibility. **Severity: P2.**
- **Proposal:** one function, no cache fallback; the job's admitted delegate dir (Z05) is the only path used afterwards.
- **Verdict:** ✅ do. **Effort:** S. **Order:** with Z05.

### Z14. The shim and git hooks point at whichever install wrote them last

- **Evidence:** every SessionStart and `tl hooks install` rewrite `<config>/bin/tl` and the 14 hooks for their own plugin root
  (`tl/app/doctor/install.py:34-77`, `tl/hook/session.py:75-77`), with a non-atomic `write_text` (`doctor/install.py:40-42`); the pre-push runs
  `<config>/bin/tl judge-push` (`:64`). An engine of install X is judged by install Y; on the Mac, the shim moves only when a Claude
  session starts there. c4-task-loop item 3.
- **Kind:** state with several writers; coupling. **Severity: P2.**
- **Proposal:** the engine passes its own `tl.py` path to its children (`childenv` already injects `core.hooksPath`; add
  `TASK\_LOOP\_TL`); the dispatcher prefers it and falls back to the shim; write the shim with `atomic_io`.
- **Verdict:** ✅ do. **Effort:** S. **Order:** with Z01-Z03 (one push-path release).

### Z15. The engine's lock lives in the writer's directory

- **Evidence:** `.task/engine.lock`, `.task/engine.take` under the worktree (`tl/contracts/paths.py:274-281`); Codex write steps get
  `UV_CACHE_DIR=.task/uv-cache` there too (`dg:app/decide.py:35-36`); run records were moved out "where no worker can write them"
  (`tl/app/run/layout.py:1-4`), the lock was not. c4-task-loop item 7 and its trust table.
- **Kind:** security-boundary weakness (cooperative). **Severity: P2.**
- **Proposal:** `<config>/locks/engine-<worktree-key>.lock` with the same holder record; `.task/` keeps only scratch.
- **Verdict:** ✅ do. **Effort:** S. **Order:** before Z04's CAS work touches lock records; uses Z18's key.

### Z16. The engine is a service locator, so the component diagram needs dotted arrows

- **Evidence:** every part is a `cached_property` built over the engine (`tl/app/run/engine.py:190-200`), takes `host: Any`
  (`tl/app/run/state.py:108`, `worker_call.py:84`), and `carries_state` installs writable aliases of every `RunState` field
  (`state.py:98-101`); `entry.py` types almost everything `Any`. c4-task-loop item 10, A.F12, C01/C02/C05, M R1, slice ENGINESPLIT.
- **Kind:** coupling; hard-to-draw smell. **Severity: P2.**
- **Proposal:** see R5. First cut: delete `carries_state`; parts receive the two or three collaborators they use.
- **Verdict:** ✅ do, after Z04. **Effort:** L. **Order:** wave 3.

### Z17. Both apps put effects in the layer they call "contracts"

- **Evidence:** task-loop `contracts/stores.py:80-121` (files), `fence.py:71-78` (bd), `runlife.py:64-75` (reconcile), `guard.py:1-13` (flock);
  delegate `contracts/stores.py:6-37` (files, locks, stderr), `contracts/stops.py:14` (reads a file at import). c4-task-loop item 12,
  c4-delegate "Dependency direction", A.F12, L04.
- **Kind:** dependency-direction violation (by effect, not by import). **Severity: P3.**
- **Proposal:** one `stores` layer per app above `contracts`; the same split in both apps lets extraction #5 (typed-json) and #6 (jsonl-log)
  take pure records only.
- **Verdict:** ✅ do. **Effort:** M. **Order:** after Z04 (the CAS store is the new home).

### Z18. Four repo keys

- **Evidence:** `ids.loop_key` (folder + sha1(path)[:8], `tl/contracts/ids.py:117-119`), `ids.repo_key` (sha1(common dir)[:12], `:112-114`),
  `check_files.repo_key` (origin name + sha1[:10], `tl/adapters/check_files.py:44-50`), `shared.py` by hand (`packages/slots/src/tlslots/shared.py:29`); the
  dashboard copies `loop_key` (`dash/readers/loops.py:7-9`). c4-task-loop item 6, M09, D.
- **Kind:** duplicated responsibility. **Severity: P2.**
- **Proposal:** one `RepoId(origin_url, common_dir)` in contracts with named projections; every file family keys by one of them, chosen in
  `paths.py` only (the slice REPOID).
- **Verdict:** ✅ do. **Effort:** S-M. **Order:** before Z15 and R1.

### Z19. task-loop's status poll changes the owner's delegate config

- **Evidence:** `status` and `next` run `FleetBuilder.build`, which sets an undecided ready lane to `enabled` in `config.json`
  (`dg:app/fleet.py:68-70`), records `offered`, saves the checkpoint, pops out marks (c4-delegate item 2). task-loop calls `status --json`
  from loop chores every 20 minutes (`tl/app/launch/loop.py:155`).
- **Kind:** state with several writers (across apps). **Severity: P2.** A lane the owner never decided on is enabled by a background poll.
- **Proposal:** `build` returns proposed writes; only `run` and owner verbs apply them; `status` reports "would enable".
- **Verdict:** ✅ do (delegate). **Effort:** S. **Order:** independent.

### Z20. One machine-wide delegate lock under N factory lanes, and its losses are silent

- **Evidence:** `state.json` lock 10 s, timeout answers `lock` (`dg:contracts/stores.py:26-37`, `dg:app/run.py:51-55`); reaping runs under it
  (M10); `HistoryStore.add` swallows every exception, the lock timeout included, and history is the breaker's only input
  (`dg:contracts/stores.py:110-116`). Mac factory: N lanes plus status polls plus the orchestrator.
- **Kind:** state contention; missing seam. **Severity: P2.**
- **Proposal:** history appends outside the state lock with its own short lock and a counted, logged failure; reap outside the lock (M10).
- **Verdict:** ❓ untested. Test: 4 lanes plus a 1 s `status --cheap` loop for an hour; count `lock` answers and missing `RunRow`s
  against the live files. **Effort:** M. **Order:** independent; data first.

### Z21. Nothing in the code delivers a release to the Mac

- **Evidence:** the release updates the marketplace and the plugin on the machine that runs it (`tl/app/release/publish.py:74-94`); the loop
  only reads `installed_plugins.json` (`tl/app/release/catalog.py:30-42`). How the Mac's Claude Code refreshes its marketplace: **(unverified)**.
- **Kind:** missing seam. **Severity: P2** (a fix released on devbox may not run in Trust Night; the owner cannot tell from the dashboard).
- **Proposal:** a loop chore compares the marketplace tag on GitHub (`git ls-remote`) with the installed version and shows "N behind" on the
  dashboard; an owner verb `tl factory update` runs the two `claude plugin` commands on that machine.
- **Verdict:** ❓ untested. Test: release from devbox, then read the Mac's `installed_plugins.json` an hour later with no Claude session
  started. **Effort:** S. **Order:** wave 1 test, wave 2 fix.

### Z22. "Lane" means three things, and the Mac keeps only lane 1 awake

- **Evidence:** loop lanes (`tl/app/loop/factory.py:58-66`), delegate subscription lanes (`dg:domain/lanes/lane.py:85-91`), check lanes
  (`tl/contracts/config.py:340`); `caffeinate -i -w` watches `children[0]` only (`tl/app/loop/factory.py:116-119`, c4-task-loop item 16).
- **Kind:** hard-to-draw smell; bug. **Severity: P2** (macOS idle sleep pauses the other lanes' Unity builds).
- **Proposal:** one `caffeinate -w` per child; rename factory lanes "loops" in logs, CLI and dashboard.
- **Verdict:** ✅ do. **Effort:** S. **Order:** wave 1.

### Z23. The two apps vendor different shelf versions

- **Evidence:** task-loop `dev/vendor.json` has stream-proc v0.2.2, delegate's has v0.2.1; `stream_proc/hold.py` differs (task-loop holds
  SIGTERM and SIGINT, delegate SIGTERM only); package sets differ (git_porcelain, static_page_check vs app_dirs, timefmt); vendor dirs are
  appended to `sys.path`, so an installed same-name module wins (extraction-shelf-reuse, `src/taskloop/__init__.py:11-13`).
- **Kind:** dependency drift. **Severity: P3.** A Ctrl-C during a delegate spawn can still orphan a worker.
- **Proposal:** prepend, not append, the vendor dir; one `shelf.lock` file both gates compare against the shelf's latest tags. D0
  (extraction #1) is the long answer; see R4.
- **Verdict:** ✅ do. **Effort:** S. **Order:** before extraction #3 (stream_proc.testing) lands in both.

### Z24. Worker git and secret guards depend on the lane

- **Evidence:** Claude write steps get `git_write` through the hook, Codex and OpenCode none, only the after-the-fact HEAD/branch compare
  (`dg:adapters/git.py:20-36`); `git_write` misses `-c k=v`, `FOO=1 git push`, `env git push` (`dg:domain/policy/shell.py:21-41`); secret
  hits stop Codex after the command started, OpenCode after it ended (c4-delegate items 10, 11; M06). Codex has no network, so a push
  needs an approved escalation **(unverified)**.
- **Kind:** security-boundary weakness. **Severity: P2.**
- **Proposal:** delegate sets `GIT_CONFIG_COUNT` in every worker env with `remote.pushDefault` unset and `url.<x>.pushInsteadOf` to a refusing
  URL; push protection then holds for all lanes without parsing shell. Fix `git_args` for `-c` and wrappers for the Claude diagnostics.
- **Verdict:** ✅ do. **Effort:** S. **Order:** independent.

### Z25. Recursion guard is prose

- **Evidence:** `DELEGATE_DEPTH=1` set for every worker (`dg:app/env.py:176`), read only by `SKILL.md:6`; Codex sub-agents cannot be turned
  off (`dg:app/decide.py:65-68`). c4-delegate item 16.
- **Kind:** missing seam. **Severity: P3.**
- **Proposal:** `route.py run` refuses with `caller` when `DELEGATE_DEPTH` is set.
- **Verdict:** ✅ do. **Effort:** S. **Order:** any.

### Z26. Docs that contradict the code (bulk)

- **Evidence:** c4-task-loop "Docs that are stale" (11 rows) and c4-delegate item 17 (7 rows), plus: `CLAUDE.md` "worker-run v1" vs contract 3;
  `CLAUDE.md` "the dashboard server only reads"; `integrations.md:60-67` "three places only"; delegate README pointing at a
  task-loop agent-runs spec that does not exist (Z10).
- **Kind:** doc-code mismatch. **Severity: P3.** These docs are what agents read first (CLAUDE.md is loaded into every session).
- **Proposal:** one pass per repo; add a rule test that `CLAUDE.md`'s contract version equals `delegate_wire.CONTRACT`.
- **Verdict:** ✅ do. **Effort:** S. **Order:** last in wave 1, after Z09 and Z10 settle the real contract.

---

## 3. Ranking and sequence

Score = risk removed / effort, with P1 = 3, P2 = 2, P3 = 1 and S = 1, M = 3, L = 8. Ties broken by how many inputs agree.

| Rank | Finding | Sev | Effort | Score | Inputs agreeing |
|---:|---|---|---|---:|---:|
| 1 | Z01 push judge on full-key evidence | P1 | S | 3.0 | 4 |
| 2 | Z02 push judge reads base profile | P1 | S | 3.0 | 4 |
| 3 | Z03 githook fails closed | P1 | S | 3.0 | 2 |
| 4 | Z12 check `run_args` at resolve | P2 | S | 2.0 | 3 |
| 5 | Z09 write the real contract list | P2 | S | 2.0 | 3 |
| 6 | Z14 engine passes its own tl to the hook | P2 | S | 2.0 | 1 |
| 7 | Z15 engine lock out of the worktree | P2 | S | 2.0 | 2 |
| 8 | Z19 status writes nothing | P2 | S | 2.0 | 1 |
| 9 | Z22 caffeinate per lane, rename lanes | P2 | S | 2.0 | 1 |
| 10 | Z24 push barrier for every worker | P2 | S | 2.0 | 2 |
| 11 | Z13 one delegate lookup | P2 | S | 2.0 | 2 |
| 12 | Z21 Mac release delivery (test first) | P2 | S | 2.0 | 0 (new) |
| 13 | Z04 CAS for manifests, parks, loop state, landed | P1 | M | 1.0 | 5 |
| 14 | Z05 freeze the job bundle | P1 | M | 1.0 | 6 |
| 15 | Z06 one factory per repo (test first) | P1 | M | 1.0 | 1 |
| 16 | Z11 refuse exec-allow, engine-run command instead | P1 | M | 1.0 | 2 |
| 17 | Z10, Z23, Z25, Z26 | P3 | S | 1.0 | 1-2 |
| 18 | Z18 one RepoId | P2 | S-M | 1.0 | 3 |
| 19 | Z07 one stop authority | P2 | M | 0.7 | 5 |
| 20 | Z08 dashboard commands through tl | P2 | M | 0.7 | 4 |
| 21 | Z20 delegate lock contention (test first) | P2 | M | 0.7 | 2 |
| 22 | Z17 effects out of contracts | P3 | M | 0.3 | 4 |
| 23 | Z16 engine without service locator | P2 | L | 0.25 | 5 |

**Wave 1, the push path and the boundary (one week, S items, two releases).** Release 1 (task-loop, announced: it touches push):
Z01, Z02, Z03, Z14. Release 2 (task-loop): Z09, Z12, Z13, Z15, Z22. Delegate release: Z19, Z24, Z25, Z10, and the decision to not merge
Z11 as written. Doc pass Z26. Run the two tests Z06 and Z21 and file what they show.

**Wave 2, state you can trust (M items).** Z18 (keys), then Z04 (CAS store), then Z07 (stop authority over safe Parks), Z08 (dashboard
commands), Z11 alternative (engine-run command), Z06 fix if the test found a collision, Z21 fix, Z20 after its measurement.
FENCE (A.F03) and PIDIDENT (A.F11) belong here too; they need Z04's CAS.

**Wave 3, rethinks (owner decisions first).** Z05 / R2 (freeze or delete the mid-job hop: owner's FREEZEBUNDLE call), R1 (one execution
store), Z16 / R5 (engine without locator), Z17, R4 (distribution). Extraction #2 (git-porcelain) waits for R1, because cleanup and land
semantics move with it; extraction #3, #4, #7 can run in parallel with any wave.

---

## 4. Rethink

Five places where the diagrams suggest a different design rather than a fix.

### R1. One authoritative execution store instead of fifteen file families

Today a run's truth is spread over `runs/R/manifest.json`, `checkpoints/B.json`, `B.call.json`, `parks/`, `pauses/`, `reexec/`, `landed/`,
`followups/`, `loop/K.<pid>.json`, `loop/K.command.json`, `K-rest.json`, `slots/K/`, `worktrees/K/`, `.task/engine.lock`, owner requests, each
with its own writer set (c4-system Level 3). Alternative:
- One SQLite file `C/factory.db` (stdlib `sqlite3`, WAL, one writer connection per process, `BEGIN IMMEDIATE`).
- Tables: `job(id, bead, bundle, profile_commit)`, `attempt(id, job, host, pid, start_id, heartbeat, state)`, `reservation(slot, attempt)`,
  `wait(job, kind, wake_at, wake_on, facts)`, `effect(job, key, state, result)` (the outbox), `loop(id, host, pid, start_id, command)`.
- Every transition is `commit(expected_revision, transition, pending_effects)` (I "Storage").
- Logs, raw answers, check outputs, screenshots stay files: they are evidence, not authority.
- The dashboard reads the DB read-only (`mode=ro` URI).
**Deletes:** the RMW bugs of Z04, A.F11's pid-only liveness (start_id column), A.F06's phantom loops, D.F03/F08/F09's outbox gaps (one
`effect` table), `LoopFiles.live()` renaming, most of `contracts/locator.py`, `parks.py`, `files.py`, `reexec.py` pointers, `Stores.loop_state`
(dead). It does not delete bd or git as authorities; cross-authority effects still go through `effect` rows and reconciliation.
Risk: macOS and the devbox both have sqlite3; NFS is not in play. Migration per I: import legacy under quiescence, one writer at a time.

### R2. An immutable job bundle; upgrades only between jobs

Today: three hop points (flow b). Alternative:
- Admission writes `bundle = (tl_dir, tl_version, delegate_dir, delegate_version, delegate run_args hash, profile_commit)` into the job.
- Engine runs `uv run --script <bundle.tl_dir>/skills/task-loop/tl.py`; every delegate call uses `bundle.delegate_dir`.
- Claude Code may delete old cache dirs: the loop copies (or hard-links) the bundle into `C/bundles/<hash>/` before admitting; GC when no
  job references it.
- The loop moves to a new install only between jobs (already does); a resumed job resumes in its bundle; a missing bundle is an owner wait.
- `tl rollback`, `pin`, `bad-versions` stay, applied at admission.
**Deletes:** `app/run/reload.py`, `app/release/reexec.py`, `TL_REEXEC` handoff in `engine_lock.py:79-90`, `runs/R/reexec.json`,
`reexec/B.json`, the crash-after-exec fallback in `loop/run.py:79-88`, per-call `Delegation.route` re-resolution, checkpoint
cross-version reading (A.F04), and the incidents 2, 3, 9, 10 class (I.F01). Cost: a fix waits for the current bead to finish.

### R3. One delivery judge, as a service the hook calls

Today: push judge (pre-push), `stackgate` (land-stack), the engine's land gate, `tl green`, each building its own evidence query and
profile view (Z01, Z02). Alternative:
- `app/land/delivery.py: judge(repo_id, tips, base_policy) -> Allowed | Refused(reasons) | Unavailable` is the only function that may say
  a tree may reach a protected ref. It reads the base profile, the full-key results, and the job's bundle.
- The pre-push hook is a 20-line stdlib client: forward stdin, exit 0 only on `Allowed` (it already nearly is; Z03 finishes it).
- The engine's land and `land-stack` call `judge` before `git push`; the hook then re-checks the same function (defense in depth, same answer).
- `tl green` becomes a display of `judge`'s reasons.
**Deletes:** `green_result` as an authority, the profile reader inside `push_judge.py`, the duplicated plan-digest logic in
`stackgate.py`, the `push_profile != cfg` race re-check (`push_judge.py:84-85`), and the shim-version mismatch (Z14) if the hook passes the
job's bundle.

### R4. Distribution: one released bundle, not two plugins plus vendor copies

Today: task-loop and delegate are released apart, always installed together (`docs/dev/integrations.md:60`), skew handled by a contract
integer, flag negotiation (Z12), two lookups (Z13), and two vendored shelf sets at different versions (Z23). Extraction D0 proposes
hash-verified shelf artifacts. The diagrams suggest a larger cut:
- One plugin repo ships `skills/task-loop` and `skills/delegate`, one version, one `_vendor/` (shelf at one tag set), one release.
- delegate keeps its own package and tests and its standalone skill for orchestrator use; worker-run stays the in-process boundary
  (a subprocess today, could stay one).
- The owner's earlier decision "everyone installs both" (2026-10-18) already makes the two plugins one product.
**Deletes:** contract-integer skew refusals, `resolve`/`find_route`, `pinned.json`'s `--delegate`, the delegate half of R2's bundle, C2/C8/C9
contradictions, one vendor copy (part of D0's 8,129 lines), one release pipeline. **Refuse condition:** if delegate must stay usable
without task-loop by other people, keep two plugins and do D0 plus Z12 instead. ❓ owner decision.

### R5. The engine as explicit steps over a transition API, not a host object

Today: `Engine` builds every part over itself; parts reach collaborators by attribute at runtime; `RunState` fields are writable from
everywhere (Z16). Alternative:
- Each step is a function `step(inputs: StepInputs, ports: StepPorts) -> StepResult` where `StepResult` names the transition
  (`Accepted`, `SendBack`, `Wait(kind, facts)`, `Land(candidate)`, `Close(outcome)`).
- `RunOnce` is a loop: load attempt from R1's store, pick step, call it, `commit(expected_revision, result.transition, result.effects)`.
- Ports are narrow Protocols per step (`Planner` gets `Delegate`, `Briefs`; `CheckRound` gets `Checks`, `Results`), built once in a composition
  root that is not passed to anyone.
**Deletes:** `carries_state`/`StateField` (`state.py:43-99`), `host: Any` parameters, `CloserHost`-style Protocol sums (C05), the forwarding
functions A lists (`land_with_engine`, `close_with_engine`), most of `engine.py`'s 50 imports, and the dotted "via Engine host" arrows in
c4-task-loop's component diagram. Depends on R1 (one place to commit) and Z04.

---

## 5. Beads to file: epic ZOOMOUT

Epic: **ZOOMOUT: one authority per fact across task-loop and delegate.** Children (title / acceptance):

**Wave 1**
- ZOOMOUT-PUSHKEY: push judge uses full-key authorization / a host receipt for a container-required check refuses the push; `green_result` unreachable from `land/`.
- ZOOMOUT-PUSHBASE: push judge reads the base's profile / a candidate committing `gate_checks: []` is still judged by the base's gate.
- ZOOMOUT-HOOKCLOSE: githook fails closed on any exception / with `taskloop.hook.prepush` unimportable, pre-push exits 1.
- ZOOMOUT-HOOKTL: the engine's children use the engine's own tl for judge-push / an engine on install X is judged by X with the shim on Y; shim written atomically.
- ZOOMOUT-CONTRACTLIST: worker-run v3 lists every verb task-loop calls; `contract.json` file read deleted / grep finds no read of delegate files in `src/`; planner report uses a route.py verb or is removed.
- ZOOMOUT-RUNARGS: resolve refuses a delegate whose `run_args` lacks a flag the request uses / an older fixture without `--only-family` gives an owner pause before claim.
- ZOOMOUT-DGLOOKUP: one delegate lookup, no newest-in-cache fallback / `find_route` deleted; every caller uses `resolve`.
- ZOOMOUT-LOCKOUT: engine lock and take move to `C/locks/` / no `.task/engine.*` written; loop/run-task handoff tests pass.
- ZOOMOUT-CAFFEINATE: one `caffeinate -w` per factory child / killing lane 1 leaves the others with idle prevention (macOS test).
- ZOOMOUT-LANENAME: factory "lanes" renamed "loops" in CLI, logs, dashboard / `factory-loop-N.log`; no UI string says lane for a loop.
- ZOOMOUT-MACUPDATE-TEST: measure whether the Mac installs a devbox release without a Claude session / a dated note with the observed delay.
- ZOOMOUT-CLAIMTEST: two clones, one Dolt remote, same bead claimed on both / a recorded result of what bd does on sync.
- ZOOMOUT-DOCS: fix the 18 stale doc rows of both C4 documents / rule test ties CLAUDE.md's contract version to `CONTRACT`.

**Wave 1, delegate repo**
- ZOOMOUT-DG-STATUSPURE: `status` and `next` write no config / a `status --json` on an undecided ready lane leaves `config.json` byte-identical.
- ZOOMOUT-DG-PUSHBAR: every worker env refuses `git push` by config / a Codex and an OpenCode write step attempting a push fail with no remote contact.
- ZOOMOUT-DG-DEPTH: `run` refuses when `DELEGATE_DEPTH` is set / a nested call answers `caller`.
- ZOOMOUT-DG-AGENTRUNS: delete agent-runs v1 producer / no `~/.config/agent-runs` write; README and integrations updated.
- ZOOMOUT-DG-EXECALLOW: do not merge `--exec-allow` as written / design note accepted by the owner: engine-run command or a Mac-only reviewed profile list.
- ZOOMOUT-VENDORPIN: both apps vendor one shelf tag set, prepended to `sys.path` / one lock file; both gates fail on drift.

**Wave 2**
- ZOOMOUT-REPOID: one `RepoId` with named projections / every file family's key chosen in `paths.py`; the dashboard imports it instead of a copy.
- ZOOMOUT-CAS: `JsonStore.update(fn, expected_revision)` under a per-document lock for manifests, parks, loop state, landed / interleaved beat vs mark_lost and two park writers never lose a write (procsim test).
- ZOOMOUT-STOPCAUSE: delegate's stop is never rewritten; engine stops carry `producer: engine`; one disposition table / a `needs_owner` stop always yields a durable owner Park; `settle.py` role/timer fallback deleted.
- ZOOMOUT-DG-ONELADDER: delegate decides a reason in `classify` only / settle, launch and run pass facts, not reasons.
- ZOOMOUT-DASHCMD: dashboard owner commands spawn `tl VERB --expect ID`; no engine import at runtime / answering a replaced ask is refused; GET handlers hold read-only objects.
- ZOOMOUT-REPOOWNER: one factory per repo unless the repo opts into shared claims / a loop refuses to start on a repo another host owns.
- ZOOMOUT-ENGINECMD: writer may request a declared engine command, run in the check round / a Unity shot requested by the writer runs on the host after the write, result in the next brief.
- ZOOMOUT-DG-LOCKLOAD: measure and fix delegate lock contention under 4 lanes / zero silent history losses; lock answers counted and shown.

**Wave 3 (each starts with an owner decision)**
- ZOOMOUT-BUNDLE: admit a job with an immutable bundle; no mid-job hop / a release during a bead changes nothing in that bead; the next bead runs the new bundle; reload.py deleted.
- ZOOMOUT-STORE: one SQLite execution store for jobs, attempts, reservations, waits, effects, loops / kill tests at every transition leave one current attempt and every pending effect.
- ZOOMOUT-STEPS: engine steps as functions returning transitions; `carries_state` and `host: Any` deleted / import-linter contract forbids `Engine` in step modules.
- ZOOMOUT-STORESLAYER: effects out of `contracts` in both apps / a rule test: no `open`, `os.replace`, `subprocess`, `fcntl` under `contracts/`.
- ZOOMOUT-ONEPLUGIN: decide one plugin vs two plus D0 / an owner note; if one, a single release ships both skills with one version.
