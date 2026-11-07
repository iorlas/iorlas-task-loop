# Review-backlog triage (2026-11-07)

Scope: the 72 open, non-hold children of REVIEW9 (tl-7i9k), ZOOMOUT (tl-sqd3), REVIEWFIX (tl-br2), ENCAPSULATION (tl-3cl), DASHBACK (tl-xvl) and the stage epic tl-7y6, judged against main at the time of writing and the open PRs then (#519, #522, #526, #529, #531, #533 and the pipeline R4 lane). Evidence was read by subagents with grep and git log, then spot-checked by hand for the top picks (tl-br2.20, tl-br2.5, tl-7i9k.31, tl-7i9k.41, tl-sqd3.7). Closed beads carry the verdict in their reason; STILL VALID beads keep their text.

Totals: STILL VALID 46, ALREADY DONE 19, WON'T DO 6, DUPLICATE 1.

Rules applied: a design note without code is not "done" (the bead stays valid until its acceptance holds); a container epic with open children stays open and has no work of its own; a bead whose premise a later decision removed (delegate as a library, no hosted CI, no OS service, no backward compatibility) is WON'T DO. Beads in progress under another lane are marked.

## Verdicts

| id | verdict | pri | kind | reason | collides-with |
|---|---|---|---|---|---|
| tl-3cl.9 | STILL VALID | P2 | code-cut | Owner question, unanswered: reload.py/reexec.py (safe-point exec, hop) still live in src/taskloop/app/pipeline/reload.py; docs/design say hop is by design (tl-7y6.9). No work until owner answers. | tl-br2.7 |
| tl-7i9k.16 | STILL VALID | P2 | code-cut | Only design note exists (#206, docs/design/quota.md); grep finds no quota_hold_pct, quota_risk or budget_fresh_tokens in src/ or packages/. | none |
| tl-7i9k.31 | STILL VALID | P2 | code-cut | Only design note shipped (#283). 109 literal "FAULT_/PAUSE_/ASK_/WAIT_" strings remain, e.g. src/taskloop/app/land/checkout.py:71,132; Kind lookup and rule test absent. | none |
| tl-7i9k.35 | STILL VALID | P2 | code-cut | Only design note #278 (docs/design/rewrite-factlog.md) landed; no project_trace projection code, cut order 40-52 unexecuted. Same work as M-115/M-385. Needs owner decisions first. | #531,#533 (run pipeline files, light) |
| tl-7i9k.36 | STILL VALID | P2 | code-cut | Only design note (#276). views/runfacts.py:143 stuck_of and views/needs.py:48 ready_count (with fallback rule) still exist in taskloop_dash. | none |
| tl-7i9k.37 | STILL VALID | P2 | code-cut | Only design note shipped (#279). replan.md still written in 3 places: app/write/check_round.py:75,101 and app/pipeline/resume.py:272; no single replan() function. | #531,#533 (pipeline R4) |
| tl-7i9k.38 | STILL VALID | P2 | code-cut | Only design note landed (#280, docs/design/rewrite-land.md); src/taskloop/app/land still has 48 files vs acceptance <=15. | none |
| tl-7i9k.39 | STILL VALID | P2 | code-cut | No commit references it; Loop still subclasses Core (src/taskloop/app/loop/loop.py:71 `class Loop(Core)`), LoopEnv still wide callables (M-141). | none |
| tl-7i9k.41 | STILL VALID | P2 | code-cut | engine_lock.py:140 LOCK global still set in run/entry.py:225; "task/" literals in 8+ files (land/stack.py:46, pipeline/target.py:9, slots/reset.py:105...); no contracts/branches.py. | none |
| tl-7i9k.53 | STILL VALID | P2 | bug | Umbrella partly shipped (#281 --no-config, #289, #290 redaction); most of the long AC list (Codex read-deny, SECRET_RE, link exfil, --no-verify, umask 077) has no commit. Split it per item before work. | none |
| tl-7i9k.59 | STILL VALID | P2 | bug | Slice 1 only (#273, off by default). shell.py:no_network says "host that cannot says so once and runs the check" which contradicts the AC (refuse, never fall back); no macOS sandbox-exec profile in taskloop. | none |
| tl-br2.14 | STILL VALID | P2 | code-cut | Contracts now live flat in packages/kernel/src/tlkernel and still hold persistence/bd/reconcile (rowstores.py, bdsafe.py, reconcile.py, bdbackup.py). Stale path 'src/taskloop' in bead. | #532 |
| tl-br2.15 | STILL VALID | P2 | bug | Retry cap is per bead fingerprint only (domain/outcome.py:33 fault_retries=3, an ask after 3), no stop of a run after the same failure twice with a typed prerequisite reason; replan rounds still independent of completion. | #531,#533 |
| tl-br2.19 | STILL VALID | P2 | bug | closing_settle.py:47-56 closes 'done with nothing to land' with no acceptance disposition check; planner.py only sends back empty-stage plans. Nothing requires criteria met/waived. | #531,#533,tl-br2.8 |
| tl-br2.20 | STILL VALID | P2 | bug | take.py:125 and run/entry.py:91,108 still print TAKEN with no attempt/lease id before engine start; no admission-failure stop of claiming in loop.py. Mac-observed loss path; unfixed. | none |
| tl-br2.5 | STILL VALID | P2 | bug | #73 fixed unreadable-ownership refusal and read-back, but no atomic compare-and-increment (marks.py:49 next_gen is read+1) and closing_settle.py:53 beads.close has no actor+generation condition. | none |
| tl-br2.7 | STILL VALID | P2 | bug | No commit; reload.py:175 still keys the hop on os.getpid() and has no candidate probe with the real checkpoint. Moot if tl-3cl.9 deletes the hop; do after the owner decides. | tl-3cl.9 |
| tl-br2.8 | STILL VALID | P2 | bug | closing_settle.py:62-63 on bd close refusal only warns 'close it by hand'; no outbox/retry, no separate synced/closed fact; a failed close still ends the run as done. | #531,#533,tl-br2.19 |
| tl-sqd3.23 | STILL VALID | P2 | bug | Admission only checks claims per bead (src/taskloop/app/asks/admission.py:32 _foreign_claim); no repo-level owner check or shared-claims opt-in, so a second host can start a loop on the repo. | none |
| tl-sqd3.26 | STILL VALID | P2 | code-cut | Owner decision recorded 2026-11-06 (docs/design/sqlite-store-plan.md); slices #164,#176,#184 landed but lease, wait, effect, check_round tables are schema-only per plan section 1; kill tests not done. Keeper for br2.9. | #531,#533,#522 |
| tl-sqd3.30 | STILL VALID | P2 | test | tests/rules/arch_invariants.py exists but no one-reader rule for profile, repo key, delivery verdict, stop reason (RCA R-A, rca-zoomout-three.md:14 still unresolved); .importlinter has no reader contract. | #532 |
| tl-sqd3.35 | STILL VALID | P2 | code-cut | The "k" shim lives on in src/taskloop/adapters/agent.py:45,53; the vendored worker_run schema part is stale (delegate in-repo) so narrow to the k shim, router reasons table and rows reading delegate state. | none |
| tl-xvl.10 | STILL VALID | P2 | code-cut | /api/version (src/taskloop_dash/http.py:118-124) still reports one "schema": SCHEMA_VERSION, no min..max range; #202 only added a test. In progress, no PR open. | none |
| tl-xvl.4 | STILL VALID | P2 | code-cut | Slices 1-2 landed (#229, #236, #17: startup lease); the atomic typed engine status generation (F10, lifecycle/hold/retry) not built, no generation in src/taskloop_dash. Bead still in_progress. | #526 |
| tl-7i9k.10 | STILL VALID | P3 | code-cut | No ntfy/notify code anywhere in src/packages; only design note docs/design/notify.md landed (#261). Acceptance (one ntfy message on ask/stop) unmet. | none |
| tl-7i9k.24 | STILL VALID | P3 | code-cut | Mostly landed (#222, #291, #314: doctor --disk 7-day slope in app/doctor/disk.py, app/prune/retention.py table). Left: main-checkout ff-only and XDG cache split (no ff-only code found; cache only in childenv/affected). Shrink to remainder. | none |
| tl-7i9k.30 | STILL VALID | P3 | code-cut | Umbrella partly done (#356 real_stores sites, #359 Checkpoints.read uses need), but no ConfigDir WRITERS table (grep empty); parks single-site and ignore-list shrink unproven. | none |
| tl-7i9k.33 | STILL VALID | P3 | code-cut | Acceptance (one process runner, one lock API, bd client default timeout, counted swallows) not shown met; no commit cites it; no rewrite-substrate doc. Vague umbrella: split before work. | none |
| tl-7i9k.43 | STILL VALID | P3 | code-cut | src/taskloop/app/release/ still exists (canary.py, catalog.py, clone.py ...); no commit cites the bead. | none |
| tl-7i9k.44 | STILL VALID | P3 | code-cut | No commit; skills/task-loop/tl.py still 483 lines (above the shim intent) and cli/land.py plus cli/land_stack.py both exist as separate land algorithms. | none |
| tl-7i9k.46 | STILL VALID | P3 | test | AC path is stale (domain/prompts holds only 2 small files) but prompt text lives in app/plan/prompts.py (131 lines) and prompt.py; no per-node golden prompt tests exist (no prompt goldens in tests). | none |
| tl-7i9k.48 | STILL VALID | P3 | test | Slice 1 only (#264 dev/record_corpus.py); nightly real-lane canary and per-model scorecard not built (no scorecard code in dev/). | none |
| tl-7i9k.54 | STILL VALID | P3 | code-cut | Only design note docs/design/workeruid.md landed (#266); acceptance (checks/workers run as tlgate) has no code; gated on DQ-07. | none |
| tl-7i9k.64 | STILL VALID | P3 | code-cut | Manifest has loop_id (#92, tlkernel/run.py:211, engine.py:88) but the run table has no loop column and dev/census.py:70-84 still counts owners as stand-in. Remaining: write column, census use. | none |
| tl-7y6.11 | STILL VALID | P3 | container | All 3 children closed but the artifacts env var and repo-declared project tools are absent: either file the missing child or close on the owner word. | #522 |
| tl-br2.18 | STILL VALID | P3 | code-cut | No dated startup spans: grep finds no claim/slot-reset/setup/plan-start timing records in src/taskloop/app (app/track/runs.py only prints attempt spans); no commit references the bead. | #531,#533 |
| tl-sqd3.16 | STILL VALID | P3 | code-cut | No code for a writer-requested engine command (grep engine_command empty); only zoom-out-review.md:169,471 mention it. | none |
| tl-sqd3.18 | STILL VALID | P3 | code-cut | No RepoId type; repo_key is a bare str at 83 sites (tlkernel/check_files.py:44 repo_key, tlkernel/reponame.py:43 repo_name, domain/lifecycle/matchers.py:147). | #532 |
| tl-sqd3.27 | STILL VALID | P3 | code-cut | carries_state still at app/run/state.py:66 and used in run/engine.py:30; host: Any in run/run_once.py:15, workers/delegation.py:10, run/stage_checks.py:16. R4b/R4c partly remove hosts. | #531,#533,#519 |
| tl-sqd3.28 | STILL VALID | P3 | code-cut | Effects sit in the kernel contract-level code: tlkernel/bdbackup.py:46 and factorybackup.py:61,104 call os.replace; no rule test (importlinter only bans urllib/http/multiprocessing). Low harm. | none |
| tl-sqd3.7 | STILL VALID | P3 | bug | One caffeinate keyed to children[0].pid only (app/loop/factory_verbs.py:165), so killing loop 1 drops keep-awake for all; 'lane' wording remains in factory_verbs.py and cli/factory.py. | none |
| tl-7y6.2 | STILL VALID | - | container | Container epic: 1 child still open; closes with it. No work of its own. | none |
| tl-7y6.4 | STILL VALID | - | container | Container epic: 2 children still open; stage carves (#529) supersede its S3 plan, so judge it when those 2 close. | #529 |
| tl-w7lt | STILL VALID | - | container | Container epic: 11 of 41 children still open; no work of its own. | none |
| tl-7i9k.56 | STILL VALID | - | container | Umbrella with 2 open children (tl-7i9k.56.1 DURABLE-MODULE, tl-7i9k.56.2 COMPOSE-RULE) that this triage did not cover (grandchildren); it closes with them. Not closed: the first pass said WON'T DO and tl refused the close. | none |
| tl-7i9k.18 | STILL VALID | - | owner-action | Slice 1 shipped (#241, queue.py skips unordered children), but slice 2 (turn the Order: lines of zoom-out-review.md into bd dep add, label tl-sqd3 'ordered') says it stays open and is the owner's; the bead cannot close until then. | none |
| tl-7i9k.13 | ALREADY DONE | - | - | Slices 1-6 are all met: #265 (step graph), #268 (effect idempotency table, tests/run/test_effect_idempotency.py), #272 (write-ahead outcome, crash after push has one truth), #274 (dev/killpoints.py SIGKILL at every effect), #275 (slice 6 design note: lost runs resume through the ordinary loop). The one measurement that note proposes is split out as tl-yc53. | none |
| tl-7i9k.17 | ALREADY DONE | - | - | | pin.warm_second sha1%10 (#250), wired dark behind engine.second_writer_family (#252), doctor share line (#296); tests/run/test_second_family.py, tests/domain/test_writer_pin.py exist. | none |
| tl-7i9k.42 | ALREADY DONE | - | - | | First slice shipped: retried stick files one bead, hold set during a redo is kept (#244). Remaining RW-14 ideas belong to later slices, not this titled slice. | none |
| tl-7i9k.45 | ALREADY DONE | - | - | | DGRUN 2-4 landed (#239 attempts ladder, #243 Hung record, #246 pure decide); delegate/app/run.py:61,166 reports attempts. Rest is closed by dgrun-rewrite series. | none |
| tl-7i9k.47 | ALREADY DONE | - | - | All of the acceptance is met: dev/census.py, tests/census/test_census.py (kind/step counts, window, gate inside/outside lock, modes and owners, Engine count) and the first reading docs/architecture/census-2026-11-06.md (#259). The loop-id follow-up is tl-7i9k.64. | none |
| tl-7i9k.49 | ALREADY DONE | - | - | | Host/Origin/X-Taskloop-Dash write guard in taskloop_dash/http.py:53; XSS rule test (#288); fixed 500 (#231). Tailscale identity/funnel not in code, but bind is tailnet-only; close, file residue if wanted. | none |
| tl-7i9k.50 | ALREADY DONE | - | - | All of the acceptance is met (#254): tlkernel/bdbackup.py nightly export (7 kept), monthly restore drill, wired in launch/loop_ops.py, tests/contracts/test_bdbackup.py covers 9 days to 7 files, same-day once, failing bd, truncated/mismatch/lower-count drill. | none |
| tl-7i9k.51 | ALREADY DONE | - | - | All of the acceptance is met (#257): probes at 30/60/120/120/120 (tests/loop/test_waits.py:88-100), tests/slots/test_aside.py, slots/aside.py. | none |
| tl-7i9k.52 | ALREADY DONE | - | - | | #255 VERSIONCENSUS: status versions block (loops, shim sha256, skew) in domain/versions.py, wire/brief.py, doctor/ops.py. | none |
| tl-7i9k.63 | ALREADY DONE | - | - | All of the acceptance is met (#251): look items are the look:<bead> row of factory.db written by compare-and-set (tlkernel/lookrows.py), no look-bead metadata write, tests/asks/test_look_row.py covers both race orders, a hold set mid-answer, old-metadata move and the gallery reading the row. | none |
| tl-7y6.6 | ALREADY DONE | - | container | Epic container with all 16 children closed; the umbrella adds no work. | none |
| tl-br2.10 | ALREADY DONE | - | - | | f7fc10a3 (#107) publishes the recovery memo before consuming the answer, with a test in tests/run/test_worker_recovery.py. | none |
| tl-br2.16 | ALREADY DONE | - | - | | #139 LANDTIME: tl runs show/slow time the land's fetch, rebase and push from engine-log start/end records, which was the ask (record dated spans). | none |
| tl-sqd3.2 | ALREADY DONE | - | - | | #45 'Pre-push is judged by the engine's own install': childenv.hooks_vars sets TL_JUDGE_TL=OWN_TL (tlkernel/childenv.py:58); hook/prepush.py:15 reads it; shim written via tmp.replace (doctor/install.py:~120). | none |
| tl-sqd3.22 | ALREADY DONE | - | - | | #85 tl answer --expect and #381 dashboard answer carries ask id, replaced ask refused; taskloop_dash imports tlkernel only (its docstring, __init__.py:1). | none |
| tl-sqd3.24 | ALREADY DONE | - | - | | Lock contention counted/shown and history losses said: #225 (history row count), #227 (orphans stopped before claim), #434 (doctor counts lock answers). | none |
| tl-sqd3.34 | ALREADY DONE | - | - | | exec-allow guard shipped in delegate/domain/policy/exec_allow.py (#29 audit row); tests/delegate/test_exec_allow.py has denial corpus incl sort --compress-program and one audit row. | none |
| tl-xvl.11 | ALREADY DONE | - | - | | Attempt-bound live cursor landed in #194 (readers/logs.py:95-107 attempt cursor). Headless-Chrome part is host-bound (no Chrome on pix); not worth a bead. | none |
| tl-xvl.6 | ALREADY DONE | - | - | | #79 idempotency key and accepted/refused receipts in factory.db; #24 cache drop; #85/#381 expected-ask precondition. All F05 parts covered. | none |
| tl-7i9k.55 | WON'T DO | P3 | code-cut | No groom verb or code exists and none is planned; age rank and an actor allowlist are polish nobody asked for since the loop's queue.py ranks already. | none |
| tl-7i9k.5 | WON'T DO | - | - | | GitHub server-side ruleset with required status: repo has no hosted CI (CLAUDE.md: the factory is the CI) and dev/release.py pushes straight to main; also deferred and no repo files to change. | none |
| tl-7i9k.9 | WON'T DO | - | - | | Deferred P4; tl factory start/stop/status (DETACHED, 7e7d07c5) with caffeinate child exists and CLAUDE.md says no OS service (rules test); LaunchAgent premise contradicted. | none |
| tl-sqd3.17 | WON'T DO | - | - | | Premise stale: delegate is now a library in this repo (src/delegate), so there are not two apps vendoring a shelf set; dev/vendor.json plus VendorGuard (tests/rules/gate_rules.py:10) already fail on drift. | none |
| tl-sqd3.29 | WON'T DO | - | - | | Owner decision, not work (CLAUDE.md: decisions live in docs, beads are work). Repo already ships one plugin (.claude-plugin/plugin.json) with delegate as an in-repo library. Record in docs, close. | none |
| tl-sqd3.8 | WON'T DO | - | - | | Owner-level release-delivery question (rca-zoomout-three.md:19: 'a design question for the owner, not a defect'); acceptance is a dated measurement on a Mac, not repo work for an agent. | none |
| tl-br2.9 | DUPLICATE | - | - | | Park is the one typed wake since #458 (STOPCAUSE tl-sqd3.20: a paused run without a park is a loud fault); remaining attempt-keyed episodes is the same as sqd3.26 STORE. Keeper: tl-sqd3.26. | none |

## Notes on STILL VALID beads that need shaping before a lane starts

- tl-7i9k.53 (security umbrella), tl-7i9k.33 (substrate rewrite), tl-7i9k.30 (ConfigDir writers) are umbrellas: split them per acceptance item first.
- tl-br2.7 depends on the owner answer in tl-3cl.9 (is the reload hop kept?); if the hop goes, br2.7 is moot.
- tl-br2.8, tl-br2.15, tl-br2.19, tl-br2.18, tl-7i9k.35, tl-7i9k.37 and tl-sqd3.27 touch the pipeline files that PRs #531/#533 (pipeline R4) rewrite: start them after those land.
- tl-sqd3.26 is the keeper for tl-br2.9 (closed as duplicate).
- tl-xvl.4 and tl-xvl.10 are marked in progress in bd; ask their lane before taking them.

## Top 8 to start as lanes (bug or code cut, no collision with open PRs)

| # | id | what | files |
|---|---|---|---|
| 1 | tl-br2.20 | a claim is announced TAKEN before the engine starts and a pre-engine failure loses the attempt (Mac-observed loss path) | src/taskloop/app/loop/take.py, src/taskloop/app/run/entry.py, src/taskloop/app/loop/loop.py |
| 2 | tl-br2.5 | slot generation is read+1, not an atomic compare-and-increment; bd close has no actor+generation condition (take the marks.py/pool.py half first: closing_settle.py is in the R4 pipeline lane's files) | src/taskloop/app/slots/marks.py, src/taskloop/app/pipeline/closing_settle.py, src/taskloop/app/slots/pool.py |
| 3 | tl-sqd3.23 | a second host can start a loop on a repo: admission checks claims per bead only | src/taskloop/app/asks/admission.py, src/taskloop/app/launch/loop.py, src/taskloop/app/launch/loop_ops.py |
| 4 | tl-7i9k.59 | no_network falls back to running the check when the host cannot sandbox; the acceptance says refuse | src/taskloop/app/run/shell.py, src/taskloop/adapters/check_net.py |
| 5 | tl-7i9k.31 | 106 literal FAULT_/PAUSE_/ASK_/WAIT_ strings remain; typed Kind lookup and its rule test do not exist | src/taskloop/app/land/checkout.py, src/taskloop/app/land/commit.py, packages/kernel/src/tlkernel/kinds.py |
| 6 | tl-7i9k.41 | engine_lock.LOCK module global and "task/" branch literals in 8+ files; no contracts/branches | src/taskloop/app/slots/engine_lock.py, src/taskloop/app/run/entry.py, src/taskloop/app/land/stack.py, src/taskloop/app/pipeline/target.py, src/taskloop/app/slots/reset.py |
| 7 | tl-7i9k.36 | dash views recompute stuck_of and ready_count themselves instead of reading one model | src/taskloop_dash/views/runfacts.py, src/taskloop_dash/views/needs.py, docs/design/rewrite-readmodel.md |
| 8 | tl-7i9k.39 | Loop subclasses Core and LoopEnv is a wide bag of callables | src/taskloop/app/loop/loop.py, src/taskloop/app/loop/env.py, src/taskloop/app/loop/core.py |

Reserve: tl-sqd3.35 (the "k" shim in adapters/agent.py), tl-7i9k.38 (app/land still 48 files, target 15).

## Closing status

20 of the beads judged non-valid were closed. Not closed: tl-7i9k.13, .47, .50, .51 and .63 are fully met clause by clause (cites in the table) and wait for the lead's force-close, because they are assigned to the owner; tl-br2.16 has another assignee and is left alone; tl-7i9k.18 and tl-7i9k.56 turned out to be open (see the table). tl-yc53 is the new bead for the one measurement the CRASHMATRIX slice-6 note proposed.

Scope note: only direct children of the six parents were triaged. Grandchildren (for example tl-7i9k.56.1/.2, tl-7y6.6.x) are a second pass.
