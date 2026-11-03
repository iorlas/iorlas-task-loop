# Nine-lens review: merged idea ledger

2026-11-02. Companion to `review-synthesis.md` (top 15, disagreements, themes, beads, decisions). This file is the full deduplicated ledger.

**Source id legend.** `DES-F-07` = DESIGN-FABLE-07, `DES-O` = DESIGN-OPUS; `STR` = STRUCT; `PIPE`; `SPL` = SPLIT; `SEC`; `SIM` = SIMPLE;
`OPS`; `FORE`; `RW-07` = REWRITE-07 and `Q-07` its UNSURE question, `RS3`/`G06` = its repeated shape / module group; `Z07`, `R1` =
zoom-out-review.md; `RCA` = rca-zoomout-three.md; `GH:X` = a bead proposed in ../design/gate-host.md. `F`/`O` in the models column = Fable/Opus.

**Verdict.** ✅ do, ❌ do not, ❓ untested or owner call. `✅/❌` = the sources disagree (see synthesis section 3). Tags: **(contra)** = a
reviewer flagged it as against current direction; **(low)** = low confidence; **(stale?)** = written against 0.23.293 or fixed since;
**(fixed)** = shipped since the review; **(flight)** = committed or in progress now.

**Bead column.** `tl-sqd3:NAME` = an existing ZOOMOUT child by name (the number is not reliable from the docs, except .32 = PUSHBASE,
.24 = DG-LOCKLOAD, .9 = CLAIMTEST); other `tl-*` ids exist; `R9-NN` = a new bead listed in synthesis section 5; `-` = no bead (fold into a
neighbour, decision only, or rejected).

Row count: 425 (above the 250-350 target because every low-confidence and contrarian idea is kept as its own row).

---

## 1. Push path and security

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-001 | Pre-push judge runs the BASE profile's checks, refuses `profile_changed`, empty gate refuses | SEC-F-01, Z02, RCA (PUSHBASE-FAILCLOSED) | sec, zo | F | ✅ | P0 | S | (flight) PUSHBASE committed: base profile, refusal, env scrub, real-git canary | tl-sqd3.32 |
| M-002 | land-stack gate (stackgate) has the same writer-profile and empty-gate holes as the judge | SEC-F-02 | sec | F | ✅ | P0 | S | verify PUSHBASE covers `stackgate.py`; if not, same fix | tl-sqd3.32 (add acceptance) |
| M-003 | Owner-only path to change a profile (`--profile-change`) and an owner label on protected files | SEC-F-04, Z02 | sec, zo | F | ✅ | P1 | S | (flight) PUSHOWNER in progress | PUSHOWNER |
| M-004 | Judge authorizes on the full check key (CHECKIDENT RunKey), never on `green_result` | Z01, RW G06, RCA step 1-5 | zo, rw | O | ✅ | P1 | S | 0.23.293 CHECKIDENT shipped; RW at e6c7f2a7 still sees `green_result` at `push_judge.py:9,74`: verify | tl-1kox / tl-sqd3:PUSHKEY |
| M-005 | pre-push githook fails closed when the judge is unavailable | Z03, RCA | zo | - | ✅ | P1 | S | (fixed) HOOKPUSH 0.23.292 | tl-sqd3:HOOKCLOSE |
| M-006 | Keep the PreToolUse hook fail-open; Z03's fail-closed applies to the pre-push hook only; one FAIL_MODE table per hook | SEC-F-36, SEC-O-37, DES-F-26 | sec, des | both | ✅ | P1 | S | SEC-O-37 rejects a fail-closed PreToolUse; DES-F-26 wants the mode as a table | R9-08 (acceptance) |
| M-007 | The judge must not run `tl check` in process; it only reads evidence and refuses | PIPE-F-31 | pipe | F | ✅ | P1 | S | overlaps PUSHBASE (judge runs base checks); decide which | tl-sqd3.32 (decide) |
| M-008 | Pre-push is client-side; enforce with GitHub rulesets / required status, marketplace repo too | SEC-O-14, SEC-O-33 | sec | O | ✅ | P1 | S | the only server-side control; Opus ranks it before Z01-03 | R9-06 |
| M-009 | Delete the pre-push judge and its dispatchers; one delivery judge inside the engine | SIM-O-04, SIM-F-20, R3 | sim, zo | both | ✅/❌ | P1 | S | (contra) conflicts with the in-flight PUSHBASE/PUSHOWNER work; see disagreement D-02 | decision DQ-05 |
| M-010 | `GIT_CONFIG` push barrier for writers | Z24, SEC-F-08 | zo, sec | F | ❓ | P2 | S | SEC-F-08: beaten by `git -c` | tl-sqd3:DG-PUSHBAR |
| M-011 | `gh` (pr merge, api) bypasses the judge; refuse for writers | SEC-F-07 | sec | F | ✅ | P1 | S | | R9-08 |
| M-012 | Writers must not run `bd`/`dolt` writes | SEC-F-09 | sec | F | ✅ | P2 | S | | R9-08 |
| M-013 | `push_tips` drops ref deletions, so a deletion is never judged | SEC-O-13 | sec | O | ✅ | P2 | S | | R9-08 |
| M-014 | One SSH key opens every repo incl. homelab; use per-repo deploy keys | SEC-O-15 | sec | O | ✅ | P1 | M | owner infra | decision DQ-14 |
| M-015 | Checks inherit `SSH_AUTH_SOCK`, `GIT_SSH_COMMAND`, tokens; split writer/check env, scratch HOME | SEC-F-03, SEC-F-39, SEC-O-02 | sec | both | ✅ | P0/P1 | S | severity split: O P0, F P1. (flight) PUSHBASE scrubs env for the judge's checks only | R9-02 |
| M-016 | Check egress off (`unshare -n` / `sandbox-exec`) | SEC-O-03 | sec | O | ✅ | P1 | M | Linux and Mac differ | R9-02 |
| M-017 | Planner can emit ad-hoc check argv that runs on the host; restrict to the profile's allow-list | SEC-O-01 | sec | O | ✅ | P1 | M | | R9-05 |
| M-018 | A `just` prefix in an allow rule runs any recipe | SEC-O-04, RCA (reject `just -f`) | sec, zo | O | ✅ | P1 | S | applies to the broader allow too | R9-04 |
| M-019 | Exec-allow: check the whole argv, reject wrappers (just -f, nice, timeout, uv, npx, make), strip engine-only commands | SEC-F-19, SEC-O-05, RCA, Z11 | sec, zo | both | ✅ | P1 | S | Denis chose a broader allow (dotnet build/test/restore/--version, pinned python -m unittest/pytest, any args); these checks are the guard shim's job | R9-04 / tl-sqd3:DG-EXECALLOW |
| M-020 | RCA exec-allow option (c) contradicts itself | SEC-F-20 | sec | F | ❌ (for (c)) | P2 | S | superseded by Denis's choice | - |
| M-021 | Broader allow: `dotnet test` / `python -m pytest` with any args run writer-written code (tests, csproj targets, conftest) on the host | RCA (no dotnet-test), SEC-O disagreement with Z11, SEC-F-19 | sec, zo | both | ❓ | P1 | - | accepted by Denis with guard shim + JSONL audit; residual risk = M-015/M-016 must hold for these commands | R9-04 + R9-02 |
| M-022 | Blocklists differ between layers; resolve absolute binaries from `host.json`; move `writer_exec_allow` to host.json | SEC-O-06, SEC-O-43 | sec | O | ✅ | P2 | S | | R9-04 |
| M-023 | Allowlisted readers escape: `sed e`, `sort --compress-program`, `git grep -O` | SEC-O-11 | sec | O | ✅ | P1 | S | test corpus for the guard | R9-04 |
| M-024 | Engine-run command instead of exec-allow (Z11 option d) | Z11, RCA (d), SEC-O disagreement | zo, sec | O | ✅/❌ | P1 | M | SEC-O: the same hole unless checks are sandboxed | tl-sqd3:ENGINECMD |
| M-025 | Codex escalation: `approval_policy=never`, no escalated commands | SEC-F-17, SEC-O-07 | sec | both | ✅ | P1 | S | | R9-58 |
| M-026 | Repo-local `.codex` config can self-grant | SEC-O-08 | sec | O | ❓ | P1 | S | test first | R9-58 |
| M-027 | Codex reads are unblocked; a read-deny profile for secrets dirs | SEC-O-31 | sec | O | ✅ | P2 | S | | R9-58 |
| M-028 | Mac `claude -p` writer lane has no sandbox (devbox fallback after Codex quota-out too); off the write chain until sandboxed | SEC-F-05, SEC-O-09 | sec | both | ✅ | P0 | S | both P0 | R9-03 |
| M-029 | `claude -p` workers load task-loop's own hooks and can rewrite the shim | SPL-F (not-thinking), OPS-O-30 | spl, ops | both | ❓ | P1 | S | | R9-03 |
| M-030 | SECRET_RE: add engine paths and the overlay auth file | SEC-F-06, SEC-O-10 | sec | both | ✅ | P2 | S | | R9-58 |
| M-031 | Filters are tripwires; stop investing in SECRET_RE | SEC-F-35, SEC-O-39 | sec | both | ✅/❌ | P3 | - | SEC-F-35 ❌ on more work, SEC-O-39 says keep as tripwire; agree on "not a boundary" | - |
| M-032 | Overlay `auth.json` refresh-token race between parallel workers | SEC-O-12 | sec | O | ✅ | P1 | S | | R9-58 |
| M-033 | Delete the Codex overlay | RCA, SEC-F-21 | zo, sec | F | ✅ | P2 | S | SEC-F-21: cleanup is hygiene, not security | tl-sqd3:DG-EXECALLOW |
| M-034 | Overlay keyed by rules hash, shared between calls | DES-F-29 | des | F | ❌ | P1 | S | rejected by its author | - |
| M-035 | Secret scan of the candidate diff before push | SEC-F-18 | sec | F | ✅ | P2 | S | | R9-58 |
| M-036 | Link-check exfiltration; entropy check on outbound URLs | SEC-F-16, SEC-O-30 | sec | both | ✅ | P2 | S | | R9-58 |
| M-037 | Comment trust by prefix; use the bd author | SEC-F-13 | sec | F | ✅ | P2 | S | | R9-07 |
| M-038 | Reviewer reads the writer's AGENTS.md; read trust roots from base | SEC-F-14, SEC-O-23 | sec | both | ✅ | P1 | S | | R9-07 |
| M-039 | Landed `.claude/settings.json`, `mise.toml` execute in owner and RC sessions | SEC-O-24, SEC-O-25 | sec | O | ❓ | P1 | S | protected-file list | R9-07 |
| M-040 | Evidence self-attestation by the writer | SEC-F-15, SEC-O-22 | sec | both | ✅ | P2 | S | | R9-07 |
| M-041 | Tailnet peer = owner; check `tailscale whois` / serve identity header; bind loopback | SEC-F-10, SEC-O-38 | sec | both | ✅ | P2 | S | | R9-54 |
| M-042 | CSRF open on 0.23.293 | SEC-F-11 | sec | F | ✅ | P1 | S | (fixed) in .299; Mac still runs older until it moves | - |
| M-043 | XSS rule test for the page | SEC-F-12 | sec | F | ✅ | P2 | S | | R9-54 |
| M-044 | GET DNS rebinding; Host header check | SEC-O-16 | sec | O | ✅ | P2 | S | | R9-54 |
| M-045 | Dashboard writes unauthenticated | SEC-O-17 | sec | O | ✅ | P2 | S | | R9-54 |
| M-046 | 500 handler leaks internals | SEC-F-41 | sec | F | ✅ | P3 | S | | R9-54 |
| M-047 | Long-poll DoS | SEC-O-44 | sec | O | ❌ | P3 | - | rejected | - |
| M-048 | Owner answers lack provenance | SEC-O-18 | sec | O | ✅ | P2 | S | | R9-47 |
| M-049 | Follow-up beads are auto-queued; land them as needs-triage | SEC-O-19 | sec | O | ✅ | P2 | S | same mechanism as M-409 | R9-22 |
| M-050 | Bead fields enter prompts unfenced; handoff fence | SEC-O-20, SEC-F-24 | sec | both | ✅ | P2 | S | | R9-58 |
| M-051 | Dolt `refs/dolt` ingress from another host | SEC-O-21, SEC-F-34 | sec | both | ❓ | P1/P3 | M | severity split O P1, F P3 | decision DQ-15 |
| M-052 | `kill -9 -1` hazard in a cleanup path | SEC-F-22 | sec | F | ✅ | P1 | S | | R9-58 |
| M-053 | Shim sha256 in the manifest | SEC-F-23 | sec | F | ✅ | P3 | S | | R9-57 |
| M-054 | Orchestrator session as confused deputy | SEC-F-25 | sec | F | ❓ | P1 | M | | decision DQ-13 |
| M-055 | uv picks up `uv.toml` from the worktree cwd; `uv lock --script` | SEC-F-26, SEC-O-32 | sec | both | ❓ | P2 | S | | R9-58 |
| M-056 | OpenCode sandbox gaps: writable `~/.cache` uv cache, project config, allow-default Mach, formatter/lsp | SEC-F-27, SEC-F-29, SEC-O-27, SEC-O-28 | sec | both | ❓ | P1 | S | OpenCode deletion is M-210 | R9-58 |
| M-057 | `docker.sock` reachable from workers | SEC-F-28 | sec | F | ❓ | P1 | S | | R9-58 |
| M-058 | `.task/` dir kept and readable across beads | SEC-F-30, SEC-O-46 | sec | both | ✅ | P3 | S | | R9-58 |
| M-059 | Delegate data dir writable by workers | SEC-F-31 | sec | F | ✅ | P2 | S | | R9-58 |
| M-060 | Separate unix user for workers (tlgate / tl-worker) | SEC-O-40, SEC-F-32, FORE-F-19, GH:GATEHOST-USER | sec, fore, zo | both | ✅/❓ | P1 | L | O ✅, F owner call, FORE-F P3 | R9-59 / DQ-07 |
| M-061 | The factory releases itself; a privileged bead class | SEC-F-33 | sec | F | ❓ | P2 | M | | decision DQ-13 |
| M-062 | TMPDIR per worker | SEC-F-37, SEC-O-29 | sec | both | ❌/❓ | P3 | S | F ❌, O ❓ | - |
| M-063 | tailscale funnel exposure | SEC-F-38 | sec | F | ❓ | P2 | S | | R9-54 |
| M-064 | `engine.host` key semantics | SEC-F-40 | sec | F | ❓ | P3 | S | | - |
| M-065 | Engine commits run the repo's pre-commit hook; use `--no-verify` | SEC-O-26 | sec | O | ✅ | P2 | S | | R9-58 |
| M-066 | Release clone `.git/config` and main checkout `fsmonitor` run code | SEC-O-34, SEC-O-35 | sec | O | ✅ | P2 | S | | R9-58 |
| M-067 | Delegate guard fails open | SEC-O-36 | sec | O | ✅ | P1 | S | | R9-04 |
| M-068 | Devbox has no docker for container checks | SEC-O-41 | sec | O | ❓ | P2 | - | gate-host EXECIDENT handles it | GH:EXECIDENT |
| M-069 | Devbox Codex Landlock never tested | SEC-O-42 | sec | O | ❓ | P1 | S | test before devbox writes more | R9-58 |
| M-070 | Secrets reach Dolt and transcripts | SEC-O-45 | sec | O | ❓ | P2 | S | | R9-58 |
| M-071 | `DELEGATE_DEPTH` refuse | Z25 | zo | - | ✅ | P3 | S | | tl-sqd3:DG-DEPTH |
| M-072 | Config dir and githooks are 775; `umask 077` at tl entry | FORE-O-31 | fore | O | ✅ | P3 | S | (low) | R9-58 |
| M-073 | Denial corpus as delegate golden tests | FORE-O-24 | fore | O | ✅ | P2 | S | | R9-04 |
| M-074 | One read-only shell classifier for both repos; stricter wins | Q-09, SPL-F-15, SPL-O-24 | rw, spl | both | ✅ | P2 | M | SPL-O-24: task-loop's is the base | R9-04 |
| M-075 | cc-hook fail-closed dispatcher as a shelf package | SPL-O-23 | spl | O | ✅ | P2 | S | | - |
| M-076 | `run_args` check | Z12 | zo | - | ✅ | P2 | S | | tl-sqd3:RUNARGS |

## 2. State and stores

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-077 | CAS `update(fn, expected_revision)` for manifests, parks, loop state, landed | Z04, RW-04 step 1, RS6 | zo, rw | O | ✅ | P1 | M | | tl-sqd3:CAS |
| M-078 | Skip Z04; go to R1 after one access path exists | DES-O-32 | des | O | ✅/❌ | P1 | L | (contra) vs Z04 order; see D-01 | DQ-01 |
| M-079 | SQLite `factory.db` as the authority (jobs, attempts, effects, asks, loops) | R1, SIM-F-01, Q-01 | zo, sim, rw | both | ✅/❌ | P1 | L | SIM-O-30 ❌, Q-01 "yes but after RW-04" | tl-sqd3:STORE / DQ-01 |
| M-080 | One SQLite for both apps (task-loop and delegate) | SPL-F-35 | spl | F | ❓ | P3 | L | | - |
| M-081 | One writer per job dir plus flock; no SQLite | SIM-O-01, SIM-O-07, SIM-O-30 | sim | O | ✅/❌ | P1 | M | the alternative to R1 | DQ-01 |
| M-082 | One store access path: finish the Stores bundle; ~70 direct constructions removed | DES-O-04, SPL-O-02, SPL-F-03, STR-O-16, STR-F-20, DES-F-07 | des, spl, str | both | ✅ | P1 | M | precondition for CAS and SQLite | R9-33 |
| M-083 | Stores layer is on paper: forbidden contract with 76 importers as a shrink-only ignore list | STR-F-02, STR-O-08 | str | both | ✅ | P2 | S | | R9-33 |
| M-084 | Delete the stores layer instead | STR-F-28, STR-O-26 | str | both | ❓ | P3 | M | (contra) | - |
| M-085 | Extract the store package only after CAS | STR-F-19 | str | F | ❓ | P3 | - | ordering note | - |
| M-086 | Contracts hold records only; no effects (open, os.replace, subprocess, fcntl) by rule test | Z17, STR-F-05, STR-F-06, STR-O-06, DES-F-08, SPL-O-29, RW-04, G18 | zo, str, des, spl, rw | both | ✅ | P2 | M | contracts are the most volatile layer (STR-F-05, STR-O-06) | tl-sqd3:STORESLAYER |
| M-087 | Delegate contracts carry effects too (`config_dir`) | STR-F-17, STR-O-33 | str | both | ✅ | P3 | S | | R9-44 |
| M-088 | `AskStore` state machine out of contracts into domain | STR-O-09, RW-04, G16 | str, rw | O | ✅ | P2 | S | | R9-47 |
| M-089 | Delegate `state.json` is wiped on version skew (CodecError → fresh StateDoc written back) | DES-O-01 | des | O | ✅ | P1 | S | delegate repo; loses holds and history | R9-28 |
| M-090 | Delegate `state.json` is a god document | DES-O-35 | des | O | ❓ | P3 | M | | - |
| M-091 | Delegate `status` writes no config | Z19, RW-17, G30 | zo, rw | O | ✅ | P2 | S | | tl-sqd3:DG-STATUSPURE |
| M-092 | Delegate `status` drops asks and holds; owner questions are lost | SPL-O-04 | spl | O | ✅ | P2 | S | | R9-30 |
| M-093 | Delegate lock contention, test first; a load column | Z20, OPS-O-36, FORE-F (measurement exists) | zo, ops, fore | both | ✅ | P2 | M | FORE-F: the measurement already exists | tl-sqd3.24 |
| M-094 | Beat thread and main thread get-then-put the same file; join or route through main; it dies silently | PIPE-F-06, PIPE-O-13 | pipe | both | ✅ | P1 | S | O ❓ on the silent death | R9-31 |
| M-095 | RunState fields written by several modules (`e.unchecked` from 6) | STR-O-02 | str | O | ✅ | P2 | M | | R9-38 |
| M-096 | Shared notes: dead record next to a live writer that drops owner notes; read-replace with no lock | STR-O-11, G04 | str, rw | O | ✅ | P2 | S | | R9-47 |
| M-097 | Owner requests overwritten; three meanings of "torn" | STR-O-22 | str | O | ✅ | P2 | S | | R9-47 |
| M-098 | `looks` whole-metadata write drops a concurrent `owner_hold`; `stick.decide` before the ledger write can file a second bead | RW-14, G15 | rw | O | ❓ | P1 | S | (H) needs the two tests | R9-47 |
| M-099 | `events.jsonl` has two writers; five JSONL appenders; one `jsonl_log` with age retention | SPL-O-05, SPL-F-06 | spl | both | ✅ | P2 | S | | R9-39 |
| M-100 | One lock API (process_lock holder); 3-5 lock entry points; `guard.py` lock has no timeout | SPL-F-07, STR-O-10, RW-02, G19 | spl, str, rw | both | ✅ | P2 | M | | R9-37 |
| M-101 | Engine lock out of the worktree | Z15 | zo | - | ✅ | P2 | S | | tl-sqd3:LOCKOUT |
| M-102 | Engine passes its own tl; atomic shim swap | Z14 | zo | - | ✅ | P2 | S | | tl-sqd3:HOOKTL |
| M-103 | `Checkpoints.read` uses lossy `get`; use `need` | DES-F-40 | des | F | ✅ | P2 | S | | R9-33 |
| M-104 | Every checkpoint write costs a bd read | DES-F-27 | des | F | ❓ | P3 | S | | - |
| M-105 | `Stores.loop_state` is dead | DES-F-43 | des | F | ✅ | P3 | S | | R9-36 |
| M-106 | `stores/memory.py` ships in production; move to tests | DES-O-21, STR-F-20 | des, str | both | ✅ | P3 | S | | R9-36 |
| M-107 | STATEFILES blind spot; vendored names belong in `root_packages` | STR-O-12 | str | O | ✅ | P3 | S | | R9-33 |
| M-108 | Hand-built paths; ConfigDir 61-74 paths; WRITERS table and count ratchet | STR-O-13, SPL-O-15, DES-F-06, STR-F-24, DES-F-23, G17 | str, spl, des | both | ✅ | P2 | S | | R9-33 |
| M-109 | One state root; planner hardcodes delegate's history path | SPL-O-14 | spl | O | ✅ | P2 | S | same as M-279 for the reader | R9-44 |
| M-110 | `~/.config/task-loop` is db plus cache (392 MB); split by XDG | DES-O-14 | des | O | ✅ | P3 | S | | R9-27 |
| M-111 | Reconcile-on-read by read verbs and by the dashboard | STR-O-21 | str | O | ✅ | P2 | M | read verbs must not write | R9-40 |
| M-112 | One read philosophy: delegate's strict reader | SPL-F-04 | spl | F | ✅ | P3 | S | | R9-44 |
| M-113 | One codec: delegate moves to msgspec | SPL-O-27, Q-14 | spl, rw | O | ✅/❌ | P2 | M | opposite of M-114 | DQ-11 |
| M-114 | Drop msgspec | SPL-F-05, SIM-O-36, SIM-F-30 | spl, sim | both | ❓/❌ | P3 | M | SIM-F-30 ❌ | DQ-11 |
| M-115 | Run history: the engine log is the one history; trace, manifest state, EndRec are projections | RW-05, RS5 | rw | O | ✅ | P2 | M | holds with either Q-01 answer | R9-39 |
| M-116 | One call ledger / call column | SPL-F-36, SIM-F-35 | spl, sim | F | ❓ | P3 | M | fold into M-115 | R9-39 |
| M-117 | Five per-run logs | SPL-O-26 | spl | O | ❓ | P3 | M | fold into M-115 | R9-39 |
| M-118 | Write-ahead outcome record | PIPE-O-12 | pipe | O | ✅ | P2 | S | | R9-15 |
| M-119 | Effect idempotency table test | PIPE-F-10 | pipe | F | ✅ | P2 | S | | R9-15 |
| M-120 | Effects return typed results stored with the key (`interpret.apply -> Result`) | RW-08, G23 | rw | O | ✅ | P2 | M | | R9-41 |
| M-121 | Crash after push leaves two truths | PIPE-O-22 | pipe | O | ❓ | P1 | S | test in the crash matrix | R9-15 |
| M-122 | Freeze the job bundle (immutable per job) | Z05, R2, SIM-O-05, DES-F (measure first) | zo, sim, des | both | ✅ | P1 | M | DES-F: FREEZEBUNDLE is a measurement first | tl-sqd3:BUNDLE |
| M-123 | `PLUGIN_ROOT` ambient global blocks R2; Install on Identity | STR-F-13 | str | F | ✅ | P2 | S | | tl-sqd3:BUNDLE |
| M-124 | Lane identity via symlink and `--lane N`; uv tier hidden; pid identity; pid+start-time join | DES-O-25, DES-O-26, SPL-O-09 | des, spl | O | ✅ | P2 | S | | R9-46 |
| M-125 | Claim once; the loop passes the claim to the engine | SPL-O-19, SIM-O-08 | spl, sim | O | ✅ | P2 | S | | R9-43 |
| M-126 | bd claims per machine, test first; cross-machine claims already happen (lifesim-hclf.24) | Z06, OPS-O-35 | zo, ops | O | ✅ | P1 | M | OPS-O-35: not hypothetical | tl-sqd3.9 |
| M-127 | bd as a lease server (slot heartbeats, `.beads` 203 MB); Mac/devbox slot noise via Dolt | DES-O-13, DES-O-36 | des | O | ❓ | P2 | M | | - |
| M-128 | bd sync failure is FAULT_LAND; should be transient | PIPE-F-26 | pipe | F | ✅ | P2 | S | | R9-13 |
| M-129 | Fence fails open on bd outage | PIPE-F-27 | pipe | F | ✅ | P1 | S | | tl-br2.5 |
| M-130 | Nightly bd backup rotation and a restore drill | FORE-O-29 | fore | O | ✅ | P2 | S | manual 137 MB backup exists | R9-55 |
| M-131 | bd metadata as the only authority (not-thinking item) | SIM-F | sim | F | ❓ | P3 | - | | - |
| M-132 | bd is the inbox only; the job dir owns run state | SIM-O-06 | sim | O | ❓ | P2 | M | part of SIM-O's 30% design | DQ-01 |
| M-133 | Tests must not write the live config dir; purge `cg-*` traces and `/r` runs; the config dir refuses foreign writers | FORE-O-06, FORE-F-02, STR-O-15 | fore, str | both | ✅ | P2 | S | 8 `/r` runs in production | R9-25 |
| M-134 | Incremental bd reads | FORE-F-30 | fore | F | ❓ | P3 | M | | - |
| M-135 | Slot ledger `start_id` | FORE-F-26 | fore | F | ✅ | P3 | S | | R9-46 |
| M-136 | Content-keyed check cache | SIM-O-12 | sim | O | ✅ | P2 | M | | R9-26 |

## 3. Engine structure

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-137 | Engine is a service locator; delete `carries_state` first; engine without locator | Z16, DES-F-01, STR-F-01, DES-O-18, RW-08, RS1 | zo, des, str, rw | both | ✅ | P1 | L | DES-O-18: a volume problem, move Z16 to wave 2 | tl-sqd3:STEPS |
| M-138 | Two injection dialects (145 Protocols vs `host: Any` in 36 modules) | DES-F-02, RS2, RW-03 | des, rw | both | ✅ | P2 | L | | R9-38 |
| M-139 | Drop per-step Protocols; steps take a frozen dataclass of concrete ports | Q-08, STR-F-21 (≤6 members) | rw, str | both | ✅ | P2 | M | STR-F-21 is the softer form | R9-38 / DQ-17 |
| M-140 | Reach ratchets: 139 engine attributes reached; host:Any per-file ratchet; Engine named only in engine.py; engine_case importers | STR-O-01, STR-F-12, STR-O-28, STR-O-35 | str | both | ✅ | P2 | S | cheap guard while the locator lives | R9-38 |
| M-141 | `LoopEnv` 40-44 callables into 5 ports | DES-F-03, RW-10, G08 | des, rw | both | ✅ | P2 | M | | R9-43 |
| M-142 | Git port (54-90 methods) split by consumer, ≤25 each | DES-F-04, STR-O-07, SIM-F-14, RW-03 | des, str, sim, rw | both | ✅ | P2 | M | | R9-38 |
| M-143 | `ports.py` god module split by capability; ports per module | STR-F-04, SPL-F-30 | str, spl | F | ✅ | P3 | S | | R9-38 |
| M-144 | Delete vendored `git_porcelain` (4.5k lines, unwired) and gitsim | DES-O-03, STR-O-24, SPL-F-09, SIM-O-22 | des, str, spl, sim | both | ✅ | P2 | S | SIM-O-22 (low) on gitsim | R9-36 |
| M-145 | Five ways to run a process; one runner over stream_proc | DES-F-05, RW-02, G19 | des, rw | both | ✅ | P2 | M | | R9-37 |
| M-146 | Dash wire types out of contracts | DES-F-08, DES-O-34, STR-F-10 | des, str | both | ✅ | P3 | S | | R9-40 |
| M-147 | Dash Ports: null object, DashPorts Protocol, dict round-trip; `quiet` catches SystemExit, should return Unavailable | DES-F-09, DES-F-30, STR-F-26, STR-O-17, STR-O-31 | des, str | both | ✅ | P3 | S | | R9-40 |
| M-148 | Delegate stringly shell: `Decision.as_dict`, dict-key channel `hung_words` | DES-F-10, RW-17 | des, rw | both | ✅ | P3 | S | | R9-50 |
| M-149 | `Run._finish` positionals → CallState | DES-F-11 | des | F | ✅ | P3 | S | | - |
| M-150 | `RunRequest` defined twice | DES-F-12 | des | F | ✅ | P3 | S | | R9-44 |
| M-151 | Five end-state vocabularies; one Kind table; `Kind.CUT` dead; two crash kinds | DES-F-13, DES-O-05, RW-01, RS3 | des, rw | both | ✅ | P2 | M | | R9-35 |
| M-152 | Two run entries, `begin` duplicated; two cursors (`select_step` vs `resume_decision`) | DES-F-14, G01 | des, rw | both | ✅ | P2 | S | | R9-41 |
| M-153 | The Step enum does not drive the run; one `next_step(state)` | DES-F-15, RW-08 | des, rw | both | ❓ | P2 | M | | R9-41 |
| M-154 | Module-attribute globals (`engine_lock.LOCK`, RUN_HALT, RUN_SLOT); rule against cross-module global assignment | DES-F-16, STR-F-14, G11, RW-13 | des, str, rw | both | ✅ | P2 | S | | R9-46 |
| M-155 | `MARKERS_ARGV` adapter run as a script | DES-F-17 | des | F | ✅ | P3 | S | | R9-37 |
| M-156 | `argparse.Namespace` typed Any; RunTaskArgs | DES-F-18 | des | F | ✅ | P3 | S | | R9-49 |
| M-157 | Constructors with no shape | DES-F-19 | des | F | ✅ | P3 | S | | - |
| M-158 | Three composition roots; dissolve `app/wire`; one root; real_stores fallbacks let a logic test write the real config | DES-F-20, STR-F-08, STR-O-15, SPL-F-33 | des, str, spl | both | ✅ | P2 | M | STR-O-15 overlaps M-133 | R9-38 |
| M-159 | `tl.py` outside the linter, regrew to 460 lines with importlib strings; one verb table | DES-F-21, DES-O-08, STR-O-30, SPL-F-12, RW-16 | des, str, spl, rw | both | ✅ | P3 | M | | R9-49 |
| M-160 | "contract" means six things; colliding names; app-loop contract misnamed | DES-F-22, SPL-O-11, STR-O-04 | des, spl, str | both | ✅ | P3 | S | | R9-35 |
| M-161 | The rules ratchet counts text, not invariants; invariant rule tests (WRITERS) | DES-F-23, RCA (ZOOMOUT-INVARIANTS) | des, zo | F | ✅ | P2 | M | | R9-14 |
| M-162 | Count swallowed errors (a dropped list); ~9 bd swallow helpers | DES-F-28, RW-02 | des, rw | both | ✅ | P2 | S | | R9-37 |
| M-163 | Fewer catch-alls | PIPE-O-27 | pipe | O | ❓ | P2 | M | (contra) | R9-01 |
| M-164 | Exceptions as the step protocol (`e.Blocked`, Exec as BaseException); SystemExit across layers; BdUnavailable | DES-O-02, STR-O-20 | des, str | O | ✅ | P2 | M | | R9-41 |
| M-165 | Core domain uses open dicts | DES-O-06 | des | O | ✅ | P3 | M | | R9-35 |
| M-166 | The edge is four layers deep; one `taskloop.edge` package | DES-O-07, STR-F-07 | des, str | both | ✅ | P3 | M | | - |
| M-167 | `--ports` is a speculative seam | DES-O-10 | des | O | ✅ | P3 | S | | R9-36 |
| M-168 | `import taskloop` rewrites the interpreter path; vendor prepends `sys.path` | DES-O-24, Z23, STR-F-27 | des, zo, str | both | ✅ | P3 | S | | tl-sqd3:VENDORPIN |
| M-169 | Lazy imports with no module SCC check; lazy imports fail at first use | STR-F-03, STR-O-19 | str | both | ✅/❓ | P2 | S | O ❓ | R9-14 |
| M-170 | `app/run` is a god slice; max 6 slices per module; split into close / delegation / hop | STR-F-11, STR-O-27 | str | both | ✅ | P2 | M | | R9-41 |
| M-171 | cli does app work (`cli/land.py` holds a land algorithm, twice with land_stack) | STR-F-22, RW-16 | str, rw | both | ✅ | P3 | S | | R9-49 |
| M-172 | Hook: importlib, hook_light/hook_full; hook/session to cli; SessionStart is a deploy step; it only indexes, writes nothing | STR-F-23, STR-O-34, DES-F-32, SPL-F-32 | str, des, spl | both | ✅ | P2 | S | | R9-49 |
| M-173 | Install discovery written 4-5 times; one installed-plugin reader; one delegate lookup | STR-F-25, SPL-O-18, RW-15, Z13, DES-F-39 | str, spl, rw, zo, des | both | ✅ | P2 | S | | tl-sqd3:DGLOOKUP |
| M-174 | OwnerCause / Stick dependency inverted | STR-O-05, SPL-O-08 | str, spl | O | ✅ | P3 | S | | R9-47 |
| M-175 | Import-linter: 156/232 deny entries redundant; allow-table | STR-O-03 | str | O | ✅ | P3 | S | | R9-14 |
| M-176 | Shrink or generate the per-slice import contracts; 4 layers | DES-F-36, DES-O-33, STR-F-29, SIM-F-16, SIM-O-24 | des, str, sim | both | ❓ | P3 | S | all ❓ or contra | DQ-18 |
| M-177 | Dashboard package cycle | STR-O-18 | str | O | ✅ | P3 | S | | R9-40 |
| M-178 | `RouteDelegate` is test-only; the promised field check is missing | STR-O-23 | str | O | ✅ | P2 | S | | R9-44 |
| M-179 | Port delegate's "domain touches no world" test | STR-O-25 | str | O | ✅ | P3 | S | | R9-14 |
| M-180 | Fan-out ratchet | STR-O-29 | str | O | ✅ | P3 | S | | R9-14 |
| M-181 | `trail.now` clock injected | STR-F-33 | str | F | ✅ | P3 | S | | - |
| M-182 | Delegate `app/env.py` is a locator; delegate Ctx | STR-F-16, SPL-F-27 | str, spl | F | ✅ | P3 | M | | R9-50 |
| M-183 | Delegate flat app | STR-F-18 | str | F | ❓ | P3 | M | | - |
| M-184 | Delegate contract verb depends on routing config | STR-F-15 | str | F | ✅ | P3 | S | | R9-44 |
| M-185 | 400-SLOC cap fragments concepts; raise to 800 | SIM-F-10, DES-O-27, STR-F-30 | sim, des, str | both | ✅/❓ | P2 | S | SIM-F ✅; STR-F-30: the cap manufactures the locator | DQ-12 |
| M-186 | Run the suite eagerly once (import everything) | STR-F-31 | str | F | ❓ | P3 | S | (contra) | - |
| M-187 | Delegate harness seam; table-driven spec (argv template, transcript locator, login probe), parsers stay | STR-F-32, Q-12 | str, rw | both | ❓ | P3 | M | Q-12: yes spec, no parsers | DQ-19 |
| M-188 | Dashboard back into the package (`taskloop.app.dash`) | STR-F-34, SPL-F-11 | str, spl | F | ❓ | P3 | M | (contra) vs Z08 and sibling root | - |
| M-189 | Dashboard as a client of `tl dash-feed` | STR-F-09 | str | F | ✅ | P3 | M | | R9-40 |
| M-190 | Golden tests keep dead records alive | STR-O-14 | str | O | ✅ | P3 | S | | R9-36 |
| M-191 | Dead modules: `delegate_route.py`, `checks_argv.py`, `netgate.py`, `class Args`, `dwell.sticky/last`, other dead code | RW-02, G01, G20, G21, G32, SIM-O-39 | rw, sim | O | ✅ | P3 | S | verified zero importers | R9-36 |
| M-192 | `selftest.py` ships `unittest.mock` in production code | G09 | rw | O | ❓ | P3 | S | (H) | R9-36 |
| M-193 | Counters as dicts | DES-F-42 | des | F | ✅ | P3 | S | | - |
| M-194 | `Engine.halt` creates a fresh event | DES-F-41 | des | F | ✅ | P3 | S | | - |
| M-195 | `how()` lists skills under the real CODEX_HOME | DES-F-44 | des | F | ❓ | P3 | S | | - |
| M-196 | RunFields survivability table (~75 fields) | DES-F-35, G04 | des, rw | F | ✅ | P2 | S | | R9-41 |
| M-197 | Code cites design docs that do not exist; stale docs (one-HTML-file claim, integrations.md:3) | DES-O-19, Z26, DES-F-31, DES-F-34, OPS-O-32, SPL-O (volume docs missing) | des, zo, ops, spl | both | ✅ | P3 | S | | tl-sqd3:DOCS |
| M-198 | One RepoId; five repo keys; `loop_key` copied into dash; storm keyed by path | Z18, SPL-O-16, G26 | zo, spl, rw | O | ✅ | P2 | S | | tl-sqd3:REPOID |
| M-199 | Execution differs between tests and production (flock at the safe point) | DES-O-22 | des | O | ❓ | P2 | S | | R9-15 |
| M-200 | One Env substrate for the dash; one lane view model | SPL-F-10, SPL-F-17 | spl | F | ✅ | P3 | S | | R9-40 |
| M-201 | `stop_recorded` | SPL-F-08 | spl | F | ✅ | P3 | S | | - |
| M-202 | Fold `domain` into app | SPL-F-34 | spl | F | ❓ | P3 | M | (contra) | - |
| M-203 | Repeated shapes: same seven shapes written 30-100 times; fix shapes before rewriting modules | RW §0, RS1-RS12 | rw | O | ✅ | P2 | - | framing for theme T7 | REVIEW9 epic |

## 4. Pipeline failure modes

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-204 | The catch-all logs no traceback | PIPE-F-01 | pipe | F | ✅ | P1 | S | | R9-01 |
| M-205 | ENGINE_CRASH retried hourly forever | PIPE-F-02, PIPE-O-03 | pipe | both | ✅ | P1 | S | (fixed) CRASHCAP: 3 tries, same fingerprint parks at once | CRASHCAP |
| M-206 | CRASHPARK swallows Fenced | PIPE-O-04 | pipe | O | ✅ | P1 | S | (fixed) CRASHCAP: Fenced is not parked | CRASHCAP |
| M-207 | ValueError from land bypasses CRASHPARK | PIPE-O-05, DES-O-23 | pipe, des | O | ✅ | P1 | S | (stale?) check against CRASHCAP | R9-01 |
| M-208 | Enum-keyed tables must be total (rule test over every `dict[Enum, ...]`); match + `assert_never`; KEYERR regression test | PIPE-F-03, PIPE-O-07, PIPE-O-21, FORE-F-25, FORE-O-38 | pipe, fore | both | ✅ | P1 | S | KEYERR (0.23.298) fixed one table; no rule yet | R9-14 |
| M-209 | In-lock STALE livelock with no counter; STALE test is str-keyed | PIPE-O-01, PIPE-F-04, PIPE-F-30 | pipe | both | ✅ | P1 | S | | R9-13 |
| M-210 | Delete the OpenCode lane | SIM-F-28 | sim | F | ❓ | P2 | M | (contra) also removes M-056 | DQ-20 |
| M-211 | Storm detector is factory death: loops exit; nap instead and quarantine the one fingerprint | PIPE-O-02, PIPE-O-28, OPS-O-13 | pipe, ops | O | ✅ | P1 | S | | R9-09 |
| M-212 | Delete the heuristics (storm, stuck, ...) | SIM-O-19 | sim | O | ❓ | P2 | M | (contra) to M-211 | - |
| M-213 | Transient pauses never use the attempt cap | PIPE-O-09 | pipe | O | ✅ | P1 | S | CRASHCAP covers engine_crash only | R9-01 |
| M-214 | No run deadline; bead wall cap; RUN_WALL_S 1200 | PIPE-F-16, OPS-F-14, OPS-F-09 | pipe, ops | F | ✅ | P1 | S | OPS-F-09 ❓ on the number | R9-13 |
| M-215 | Land: no max iterations, LandTry n=1, lock waiters unbounded; LandCaps | PIPE-O-14, PIPE-O-15, PIPE-O-16, PIPE-F-25 | pipe | both | ✅ | P1 | S | | R9-13 |
| M-216 | No lane supervisor; loops exit 0; "supervised loops" is false; `tl factory keep` | PIPE-F-08, PIPE-O-17, OPS-F-17, OPS-O-15, DES-O-11 | pipe, ops, des | both | ✅ | P1 | M | | R9-10 |
| M-217 | Crashed lane exit detail empty; no crash event; incidents.jsonl | PIPE-F-09, PIPE-F-17, PIPE-O-29 | pipe | both | ✅ | P2 | S | | R9-01 |
| M-218 | Four crash classifications → one `classify_crash`; Kind family attribute; split Problem into Retry / Fixable | PIPE-F-19, PIPE-O-08, PIPE-O-06, PIPE-F-13 | pipe | both | ✅ | P2 | M | | R9-35 |
| M-219 | Retry history read under `suppress` | PIPE-F-14 | pipe | F | ✅ | P2 | S | | R9-01 |
| M-220 | Settle swallows OSError | PIPE-F-18 | pipe | F | ✅ | P2 | S | | R9-01 |
| M-221 | A dirty slot is reported as stale base | PIPE-F-20 | pipe | F | ✅ | P2 | S | | R9-13 |
| M-222 | Parks written at two sites | PIPE-F-21 | pipe | F | ✅ | P2 | S | | R9-33 |
| M-223 | Land counters kept in memory | PIPE-F-22 | pipe | F | ❓ | P3 | S | | - |
| M-224 | Delete `safe_point("land")`; hop runs land on the newest code; hop cap 1 per run, never at land | PIPE-F-23, PIPE-O-35, OPS-O-26 | pipe, ops | both | ✅ | P1 | S | | tl-br2.7 |
| M-225 | Delete the mid-bead hop entirely (reload, reexec, TL_REEXEC) | SIM-F-03, Q-10, Z05 | sim, rw, zo | both | ✅ | P1 | M | after M-224 and M-122 | tl-sqd3:BUNDLE / DQ-04 |
| M-226 | Crash-after-exec fallback never fires | PIPE-F-24 | pipe | F | ❓ | P2 | S | | R9-15 |
| M-227 | Already-landed detected by subject line; squash `already()` | PIPE-F-11, PIPE-O-23 | pipe | both | ❓ | P2 | S | | R9-42 |
| M-228 | A fenced run never saves its work | PIPE-F-12 | pipe | F | ❓ | P2 | S | | tl-br2.5 |
| M-229 | Delete `Placing.INSIDE` (the in-lock optimistic gate) | PIPE-F-15 | pipe | F | ❓ | P2 | M | (contra) opposite of M-230 | DQ-09 |
| M-230 | Delete the optimistic outside-lock gate | PIPE-O-25 | pipe | O | ❓ | P2 | M | (contra) opposite of M-229 | DQ-09 |
| M-231 | Delete land fix rounds | PIPE-O-26 | pipe | O | ❓ | P2 | M | (contra) | - |
| M-232 | Closer ignores SIGTERM | PIPE-F-28 | pipe | F | ❓ | P2 | S | | R9-15 |
| M-233 | Cold uv start loses up to 300 s; cold uv in hooks; prewarm then `UV_OFFLINE=1` | PIPE-F-29, OPS-F-24, FORE-O-25 | pipe, ops, fore | both | ❓ | P2 | S | test with network blocked | R9-26 |
| M-234 | Reopen semantics | PIPE-F-32 | pipe | F | ❓ | P3 | S | | - |
| M-235 | The landed override excludes ENGINE_CRASH | PIPE-F-33 | pipe | F | ✅ | P2 | S | check against CRASHCAP | R9-01 |
| M-236 | Fenced handled in interpret | PIPE-F-34 | pipe | F | ❓ | P3 | S | | - |
| M-237 | Push classification reads the whole tail | PIPE-O-10 | pipe | O | ✅ | P2 | S | | R9-42 |
| M-238 | Exit 78 decided by log scraping | PIPE-O-11 | pipe | O | ✅ | P2 | S | | R9-01 |
| M-239 | `Unknown(raw)` stop policy | PIPE-O-19 | pipe | O | ✅ | P2 | S | | R9-29 |
| M-240 | Two disposition tables disagree | PIPE-O-20 | pipe | O | ✅ | P1 | S | see M-262 for the verified cross-repo case | R9-29 |
| M-241 | Crash-matrix gate test; kill -9 at every recorded transition (nightly) | PIPE-O-24, FORE-O-36, RW-08 | pipe, fore, rw | O | ✅ | P1 | M | 36 lost runs (tl-br2.20) | R9-15 |
| M-242 | Dashboard blind-spot ratchet | PIPE-O-30 | pipe | O | ✅ | P3 | S | | R9-40 |
| M-243 | Main checkout drift; ff-only update | PIPE-O-31, OPS-F-36, OPS-O-34 | pipe, ops | both | ✅ | P2 | S | OPS-F ❓ | R9-27 |
| M-244 | `blocked_for(kind: str)`; Blocked constructors | PIPE-O-32, PIPE-O-33, RW-01 | pipe, rw | O | ✅ | P2 | S | | R9-35 |
| M-245 | Pause keys by (producer, reason) | PIPE-O-34 | pipe | O | ✅ | P2 | S | | R9-29 |
| M-246 | Judge hangs while holding the land lock | PIPE-O-36 | pipe | O | ❓ | P2 | S | | R9-13 |
| M-247 | TLS error regex | PIPE-O-37 | pipe | O | ❓ | P3 | S | | - |
| M-248 | `fails_to_stop=2` | PIPE-O-38 | pipe | O | ❓ | P3 | S | | - |
| M-249 | wip_push after a fix round | PIPE-O-39 | pipe | O | ✅ | P3 | S | | R9-42 |
| M-250 | `Gate.green` builds a clean tree per call | PIPE-F-05 | pipe | F | ❓ | P3 | S | | - |
| M-251 | `nodename` as host identity | PIPE-F-07 | pipe | F | ❓ | P3 | S | | - |
| M-252 | 12 h slot set-aside is a capacity cliff; exponential 30/60/120 with probe | FORE-O-30 | fore | O | ✅ | P2 | S | | R9-56 |
| M-253 | Interrupted call skips `calls.end`; `reload.py:105` records "moved" before the hand-over can fail | G02, G04 | rw | O | ❓ | P2 | S | (H) one test each | R9-15 |
| M-254 | Settle matches `why` text; prose regex as protocol | G08, RS12 | rw | O | ✅ | P2 | M | | R9-43 |

## 5. Delegate and the worker-run contract

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-255 | One stop authority / one ladder | Z07 | zo | - | ✅ | P2 | M | | tl-sqd3:STOPCAUSE / DG-ONELADDER |
| M-256 | Delegate returns the disposition (reverse of Z07); client is 2.7k lines | DES-O-17 | des | O | ❓ | P2 | M | (contra) | DQ-10 |
| M-257 | Delete task-loop's stop policy; a 3-line mapping | SIM-O-03 | sim | O | ✅ | P2 | S | same direction as M-256 | DQ-10 |
| M-258 | Delegate owns all lane retries; task-loop waits for `retry_at` except engine-made stops | Q-03 | rw | O | ✅ | P2 | M | | DQ-10 |
| M-259 | In-call retries invisible to task-loop; report `RunResult.attempts` | RW-17 | rw | O | ✅ | P2 | S | additive, measures double retry | R9-50 |
| M-260 | Real contract list | Z09 | zo | - | ✅ | P2 | S | | tl-sqd3:CONTRACTLIST |
| M-261 | worker-run as one wire package owned by delegate; schema generator identical in both repos; reason table from one source | SPL-F-01, SPL-O-01, RW-11, DES-O-16, STR-O-32 | spl, rw, des, str | both | ✅ | P1 | M | DES-O-16: the 13-line v3 note is owned by the consumer | R9-44 |
| M-262 | Permanence conflict: `no_lane` and `crash` transient in task-loop, `needs_owner` in delegate's contract | RW-11 (V) | rw | O | ✅ | P1 | S | verified bug | R9-29 |
| M-263 | Live-line tag `"k"` vs `"kind"` patched by two dash shims | RW-11, G28 | rw | O | ✅ | P2 | S | | R9-44 |
| M-264 | Delegate as an in-process library | SPL-F-02, DES-F-38, SPL-O-13, DES-O-31, SIM-O-32 | spl, des, sim | both | ✅/❌ | P1 | L | F ✅/❓, O ❓/❌ | DQ-03 |
| M-265 | One plugin (R4), delegate stays a child process | R4, SPL-F-22, SPL-O-12, SIM-F-09, SIM-O-21, DES-F-38, Q-02 | zo, spl, sim, des, rw | both | ✅ | P1 | L | broad agreement | tl-sqd3:ONEPLUGIN / DQ-02 |
| M-266 | Delete agent-runs v1 | Z10, SIM-F-21 | zo, sim | F | ✅/❓ | P3 | S | FORE-O-32 wants it kept as a feed | tl-sqd3:DG-AGENTRUNS |
| M-267 | Keep agent-runs v1 as the multi-machine run feed | FORE-O-32 | fore | O | ❓ | P3 | S | (contra) test: can `status --history` carry it | tl-sqd3:DG-AGENTRUNS |
| M-268 | Delete delegate cockpit, doctor, onboard, dwell, statusline, codex_policy | SIM-F-21 | sim | F | ✅ | P2 | M | | DQ-20 |
| M-269 | Merge the two doctors; cockpit into the dashboard | SPL-O-33, SPL-O-32 | spl | O | ❓ | P3 | M | | - |
| M-270 | Delegate status is one record | SIM-F-22 | sim | F | ✅ | P2 | S | | R9-30 |
| M-271 | Delete delegate's health breaker | SIM-F-27 | sim | F | ❓ | P3 | S | (contra) | - |
| M-272 | Delegate supervisor re-implements `stream_proc.run`; typed Outcome; pure decide | RW-17, G29 | rw | O | ✅ | P2 | M | | R9-50 |
| M-273 | Two schedulers of capacity (delegate lanes vs task-loop loops) | SPL-O-30 | spl | O | ❓ | P2 | M | | - |
| M-274 | One worker env builder | SPL-F-19 | spl | F | ✅ | P2 | S | ties to M-015 | R9-02 |
| M-275 | Hold a writer slot at claim time (reserve verb) | FORE-O-12 | fore | O | ❓ | P2 | M | 55 `busy` refusals on 11-01 | R9-19 |
| M-276 | Account-wide lane accounting across both machines | FORE-O-13, OPS-F (one subscription, two machines) | fore, ops | both | ❓ | P2 | M | | R9-19 |
| M-277 | A second writer family kept warm (~10% of light beads) | FORE-O-14 | fore | O | ✅ | P1 | S | 154/154 runs on one lane; review lost independence | R9-20 |
| M-278 | Per-model scorecard; model diversity | FORE-O-21, FORE-F-27 | fore | both | ✅/❓ | P2 | S | | R9-53 |
| M-279 | Stop reading other tools' private state (opencode.db, transcripts, delegate history); delete `adapters/opencode.py` | Q-06, SPL-F-16, SPL-O-14 | rw, spl | both | ✅ | P2 | S | CLAUDE.md already forbids it | R9-44 |
| M-280 | Vendor drift between the two apps; VENDORPIN; `vendor.py` to shelf | Z23, SPL-F-13, SPL-O-28 | zo, spl | both | ✅ | P3 | S | | tl-sqd3:VENDORPIN |
| M-281 | Outcome / Result types joined across repos | SPL-O-25 | spl | O | ✅ | P3 | M | | R9-44 |
| M-282 | Usage series as a shared module | SPL-F-18 | spl | F | ❓ | P3 | S | | - |

## 6. Release and operations

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-283 | Release cadence budget: batch (train ≤1 per 2 h, 2/day, 1/hour cap) | DES-F-24, SIM-F-24, SIM-O-29, FORE-O-02, DES-O-29, OPS-F-31, FORE-F-31 | des, sim, fore, ops | both | ✅/❓ | P1 | S | 22-69 releases/day; F ✅ (rank 0), OPS-F and DES-O ❓ owner | R9-16 / DQ-06 |
| M-284 | Release vs promote channel; Mac standing pin; devbox canary ring | OPS-O-01, OPS-O-25, OPS-O-37, FORE-O-02 | ops, fore | O | ✅ | P1 | M | | R9-16 |
| M-285 | Factory breaker plus version canary; a FAULT-breaking version is marked bad | FORE-F-03, OPS-O-14 | fore, ops | both | ✅ | P1 | S | | R9-17 |
| M-286 | Wire `tl selftest` into the move (`Installs.target`), failures into bad-versions | FORE-O-09, FORE-F-17 | fore | both | ✅ | P1 | S | docstrings contradict | R9-17 |
| M-287 | Delete the selftest gate | SIM-O-38 | sim | O | ❓ | P3 | S | (contra) to M-286 | - |
| M-288 | Replay corpus of real runs as a release gate; `tl replay` | FORE-O-15, FORE-F-06 | fore | both | ✅ | P2 | M | | R9-53 |
| M-289 | Nightly canary bead on the real lane | FORE-O-16 | fore | O | ✅ | P2 | S | | R9-53 |
| M-290 | Release runs the suite 3x; the cache key is the post-bump tree; release reruns the suite inside the land lock; cache records container suite | OPS-F-01, OPS-O-23, OPS-O-31 | ops | both | ✅ | P1 | S | | R9-26 |
| M-291 | Release gate is red more often than green; a release ledger; 353 red logs | OPS-F-02, DES-O-15 | ops, des | both | ❓ | P1 | S | | R9-23 |
| M-292 | Flake ledger from red suite logs; quarantine ratchet; junit output | OPS-O-04, FORE-F-05, FORE-O-07, OPS-F-04 | ops, fore | both | ✅ | P1 | M | real tests are red most | R9-23 |
| M-293 | Per-test time limits flake under load; `TL_TIME_SCALE` | OPS-F-03, OPS-O-05 | ops | both | ✅ | P1 | S | | R9-23 |
| M-294 | Red logs written twice | OPS-F-05 | ops | F | ✅ | P3 | S | | R9-27 |
| M-295 | CI red for 300 runs: gate on it or delete; delete the unit job (third run nobody reads) | OPS-O-02, OPS-F-11 | ops | both | ✅ | P1 | S | same goal, different cut | R9-24 / DQ-16 |
| M-296 | macOS never tested in CI; macos-latest job; compatibility matrix | OPS-O-03, FORE-F-24 | ops, fore | both | ✅ | P1 | S | | R9-24 |
| M-297 | Nightly race / live job | OPS-F-12 | ops | F | ✅ | P2 | S | | R9-24 |
| M-298 | Goldens belong in rules | OPS-F-13 | ops | F | ✅ | P3 | S | | - |
| M-299 | Suite lock wait; release locks | OPS-F-15, OPS-O-42 | ops | both | ✅/❓ | P2 | S | | R9-26 |
| M-300 | Do not spend on suite speed | OPS-F-32, OPS-O-33 | ops | both | ❌ | P3 | - | both reject the speed-up; FORE-F-36 wants a time governor | - |

| M-301 | Suite time governor | FORE-F-36 | fore | F | ✅ | P2 | S | | R9-23 |
| M-302 | Two release pipelines | OPS-O-24 | ops | O | ✅ | P2 | S | | R9-48 |
| M-303 | Mac release delivery test | Z21 | zo | - | ✅ | P2 | S | | tl-sqd3:MACUPDATE-TEST |
| M-304 | Plugin cache 1.8 GB with no GC; disk forecast for caches tl does not own | OPS-F-07, OPS-O-18, FORE-O-03 | ops, fore | both | ✅ | P1 | S | prints commands, deletes nothing of others | R9-27 |
| M-305 | Prune suite logs, loop logs, /tmp debris, slot-state/NuGet, per lane | OPS-F-06, OPS-O-19, OPS-O-20, OPS-O-21, OPS-O-22, OPS-O-44 | ops | both | ✅ | P2 | S | | R9-27 |
| M-306 | One retention table; `keep_days` has two meanings; 7 vs 30 days; runs/ size; delegate retention and history chunks | FORE-F-04, OPS-F-29, OPS-F-30, OPS-F-33, OPS-F-37, FORE-F-37 | fore, ops | F | ✅ | P2 | S | OPS-F-30 ❓ | R9-27 |
| M-307 | Low disk → wait, not exit 0; refuse on low RAM | OPS-O-38, OPS-O-39, FORE-O-03 | ops, fore | O | ✅ | P1 | S | | R9-09 |
| M-308 | caffeinate per lane | Z22 | zo | - | ✅/❓ | P2 | S | OPS-O-28: supervisor owns it | tl-sqd3:CAFFEINATE |
| M-309 | caffeinate owned by the supervisor; `caffeinate -s` | OPS-O-28, OPS-F-16 | ops | both | ✅/❓ | P2 | S | | R9-10 |
| M-310 | Rename lanes to loops; "lane" has a fourth meaning (lifesim `lane:` labels) | Z22, FORE-F-29 | zo, fore | F | ✅ | P3 | S | | tl-sqd3:LANENAME |
| M-311 | LaunchAgent on the Mac; drop the no-OS-integration rule there | OPS-O-16 | ops | O | ✅ | P1 | M | | R9-10 / DQ-08 |
| M-312 | Dashboard decays; rebind | OPS-O-17 | ops | O | ✅ | P3 | S | | R9-54 |
| M-313 | Push notification (ntfy) for asks, storms, factory stop | PIPE-O-18, OPS-F-18, FORE-F-21 | pipe, ops, fore | both | ✅ | P2 | S | | R9-11 |
| M-314 | Factory start / stop / keep from the phone | OPS-F-34, OPS-O-15 | ops | both | ✅ | P2 | M | | R9-10 |
| M-315 | Peers view (other host's loops) | OPS-F-19 | ops | F | ✅ | P3 | M | | tl-4af |
| M-316 | `tl pin` at Night start | OPS-F-20 | ops | F | ✅ | P2 | S | | R9-16 |
| M-317 | `reload_fallback` 120 s | OPS-F-21 | ops | F | ✅ | P3 | S | | tl-br2.7 |
| M-318 | Load awareness: host budget (max_lanes, resources, load_ceiling); load-aware admission; nice / taskpolicy | OPS-F-22, OPS-O-07, OPS-O-09, OPS-O-10, FORE-F-22, FORE-O-11, GH:CHECKNICE | ops, fore, zo | both | ✅ | P1 | M | Mac load 281 | GH:LOADCAP |
| M-319 | Per-slot .NET daemon multiplication; dotnet lease 2, DOTNET_PROCESSOR_COUNT=4, CsCheck_Threads=1 | OPS-O-06, GH:LOADCAP, GH:DESIGNTESTCAP | ops, zo | O | ✅ | P1 | S | profile-only, 281 → ~40 | GH:LOADCAP |
| M-320 | Two Unity limiters disagree (LIFESIM_UNITY_SLOTS 5 vs 1) | OPS-O-08 | ops | O | ✅ | P2 | S | | GH:LOADCAP |
| M-321 | Fixed budgets under load; adaptive concurrency | OPS-O-11, FORE-F-23 | ops, fore | both | ❓ | P3 | M | | - |
| M-322 | writer_split uses max; use median | OPS-O-12 | ops | O | ✅ | P3 | S | | - |
| M-323 | Sleep budget | OPS-O-27 | ops | O | ❓ | P3 | S | | - |
| M-324 | Hook timeouts | OPS-O-29 | ops | O | ❓ | P3 | S | | - |
| M-325 | Mac RLIMIT; macOS free pages metric | OPS-F-23, OPS-F-08 | ops | F | ❓ | P3 | S | | - |
| M-326 | Document `TL_RELEASE_REEXEC` | OPS-F-25 | ops | F | ✅ | P3 | S | | tl-sqd3:DOCS |
| M-327 | Co-author trailer on engine commits | OPS-F-26 | ops | F | ✅ | P3 | S | | - |
| M-328 | Marketplace ledger | OPS-F-27 | ops | F | ❓ | P3 | S | | - |
| M-329 | Doctor ops checks; capability manifest and secret diagnostics; clone freshness | OPS-F-28, FORE-F-18, FORE-F-13 | ops, fore | F | ✅ | P2 | S | | R9-57 |
| M-330 | Owner time zone for "night" and "daily"; DST | FORE-O-37, OPS-F-35 | fore, ops | both | ✅ | P3 | S | OPS-F ❓ | - |
| M-331 | rusage accounting per run | OPS-O-40 | ops | O | ✅ | P3 | S | | - |
| M-332 | Gate in a fresh worktree rebuilds the Unity Library | OPS-O-41 | ops | O | ❓ | P1 | S | measure | GH:GATEHOST-MEASURE |
| M-333 | More lanes than slots | OPS-O-43 | ops | O | ✅ | P3 | S | | - |
| M-334 | Not-thinking ops risks: vendor CLIs unpinned, ISP/GitHub SPOF, one beads backup, thermal, no cost ceiling, release machine = dev machine | OPS-F (not-thinking) | ops | F | ❓ | P2 | - | | - |
| M-335 | Version-skew census per host (loop engine, shim, hook, newest installed, newest released) | FORE-O-39, Z14, Z21 | fore, zo | O | ✅ | P2 | S | shim on 0.23.271 vs 0.23.301 | R9-57 |
| M-336 | Devbox as overflow gate host (EXECIDENT, GATEHOST-AUTH, GATECLEAN, RECEIPT, LANE, DEVBOX) | GH part b, FORE-F-12 | zo, fore | F | ✅/❓ | P2 | L | FORE-F-12 ❓ | GH:EXECIDENT.. |
| M-337 | Delete container execution | SIM-O-11 | sim | O | ❓ | P2 | M | (contra) vs gate-host executor identity | DQ-21 |
| M-338 | Delete check lanes / resources | SIM-F-34 | sim | F | ❓ | P2 | M | (contra) vs gate-host lease | DQ-21 |
| M-339 | GitHub merge queue plus a self-hosted runner | SIM-O-35 | sim | O | ❓ | P2 | L | (contra) | DQ-05 |
| M-340 | Generate PEP 723 headers | SPL-F-26 | spl | F | ✅ | P3 | S | | - |
| M-341 | metrics.jsonl | FORE-F-20 | fore | F | ✅ | P3 | S | | R9-53 |
| M-342 | Reflect digest: measure, then revive or delete; keep as a pure cluster + loop chore | FORE-F-15, FORE-O-22, SIM-F-06, SIM-O-17, Q-13 | fore, sim, rw | both | ❓ | P3 | S | last Reflect bead 10-27 | R9-52 |
| M-343 | Reflect learns per machine and double-files; key by bd label | FORE-O-23 | fore | O | ✅ | P3 | S | | R9-52 |
| M-344 | Nightly scorecard as a bd comment on tl-bxk.10; roadmap M2 is bypassed | FORE-O-26 | fore | O | ✅ | P2 | S | | tl-bxk.10 |
| M-345 | Net-negative line ratchet | SIM-O-26 | sim | O | ✅ | P1 | S | | R9-14 |
| M-346 | Phase-0 usage census: which paths fire (hop, land-stack, look, reflect, OpenCode) before rewriting | SIM-O-27, RW §4 | sim, rw | O | ✅ | P1 | S | | R9-52 |

## 7. Extraction, join, delete

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-347 | Delete `look` / fold look into review | SIM-F-05, SIM-O-28 | sim | both | ✅/❓ | P2 | M | O ❓ | DQ-20 |
| M-348 | Look gallery path into its own package | Q-15 | rw | O | ✅ | P3 | M | alternative to M-347 | DQ-20 |
| M-349 | Delete land-stack | SIM-F-07 | sim | F | ✅ | P2 | M | removes M-002 too | DQ-20 |
| M-350 | Delete the M2 report, traces, report verbs; delete `planner.py` report | SIM-F-08, SIM-O-18, Q-13 | sim, rw | both | ✅ | P3 | S | | R9-52 |
| M-351 | 47 verbs down to 12 (F) or 8 (O) | SIM-F-04, SIM-O (8 verbs) | sim | both | ✅ | P2 | M | | R9-49 |
| M-352 | Asks as a row; slots as worktree dirs plus an attempt row | SIM-F-11, SIM-F-12 | sim | F | ✅ | P2 | M | depends on DQ-01 | DQ-01 |
| M-353 | Dashboard commands go through `tl` (POST spawns tl) | Z08, SIM-F-17 | zo, sim | F | ✅ | P2 | M | | tl-sqd3:DASHCMD |
| M-354 | Dashboard read-only plus answer | SIM-O-16, DES-O-30 | sim, des | O | ✅/❓ | P2 | S | FORE-F-33 ❌ | DQ-22 |
| M-355 | Control plane is bd labels; dashboard one writer among others | FORE-O-33 | fore | O | ❓ | P2 | M | test latency first | DQ-22 |
| M-356 | Delete status mirroring | SIM-F-18 | sim | F | ✅ | P3 | S | | - |
| M-357 | Delete shared notes, ADR, handoff, waits, stuck | SIM-F-19 | sim | F | ✅ | P3 | M | | DQ-20 |
| M-358 | Profile ≤40 fields; config ≤25 knobs; config is a junk drawer | SIM-F-23, SIM-O-10, SIM-O-40 | sim | both | ✅ | P2 | M | | - |
| M-359 | Delete the PreToolUse hook | SIM-F-25 | sim | F | ❓ | P3 | S | (contra) to M-006 | - |
| M-360 | Delete checkpoints | SIM-F-26 | sim | F | ❓ | P3 | M | (contra) | - |
| M-361 | Delete the planner | SIM-F-29 | sim | F | ❌ | - | - | rejected by its author | - |
| M-362 | Devbox does not loop / no devbox factory | SIM-F-31, SIM-O-37 | sim | both | ❓ | P2 | - | (contra) to FORE-F-32 | DQ-23 |
| M-363 | Own repos per host | FORE-F-32 | fore | F | ✅ | P2 | S | | DQ-23 |
| M-364 | Split one repo between machines by capability (`needs:unity` on the Mac) | FORE-O-20 | fore | O | ✅ | P2 | S | (contra) to symmetric | DQ-23 |
| M-365 | Delete events/track | SIM-F-32 | sim | F | ✅ | P3 | M | | - |
| M-366 | Delete reconcile observe | SIM-F-33 | sim | F | ✅ | P3 | S | | - |
| M-367 | Delete the matchers.py convention | SIM-F-37 | sim | F | ✅ | P3 | S | | - |
| M-368 | One delivery mode | SIM-O-14 | sim | O | ❓ | P2 | M | | - |
| M-369 | One loop process per repo, no lanes | SIM-O-15 | sim | O | ❓ | P2 | M | (contra) vs Z22 | - |
| M-370 | Call memo keyed by id | SIM-O-20 | sim | O | ✅ | P3 | S | | - |
| M-371 | A fresh worktree per bead | SIM-O-31 | sim | O | ❌ | - | - | rejected | - |
| M-372 | The orchestrating session is the loop | SIM-O-33 | sim | O | ❓ | P3 | - | | - |
| M-373 | Sampled review | SIM-O-34 | sim | O | ❓ | P3 | - | | - |
| M-374 | Engine v2 written beside the old one (phases 0-9) | SIM-O-09 | sim | O | ✅/❓ | P1 | L | RW §2.0 prefers a strangler inside the current Engine | DQ-24 |
| M-375 | Shelf packages: shell-verdict, claude-plugin module, factory-rules preset, plugin-release, any-beads, reason enum generator | SPL-F-14, SPL-F-15, SPL-F-20, SPL-F-29, SPL-F-31, SPL-O-06 | spl | both | ✅ | P3 | M | | - |
| M-376 | Shelf packages, low confidence: check executor, tests/world, worktree-pool, action-cache, mailbox | SPL-F-23, SPL-F-25, SPL-O-20, SPL-O-21, SPL-O-22 | spl | both | ❓ | P3 | M | | - |
| M-377 | Stop extracting two-consumer packages | SPL-O-31 | spl | O | ❓ | P3 | - | (contra) | - |
| M-378 | Dashboard as its own plugin | SPL-O-35 | spl | O | ❓ | P3 | M | | - |
| M-379 | MemoryBeads into adapters | SPL-O-34 | spl | O | ✅ | P3 | S | | - |
| M-380 | Cross-repo bead "train" (shelf, then tl, then delegate legs) | FORE-O-08 | fore | O | ✅ | P2 | M | | - |

## 8. Rewrite candidates (lens 9)

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-381 | REWRITE-VOCAB: one StrEnum vocabulary (Kind, Step, Flow, Cause, CheckStatus, SlotState, LoopExit); `blocked_for(kind: Kind)`; rule bans string kinds in app | RW-01, RS3 | rw | O | ✅ | P2 | M | 62 literal sites (V); first in the rewrite order | R9-35 |
| M-382 | REWRITE-SUBSTRATE: one process runner, git `_run`, lock, signal scope, bd client with typed errors and a default timeout | RW-02, RS8 | rw | O | ✅ | P2 | L | bd timeout unbounded today (H) | R9-37 |
| M-383 | REWRITE-PORTS: Git split into five sub-ports; land Protocol sums deleted | RW-03 | rw | O | ✅ | P2 | L | | R9-38 |
| M-384 | REWRITE-STORES: one store layer with Doc/Log, registry table, `fake_stores()` | RW-04 | rw | O | ✅ | P1 | M | = M-082 + M-086 | R9-33 |
| M-385 | REWRITE-FACTLOG: RunTrace as a projection of the engine log | RW-05 | rw | O | ✅ | P2 | M | = M-115 | R9-39 |
| M-386 | REWRITE-READMODEL: the engine publishes projections; dashboard renders; `stuck_of` and `ready_count` re-derivations deleted | RW-06, RS9 | rw | O | ✅ | P2 | M | | R9-40 |
| M-387 | REWRITE-STAGE: one worker-stage primitive; rounds return StageResult; `replan.md` written once | RW-07, RS4 | rw | O | ✅ | P2 | L | | R9-41 |
| M-388 | REWRITE-CORE: run as a state machine over StepResult and a result-returning effect outbox | RW-08, R5, SIM-F-02, SIM-O-02 | rw, zo, sim | both | ✅ | P1 | L | only after 01/03/04/05/07 | tl-sqd3:STEPS |
| M-389 | REWRITE-LAND: land as a phase machine over LandPorts; ≤15 files | RW-09, SIM-F-13, SIM-O-13 | rw, sim | both | ✅ | P2 | L | after Z01-03 | R9-42 |
| M-390 | REWRITE-LOOP: pure pick and settle over a per-tick snapshot | RW-10 | rw | O | ✅ | P2 | M | | R9-43 |
| M-391 | REWRITE-WIRE: one worker-run package; reasons from one table | RW-11 | rw | O | ✅ | P1 | M | = M-261..263 | R9-44 |
| M-392 | REWRITE-CHECKS: one CheckEnv, pure round planner, resolver chain; first a key-equality test (delivery `check_env()` vs round `bead_env`) | RW-12 | rw | O | ✅ | P1 | S (test) / M | possible key mismatch: fail-closed reruns or wrong-env evidence | R9-45 |
| M-393 | REWRITE-SLOTS: Slot aggregate; one `profile_at(git, rev)`; one branch-name module | RW-13, SPL-O-03, RS7 | rw, spl | O | ✅ | P1 | S (profile) / M | profile reader needed by PUSHBASE | R9-32 / R9-46 |
| M-394 | REWRITE-OWNERCMD: owner verbs as typed commands; ledger before effect | RW-14 | rw | O | ✅ | P1 | S (tests) / M | | R9-47 |
| M-395 | REWRITE-RELEASEOUT: release pipeline to `dev/`; one plugin-install lookup in src | RW-15, SIM-F-15, SIM-O-29, SPL-F-21, SPL-O-07 | rw, sim, spl | both | ✅ | P3 | M | | R9-48 |
| M-396 | REWRITE-TLTABLE: one verb table; cli parses and prints only | RW-16 | rw | O | ✅ | P3 | M | = M-159 | R9-49 |
| M-397 | REWRITE-DGRUN: delegate run path on stream_proc, typed Outcome, attempts reported | RW-17 | rw | O | ✅ | P2 | M | | R9-50 |
| M-398 | REWRITE-PROMPTS: prompts as template files with byte-equal goldens | RW-18 | rw | O | ✅ | P3 | S | | R9-51 |
| M-399 | Structured worker answers replace prose regex where we own the schema (review first) | Q-05, RS12 | rw | O | ✅ | P2 | M | measure send-back for a week | DQ-25 |
| M-400 | Dashboard JS a pure renderer, after the read model | Q-11 | rw | O | ✅ | P3 | M | | R9-40 |
| M-401 | Strangler rule: each slice one release, records keep a reader for the old version, land and push touched last and alone | RW §2.0 | rw | O | ✅ | P1 | - | governs every R9 rewrite bead | REVIEW9 epic |

## 9. Foresight and scale

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-402 | Quota-aware admission: hold claims when the weekly window runs out before reset; typed `quota` wait | FORE-O-01, FORE-F-09 | fore | both | ✅ | P1 | M | 1.2 pt/h burn; 35% busy/no_lane (F) | R9-19 |
| M-403 | Per-bead token budget on by default (fresh tokens, window %); dollars are always 0 | FORE-O-10, FORE-F-10 | fore | both | ✅ | P1 | S | tl-7y6.4.12 stores, caps nothing | R9-19 |
| M-404 | Context diet | FORE-F-11 | fore | F | ✅ | P2 | M | | - |
| M-405 | Cross-host evidence feed `refs/factory/<host>` | FORE-F-01 | fore | F | ✅ | P1 | M | | GH:GATEHOST-RECEIPT |
| M-406 | Host presence bead per host; one dashboard for both hosts | FORE-O-19, FORE-F-16 | fore | both | ✅/❓ | P2 | S | | tl-4af |
| M-407 | Queue aging; priority deflation (34% of open are P1) | FORE-F-07, FORE-O-27 | fore | both | ✅ | P2 | S | | R9-60 |
| M-408 | Order as data: review "Order:" lines become bd deps; dependency-aware rank | FORE-O-04, FORE-F-08 | fore | both | ✅ | P1 | S | 51 children, 0 deps | R9-21 |
| M-409 | Intake budget for agent-filed beads (deferred, `from-review`, K a day) | FORE-O-05 | fore | O | ✅ | P2 | S | applies to this review | R9-22 |
| M-410 | Automatic grooming report (stale in_progress, unused statuses, duplicates, dead Touches) | FORE-O-17, FORE-F-14 | fore | both | ✅ | P2 | M | | R9-60 |
| M-411 | Actor and identity hygiene for `bd create` | FORE-O-18 | fore | O | ✅ | P3 | S | | R9-60 |
| M-412 | Queue cost grows with the backlog (`parent_of` per bead) | FORE-O-28 | fore | O | ❓ | P3 | S | (low) | - |
| M-413 | Scheduling windows | FORE-F-28 | fore | F | ✅ | P3 | S | | - |
| M-414 | Auto-resume lost runs | FORE-F-34 | fore | F | ✅ | P2 | M | | R9-15 |
| M-415 | Worktree sprawl | FORE-F-35 | fore | F | ✅ | P3 | S | | R9-27 |
| M-416 | Intent field on beads | FORE-F-38 | fore | F | ❓ | P3 | S | | - |
| M-417 | Fewer loops may be faster; measure landed/hour at 2, 3, 4 loops | FORE-O-34 | fore | O | ❓ | P3 | S | (contra, low) | R9-52 |
| M-418 | Owner attention budget (ask rate cap) | FORE-O-35 | fore | O | ❓ | P3 | S | | - |
| M-419 | Machines are not symmetric; roadmap M4 has no beads | FORE-F (disagreements) | fore | F | ✅ | P2 | - | | DQ-23 |

## 10. Tests

| M | idea | sources | lens | mod | v | sev | eff | note | bead |
|---|---|---|---|---|---|---|---|---|---|
| M-420 | Rewrite tests at the new seams per rewrite bead; no separate epic; a rewrite bead must not grow test lines | Q-04, SPL-F-24 | rw, spl | both | ✅ | P2 | - | rule for every R9 rewrite | REVIEW9 epic |
| M-421 | Tests test fakes | DES-F-37 | des | F | ❓ | P3 | - | | - |
| M-422 | Dedupe test fakes | SPL-O-10 | spl | O | ✅ | P3 | S | | - |
| M-423 | Golden scenario tests | SIM-O-23 | sim | O | ✅ | P2 | M | | R9-53 |
| M-424 | Count how many tests construct Engine or a host fake (decides the cost of RW-03/08) | RW §4 | rw | O | ✅ | P2 | S | | R9-52 |
| M-425 | Cut SKILL.md (674 lines) to a ~150-line orchestrator procedure; a schema for its tables; move procedure into tl verbs | DES-F-33, DES-O-20, SPL-F-37, SIM-F-36, SIM-O-25, Q-07 | des, spl, sim, rw | both | ✅ | P2 | M | after the verb table | DQ-26 |

All rows are distinct ideas; true duplicates are merged into the sources column.
