# Nine-lens architecture review: synthesis

2026-11-02. Inputs: the 16 lens reviews (design, struct, pipe, split, sec, simple, ops, fore; each in Fable and Opus), lens 9
`review-rewrite-opus.md`, `zoom-out-review.md` (Z01-Z26, R1-R5, epic tl-sqd3), `rca-zoomout-three.md`, `../design/gate-host.md`,
`review-brief.md`. The full deduplicated ledger is **`review-ledger.md`** (425 canonical rows M-001..M-425, grouped by theme). This file holds
the ranked actions, the disagreements, the root causes, the beads to file, and the decisions for Denis.

Id legend (same as the ledger): `SEC-F-01` = SEC-FABLE-01, `PIPE-O-09` = PIPE-OPUS-09, `DES`/`STR`/`SPL`/`SIM`/`OPS`/`FORE` likewise;
`RW-nn` / `Q-nn` = lens 9; `Z`, `R` = zoom-out; `GH:` = gate-host bead proposals; `R9-nn` = new beads in section 5.

**State since the reviews.** CRASHCAP is committed (engine_crash capped at 3 tries, a repeated fingerprint parks at once, Fenced is not
parked): M-205 and M-206 are fixed. PUSHBASE is committed (base profile, `profile_changed` refusal, env scrub for the judge's checks,
real-git canary): M-001 is done, pending release. PUSHOWNER (owner `--profile-change` path) is in progress (M-003). Denis chose a broader
exec-allow (dotnet build/test/restore/--version and pinned `python -m unittest|pytest` with any args; guard shim and JSONL audit are
mandatory). Several reviewers read 0.23.293; their KEYERR/CRASHPARK rows are tagged (stale?) or (fixed) in the ledger.

---

## 1. Top 15 actions

Ranked by risk removed per effort, then by agreement across reviewers.

| # | Action (one sentence) | Ledger ids | Size | Bead | Unblocks |
|---|---|---|---|---|---|
| 1 | **In flight.** Release PUSHBASE, finish PUSHOWNER, and confirm land-stack's `stackgate` gets the same base-profile and empty-gate refusal. | M-001, M-002, M-003, M-004, M-007 (SEC-F-01/02/04, Z01-Z03, PIPE-F-31) | S | tl-sqd3.32, PUSHOWNER, tl-1kox | every other push-path change; DQ-05 |
| 2 | **In flight.** Release CRASHCAP, then extend the cap to transient pauses, send ValueError from land into CRASHPARK, and log a traceback in the catch-all. | M-205, M-206 (fixed), M-207, M-213, M-204, M-217 (PIPE-F-01/02, PIPE-O-03/04/05/09, DES-O-23) | S | CRASHCAP + R9-01 | stops overnight retry burns; crash matrix (#9) |
| 3 | Run every check execution (round, land, stack, judge) with a scrubbed env (no SSH agent, `GIT_SSH_COMMAND`, tokens; scratch HOME) and egress off where the OS allows. | M-015, M-016, M-274, M-021 (SEC-F-03/39, SEC-O-02/03, SPL-F-19) | S-M | R9-02 (judge part in flight via PUSHBASE) | makes the broader exec-allow (#5) safe enough; Z11 |
| 4 | Take `claude -p` off the writer chain (Mac lane and the devbox quota-out fallback) until it runs sandboxed. | M-028, M-029 (SEC-F-05, SEC-O-09, OPS-O-30) | S | R9-03 | closes the second P0 both security reviewers found |
| 5 | Build Denis's broader exec-allow behind the guard shim: whole-argv match, absolute binaries from host.json, wrapper rejection, the escape corpus, JSONL audit, writer-only. | M-018, M-019, M-021..M-023, M-067, M-073, M-074 (SEC-F-19, SEC-O-04/05/06/11/36/43, RCA, FORE-O-24) | M | R9-04 (extends tl-sqd3:DG-EXECALLOW) | UNITYCODEX (tl-auky); deletes the overlay (M-033) |
| 6 | Never stop quietly: storm, low disk and no-lane become typed waits with a wake; a per-host supervisor restarts loops and owns caffeinate; ntfy for asks and stops. | M-211, M-307, M-216, M-309, M-311, M-313, M-304 (PIPE-O-02/17/18/28, PIPE-F-08, OPS-F-17/18, OPS-O-13/15/16/38, DES-O-11, FORE-O-03) | M | R9-09, R9-10, R9-11, R9-27 | unattended nights; Z22 |
| 7 | Delete `safe_point("land")` and cap the hop at one per run, never during land. | M-224, M-317 (PIPE-F-23, PIPE-O-35, OPS-O-26, OPS-F-21) | S | tl-br2.7 (add acceptance) | M-225 delete the hop; RW-08 shrinks |
| 8 | Liveness caps: a counter on the in-lock STALE retry, max land iterations and bounded lock waiters, and a run deadline. | M-209, M-214, M-215, M-128, M-246 (PIPE-O-01/14/15/16/36, PIPE-F-04/16/25/26, OPS-F-14) | S | R9-13 | removes the livelock class |
| 9 | Rule test that every enum-keyed table is total (plus `assert_never`), and a nightly kill-at-every-transition crash matrix. | M-208, M-241, M-118, M-119, M-121 (PIPE-F-03/10, PIPE-O-07/12/21/22/24, FORE-F-25, FORE-O-36/38) | S + M | R9-14, R9-15 | KEYERR class closed; safe REWRITE-CORE |
| 10 | Release train (at most one per 2 h, `--urgent` to skip), devbox-first ring, Mac standing pin, and `tl selftest` wired into the move, with failing versions marked bad. | M-283..M-286, M-316 (DES-F-24, SIM-F-24, SIM-O-29, OPS-O-01/14/25/37, FORE-O-02/09, FORE-F-03/17) | S | R9-16, R9-17 | shrinks the hop, cache and red-suite volume at once; DQ-06 |
| 11 | Cap Mac load with profile settings first (dotnet lease 2, DOTNET_PROCESSOR_COUNT=4, CsCheck_Threads=1, nice), then load-aware admission. | M-318, M-319, M-320 (OPS-F-22, OPS-O-06/07/08/09/10, FORE-F-22, FORE-O-11, GH part a) | S then M | GH:LOADCAP, GH:CHECKNICE (file if absent) | flake rate (#15); gate-host part b |
| 12 | Quota-aware admission with a per-bead token budget, and a second writer family kept warm at about 10% of light beads. | M-402, M-403, M-277, M-275 (FORE-O-01/10/12/14, FORE-F-09/10) | S-M | R9-19, R9-20 | a Thursday with a dead lane; review independence |
| 13 | Before filing this review's beads: turn every "Order:" line into `bd dep add`, and land agent-filed beads as deferred `from-review` with a daily promote budget. | M-408, M-409, M-049 (FORE-O-04/05, FORE-F-08, SEC-O-19) | S | R9-21, R9-22 | stops 4 loops starting R1 and Z04 at once |
| 14 | Fix the verified boundary bugs: delegate `state.json` wiped on version skew, the `no_lane`/`crash` permanence conflict, delegate status dropping asks/holds, the beat-thread get-then-put. | M-089, M-262, M-240, M-092, M-094 (DES-O-01, RW-11, PIPE-O-20, SPL-O-04, PIPE-F-06, PIPE-O-13) | S each | R9-28, R9-29, R9-30, R9-31 | REWRITE-WIRE; trust in the contract |
| 15 | Test health: run the suite once per release (pre-bump content key), a flake ledger with a quarantine ratchet and TL_TIME_SCALE, decide CI (gate or delete), and refuse test writes into the live config. | M-290, M-292, M-293, M-295, M-296, M-133 (OPS-F-01/02/03/11, OPS-O-02/03/04/05/23, FORE-F-02/05, FORE-O-06/07, STR-O-15) | S-M | R9-23, R9-24, R9-25, R9-26 | faster releases; trustworthy reports |

Next after the top 15, in order: one profile reader (R9-32), one store access path (R9-33, the precondition for CAS and for Q-01), the
check-key equality test (R9-45), the owner-command idempotence tests (R9-47), dead-code deletion incl. git_porcelain (R9-36), the usage
census (R9-52), then the rewrite sequence RW-01 → RW-02 → ... (section 5, R9-35..R9-51).

---

## 2. Merged idea ledger

In `review-ledger.md`. Sections and row ranges:

| Section | Rows |
|---|---|
| 1. Push path and security | M-001..M-076 |
| 2. State and stores | M-077..M-136 |
| 3. Engine structure | M-137..M-203 |
| 4. Pipeline failure modes | M-204..M-254 |
| 5. Delegate and the worker-run contract | M-255..M-282 |
| 6. Release and operations | M-283..M-346 |
| 7. Extraction, join, delete | M-347..M-380 |
| 8. Rewrite candidates (lens 9) | M-381..M-401 |
| 9. Foresight and scale | M-402..M-419 |
| 10. Tests | M-420..M-425 (M-425 SKILL.md) |

Count: 425 rows from about 650 source ideas. That is over the 250-350 target because the brief says to keep every distinct idea, and the
simplicity and split lenses produced many single-source deletion and extraction ideas that are not duplicates of anything.

---

## 3. Disagreements

### 3.1 Fable vs Opus on the same lens

| D | Topic | Fable | Opus | Evidence | Recommendation |
|---|---|---|---|---|---|
| D-01 | **Store authority** (simple lens) | SIM-F-01: SQLite factory.db, strangler phase 1, ✅ | SIM-O-01/07: one writer per job dir + flock; SIM-O-30 ❌ SQLite | R1 favours SQLite; Q-01 says "SQLite, but only after one store seam"; DES-O-32 says skip Z04 and go to R1 | Do the one access path (R9-33) and Z04 CAS first; then a one-week spike decides. Both designs need the same seam. DQ-01 |
| D-02 | **Pre-push judge** (simple lens) | SIM-F-20: one judge | SIM-O-04: delete the judge and dispatchers, ✅ | SEC-F-01 found a P0 in the judge; SEC-O-14 says client-side hooks are bypassable, rulesets first | Keep the judge until rulesets (R9-06) are live on every factory repo, then revisit deleting it. DQ-05 |
| D-03 | **SSH agent in checks** severity (sec lens) | SEC-F-03: P1 | SEC-O-02: P0 | Both describe the same env inheritance | Treat as P0: with the broader exec-allow, writer-written tests run with the agent. R9-02 |
| D-04 | **Dolt ingress** severity (sec lens) | SEC-F-34: P3 | SEC-O-21: P1 ❓ | Neither tested it | Ask (DQ-15); no bead before a test |
| D-05 | **Separate unix user** (sec lens) | SEC-F-32: owner call ❓ | SEC-O-40: ✅ P1 M | gate-host plans GATEHOST-USER later; FORE-F-19 P3 | Do it for the devbox gate host first (smaller blast radius), Mac after. DQ-07 |
| D-06 | **In-process delegate** (split/design lenses) | SPL-F-02 ✅ P1 L; DES-F-38 ❓ | SPL-O-13 ❓; DES-O-31 ❌; SIM-O-32 ❌ | Both agree on one plugin (R4) with a child process | One plugin yes, in-process no for now. DQ-02, DQ-03 |
| D-07 | **Codec** (split lens) | SPL-F-05: drop msgspec ❓ | SPL-O-27: delegate moves to msgspec | Q-14 sides with Opus if delegate already runs under `uv run --script`; SIM-F-30 ❌ replace msgspec | Opus. DQ-11 |
| D-08 | **Optimistic gate** (pipe lens) | PIPE-F-15: delete `Placing.INSIDE` | PIPE-O-25: delete the outside-lock gate | Both ❓, both contrarian, opposite halves | Measure how often each finds a red first (R9-52), then delete the one that never decides. DQ-09 |
| D-09 | **Storm detector** | PIPE-F: none | PIPE-O-02/28: nap + quarantine one fingerprint; SIM-O-19: delete heuristics | OPS-O-13 storm outage | Keep it, make it a wait (R9-09). SIM-O-19 rejected for storm |
| D-10 | **Selftest** (fore/simple) | FORE-F-17: canary before factory start | SIM-O-38: delete the selftest gate; FORE-O-09: wire it into the move | the docstrings contradict (`selftest.py:1-2` vs `versions.py:4-5`) | Wire it in (R9-17); deletion only if it never catches anything in a month |
| D-11 | **CI** (ops lens) | OPS-F-11: delete the unit job, third run nobody reads | OPS-O-02: CI red for 300 runs, gate on it or delete; OPS-O-03 add macOS | | Keep one CI job, make it required via ruleset, add macOS; delete the duplicate unit job. DQ-16 |
| D-12 | **Release cadence** | DES-F-24 ✅ P1 "rank 0"; SIM-F-24 ✅; OPS-F-31 ❓ owner | DES-O-29 ❓; SIM-O-29 ✅ 1/h cap; FORE-O-02 ✅ train | 22-69 releases/day (FORE-O); 224 cached versions | Train. DQ-06 |
| D-13 | **File-size cap** | SIM-F-10: raise to 800 ✅; STR-F-30 ❓: the cap manufactures the locator | DES-O-27 ❓ | | Raise to 600 for src, keep 800 for tests; revisit after REWRITE-PORTS. DQ-12 |
| D-14 | **Dashboard control** | FORE-F-33: ❌ read-only; OPS-F-34 more controls; SPL-F-11 dash into the package | SIM-O-16, DES-O-30: read-only + answer; FORE-O-33: bd labels as control plane | Z08 DASHCMD: POST spawns tl | Z08 now (one host); test FORE-O-33's latency before two-host control. DQ-22 |
| D-15 | **Devbox role** | SIM-F-31: devbox does not loop ❓; FORE-F-32: own repos per host ✅ | SIM-O-37 no devbox factory ❓; FORE-O-20 split by `needs:unity` | OPS-O-35 cross-machine claims already happen | FORE-O-20 first (uses existing AFFINITY), after CLAIMTEST. DQ-23 |
| D-16 | **delete look** | SIM-F-05 ✅ | SIM-O-28 fold into review ❓; Q-15 own package | | Census first (R9-52). DQ-20 |

### 3.2 Reviewers vs the zoom-out and RCA documents

| D | Doc position | Reviewer position | Evidence | Recommendation |
|---|---|---|---|---|
| D-17 | Z11/RCA: refuse broad exec-allow; option (c) narrow, (d) engine-run command | SEC-O: Z11's engine command is the same hole unless checks are sandboxed; SEC-F-20: option (c) contradicts itself; Denis chose a broader allow | RCA says no dotnet-test | Denis decided. The residual risk sits in M-015/M-016: R9-02 must ship with R9-04, not after |
| D-18 | Z01-Z03 as security fixes, wave 1 | SEC-O: they are correctness; rulesets first (SEC-O-14) | client-side hooks are bypassed by any `git push --no-verify` from a non-engine process | Both: PUSHBASE is in flight anyway; add R9-06 rulesets now (S) |
| D-19 | Z04 CAS before R1 | DES-O-32: skip Z04, go to R1 after one access path; STR-F-19: extract the store after CAS | | Keep Z04 but only on top of R9-33; Z04 is the cheap fix if DQ-01 says "no SQLite" |
| D-20 | Z05/R2: freeze the bundle (mechanism) | FORE-O-02, DES-F-24: the hop is a volume problem, a release train first; DES-F: FREEZEBUNDLE is a measurement | 69 releases on 10-30 | Train (R9-16) and land-safe-point deletion (tl-br2.7) first; bundle after |
| D-21 | Z07: one stop authority in task-loop | DES-O-17: delegate returns the disposition; SIM-O-03: 3-line mapping; Q-03: delegate owns lane retries | permanence conflict verified (RW-11) | Delegate owns lane-stop permanence; task-loop keeps engine-made stops (`producer: engine`). DQ-10 |
| D-21b | Z10: delete agent-runs v1 | FORE-O-32: keep as the cross-tool run feed | 154 rows with lane, model, transcript | Delete unless `status --history` cannot carry FORE-O-21's fields (one check) |
| D-22 | Z16 (engine without locator) in a later wave | DES-O-18: the locator is a volume problem, move to wave 2; RW: fix the seven shapes first (RW-01..07) | 36 `host: Any`, 38 cached parts, 111 Protocols (V) | Follow RW's order: vocab, substrate, ports, stores before Z16/R5 |
| D-23 | Z20: delegate lock contention, test first | FORE-F: the measurement already exists | | Read the existing data before writing a test (tl-sqd3.24) |
| D-24 | Z22: caffeinate per lane, rename lanes | OPS-O-28: the supervisor owns caffeinate; SIM-O-15: no lanes at all | | Supervisor owns it (R9-10); rename still worth it |
| D-25 | The zoom-out's order lives in prose | FORE-O-04: the factory cannot read it; 51 children, 0 deps | `bd dep tree tl-sqd3.19` | R9-21 before any REVIEW9 filing |
| D-26 | RCA's three root causes (R-A, R-B, R-C) | DES-F adds R-D: no owner of design style; PIPE-F/PIPE-O add R-D: untyped error paths | | Both added as themes T4 and T7 below |
| D-27 | gate-host: check lanes/resources and container executors stay | SIM-F-34 delete check lanes/resources; SIM-O-11 delete container execution | Mac load 281; EXECIDENT design | Keep (gate-host is the measured need). DQ-21 |
| D-28 | Roadmap: M2 blocks M3/M4 | FORE-O-26: 4 loops run while M2 is open; FORE-F: M4 has no beads | tl-bxk.10 open | Write the nightly scorecard (M-344); Denis says whether the roadmap still governs |

---

## 4. Themes and root causes

| T | Root cause | Explains (canonical ids) |
|---|---|---|
| T1 | **A fact has no single owner** (RCA R-A). Profile, repo key, install lookup, branch prefix, permanence, vocabulary are each read or written in several places. | M-004, M-108, M-109, M-151, M-173, M-198, M-240, M-261..M-263, M-279, M-280, M-381, M-393 |
| T2 | **Multi-writer get-then-put** (RCA R-B). JSON files are read, changed, written by more than one actor with no revision. | M-077, M-082, M-094..M-099, M-114, M-115, M-222, M-384, M-394 |
| T3 | **The trust line is punched** (RCA R-C). The writer can influence what judges it (profile, env, hooks, trust-root files) and some lanes have no sandbox. | M-001..M-003, M-008, M-011..M-023, M-025..M-029, M-038..M-040, M-056, M-060 |
| T4 | **Failure paths are untyped and not total** (pipe R-D). Kinds are strings converted late, tables are not exhaustive, catch-alls drop detail, classifications differ. | M-163, M-164, M-204..M-209, M-213, M-217..M-220, M-235, M-238, M-244, M-254, M-381 |
| T5 | **Liveness has no supervisor and no ceiling.** Loops exit 0, storms end the factory, nothing has a deadline or an iteration cap, nobody is notified. | M-209, M-211, M-214..M-216, M-252, M-307, M-309, M-311, M-313, M-314 |
| T6 | **Volume without budgets.** Releases, caches, red logs, review-filed beads, tokens and host load all grow with no cap, and the factory is forbidden to prune what it fills. | M-283, M-290, M-292, M-304..M-306, M-318, M-319, M-402, M-403, M-408, M-409 |
| T7 | **No owner of design style** (DES-F R-D, RW RS1-RS12). Each bead added a new local shape; the service locator, Protocol sums, round skeleton and re-derived read model are repeated 30-100 times. | M-137..M-143, M-145, M-158, M-170, M-185, M-203, M-382..M-390 |
| T8 | **Two plugins released apart.** Delegate and task-loop copy machinery (schema, codec, classifier, permanence) and drift. | M-074, M-089, M-113, M-261..M-265, M-272, M-280, M-391, M-397 |

---

## 5. Beads to file

New epic: **REVIEW9: nine-lens review actions** (P1). Its description carries M-401 (strangler rules) and M-420 (tests move with each
rewrite bead). File R9-21 and R9-22 first, then add the deps named below with `bd dep add`. Existing tl-sqd3 children are not re-filed;
where a row extends one, the acceptance goes onto that bead instead.

| R9 | Title | Acceptance | Parent | P | Ledger |
|---|---|---|---|---|---|
| R9-01 | CRASHCAP-2: cap transient pauses, ValueError into CRASHPARK, traceback in the catch-all | a transient pause repeats at most N times then parks; a ValueError from land parks; every catch-all log row has a traceback; retry history and settle errors are logged, not suppressed | REVIEW9 | P1 | M-204, M-207, M-213, M-217, M-219, M-220, M-235, M-238 |
| R9-02 | CHECKENV: scrubbed env for every check execution | a test check that prints env sees no SSH_AUTH_SOCK, GIT_SSH_COMMAND, tokens; HOME is scratch; on Linux the check has no network (`unshare -n`); one worker env builder | REVIEW9 | P0 | M-015, M-016, M-021, M-274 |
| R9-03 | CLAUDEP-OFF: claude -p is not a writer lane until sandboxed | delegate refuses role=writer on claude -p; the devbox quota-out fallback does not pick it; claude -p workers do not load task-loop hooks | REVIEW9 | P0 | M-028, M-029 |
| R9-04 | EXECALLOW-GUARD: Denis's broader allow behind the guard shim | whole-argv match; absolute binaries from host.json; wrappers refused; escape corpus (sed e, sort --compress-program, git grep -O, just -f) refused; JSONL audit row per call; delegate guard fails closed; denial corpus test | tl-sqd3 (extends DG-EXECALLOW) | P1 | M-018, M-019, M-021..M-023, M-067, M-073, M-074 |
| R9-05 | PLANNER-ARGV: planner check argv only from the profile | a planner answer naming an argv not in the base profile is refused | REVIEW9 | P1 | M-017 |
| R9-06 | RULESETS: server-side protection on factory repos and the marketplace | main of each factory repo and iorlas-marketplace has a ruleset (no force push, required status) | REVIEW9 | P1 | M-008 |
| R9-07 | TRUSTROOTS: protected trust-root files and reviewer reads from base | AGENTS.md, .claude/, mise.toml, .codex/, .task-loop.json, githooks changes need the owner label; the reviewer prompt uses base copies; comment trust by bd author | REVIEW9 (with PUSHOWNER) | P1 | M-037..M-040 |
| R9-08 | WRITER-BYPASS: block gh, bd/dolt writes, git -c and ref deletion for writers | each bypass has a refusing test; `push_tips` includes deletions; PreToolUse fail-open and pre-push fail-closed in one FAIL_MODE table | REVIEW9 | P2 | M-006, M-011..M-013 |
| R9-09 | LOOPWAIT: storm, low disk, low RAM and no lane are waits, not exits | the loop never exits 0 on these; a storm quarantines one fingerprint and naps; each wait has a wake condition | REVIEW9 | P1 | M-211, M-307 |
| R9-10 | SUPERVISOR: per-host loop supervisor owns restart and caffeinate | LaunchAgent on the Mac and a user unit or `tl factory keep` on the devbox restart a dead loop within 1 min; caffeinate held by the supervisor; start/stop reachable from the phone | REVIEW9 | P1 | M-216, M-309, M-311, M-314 |
| R9-11 | NOTIFY: push channel for asks, storms and factory stop | an ask or a stopped factory sends one ntfy message | REVIEW9 | P2 | M-313 |
| R9-12 | (do not file) add to tl-br2.7 HOPSAFE: delete `safe_point("land")`, hop ≤1 per run, never at land | - | tl-br2.7 | P1 | M-224, M-317 |
| R9-13 | LIVENESS-CAPS: in-lock STALE counter, land iteration cap, bounded lock waiters, run deadline | each cap has a test; bd sync failure is transient; dirty slot is not "stale base"; a judge hang inside the land lock times out | REVIEW9 | P1 | M-128, M-209, M-214, M-215, M-221, M-246 |
| R9-14 | ENUMTOTAL and invariant rules | AST rule: every dict keyed by enum members covers the enum; module SCC check; net-negative line ratchet; invariant rules (WRITERS) not text counts | REVIEW9 | P1 | M-161, M-169, M-175, M-179, M-180, M-208, M-345 |
| R9-15 | CRASHMATRIX: kill at every recorded transition, nightly | `dev/killpoints.py` resumes to the same next step at every transition; effect idempotency table test; write-ahead outcome; crash after push has one truth; auto-resume lost runs | REVIEW9 | P2 | M-118, M-119, M-121, M-199, M-226, M-232, M-241, M-253, M-414 |
| R9-16 | TRAIN: release train and ring | `dev/release.py` refuses within 2 h of the last release without `--urgent "why"`; ring stage recorded; Mac standing pin moves only after devbox-ok; `tl pin` at Night start | REVIEW9 | P1 | M-283, M-284, M-316 |
| R9-17 | SELFTEST-MOVE: selftest gates a move; breaking versions are bad | `Installs.target()` runs selftest once per install; a failure or a FAULT-breaking version lands in bad-versions.json | REVIEW9 | P1 | M-285, M-286 |
| R9-18 | (file only if absent) GH:LOADCAP + GH:CHECKNICE from gate-host.md | as in gate-host.md beads 1 and 4; add OPS-O-08's Unity limiter agreement | tl-sqd3 / gate-host | P1 | M-318..M-320 |
| R9-19 | QUOTA: quota-aware admission and per-bead token budget | loop chore writes `quota_risk` when the week runs out before reset and holds claims for that lane; `budget_fresh_tokens` charged from delegate tokens | REVIEW9 | P1 | M-275, M-276, M-402, M-403 |
| R9-20 | SECONDFAMILY: a non-OpenAI writer kept warm | 1 in 10 light writer calls goes to the second family; a failure there alerts | REVIEW9 | P1 | M-277 |
| R9-21 | BEADDEPS: review order as bd deps | every "Order:" line in zoom-out-review.md and this file has a `bd dep`; the loop refuses a child of an ordered epic that has no dep | REVIEW9 | P1 | M-408 |
| R9-22 | INTAKE: agent-filed beads are deferred until promoted | review, reflect and follow-up beads get label `from-review` and status deferred; at most K promoted a day | REVIEW9 | P2 | M-049, M-409 |
| R9-23 | FLAKELEDGER: flake ledger, quarantine ratchet, time scale | `dev/flakes.py` builds flakes.jsonl from red suite logs; quarantined tests run apart and cannot block; the count may only shrink; TL_TIME_SCALE on loaded hosts; suite time governor | REVIEW9 | P1 | M-291..M-293, M-301 |
| R9-24 | CIDECIDE: one required CI job plus macOS | duplicate unit job deleted; remaining job required by ruleset; macos-latest job; nightly race/live job | REVIEW9 | P1 | M-295..M-297 |
| R9-25 | TESTHOME: tests cannot write the live config | paths raise when the real config root is used under unittest/pytest without TASK_LOOP_TEST_HOME; fixture traces and `/r` runs purged; rule test | REVIEW9 | P2 | M-133 |
| R9-26 | SUITEONCE: one suite run per release | the cache key is the pre-bump tree content; the release does not rerun the suite inside the land lock; uv prewarm then offline spawns | REVIEW9 | P1 | M-136, M-233, M-290, M-299 |
| R9-27 | DISK: forecast, retention table, prune | `tl doctor --disk` with a 7-day slope; one retention table; loop/suite logs, /tmp, slot-state pruned; main checkout ff-only; XDG cache split | REVIEW9 | P1 | M-110, M-243, M-294, M-304..M-306, M-415 |
| R9-28 | DG-STATESKEW (delegate): state.json survives version skew | a CodecError leaves the old file in place and reads what it can; test with an older and a newer file | REVIEW9 | P1 | M-089 |
| R9-29 | PERMANENCE: one permanence per stop reason | `no_lane` and `crash` follow contract.json; a test fails when a pauses.TABLE key differs from the contract; Unknown(raw) policy; pause keys by (producer, reason) | REVIEW9 | P1 | M-239, M-240, M-245, M-262 |
| R9-30 | DG-STATUSASKS (delegate): status keeps asks and holds | `status --json` lists asks and holds; one status record | REVIEW9 | P2 | M-092, M-270 |
| R9-31 | BEATJOIN: the beat thread does not race main | beat writes go through the main writer or a CAS; the thread is joined and its death is logged | REVIEW9 | P1 | M-094 |
| R9-32 | PROFILESOURCE: one `profile_at(git, rev)` | push judge, check, doctor, stackgate, loop and engine use it; `.task-loop.json` is opened in one module | REVIEW9 | P1 | M-393 |
| R9-33 | STOREPATH: one store access path | no store constructed outside `stores/`; the forbidden contract's ignore list may only shrink; parks written at one site; Checkpoints.read uses `need`; ConfigDir WRITERS table | REVIEW9 (before tl-sqd3:CAS and STORE) | P1 | M-082, M-083, M-103, M-107, M-108, M-222, M-384 |
| R9-35 | REWRITE-VOCAB (RW-01) | grep for `"(FAULT|PAUSE|ASK|WAIT)_` in app is empty with a rule test; `Kind[...]` lookup gone | REVIEW9 | P2 | M-151, M-160, M-165, M-218, M-244, M-381 |
| R9-36 | DEADCODE: delete unwired modules | git_porcelain and gitsim, delegate_route.py, checks_argv.py, netgate.py, class Args, dwell.sticky, Stores.loop_state, stores/memory.py to tests, --ports, unittest.mock out of selftest | REVIEW9 | P2 | M-105, M-106, M-144, M-167, M-190..M-192 |
| R9-37 | REWRITE-SUBSTRATE (RW-02) | one process runner, git `_run`, lock API, signal scope, bd client with a default timeout; counted swallows | REVIEW9 (after R9-36) | P2 | M-100, M-145, M-155, M-162, M-382 |
| R9-38 | REWRITE-PORTS (RW-03) + reach ratchets | Git in five sub-ports; app/land ≤2 Protocols; reach and host:Any ratchets; one composition root | REVIEW9 (after R9-35) | P2 | M-095, M-138..M-143, M-158, M-383 |
| R9-39 | REWRITE-FACTLOG (RW-05) | `project_trace(log)` equals the last 50 real traces; one Tokens; one jsonl_log; events.jsonl one writer | REVIEW9 | P2 | M-099, M-115..M-117, M-385 |
| R9-40 | REWRITE-READMODEL (RW-06) | `stuck_of` and `ready_count` fallback deleted; dash wire types out of contracts; read verbs do not reconcile | REVIEW9 (after R9-39) | P2 | M-111, M-146, M-147, M-177, M-189, M-200, M-242, M-386, M-400 |
| R9-41 | REWRITE-STAGE (RW-07) | `replan.md` written in one function; rounds return StageResult; one run entry and one cursor | REVIEW9 (after R9-35) | P2 | M-120, M-152, M-153, M-164, M-170, M-196, M-387 |
| R9-42 | REWRITE-LAND (RW-09) | app/land ≤15 files; one step-begin; procsim land tests green | REVIEW9 (after PUSHBASE, R9-37, R9-38) | P2 | M-227, M-237, M-249, M-389 |
| R9-43 | REWRITE-LOOP (RW-10) | one bd ready and one parks read per tick (counted); Loop does not inherit Core; claim passed once | REVIEW9 | P2 | M-125, M-141, M-254, M-390 |
| R9-44 | REWRITE-WIRE (RW-11) | one vendored worker_run schema module; `"k"` shims deleted; router reasons all in the table; no reads of other tools' private state | tl-sqd3 (with CONTRACTLIST) | P1 | M-087, M-109, M-112, M-150, M-178, M-184, M-261, M-263, M-279, M-281, M-391 |
| R9-45 | CHECKKEY: delivery and round compute the same check key | a test proves `check_env()` and `bead_env` give the same key for one tree, or the mismatch is fixed | REVIEW9 | P1 | M-392 |
| R9-46 | REWRITE-SLOTS (RW-13) | `"task/"` only in contracts/branches.py; `engine_lock.LOCK` gone; lane identity by `--lane N` | REVIEW9 (after R9-32) | P2 | M-124, M-135, M-154, M-393 |
| R9-47 | OWNERCMD-TESTS (RW-14 first slice) | a retried `stick` files one bead; a `look` answer keeps a concurrent `owner_hold`; shared notes and owner requests not overwritten; answers carry provenance | REVIEW9 | P1 | M-048, M-088, M-096..M-098, M-174, M-394 |
| R9-48 | REWRITE-RELEASEOUT (RW-15) | `src/taskloop/app/release/` gone; one release pipeline | REVIEW9 | P3 | M-302, M-395 |
| R9-49 | REWRITE-TLTABLE (RW-16) | `tl --help` from the verb table; cli/land and cli/land_stack call one app function; hook light/full split | REVIEW9 | P3 | M-156, M-159, M-171, M-172, M-351, M-396 |
| R9-50 | REWRITE-DGRUN (RW-17, delegate) | `RunResult.attempts` reported; supervisor has no own pump loop; pure decide | REVIEW9 | P2 | M-148, M-182, M-259, M-272, M-397 |
| R9-51 | REWRITE-PROMPTS (RW-18) | no multi-line prompt text in `tl/domain/prompts/*.py`; a golden per node | REVIEW9 (with R9-41) | P3 | M-398 |
| R9-52 | CENSUS: one week of which paths fire | counts by step and Kind for hop, land-stack, look, reflect, OpenCode, both optimistic gates, and loops 2/3/4; count of tests constructing Engine | REVIEW9 | P1 | M-342, M-346, M-350, M-417, M-424 |
| R9-53 | CANARIES: replay corpus, nightly real-lane canary, per-model scorecard | the last 30 landed runs replay in the release suite; one nightly canary bead; `tl report --by-model` | REVIEW9 | P2 | M-278, M-288, M-289, M-341, M-423 |
| R9-54 | DASH-SEC: dashboard hardening | Host header check, tailscale identity, authenticated writes, XSS rule test, 500 handler without internals, funnel off | REVIEW9 | P2 | M-041, M-043..M-046, M-063, M-312 |
| R9-55 | BDBACKUP: nightly bd backup and restore drill | 7 rotations; monthly restore compares counts | REVIEW9 | P2 | M-130 |
| R9-56 | SLOTASIDE: exponential set-aside with probes | 30/60/120 min with a reset probe between | REVIEW9 | P2 | M-252 |
| R9-57 | VERSIONCENSUS and doctor ops checks | `tl status --json` versions block; shim sha256; doctor checks clone freshness, capabilities, secrets | REVIEW9 | P2 | M-053, M-329, M-335 |
| R9-58 | WRITER-HARDEN-2: the remaining sandbox gaps | Codex `approval_policy=never` and read-deny; overlay refresh race; SECRET_RE engine paths; diff secret scan; link exfil check; bead fields fenced; `--no-verify` engine commits; .git/config of release clone; kill -9 -1 gone; docker.sock, OpenCode, uv.toml, Landlock tested; umask 077 | REVIEW9 | P2 | M-025..M-027, M-030, M-032, M-035, M-036, M-050, M-052, M-055..M-059, M-065, M-066, M-069, M-070, M-072 |
| R9-59 | WORKERUID: workers run as a separate unix user (after DQ-07) | the gate host's checks and workers run as tlgate; the owner's SSH key and config are unreadable | REVIEW9 | P2 | M-060 |
| R9-60 | GROOM: grooming report, queue aging, actor allowlist | `tl groom --report`; age rank in the queue key; bd create refuses unknown actors | REVIEW9 | P3 | M-407, M-410, M-411 |

(R9-34 is not used: the "no IO in contracts" rule is the existing tl-sqd3:STORESLAYER. R9-12 and R9-18 are acceptance additions, not new
beads. That leaves 56 new beads plus the epic.)

Deps to add after filing: R9-33 → tl-sqd3:CAS → tl-sqd3:STORE; R9-36 → R9-37; R9-35 → R9-38, R9-41; R9-39 → R9-40; R9-32 → R9-46;
tl-sqd3.32 + R9-37 + R9-38 → R9-42; R9-02 with R9-04 (same release); R9-21 before every other R9.

---

## 6. Decisions for Denis

Yes/no. Each: the idea, size, risk, and my recommendation.

| DQ | Question | Ids | Size | Risk | Recommendation |
|---|---|---|---|---|---|
| DQ-01 | Move run authority to SQLite (`factory.db`), rather than CAS JSON or one-writer job dirs with flock? | M-078, M-079, M-081, M-132, M-352; Q-01, R1, SIM-F-01, SIM-O-01 | L | high: every state file, `cat` debugging lost | **Yes, but second.** Do R9-33 and Z04 first; then a one-week spike between SQLite and flock decides. Without one seam it is a big bang |
| DQ-02 | Merge delegate into the task-loop repo as one plugin (delegate stays a child process)? | M-265; R4, Q-02 | L | medium: history, delegate users | **Yes**, if nobody uses delegate alone; every RS10 drift comes from releasing apart |
| DQ-03 | Call delegate in process instead of a child process? | M-264 | L | high: one crash takes both | **No** for now; revisit after DQ-02 |
| DQ-04 | Delete the mid-bead hop (reload, reexec, TL_REEXEC); a fix waits for the bead to finish? | M-225; Q-10, Z05 | M | low once the train exists | **Yes**, after tl-br2.7's land-safe-point deletion and the train |
| DQ-05 | Delete the pre-push judge once GitHub rulesets protect main? | M-009, M-008, M-339 | S | medium: loses the local refusal before a push reaches GitHub | **Not yet.** Rulesets first (R9-06); revisit when the engine-side judge is the only path |
| DQ-06 | Batch releases into a train (at most one per 2 h, `--urgent` override)? | M-283 | S | low; a fix waits up to 2 h | **Yes**; cheapest cut of the hop, cache and red-suite volume |
| DQ-07 | Run workers and checks as a separate unix user? | M-060 | L | medium: file permissions, tool logins per user | **Yes, devbox gate host first**, Mac later |
| DQ-08 | Allow OS integration on the Mac (LaunchAgent) for the supervisor? | M-311 | M | low | **Yes**; the current rule leaves loops unsupervised |
| DQ-09 | Delete one of the two optimistic gates (in-lock INSIDE or outside-lock)? | M-229, M-230 | M | medium | **Measure first** (R9-52), then delete the one that never decides |
| DQ-10 | Delegate owns lane-stop permanence and lane retries; task-loop keeps only engine-made stops? | M-256..M-258; Q-03, Z07 | M | medium | **Yes** |
| DQ-11 | Delegate adopts msgspec for the shared wire package? | M-113, M-114; Q-14 | M | low-medium: a dependency on every worker call | **Yes** if delegate already runs under `uv run --script`; else keep delegate's codec as the shared one |
| DQ-12 | Raise the 400-SLOC src cap? | M-185 | S | low | **Yes, to 600** for src; tests stay at 800 |
| DQ-13 | Is the factory allowed to release itself, and is the orchestrating session trusted as a deputy? | M-054, M-061 | M | high if wrong | **Keep releases owner-session only**; mark release beads as privileged |
| DQ-14 | Replace the one SSH key with per-repo deploy keys (homelab out of reach)? | M-014 | M | low | **Yes** |
| DQ-15 | Treat refs/dolt ingress from another host as untrusted input? | M-051 | M | unknown | **Test first**; no bead before a reproduction |
| DQ-16 | Make one CI job required (ruleset) and delete the duplicate unit job, plus macOS? | M-295, M-296 | S | low | **Yes** |
| DQ-17 | Drop per-step Protocols for frozen dataclasses of concrete ports? | M-139; Q-08 | M | low runtime | **Yes**, within R9-38 |
| DQ-18 | Shrink import-linter to four layers (generated per-slice contracts)? | M-176 | S | low | **Yes, after R9-38**; until then the contracts carry the locator ratchet |
| DQ-19 | Table-driven delegate harnesses? | M-187; Q-12 | M | medium | **Yes for the spec, no for the parsers** |
| DQ-20 | Delete product-specific or rarely used paths: look (or move it to its own package), land-stack, shared/ADR/handoff, delegate cockpit/doctor/onboard, OpenCode lane? | M-210, M-268, M-347..M-349, M-357 | M each | low if the census shows they never fire | **Census first (R9-52)**, then delete what did not fire in a week; look → own package (Q-15) if it fires |
| DQ-21 | Keep check lanes/resources and container execution (gate-host direction) rather than delete them? | M-337, M-338, M-336 | - | - | **Keep**; gate-host's measured Mac load is the need |
| DQ-22 | Dashboard control: Z08 (POST spawns tl) now, bd labels as the two-host control plane later? | M-353..M-355 | M | low | **Yes**; test bd-label latency before building two-host control |
| DQ-23 | Split work between machines by capability (`needs:unity` on the Mac, the rest on the devbox) instead of shared claims or one factory per repo? | M-362..M-364, M-419, M-126 | S | low after CLAIMTEST | **Yes**, after tl-sqd3.9 shows claims are safe |
| DQ-24 | Write engine v2 beside the old engine, or strangle inside the current Engine? | M-374, M-401 | L | high either way | **Strangle** (RW §2.0); a parallel v2 doubles the surface during the move |
| DQ-25 | Replace prose-regex classification of our own workers' answers with schema fields, review first? | M-399; Q-05 | M | medium: models fill enums worse | **Yes, review only**, measure send-backs for a week |
| DQ-26 | Cut SKILL.md to the ~150-line orchestrator procedure and move the rest into tl verbs? | M-425 (DES-F-33, DES-O-20, SPL-F-37, SIM-F-36, SIM-O-25, Q-07) | M | medium: session behaviour follows the text | **Yes, after R9-49** (the verb table renders the reference) |
| DQ-27 | Stop reading other tools' private state (OpenCode db, transcripts, delegate history)? | M-279; Q-06 | S | low | **Yes** (CLAUDE.md already forbids it) |
| DQ-28 | Keep or delete the reflect digest's auto-filing? | M-342, M-343; Q-13 | S | low | **Measure** (census), then keep as a pure cluster + loop chore or delete; delete `report/planner.py` now |
| DQ-29 | Does the roadmap's "M2 blocks M3/M4" still govern while 4 loops run? | M-344, M-419 | - | - | Say which; if yes, the nightly scorecard is the next M2 bead |
| DQ-30 | Drop or keep msgspec in task-loop itself? | M-114 | M | medium | **Keep** (SIM-F-30 ❌; SPL-F-05 and SIM-O-36 are ❓ without evidence) |

Note on the decided exec-allow: the broader allow runs writer-written code (tests, csproj targets, conftest) on the host (M-021). The guard
shim limits which commands run, not what those commands execute. R9-02 (scrubbed env, no network) has to ship in the same release as
R9-04, or the allow inherits the SSH agent hole (D-03).
