# Encapsulation review: modules and packages

Static review of the supplied tree, 2026-11-01. The engine's directories describe responsibilities more convincingly than its interfaces enforce them. Passing an import rule does not establish ownership, purity, read-only access, or recoverability. The delegate copy has substantially better separation around vendor parsing, but its process and persistence boundaries still give callers obligations they cannot reliably discharge.

This review is additive to [architecture.md](architecture.md) and [dataflow.md](dataflow.md), referenced as A.Fxx and D.Fxx. It does not re-file their findings. Source files, declarations, selected implementations, and selected tests were read; nothing was executed. No git, tracker, network, installed plugin, credential file, or external filesystem state was inspected. The delegate reviewed here is `_delegate/`, not proof of the currently installed delegate's behavior. Runtime validation is **untested throughout**. A structural keep below is not a claim that its tests passed.

P1 means an incorrect authorization, concurrent writer, or lost ownership protection. P2 means broken recovery, routing, delivery of observations, or machine-wide availability. P3 means unnecessary interface complexity. Findings distinguish a source-demonstrable counterexample from an untested operational consequence.

## Reading the inventory

Every Python package and every Python module of at least 80 physical lines is listed. Browser ES modules of at least 80 lines are also listed; the stylesheet assets receive separate verdicts. Shorter modules are included when their boundary matters. Empty `__init__.py` files are namespace markers, not deep abstractions: deleting one usually changes packaging/import discovery, not business complexity. Their package verdict is the verdict of the enclosed boundary.

Path prefixes: **T** = `src/taskloop/`; **H** = `src/taskloop_dash/`; **G** = `_delegate/src/delegate/`. Each module row's evidence anchor is its actual `:1` purpose declaration plus the named class/function surface read during this review. Numbered findings supply implementation-level line evidence. A declaration was not accepted as proof of the invariant it advertises.

Verdicts are deliberately two-dimensional:

* **K ✅ deep / keep**: removes a concrete decision or representation problem from its caller. Deletion **R** means the real complexity reappears in callers.
* **R ⚠ leaky / refuse-and-redo**: demonstrated contract problem; the cited M finding or R refactor below specifies its replacement, rollout, and discriminating test. Deletion **R** means inlining would merely move the defect.
* **R ❌ shallow / refuse-and-redo**: adds names, forwarding, or an aggregate host without hiding an invariant. Deletion **V** means that wrapper's complexity vanishes; the underlying operation still exists.
* **U ⚠ leaky / untested**: the surface requires the listed caller knowledge, and the inspected evidence does not establish that the boundary contains it. Do not approve its behavioral contract on this review. Deletion **R** means its work would still have to be implemented elsewhere.

The caller column uses these explicit shared contracts to avoid repeating a paragraph in every row:

| Code | Types, invariants, ordering, errors, configuration the caller must supply or understand |
| --- | --- |
| E | Engine-like host: bead/run/worktree, `EngineConfig`, stores, git, log, cursor and mutable state must describe the same attempt. Admission precedes effects; effects precede durable acknowledgment. `Blocked`, fencing, spawn, git and storage failures can interrupt the sequence. Configuration must remain the admitted revision. |
| C | `Check`/`CheckPlan`/`CheckResult`/`CheckRun`, tree/base and execution identity. Fix before fingerprinting; acquire resources before launch; preserve cancellation and unverified results; never turn a skip into a pass. Check registry, `when`, plan producer, environment and container policy affect validity. |
| S | `SlotEnv`, slot/task beads, checkout, generation, process identities and setup inputs. Ownership precedes reset/setup/removal; cleanup follows release only with separate ownership. `SlotFail`, `SlotGitError`, held/busy states and partial git work must be handled. |
| A | `Ask`/answer/action/ledger/ADR plus bead and expected ask identity. Validate the question displayed, lock compare-and-answer, then apply effects. Superseded/invalid/unavailable are separate results. Holds and wakes are typed state, not comment prose. |
| P | `PlanData`, stage/check registry, brief snapshot and answer schema. Decode, validate, then accept/persist an executable cursor. Reject unknown refs, invalid commands, missing proof and no-op work explicitly. Engine plan limits and repo checks apply. |
| L | `LoopEnv`/queue/verdict/carry plus slot, task and execution identity. Observe before rank, acquire before spawn, settle before reuse; distinguish infrastructure refusal from task failure. Loop profile, cooldowns, role/network readiness and version policy apply. |
| Q | Dashboard `World`/snapshot/run/card DTOs plus clock and identity. These are observations of independently changing sources, not transactional receipts. Handle missing, foreign, truncated and stale records explicitly; commands require owner ports. |
| D | Delegate typed routing/state plus `Args`, role/family/model/runner, cwd, schema, resume and engine-only policy. Admit capabilities, claim, register worker, supervise, settle, then release. Caller/config/lock/vendor/network/schema/termination errors are distinct. |
| W | Record/union/version and codec/schema rules. Unknown fields and foreign versions can refuse decoding; omitted and null differ. Construct the correct record, validate at the edge, and never mistake an incompatible authority for an empty cache. |
| F | Typed document/log/key plus storage root. Reads may be lossy; locks are scoped to one file/family. A replaced file is not a transaction with another file or external effect. Caller must choose strictness, lock scope, crash recovery and retention. |

## Package verdicts

All paths in this table are packages, including the root packages. The job/hiding column says what boundary deserves to exist; U means the implementation has not earned approval of that promise.

| Package | One job / what it hides; caller obligation | Verdict; deletion |
| --- | --- | --- |
| T | Coordinate repository work; should hide task lifecycle, but exposes many mutation front doors (A mutation-path inventory). E/L/S/A | U ⚠; R |
| T/app | Compose effects from policy; hides use-case sequencing only if hosts stop exporting shared mutation. E; R1 | R ⚠; R |
| T/contracts | Shared vocabulary; also contains concrete effects. W/F; R2 | R ⚠; R |
| T/domain | Decide over supplied facts; no direct app/adapter/store imports found in the inspected import scan. W, explicit clocks/facts | K ✅; R |
| T/adapters | Translate external processes/formats; callers still select policy and failure strictness. E/C/D | U ⚠; R |
| T/stores | Persistence implementations; currently wraps concrete implementations below itself. F; R2 | R ⚠; R |
| T/cli | Parse/render verbs; hides argument syntax, not workflow. Caller needs composed ports and exit semantics | K ✅; R |
| T/hook | Lightweight hook decisions without record imports; hides hook protocol. Input JSON and fail policy still matter | U ⚠; R |
| T/app/asks | Owner input and persistence; A, multi-effect receipts and retry still external | U ⚠; R |
| T/app/checks | Execute and prove checks; C, but weaker proof queries escape the boundary. M04/M05 | R ⚠; R |
| T/app/doctor | Setup diagnostics; caller supplies repo/installed profile/version facts | U ⚠; R |
| T/app/land | Deliver checked work; C/S/E. Ownership and proof defects already catalogued in A/D; new proof interface M04/M05 | R ⚠; R |
| T/app/launch | Compose concrete ports and start services; process identities and chosen roots must be coherent | U ⚠; R |
| T/app/look | Render, retain and judge visual evidence; E/C, shot-table revision and owner disposition must agree | U ⚠; R |
| T/app/loop | Schedule repeated work; L, recovery and version transitions cross its boundary | U ⚠; R |
| T/app/plan | Acquire and validate executable plans; P, draft/accept ordering remains caller-sensitive (D.F06) | U ⚠; R |
| T/app/prune | Reconcile and expire data; F/S, age alone cannot authorize deleting live work | U ⚠; R |
| T/app/reconcile | Observe/diff/apply repairs; typed observations hide discovery but not freshness through mutation | U ⚠; R |
| T/app/release | Build/install releases; hides release workflow, not live-run compatibility (A.F04) | U ⚠; R |
| T/app/report | Derive reports and recurring-fault work; F, digest filing is an effect despite read-looking neighbors | U ⚠; R |
| T/app/review | Route findings to proof or owner; E/C, prose classification is not proof of execution | U ⚠; R |
| T/app/run | One attempt; exposes essentially the same Engine state to its parts. E; R1 | R ⚠; R |
| T/app/slots | Own reusable execution directories; S, capability not carried by reset/cleanup APIs (A.F02/D.F04) | U ⚠; R |
| T/app/track | Bead commands/provenance; hides argv, not atomic generation authorization (A.F03) | U ⚠; R |
| T/app/wire | Real-world assembly; profile, hooks, asks, slots, lanes and closing policy share an integration bucket. E/L/A/S | U ⚠; R |
| T/app/write | Stage write/check/review cycle; E/P/C, shared host carries round state across parts | U ⚠; R |
| T/domain/asks | Construct/lint owner questions; hides wording and option rules. A, facts must be accurate | K ✅; R |
| T/domain/beads | Eligibility, self-containment and question wakes; typed bead facts, root and children required | K ✅; R |
| T/domain/checks | Plan/order/fingerprint checks; C, execution identity incomplete (M05) | R ⚠; R |
| T/domain/checks/cmd | Recognize supported command forms; argv grammar and probe facts required; rejection is conservative | K ✅; R |
| T/domain/checks/diag | Recognize diagnostic formats; raw output and supported parser dialect required | K ✅; R |
| T/domain/land | Interpret git delivery text; typed effects belong elsewhere; unknown failures must survive | K ✅; R |
| T/domain/lanes | Decide retry/reroute/wake; stop facts and context required. Producer enforcement differs (M06) | U ⚠; R |
| T/domain/look | Visual text matching; no evidence creation hidden here; caller supplies images/facts | K ✅; R |
| T/domain/plan | Brief and plan views; P, callers retain admission and validation obligations | K ✅; R |
| T/domain/prompts | Role-specific instructions; hides wording, never enforcement. P/E/D | U ⚠; R |
| T/domain/reconcile | Repair decisions over facts; hides decision table, caller must refresh before effects | K ✅; R |
| T/domain/report | Fingerprints/recurrence; hides clustering heuristic, not authoritative cause identity | U ⚠; R |
| T/domain/review | Classify findings/criteria; hides routing heuristics, caller must prove checks actually apply | U ⚠; R |
| T/domain/write | Diff test-count policy; hides counting patterns, caller supplies complete diff/config | K ✅; R |
| H | Observe runs and accept owner commands; Q/A, read-only is not its capability boundary | U ⚠; R |
| H/api | HTTP query/command adaptation; Q/A. Cursor delivery contract fails (M08) | R ⚠; R |
| H/cli | Launch dashboard shell; caller must provide correct bind/ports/version | U ⚠; R |
| H/readers | Build observations; Q/F. Repo identity collapses at basename (M09) | R ⚠; R |
| H/views | Project observations into DTOs; Q, independently duplicates lifecycle display policy | U ⚠; R |
| G | Route one worker call; D. Lease/state boundaries fail M01–M03/M10 | R ⚠; R |
| G/adapters | Vendor/process/usage translation; D, end reports must preserve uncertainty (M02) | R ⚠; R |
| G/adapters/harness | CLI-specific launch/events; hides real vendor dialect complexity; broad inputs still leak kind-specific fields | U ⚠; R |
| G/app | Call lifecycle and status assembly; D, worker authority cannot be optional telemetry | R ⚠; R |
| G/cli | Parse/dispatch commands; hides syntax; admitted request capabilities remain unproven (A.F08 extension below) | U ⚠; R |
| G/contracts | Typed wire/state; also concrete storage, so type vocabulary is not purity. W/F; R2 | R ⚠; R |
| G/domain | Routing decisions over facts; no direct app/adapter imports found in inspected scan | K ✅; R |
| G/domain/cost | Fold vendor usage into per-call cost; explicit cumulative baseline/currency semantics required | K ✅; R |
| G/domain/health | Replay breaker state; timestamp cursor loses events (M07) | R ⚠; R |
| G/domain/holds | Match owner holds by role/lane/time; hides precedence and expiry | K ✅; R |
| G/domain/lanes | Availability and leases as facts; caller must reconcile physical processes, not only TTL | U ⚠; R |
| G/domain/policy | Judge worker operations; promises read-only semantics its allowlist does not contain (M06) | R ⚠; R |
| G/domain/routing | Choose model/lane/tier/resume; hides a genuine decision tree; caller supplies fresh fleet/capabilities | K ✅; R |
| G/domain/time | Parse/render explicit times; caller supplies epoch/timezone intent; invalid input must be refused | K ✅; R |

## Module inventory: task-loop contracts and domain

These are source-relative module paths, not invented services. Each row states its job and hidden representation, then the extra knowledge its caller still carries. An R reference applies to that module, not merely its package.

| T module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| contracts/adrs.py | ADR files and use counts | A/F, repo key, in-force versus retired | U ⚠; R |
| contracts/answers.py | Role answer records, schema, validation | W, node and visual variant, sent versus internal schema | K ✅; R |
| contracts/ask.py | Owner question/answer/thread representation | A/W, status/action and expected identity | K ✅; R |
| contracts/checkpoint.py | Persistent cursor and recovery representation | E/W, draft/accepted/closing state and schema reader | U ⚠; R |
| contracts/checks.py | Check/result/round/provenance vocabulary | C/W, red/base-red/cancelled/unverified distinctions | K ✅; R |
| contracts/config.py | Typed repo policy and validation | P/C/S/W, argv lists, base hint, resources, graph constraints | K ✅; R |
| contracts/dash.py | HTTP DTOs, display enums and command requests | Q/A/W, API versions and field meanings | U ⚠; R |
| contracts/delegate.py | Subprocess request/result/live vocabulary | D/W, supported flags and stop semantics; A.F08 | U ⚠; R |
| contracts/enums.py | Closed vocabulary | W, enums are not interchangeable strings | K ✅; R |
| contracts/events.py | Cross-repo tagged events | W/F, event versus receipt and rotation | K ✅; R |
| contracts/fence.py | Claim token and ownership authorization | E/S, unreadable and atomicity gaps in A.F03 | U ⚠; R |
| contracts/gallery.py | Look-item description/metadata representation | Q/A, formatting and path rules must match producer | U ⚠; R |
| contracts/gitfacts.py | Parsed git fact records | W, git adapter supplies complete observations | K ✅; R |
| contracts/ids.py | Parse IDs/version and derive keys | W, path-derived versus origin-derived repo identity | K ✅; R |
| contracts/kinds.py | Closed outcomes and fault/action mapping | E/W, caller fault versus infra/owner | K ✅; R |
| contracts/locator.py | Locate runs and mutate manifests | Q/E/F, liveness and takeover; A.F11, R2 | R ⚠; R |
| contracts/log.py | Engine tagged log vocabulary | W/F, IDs pair starts/ends, log is not effect receipt | K ✅; R |
| contracts/loop.py | Loop state/carry/command records | L/W, logical execution versus PID target | U ⚠; R |
| contracts/paths.py | Canonical storage paths | F, bead/repo/run key namespaces and root choice | K ✅; R |
| contracts/plancheck.py | Plan/check union and wire conversion | P/W, stored versus worker form and registry refs | K ✅; R |
| contracts/ports.py | External capabilities and protocol records | E/C/D, very broad Git/Spawner/Beads surfaces | U ⚠; R |
| contracts/reconcile.py | Lease/loop facts and pure predicates | S/L, current time and completeness of observations | K ✅; R |
| contracts/run.py | Manifest/report/handover/counter records | E/L/W, two RunState meanings across modules | U ⚠; R |
| contracts/schema.py | Record schema and strict/null rewrite | W, schema consumer dialect and round-trip limits | K ✅; R |
| contracts/snapshots.py | Persisted cache/index/release DTOs | F/W, which records are disposable versus authority | U ⚠; R |
| contracts/stores.py | Concrete JSON/log/ask/index storage | F/A, lossy reads versus strict states; R2 | R ⚠; R |
| contracts/trace.py | Finished-run report representation | W/F, partial/unknown cost and evidence retention | K ✅; R |
| contracts/wire.py | Strict msgspec codec/version boundary | W, unknown keys and version refusal | K ✅; R |
| contracts/needs.py | Owner-attention DTO extracted by cap | Q/W; explicit cap rationale, R3 | R ❌; V |
| contracts/dashcost.py | Cost DTO family extracted by cap | Q/W; cohesive concept despite stated cap motive | K ✅; R |
| domain/brief.py | Status/handoff text from supplied facts | L/A, truncation budgets and current clock | K ✅; R |
| domain/effects.py | Close/land effect plans | E, interpreter acknowledgments must mean applied | K ✅; R |
| domain/outcome.py | One run-disposition policy table | E, typed Kind, fingerprint and escalation context | K ✅; R |
| domain/asks/lint.py | Question/option validity | A, syntax validity does not establish answer identity | K ✅; R |
| domain/asks/specs.py | Questions from concrete stop facts | A, real attempts/evidence/budget and no-op reason | K ✅; R |
| domain/beads/matchers.py | Prose references and command extraction | P, root/check registry and supported text grammar | U ⚠; R |
| domain/checks/cmd/matchers.py | Recognize command/operand forms | C/P, argv language, no general shell evaluator | K ✅; R |
| domain/checks/diag/matchers.py | Diagnostic line-format recognition | C, supported compiler/linter format pairs | K ✅; R |
| domain/checks/diagnostics.py | Parse/render structured failures | C, complete raw text and output budget | K ✅; R |
| domain/checks/inputs.py | Fingerprint check inputs/settings | C, actual executor identity absent; M05 | R ⚠; R |
| domain/checks/lint.py | Reject invalid plan checks | P/C, TreeProbe facts and registry; exceptions on missing paths/tools | K ✅; R |
| domain/checks/matchers.py | Globs plus command/output/failure classifiers | C, several grammars in one regex-placement home | U ⚠; R |
| domain/checks/planref.py | Resolve refs against repo registry | P/C, reject unknown/forbidden references | K ✅; R |
| domain/checks/specs.py | Build round checks and due decisions | C, repo versus adhoc/cache/group policy | K ✅; R |
| domain/checks/trim.py | Bound log evidence without losing failure groups | C, lossy prompt excerpt, retain original elsewhere | K ✅; R |
| domain/lanes/matchers.py | Conservative read-command recognition | D, command flags/operator restrictions; differs from delegate M06 | K ✅; R |
| domain/lanes/pauses.py | Reason-to-wake policy and pause episodes | L/D, owner versus timer and episode identity; A.F07/D.F11 | U ⚠; R |
| domain/lanes/policy.py | Stop facts/context to retry/wait/yield/fail | D, scope/permanence and prior attempts | K ✅; R |
| domain/plan/brief.py | Render/snapshot/diff bead briefs | P, comment provenance, linked beads and room budget | K ✅; R |
| domain/plan/matchers.py | Acceptance/plan prose rules | P, supported wording and configured checks | U ⚠; R |
| domain/prompts/plan.py | Planner instructions/templates | P, prompt is guidance, validation separate | U ⚠; R |
| domain/prompts/write.py | Fresh/resumed writer prompt | E/P, full/delta and predecessor context must agree | U ⚠; R |
| domain/reconcile/diff.py | Pure repair action selection | S/F, observations age before apply | K ✅; R |
| domain/reconcile/facts.py | Typed observed world and guarded action payloads | S/F, OID/generation completeness | K ✅; R |
| domain/report/matchers.py | Fingerprints, times, names and prose parsing | Q, unrelated grammars coexist because regex placement permits it | U ⚠; R |
| domain/report/reflect.py | Group recurring faults into candidate fixes | Q/E, heuristic identity and historical window | U ⚠; R |
| domain/review/findings.py | Blocking and follow-up routing | P, criterion scope and textual classification | U ⚠; R |
| domain/review/followups.py | Stable item keys and batch/cap decisions | E/F, key must reach external creation; D.F08 | K ✅; R |
| domain/work/ledger.py | Criterion proof/defer decisions | P/C, actual check authority versus planned proof | U ⚠; R |
| domain/review/matchers.py | Tools/actions/gate-proof/acceptance recognizers | P/C, grammar-dependent inference can settle work | U ⚠; R |
| domain/work/visual.py | Visual classification from typed facts | P, changed paths/criteria/config complete | K ✅; R |

## Module inventory: task-loop adapters, stores, CLI and hook

| T module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| adapters/applog.py | Append handles and their lifecycle | F, close/rotation/thread behavior | U ⚠; R |
| adapters/bd.py | bd argv/JSON/error translation | E/A/S, conditional mutation limits and multiline diagnostics | U ⚠; R |
| adapters/childenv.py | Child environment and script argv | E/D, scrubbed identities, uv topology and exec; A.F06 | U ⚠; R |
| adapters/container_run.py (history: deleted in 0.23.403) | Docker copy/run/artifact helper | C, host/container paths, cleanup and exit forwarding | U ⚠; R |
| adapters/delegate.py | Resolve/install/probe/call boundary | D, contract integer insufficient; A.F08 | U ⚠; R |
| adapters/delegate_wire.py | External envelope to internal typed facts | D/W, absent/default/coerced and synthesized facts | U ⚠; R |
| adapters/git.py | Typed git operations | S/C, pinned cwd, expected OIDs, command failure variants | U ⚠; R |
| adapters/git_base.py | Git invocation and error classification | S, environment/pinning and typed errors | U ⚠; R |
| adapters/gitmemo.py | Git observation cache identity | S/C, invalidation across refs/index/config/worktrees | U ⚠; R |
| adapters/gitrepo.py | Repository/common-dir discovery and pinning | S, main/worktree identity, missing paths | U ⚠; R |
| adapters/landlock.py | Canonical remote identity and OS land lock | S/E, acquire/release scope, timeout and holder | U ⚠; R |
| adapters/links.py | Extract and check public links | E, network failures versus bad links; caller retains retry policy | U ⚠; R |
| adapters/locks.py | Process resource locks and holder hints | C/S, kernel ownership versus observational holder JSON | U ⚠; R |
| adapters/looks.py | Shot-table parsing, argv, collection, scaling and judge text | E/P, mixed policy/I/O; typed table/paths and process errors leak | U ⚠; R |
| adapters/opencode.py | Read external session database/transcript facts | D/Q, missing/unknown schema and read-only access | U ⚠; R |
| adapters/procs.py | Capture/stream/spawn/stop process groups | E/D, PID/start identity, partial/timeout/survivor semantics | U ⚠; R |
| adapters/runner.py | Stream delegate process and live metadata | D, launch/worker identities differ; last-line answer parsing | U ⚠; R |
| adapters/spawner.py | Concrete process port | E/C/D, group ownership, streams, timeout/signal result | U ⚠; R |
| adapters/treehash.py | Fingerprint effective tree and ignored rules | C/S, index/working tree consistency and tree errors | U ⚠; R |
| stores/call_state.py | Call intent/return/consume and reattachment | E/D/F, matching coordinates and consumed recovery; D.F12 | U ⚠; R |
| stores/files.py | Keyed file documents and slot tickets | F/S, concrete document behavior lives below it; R2 | R ⚠; R |
| stores/memory.py | In-memory implementations for test seams | F, must reproduce strict reads, lock and ticket behavior | U ⚠; R |
| cli/asks.py | Owner verbs and answer flags | A, expected identity, action/payload/exit semantics | U ⚠; R |
| cli/land_stack.py | Parse stack items and compose delivery | S/C, judged OID/base and command stop codes | U ⚠; R |
| cli/loop.py | Next/stop/status/loop presentation | L, command targets and stale registry behavior | U ⚠; R |
| cli/report.py | Render reports/lost/reflection output | Q, report versus digest-filing side effects | U ⚠; R |
| cli/wait.py | Poll completion and asks | E/Q, liveness/retention and blocked versus finished | U ⚠; R |
| hook/prepush.py | Lightweight gate adapter | C, ID-only proof query and explicit fail-open hook policy; M04 | R ⚠; R |

## Module inventory: run and land

R1 applies only where named. Moving an Engine method into a file and passing the Engine back into it does not create a private state machine.

| T module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| app/run/calls.py | Pair call records and accumulate usage | E/D, step identity, sessions/stats aliasing | U ⚠; R |
| app/run/closer.py | Order close effects/replay | E/F, host plus parts and acknowledgment order; R1 | R ⚠; R |
| app/run/closer_branch.py | Save branch and leave/release slot | E/S, separate ownership and branch disposition | U ⚠; R |
| app/run/closer_host.py | Aggregate the step host protocols | E; aggregates aliases, grants no new invariant; R1 | R ❌; V |
| app/run/closer_notes.py | File leftovers/owner look and reflection | E/A/F, pending/filed/refused external obligations | U ⚠; R |
| app/run/closer_record.py | Close log/trace/reflection/ask record | E/F, terminal fact versus projected prose | U ⚠; R |
| app/run/closer_settle.py | Final bead state | E, disposition, claim and external failure; D.F07 | U ⚠; R |
| app/run/context.py | Construct run writers and observers | E, duplicates objects also copied to Engine; R1 | R ⚠; R |
| app/run/decide.py | Pure resume decision over checkpoint/world | E/P, freshness and compatible accepted plan required | K ✅; R |
| app/run/engine.py | Compose attempt and common methods | E, state aliases, lazy parts, global lock and optional offline claim; R1 | R ⚠; R |
| app/run/entry.py | Admit/claim/select directory/start engine | E/S/L, multiple pre-engine exits and release ordering | U ⚠; R |
| app/run/fields.py | Initialize mutable Engine fields | E, full field taxonomy and persistent/ephemeral split; R1 | R ❌; V |
| app/run/lane_acts.py | Execute retry/wait/reroute/yield policy | E/D/L, original stop, family and durable wake | U ⚠; R |
| app/run/layout.py | Run layout plus age-based pruning | E/F, open/adopt identity and retention exemptions | U ⚠; R |
| app/run/preflight.py | Read-only admission preview | E/C/P, preview cannot authorize later mutation | U ⚠; R |
| app/run/records.py | Start/terminal record and trace assembly | E/Q, aliased counters and clipped causality | U ⚠; R |
| app/run/reload.py | Adopt version and transfer counters | E/F/D, compatibility and rollback; A.F04 | U ⚠; R |
| app/run/requests.py | Live owner command post/take/consume | E/A/F, exact logical run identity and beat/step ordering | U ⚠; R |
| app/run/resume.py | Observe world, restore/amend/restart plan | E/P, checkpoint strictness and config compatibility | U ⚠; R |
| app/run/run_once.py | Execute attempt through mandatory close | E/P/C, all shared host state and outcome precedence; R1 | R ⚠; R |
| app/run/shared.py | Cross-bead notes/flakes/context | E/F, stale neighbors and advisory versus authoritative data | U ⚠; R |
| app/run/stages.py | Continuous and standalone step dispatch | E/P/C, cursor/round/session recovery and stage selector | U ⚠; R |
| app/run/state.py | Checkpoint writer plus automatic writable aliases | E/F, caller mutation schedule not hidden; R1 | R ⚠; R |
| app/run/trace.py | Typed trace conversion | E/Q/W, incomplete source mappings and clipped facts | U ⚠; R |
| app/run/waits.py | Account/wait for locks and resources | E/C, wait excluded from budget and cancellation propagation | U ⚠; R |
| app/run/worker_call.py | Complete AI call, recovery and policy loop | E/D/P, ops callbacks, persistent call/memo/worker identities | U ⚠; R |
| app/land/checkout.py | View/stage/hash checkout | E/S/C, pinned git and expected tree/revision | U ⚠; R |
| app/land/cleanup.py | Retry recorded local/remote cleanup | S/F, active ownership not guaranteed; D.F04 | U ⚠; R |
| app/land/fixer.py | Writer round for land failures | E/P/C, accepted-state barrier and limited retry | U ⚠; R |
| app/land/gate.py | Gate checks and proof token | C/E, capture/issue ordering; D.F02 | U ⚠; R |
| app/land/lander.py | Optimistic/locked delivery state machine | E/C/S, host/parts split still aliases Engine; R1 | R ⚠; R |
| app/land/lander_host.py | Union of land host surfaces | E/C/S, typing sum does not hide transaction; R1 | R ❌; V |
| app/land/outbound.py | Delivery argv/LFS/data sync | E/S, exact pushed ref and separate effects | U ⚠; R |
| app/land/push.py | Validate token and push under land lock | E/C/S, proof authority, fence and ambiguous remote result | U ⚠; R |
| app/land/rebase.py | Resume-branch rebase and recovery choice | E/S/P, conflict snapshot, salvage limits and restart | U ⚠; R |
| app/land/restart.py | Preserve conflicting branch and reset planning | E/S/P, state invalidation spans host members | U ⚠; R |
| app/land/stack.py | Existing branch/PR stack delivery | S/C/F, source/check/cleanup identity across items | U ⚠; R |
| app/land/tree.py | Reset/WIP/leave directory | E/S, multiple directory mutators; D.F04 | U ⚠; R |
| app/land/stackgate.py | Authorize stack tip from check evidence | C, erases expected Check to CheckId; M04 | R ⚠; R |

## Module inventory: other application slices

| T module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| app/asks/intake.py | Apply typed owner input | A/E, answer identity, receipt and bead effects | U ⚠; R |
| app/asks/looks.py | Apply/undo look verdict and file redo | A/F, metadata/item ID and created-bead receipt | U ⚠; R |
| app/asks/raiser.py | Build/persist question and consume answer | A/E, queue removal and multi-effect failure | U ⚠; R |
| app/asks/stick.py | Promote owner answer into lasting action | A/F, typed outcome and external create/ADR effects | U ⚠; R |
| app/asks/sweeps.py | Reconcile stale/closed/orphan asks | A/F, age threshold, bead availability, consumed state | U ⚠; R |
| app/checks/attempts.py | Retry one check, capture output, classify timeout | C, actual Box execution and cancellation | U ⚠; R |
| app/checks/cache.py | Persist/query check evidence | C/F, full RunKey versus weak exported query; M04/M05 | R ⚠; R |
| app/checks/container.py | Choose host/container execution | C, silent location substitution and missing identity; M05 | R ⚠; R |
| app/checks/evidence.py | Check-result prompt/log presentation | C/Q, lossy summaries cannot authorize outcomes | K ✅; R |
| app/checks/executor.py | Decide/launch/publish each check | C, memo/resources/producer/lane state and cache identity; M05 | R ⚠; R |
| app/checks/gateplan.py | Run/parse neutral repo plan producer | C/P, argv, exact base/paths and malformed fallback | U ⚠; R |
| app/checks/host.py | Check runner's required capabilities | C, broad host exports rather than owned execution object | U ⚠; R |
| app/checks/lanes.py | Concurrent lane cancellation/folding | C, shared memo and default-lane sentinel semantics | U ⚠; R |
| app/checks/resources.py | Machine resource acquisition and cancellation | C/S, named limits and holder scope | U ⚠; R |
| app/checks/runner.py | Build/run/persist a check round | C/E, round tree/base/config capture and multiple consumers | U ⚠; R |
| app/launch/check.py | Standalone registry checks | C/E, selected profile and independent run lifecycle | U ⚠; R |
| app/launch/check_host.py | Adapt standalone checks to CheckHost | C, absent engine features and explicit no-op implementations | U ⚠; R |
| app/launch/dash.py | Start/identify/stop dashboard | Q, PID/server identity, bind policy and installed version | U ⚠; R |
| app/launch/dash_ports.py | Wire owner/query callbacks into dashboard | A/Q, full mutation capabilities cross import boundary | U ⚠; R |
| app/launch/loop.py | Build concrete LoopEnv | L/E/S/D, callback semantics and uv exec topology | U ⚠; R |
| app/launch/selftest.py | Script an entire engine flow | E/D, scripted lane is not real installed compatibility proof | U ⚠; R |
| app/launch/selftest_beads.py | In-memory tracker for selftest | E/S, model omits real process/DB failure interleavings | U ⚠; R |
| app/look/judge.py | Objective visual evaluation/repair history | E/P, rendered freshness, judge schema and repeated-defect rules | U ⚠; R |
| app/look/keep.py | Retain/deduplicate visual evidence | F, inode/content/storage budgets and expired source paths | U ⚠; R |
| app/look/owner_look.py | One owner-look bead per epic | A/E/F, external idempotency and artifacts surviving cleanup | U ⚠; R |
| app/look/shots.py | Choose/run repo shot methods | E/C/P, trusted table revision and output collection | U ⚠; R |
| app/loop/core.py | Common scheduler bookkeeping | L, queue/profile/current task and carried counters | U ⚠; R |
| app/loop/env.py | Scheduler dependencies/callback records | L, callback error/side-effect semantics remain external | U ⚠; R |
| app/loop/files.py | Loop registry, commands and rest files | L/F, PID-scoped state versus logical identity; A.F06 | U ⚠; R |
| app/loop/loop.py | Run scheduling passes and lifecycle | L/S/E, settlement/release/version ordering | U ⚠; R |
| app/loop/queue.py | Rank eligible ready tasks | L/P, parent/area/park snapshots and owner queue | U ⚠; R |
| app/loop/run.py | Start/read child run and version fallback | L/E, early crash versus task result and outcome-file availability | U ⚠; R |
| app/loop/settle.py | Convert child result to retry/rest/slot policy | L/S, original cause/wake and mutating health probe; A.F02/F07 | U ⚠; R |
| app/loop/take.py | Acquire candidate, slot and task | L/S/E, claim rollback and directory authority | U ⚠; R |
| app/loop/verdict.py | Decode child exit/outcome/refusal | L/E, profile-ahead and pre-engine failures | U ⚠; R |
| app/loop/versions.py | Choose installed version/fallback | L/D, version ordering, pin/bad-install state | U ⚠; R |
| app/plan/cases.py | Resolve executable acceptance cases | P/C, registry refs, generated cases and shared plan state | U ⚠; R |
| app/plan/planner.py | Request and accept/reject plans | P/E, draft versus accepted cursor; D.F06 | U ⚠; R |
| app/plan/probe.py | Probe acceptance work before planning | P/E, tooling facts, current tree, result versus assumption | U ⚠; R |
| app/plan/prompt.py | Gather and render planner context | P/E, ADRs, budget, linked bead facts and truncation | U ⚠; R |
| app/plan/sendback.py | Aggregate plan rejection reasons | P/C, validation order and limits before acceptance | K ✅; R |
| app/reconcile/observe.py | Collect repair facts | S/F, read errors versus absence and observation age | U ⚠; R |
| app/release/flow.py | Orchestrate release clone/build/publish/install | E/F, clean clone, suite proof, owner pin, live-run compatibility | U ⚠; R |
| app/release/pins.py | Owner pin/rollback override | D/F, only explicit owner actions may mutate pin | U ⚠; R |
| app/release/publish.py | Marketplace/version/tag/install effects | D/F, release clone, manifest and remote/installer failures | U ⚠; R |
| app/release/suite.py | Full-suite scheduling/resources/proof | C/F, host lock, cgroup limits, serial phase and cache identity | U ⚠; R |
| app/report/card.py | Aggregate scorecard | Q/F, attribution, retained logs and unknown values | U ⚠; R |
| app/report/reflect.py | Cluster and file recurring issues | E/Q/F, stable cause identity and durable creation receipts | U ⚠; R |
| app/review/routing.py | Route unchecked items to engine/owner/follow-up | E/P/C, scope and actual executable proof | U ⚠; R |
| app/review/settles.py | Prove/reject reviewer gaps | E/C/P, check names, tree freshness and repo linter availability | U ⚠; R |
| app/review/verifier.py | Read-only verification and owner residue | E/D/P, claimed proof versus quoted evidence | U ⚠; R |
| app/slots/engine_lock.py | Engine ownership and worker liveness | S/E, global current lock and handover/process-start identities | U ⚠; R |
| app/slots/owned.py | Record/survey/clean owned worktrees | S/F, recorded ownership versus active lifecycle | U ⚠; R |
| app/slots/pool.py | Slot discovery/take/release/reset interface | S, ready_for forwards without capability; A.F02 | U ⚠; R |
| app/slots/reset.py | Preserve/reset/setup reusable directory | S, all mutation guards must remain held | U ⚠; R |
| app/slots/verbs.py | Slot owner commands | S, force/hold/reset semantics and failure exit codes | U ⚠; R |
| app/track/trail.py | Event/provenance/repo registration | E/F, advisory failure versus authoritative mutation | U ⚠; R |
| app/track/verbs.py | Claim/close/block/land/passthrough | E/A/S, actor/generation and bypass surface | U ⚠; R |
| app/wire/closeguard.py | Close eligibility and manual delivery receipts | E/S, expected work/land/owner waiver facts | U ⚠; R |
| app/wire/doctor.py | Aggregate local installation/setup warnings | Q/S/D, errors are observations, not repairs | U ⚠; R |
| app/wire/hook.py | Session indexing and generated hook shims | E/F, main checkout and fail policy | U ⚠; R |
| app/wire/slots.py | Profile/slot/worktree composition | S/E/L, local slot profile versus committed engine profile; A.F05 | U ⚠; R |
| app/write/check_round.py | Feed engine check results into stage outcome | E/C, faults versus code failures and retry budget | U ⚠; R |
| app/write/handoff.py | Writer continuation/fresh-thread context | E/D/P, session family, counters and durable predecessor summary | U ⚠; R |
| app/write/newfiles.py | Accept/ignore/quarantine untracked files | E/S/P, plan/writer ownership and deletion-safe evidence | U ⚠; R |
| app/write/review_round.py | Reviewer verdict to accept/retry/replan | E/P/C, check freshness, criteria, leftovers and caps | U ⚠; R |
| app/write/write_round.py | Writer prompt/call/update for one round | E/P/D, full versus delta, usage, accepted changes | U ⚠; R |

## Module inventory: dashboard

“Read-only dashboard” is already rejected as a capability description by A.F09 and the A mutation-path inventory. The additional defects here are identity loss and stream acknowledgment, not that same answer race again.

| H module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| bind.py | Bind address policy and server sockets | Q, installed/dev mode, loopback/address refusal and partial bind cleanup | U ⚠; R |
| env.py | Shared caches/clock/ports | Q/A, query and full mutation capabilities in one object | U ⚠; R |
| http.py | HTTP routing, serialization and error handling | Q/A, body limits, status/error behavior and bind trust | U ⚠; R |
| api/live.py | Merge live sources and issue byte cursors | Q/F, delivery versus read offsets; M08 | R ⚠; R |
| api/reads.py | Versioned query responses and ETags | Q/W, conditional fetch versus stale underlying sources | U ⚠; R |
| api/writes.py | Decode/validate/dispatch owner commands | A/Q, displayed identity must traverse port; A.F09 | U ⚠; R |
| readers/beads.py | Cache external bead lists/comments | Q/F, unavailable versus old/empty results and TTL | U ⚠; R |
| readers/records.py | Read indices/traces/run bundles | Q/F, retained versus full history and skipped records | U ⚠; R |
| readers/world.py | Assemble multi-source World | Q/A, basename map loses repository identity; M09 | R ⚠; R |
| views/bead_detail.py | Build bead page DTO | Q, matched repo/bead/run, artifacts and incomplete comments | U ⚠; R |
| views/board.py | Derive board cards and blockers | Q, status/ask/loop precedence and missing data | U ⚠; R |
| views/columns.py | Assign column/marker/status/tone | Q, lifecycle projection policy independently encoded | U ⚠; R |
| views/cost.py | Aggregate retained run cost/time/tokens | Q, unknown costs and window attribution | K ✅; R |
| views/floor.py | Project slots/strays/startup | Q/S, display observations never imply writable directory | U ⚠; R |
| views/learning.py | Time-bucket owner decisions and rates | Q, timezone/week boundaries and missing events | K ✅; R |
| views/live_lines.py | Render typed event terminal lines | Q/W, clipped display versus complete source | K ✅; R |
| views/needs.py | Collect things waiting on owner | Q/A/L, current wake and run/slot observations may disagree | U ⚠; R |
| views/passes.py | Derive passes/segments/resumes/messages | Q, event order, missing pairs and terminal precedence | U ⚠; R |
| views/phases.py | Map engine enums to display phases/endings | Q/W, unknown enum/cause fallbacks and NOOP versus DONE | K ✅; R |
| views/runfacts.py | Fold logs into run/call/wait spans | Q/F, unpaired events, current clock and manifest liveness | U ⚠; R |
| views/snapshot.py | Compose top-level snapshot | Q, project identity and independently fresh inputs | U ⚠; R |

Browser files below are real modules under `H/static/js/`; their evidence anchors are file starts and exported/imported interfaces. Their behavior was not browser-tested. CSS is included as an asset boundary, not mislabeled as Python packaging.

| Browser module / asset | One job / hiding | Caller knowledge; verdict; deletion |
| --- | --- | --- |
| actions.js | Owner action/undo/optimistic UI timing | Ask/run/project identity, five-second hold, HTTP refusal and reconciliation; U ⚠; R |
| api.js | Fetch/cache/hooks/live polling | Resource lifecycle, HTTP/API versions, stale data and stream cursor; U ⚠; R |
| app.js | Mount and compose desktop/phone views | Global UI state, subscriptions, snapshot freshness and responsive branch; U ⚠; R |
| components.js | Shared live/detail display components | DTO fields, callbacks and imported global state; U ⚠; R |
| data.js | Index/filter/select snapshot entities | Reads global `ui` as well as supplied snapshot, project-qualified keys; U ⚠; R |
| format.js | Format time/IDs/Markdown | Escaping, clock, project-display global and field units; U ⚠; R |
| state.js | UI navigation, drafts and persistence | Mutable exported `ui`, setters/subscriptions/history order, persisted compatibility; U ⚠; R |
| ui/ask.js | Question/options/answer controls | Ask option IDs, action callbacks and draft/hold state; U ⚠; R |
| ui/kit.js | Shared widgets, overlays, cards, Markdown | Presentation DTOs, callbacks, global formatting/state conventions; U ⚠; R |
| views/decisions.js | Owner inbox/ledger/ADR views | Ask identity, action lifecycle, project filter and stale snapshot; U ⚠; R |
| views/drawer.js | Bead detail/live drawer | Selected project/bead, polling disposal, owner command target; U ⚠; R |
| views/floor.js | Slots/resources/machine view | Display-only capacity, identity and timestamps; U ⚠; R |
| views/goals.js | Epic/goal navigation | Project/epic selection, closed visibility and hierarchical state; U ⚠; R |
| views/phone.js | Mobile navigation/sheets | Shares global UI/actions, swipe/back/selection and pending commands; U ⚠; R |
| css/phone.css | Phone layout | DOM classes, media breakpoint and sheet behavior; U, visual behavior untested; R |
| css/layout.css | Desktop layout | DOM structure and breakpoint coupling; U, visual behavior untested; R |
| css/kit.css | Shared component styling | Theme tokens, semantic classes and modal structure; U, visual behavior untested; R |
| static/vendor/ui-runtime.js | Vendored UI runtime, one physical line | Third-party runtime is opaque in this review; U, no claim of vendor audit; R |

The absence of a directory named `utils` is not a win. `data.js`, `format.js`, `components.js`, `ui/kit.js`, and the exported mutable `ui` distribute hidden inputs across ostensibly reusable presentation functions. U means those boundaries remain unapproved; this review does not invent a browser regression from their names.

## Module inventory: delegate

Only the permitted `run` and `status` boundary is relevant to production integration. The copied implementation is inspected to judge the strength of that boundary; task-loop must not start importing these internals or reading delegate state to compensate for them.

| G module (evidence at :1) | One job / what it hides | Caller must know | Verdict; deletion |
| --- | --- | --- | --- |
| adapters/codex_account.py | Codex usage/session accounting translation | D, cumulative versus per-call, missing rollout/service data | U ⚠; R |
| adapters/netprobe.py | Bounded network observation/cache | D, DNS/socket budget, stale versus current and host set | U ⚠; R |
| adapters/procs.py | Spawn/stop/report worker identity | D, failed stop must not become OK; M02 | R ⚠; R |
| adapters/harness/base.py | Common vendor launch/event/summary protocol | D, kind-specific LaunchInputs and dict Summary fields still leak | U ⚠; R |
| adapters/harness/classify.py | Vendor facts to stop reason | D, source precedence and structured versus text evidence | K ✅; R |
| adapters/harness/claude.py | Claude CLI argv/stream/transcript dialect | D, Bash guard supplies read-only promise; M06 | R ⚠; R |
| adapters/harness/codex.py | Codex CLI argv/stream/session dialect | D, supplied sandbox/isolation, parse order, usage baseline | K ✅; R |
| adapters/harness/opencode.py | OpenCode launch/log/events/usage/export | D, macOS sandbox, provisional tools, free-price proof and cleanup/export order | U ⚠; R |
| adapters/harness/opencode_sandbox.py | Build OpenCode command sandbox | D, platform, permissions/roots/cache lifetime and preflight | U ⚠; R |
| adapters/harness/reset_parse.py | Vendor limit time or bounded guess | D, explicit time and source/reset fallback semantics | K ✅; R |
| app/cockpit.py | Present lane readiness and next worker | D/Q, snapshot state/usage/holds/breaker must agree | U ⚠; R |
| app/decide.py | Build fleet, choose route, build launch policy | D, typed-to-dict conversion, config and runner capability | U ⚠; R |
| app/doctor.py | Diagnose/configure lanes | D, check results, unavailable versus disabled, persistent config writes | U ⚠; R |
| app/env.py | Global config/clock/store/environment access | D/F, plugin-derived root, test clock and mutable global context | U ⚠; R |
| app/fleet.py | Assemble lane facts, health and readiness | D/F, concrete stores, history checkpoint, in-place readers; M07 | R ⚠; R |
| app/launch.py | Prepare/supervise/classify/settle one worker | D, many raw dict keys and runner-specific lifecycle obligations; M03/M06 | R ⚠; R |
| app/lease.py | Claim/renew/register/reap/release lane lease | D/F, task exclusivity and real process identity; M02/M03/M10 | R ⚠; R |
| app/onboard.py | Machine readiness and fix hints | D, CLI/login/provider availability; no actual credential files read by review | U ⚠; R |
| app/publish.py | Best-effort bounded live event feed | D/Q, telemetry may fail without changing worker authority | K ✅; R |
| app/run.py | Full routed call and answer/history | D, release before final survivor determination; M02/M03 | R ⚠; R |
| app/settle.py | Apply classified stop to answer/lane state | D, injected clock/net/state, per-reason side effects and original detail | K ✅; R |
| app/status.py | Full/cheap status and snapshot | D/Q/F, cheap age and refresh semantics; not coherent authority | U ⚠; R |
| app/supervisor.py | Own worker/pumps/watchers/termination | D, registration cannot be swallowed telemetry; M03 | R ⚠; R |
| app/usage.py | Populate lane usage/auth/window facts | D/F, vendor baselines, stale readings and injected caches | U ⚠; R |
| app/watch.py | Turn/idle/first-event/sleep-gap policy | D, monotonic versus wall, touch/poll/event ordering | K ✅; R |
| cli/verbs.py | Command handlers and output | D, which commands mutate state/config and typed exit behavior | U ⚠; R |
| contracts/codec.py | Dataclass record/union codec | W, unknown keys, missing/null and version semantics | K ✅; R |
| contracts/events.py | Vendor-neutral harness event union | D/W, IDs/order/finality and provisional events | K ✅; R |
| contracts/history.py | Run/refusal/health/gap/checkpoint records | D/F/W, timestamp is not an ordered journal cursor; M07 | R ⚠; R |
| contracts/live.py | External live event vocabulary | D/Q/W, telemetry truncation and worker identity prelude | K ✅; R |
| contracts/routing.py | Routing/settings/decision records | D/W, role/tier/runner and engine-only invariants | K ✅; R |
| contracts/schema.py | Generate strict JSON Schema from records | W, null/union/default semantics and consumer dialect | U ⚠; R |
| contracts/state.py | Shared mutable router state representation | D/F/W, incompatible document cannot mean no leases; M01 | R ⚠; R |
| contracts/status.py | Typed status/cockpit/role payload | D/Q/W, freshness and nullable unknowns | K ✅; R |
| contracts/stores.py | Atomic locked state/config/history/checkpoint storage | F/D, authority/cache distinction and lock callback scope; M01/M10, R2 | R ⚠; R |
| contracts/wire.py | Request/result/stop/worker envelope | D/W, capability support beyond version integer | U ⚠; R |
| domain/cost/accounting.py | Fold/merge usage and per-call cost | D, cumulative baseline and vendor billing units | K ✅; R |
| domain/health/ledger.py | Replay breaker and lane-health decisions | D/F, event identity cannot be timestamp; M07 | R ⚠; R |
| domain/lanes/lane.py | Availability/reserve/strain/window policy | D, complete usage/out/hold/model facts and current time | K ✅; R |
| domain/policy/matchers.py | Parse supported shell/policy text | D, unsupported forms must not silently permit writes | U ⚠; R |
| domain/policy/shell.py | Judge allowed shell effects | D, executable names do not define read-only behavior; M06 | R ⚠; R |
| domain/routing/router.py | Choose route/resume under tiers/holds/health | D, current fleet and runner enforcement capability | K ✅; R |

## Import graph and deletion verdict

The enforced engine graph is `cli/hook → app → stores → (domain | adapters) → contracts` (`.importlinter:16`). App slices are separately ordered. The scan did not show domain importing app, stores, or adapters directly in either project. That is a **keep for direct direction**, not proof of effect freedom: `T/contracts/locks.py:5` imports `stream_proc`; both contracts packages expose concrete storage. Domain's permitted bottom layer is therefore not intrinsically pure. A.F12 already owns that defect; R2 makes its migration reviewable.

Observed engine dependency spine:

```text
app/launch -> app/run/entry -> Engine
Engine -> run/stages -> run/run_once -> lower slices
Engine -> land/lander -> lander_host -> step-host protocols
Engine -> run/closer -> closer_host -> step-host protocols
app/loop -> slots + asks + release + report + injected run launcher
dashboard -> contracts (including concrete readers) + injected owner callbacks
```

`run/stages.py:32` and `run/worker_request.py:14` put reverse Engine imports behind `TYPE_CHECKING`; these are type-reference cycles, not demonstrated runtime import cycles. No runtime cycle was established in the inspected edges. A complete computed strongly-connected-component check was not run and is **untested**. The delegate's inspected spine is `run → decide/fleet/launch → supervisor/watch/harnesses → contracts/domain`; `cockpit → decide` does not by itself form a return edge. Do not describe a busy graph as cyclic without the return import.

The more damaging graph is the capability graph. `Engine` hands itself to lazily built parts (`T/app/run/engine.py:189`), and `CloserHost`/`LanderHost` union the same underlying host's views (`T/app/run/closer_host.py:94`, `T/app/land/lander_host.py:82`). The arrow back to writable state is an object reference, so an import DAG cannot catch it. Configuration, state, stores and a checkpoint writer remain reachable across these conceptual “modules.”

The approved layer skips are structural policy choices, not accidental violations: app can import concrete adapters and bottom contracts; CLI can directly use bottom contracts; dashboard imports effectful contracts; hook/prepush starts its lightweight subprocess boundary. The engine prohibition against direct domain→adapter imports says nothing about transitive I/O through contracts or callbacks. The delegate `domain/policy/shell.py` and engine `domain/lanes/matchers.py` independently implement a safety-relevant command language and already disagree (M06).

**A.F12 is too soft:** it ranks the symptom as P3 and recommends removing hosts. The actual deletion exercise has to name which guarantees disappear, and which were never present. `land_with_engine` and `close_with_engine` (`T/app/run/engine.py:95`, `:99`) contribute forwarding names only. Delete them: composition remains. Delete `closer_host.py`: the sum-type boilerplate vanishes, but each step still needs its dependencies. Delete the domain check planner or a vendor event parser: ordering/grammar complexity returns in every caller. Those are different verdicts, not the same complaint about file count.

**Size splits:** `T/contracts/needs.py:1` explicitly says the module exists to keep `dash.py` below its cap. Refuse that boundary (R3). `T/contracts/dashcost.py:1` also cites the cap, but its cost-page record family has a coherent API of its own: keep the concept, reject the rationale. The many `parts`, `*_host`, `fields`, `shared`, `common`, and `matchers` files are not automatically size splits. The code proves state fragmentation in the Engine host case; it does not prove their commit-history motive. `domain/prompts/common.py` is shared prompt vocabulary, whereas `adapters/looks.py:1` explicitly combines parsing, filesystem collection, image processes, comparison policy and prompt writing. The latter is an unapproved dumping ground even though it is under 400 SLOC.

### R1 — P2: replace writable host sums with owned transitions (extends A.F12)

Applies to the R1 inventory rows. Engine and `RunOnce` own attempt transitions; `Closer` owns close progress; `Lander` owns delivery progress. `fields.py`, `StateField`, and aggregate host files are implementation scaffolding to remove after those owners exist. `RunContext` retains immutable identity and explicit ports rather than a second alias set.

Target interface, five lines:

```python
RunContext(identity: RunIdentity, profile: AdmittedProfile, ports: RunPorts)
Attempt.advance(state: AttemptState, event: AttemptEvent) -> Transition
Close.advance(state: CloseState, receipt: EffectReceipt) -> Transition
Land.advance(state: LandState, receipt: EffectReceipt) -> Transition
StateOwner.commit(expected_revision: int, transition: Transition) -> Committed
```

Migration: first construct the explicit immutable context alongside Engine; move close state/receipts behind `Close` while keeping existing CLI behavior; move land state behind `Land`; make RunOnce consume returned transitions; remove writable Engine state aliases and the now-empty sum hosts/field initializer. Each step can release with an adapter at the old call site. Do not rewrite the whole engine at once.

Proof: a component test supplies only its declared ports and state, exercises a stop/restart between transitions, and checks the same next effect and final state. Add a boundary rule that these components cannot accept Engine/Any hosts or obtain a raw checkpoint document. Merely mocking Engine attributes proves nothing. The semantic replay test must pass before deleting the wrappers.

### R2 — P2: separate schema, read projection and authority storage (extends A.F12)

Applies to `T/contracts/stores.py`, `locator.py`, `T/stores/files.py`, both contracts packages, and the stores package verdict. This is relocation with capability narrowing, not a rename from contracts to utils.

Target interface:

```python
Document.read() -> Present[T] | Absent | Unreadable | Incompatible
Document.update(expected_revision: int, change: Change[T]) -> Receipt
RunQuery.get(run: RunId) -> RunView | ReadFailure
RunAuthority.transition(expected: AttemptToken, change: RunChange) -> Receipt
```

Migration: expose those protocols while preserving old imports as deprecated adapters; move concrete filesystem/manifest writers into stores; inject a query-only implementation into dashboard readers; move callers individually; remove old effectful exports and ban process/filesystem writer imports beneath domain. Apply M01's refusal semantics to delegate authority state rather than copying permissive cache behavior.

Proof: import-boundary tests reject a concrete storage/process writer reachable through the pure contract facade; shared store contract cases distinguish absent from incompatible/unreadable; dashboard query tests run with a port that offers no mutation method. This proves less than an OS sandbox but substantially more than “imports contracts only.”

### R3 — P3: split dashboard vocabulary by API concept, not leftover lines

Applies to `contracts/needs.py` and its shallow verdict. Target:

```python
attention.NeedRow
attention.AttentionView
snapshot.Snapshot(needs: list[attention.NeedRow], ...)
```

Migration: establish the attention record family, move `NeedRow` with a compatibility re-export, migrate imports, remove the cap-driven standalone file. Proof: the serialized snapshot schema and golden payload remain identical; dependency tests permit an attention consumer without importing unrelated dashboard command DTOs. Deleting `needs.py` alone saves a file, not the owner's attention model.

## Ranked findings beyond the previous reviews

### M01 — P1, refuse-and-redo: delegate's state store can erase live ownership on the next unrelated write

Evidence: `G/contracts/stores.py:75` loads the whole authority; `:85` catches a codec error and `:89` returns `StateDoc()`. `:92` begins a locked transaction, calls that loader, then `:96` overwrites the file with the yielded document. `G/contracts/state.py:1` advertises that foreign shapes read empty; the document includes leases, holds, refs and lane-out facts.

This is not a harmless cache miss. An older router reading a newer state, or a temporarily unreadable/corrupt state, can see no leases and overwrite the shared authority during claim, usage, ref, or config-adjacent bookkeeping. Another process can then admit a duplicate task or ignore an owner hold while the original worker still edits. The lock serializes destruction; it does not make the empty replacement truthful. A.F04 concerns task-loop checkpoints, not this separate delegate authority.

Target:

```python
StateStore.read() -> Present[StateDoc] | Absent | Corrupt | Incompatible
StateStore.transact(expected_schema: SchemaRange, fn: StateChange) -> Receipt
# Only an explicitly absent store may initialize empty state.
```

Migration: introduce strict authority reads next to permissive cache reads; make claim/renew/hold/ref operations refuse unreadable state with typed machine/owner stops; add negotiated migrations or pin readers; retire empty-on-error authority loading. Retain the original bytes on every refusal.

Proof: seed a valid document containing a live lease and hold plus an unknown field/version; attempt every authority mutation from an older reader; assert no worker launch, no byte change, and an incompatible-state diagnostic. Inject a read permission/I/O failure and demand the same outcome. Never exercise this against real user state.

### M02 — P1, refuse-and-redo: delegate releases its task/lane before proving the worker is gone

Evidence: `G/app/run.py:130` calls `lease.release()` before `_finish` at `:131`. Only at `:251` does `_finish` aggregate termination, and `:255` can replace successful outcome with `worker_survived`. `G/app/lease.py:114` unconditionally removes the lease. Separately `G/adapters/procs.py:59` converts a failed stop to `END_ERROR`, but `worker_end` at `:78` recomputes end from survivors/outcome and can erase that stop error when there are no recorded survivors and no outcome.

The lifecycle owner gives away exclusion before it knows whether exclusion is still needed. A following caller can claim the same task or consume the freed lane while a survivor remains. Task-loop may retain its own worker lock; that does not repair delegate's cross-caller lease authority. An unknown stop result is not evidence of absence. The post-release `done`/history calculation also precedes the final survivor override, so history can disagree with the final answer.

Target:

```python
WorkerSession.finish() -> Exited | Survived[ProcessIdentity] | TerminationUnknown
RunLease.settle(end: WorkerTermination) -> Released | Quarantined
# Survived and Unknown retain task exclusion and capacity accounting.
```

Migration: preserve stop errors in WorkerEnd first; decide final termination before history and release; retain/quarantine leases with survivor identities; add a bounded explicit reaper transition before permitting retake. Publish one final disposition to history and answer.

Proof: inject a stopped tree with a survivor and concurrently claim the same task: it must remain refused. Inject `stop_tree` raising with an otherwise successful answer: the lease must stay quarantined, and answer/history must both say termination unknown. Verify eventual release only after positive process-identity absence.

### M03 — P1, refuse-and-redo: process registration is treated as optional telemetry after an irreversible spawn

Evidence: `G/app/supervisor.py:191` spawns; `:194` invokes `hooks.started` under `contextlib.suppress(Exception)` at `:195`. The callback at `G/app/run.py:138` records the worker in the lease through `worker_started`; that persistence operation uses the state transaction (`G/app/lease.py:98`). The supervisor starts pumping work after the suppressed callback. `Run._run` starts its release-protected try only at `G/app/run.py:121`, after post-claim setup at `:119`–`:120`.

Printing a PID on stderr or a best-effort live file is not durable registration in the authority whose reaper needs the worker identity. If the registration store times out, the worker continues; killing route.py then leaves a lease without the worker identity required by `orphan` (`G/app/lease.py:19`). The same callback type mixes required ownership with optional observation. Claim setup outside the try is an additional lifecycle hole, not justification for more suppression.

Target:

```python
Lease.spawn(prepared: LaunchSpec) -> RegisteredWorker | SpawnFailure
RegisteredWorker.run(deadline: Deadline, observers: Observers) -> WorkerTermination
# Registration failure stops/quarantines the spawned identity before returning.
```

Migration: separate mandatory worker registration from best-effort live/ref observers; place all post-claim setup under one scope; fail closed and stop/quarantine on registration failure; move pumping/stdin release after registration; remove suppression around authority writes. Keep observer suppression only where failure cannot affect ownership.

Proof: make registration fail immediately after fake spawn and assert no prompt is fed and stop/quarantine occurs. A real isolated-process regression should kill the router at each spawn/register boundary and prove that a later claim either reaps the recorded group or remains blocked. Proposed tests were not run.

### M04 — P1, refuse-and-redo: a “green” query throws away the check identity that execution carefully computed

Evidence: `T/app/checks/cache.py:112` computes a full RunKey and `:144` compares it on a normal cache hit. The exported `green_result` at `:218`, especially `:224`, accepts check ID/tree/base plus a limited planned-skip producer predicate, without matching expected command, selected tests, environment, toolchain, or full config. `T/app/land/stackgate.py:47` reduces configured gate checks to IDs and `:34` asks that weak query. `T/hook/prepush.py:4` describes the same `tl green STEP --tree --base` authorization.

A result-store query interface has become a second, weaker proof policy. For the same tree/base/check ID, a pass obtained under environment A can authorize delivery under environment B. This does not require the concurrent tree mutation in D.F02. Even when a profile change would change the tree, environment and actual execution facts can differ without it. “Same green decision” in the query docstring is false relative to RunMemo's equality contract.

Target:

```python
Evidence.require(expected: CheckIdentity, subject: TreeBase) -> Proof | Missing
Evidence.record(proof: Proof) -> Receipt
StackGate.require(subject: JudgedCommit, checks: list[ResolvedCheck]) -> GateReceipt
```

Migration: add strict identity-aware reads; pass resolved checks and admitted execution environment from stack/hook adapters; deprecate the ID-only authorization path; keep historical ID-only rows for display only. A hook may invoke a typed helper process without importing record libraries itself.

Proof: create a pass for one tree/base/ID with changed env, argv, selected tests or toolchain identity; ordinary gate, stack gate and `tl green` must all agree that it is missing. A display query may still show the old pass with its original provenance.

### M05 — P1, refuse-and-redo: the executor changes host/container semantics after the cache has already chosen an identity

Evidence: `T/app/checks/container.py:30` probes readiness, and `:32` returns host argv on failure despite a container check declaration. `_probe` at `:54` resolves the configured image/build later. `T/app/checks/cache.py:124` builds the pass identity before execution; `command_key` at `:128`/`:130` omits configuration/toolchain altogether. `T/domain/checks/inputs.py:88` hashes the declared container boolean among settings, not the actual host fallback or resolved image. `T/app/checks/executor.py:163` uses the command key for within-block reuse. `T/app/checks/attempts.py:76` performs the actual Box plan.

A host fallback pass and a container pass can be represented as the same declared check. More directly, two checks with equal argv/env but different host/container declarations can reuse one within-block result through `command_key`. The module hides a consequential policy substitution inside what looks like argv preparation. The caller cannot insist on container proof because the interface returns only argv plus display wording. A warning cannot make the evidence equivalent.

Target:

```python
Executor.resolve(check: Check, policy: ExecutionPolicy) -> ExecutionPlan | Unavailable
ExecutionPlan.identity -> ExecutorIdentity  # host toolchain or resolved image digest
Evidence.key(check: Check, plan: ExecutionPlan, subject: TreeBase) -> CheckIdentity
```

Migration: resolve executor before any reuse decision; make fallback an explicit profile policy with a distinct identity; add image digest/build-input identity to persistent and in-block keys; invalidate legacy records for authorization; then stop accepting a tuple of argv/display text as the execution plan.

Proof: in one block run identical argv once on host and once in a container, and assert two executions. Persist a host-fallback pass, restore Docker, and demand a container run. Change resolved image contents under a mutable tag and demand another run. Existing container construction tests do not establish these identities.

### M06 — P1, refuse-and-redo: the delegate shell-policy module does not contain the read-only contract its harness relies on

Evidence: `G/adapters/harness/claude.py:95` gives a read-only worker Bash and says it is limited by the guard. `G/app/launch.py:42` configures that guard. `G/domain/policy/shell.py:10` allows `sort` and `sed`; `piece_problem` at `:45` rejects sed's in-place flags (`:52`) but has no sort-output rule or sed-script restriction, returning permission at `:65`. By contrast `T/domain/lanes/matchers.py:73` and `:79` explicitly restrict printing sed and reject sort output flags.

`sort -o output input` and a sed write script have no shell redirection or substitution, yet write files through commands admitted as reads. The verdict module judges executable names and a few flags while its caller assumes effect safety. Claude's own permission layer might independently refuse an individual operation; the supplied code does not provide a reliable read-only boundary. This is an interface counterexample, not a claim that a live worker was exploited.

Target:

```python
ReadCommand.parse(argv: list[str]) -> ProvenRead | Unsupported
ReadExecutor.run(command: ProvenRead, sandbox: ReadOnlyCapability) -> Result
# The OS capability enforces writes; parsing improves diagnostics only.
```

Migration: refuse all unsupported write/exec flags and non-print sed forms immediately; share an explicit adversarial command corpus between producer/consumer without importing sibling internals; enforce read-only filesystem capability for every read runner; advertise that capability to task-loop before admitting the role. Do not add another prompt sentence and call it enforcement.

Proof: policy cases for `sort -o`, combined output flags, sed write/exec scripts, find actions and git external commands must refuse. An isolated read-runner test attempts a harmless write to a temporary fixture and proves the filesystem blocks it even if the parser is bypassed. No credential or real repository target is needed.

### M07 — P2, refuse-and-redo: health checkpoints identify replay progress by time, so equal-time events disappear

Evidence: `G/domain/health/ledger.py:92` advances `state.ts` to max row time. `fold` at `:140` claims chunked replay equals full replay, but `:144` filters tail rows using `r.ts > state.ts`. The fleet reads health through that fold (`G/app/fleet.py:85`). `G/contracts/history.py:1` is the typed history/checkpoint family.

Two different events can have the same timestamp. Fold the first, checkpoint, then append the second at that timestamp: the second is dropped. Full replay of both from an earlier cursor includes both, because the sorted input is selected before stepping. A delayed row older than the saved max is also skipped. Routing's breaker can therefore differ depending on where a cache was cut. Wall time is not event identity or journal position.

Target:

```python
History.append(event: HealthEvent) -> EventId
HealthCursor(sequence: int, policy_digest: str)
HealthLedger.fold(events: OrderedEvents, cursor: HealthCursor) -> HealthCheckpoint
```

Migration: add stable event sequence/identity to append receipts; build checkpoints by that cursor, using timestamp only inside time-window policy; invalidate old timestamp-only checkpoints and rebuild; retire `ts` as replay acknowledgment.

Proof: property test all partitions of the same ordered event stream, including equal timestamps and delayed append times: chunked and full replay must match. Include lane-out followed by success and the reverse order at the same timestamp so skipped facts change the expected answer visibly.

### M08 — P2, refuse-and-redo: the live-feed module acknowledges events it never returned

Evidence: `H/api/live.py:22` caps a page at 2,000. `page` at `:102` selects events since the client cursor, returns only the last capped slice at `:105`, and advances the cursor to all current source offsets at `:106`. Source reset detection at `:50` is size-based, not a file generation identity.

After a client falls 2,001 events behind, at least one unseen event is discarded and acknowledged; the next poll cannot retrieve it. Page size is presented as a transport limit but implemented as silent data loss. It can hide the beginning of the causal chain that explains a stop. This is distinct from the producer's intentional message truncation or source retention documented in D. File replacement adds a second cursor-contract uncertainty; equal-size/larger replacements are not detected by the inspected reset rule.

Target:

```python
Live.page(cursor: SourceCursor, limit: int) -> Page[Event]
Page(events, next_cursor, has_more, gap: Gap | None)
SourceCursor(file_generation, delivered_offset)
```

Migration: return the earliest pending capped slice and advance only delivered source offsets; add `has_more`; explicitly mark an initial tail/gap policy; add source generation to new cursors while accepting legacy cursors as requiring resync; bound retained in-memory event buffers separately.

Proof: poll after 2,001+ mixed engine/worker events and drain multiple pages; every seq appears exactly once without unexplained gaps. Replace a file with equal-size content and verify explicit reset/gap rather than silent acknowledgment. The inspected `tests/dash/test_dash_live.py` exercises small merges and partial lines, not this overflow contract.

### M09 — P2, refuse-and-redo: dashboard repository identity is a folder label

Evidence: `H/readers/world.py:61` defines the repository map; `:63` constructs `{basename(p): p}`. Later project/run/lease joins use that map (`:94`, `:112`, `:140`), and event attribution at `:144` accepts basename equality as well as path equality.

Register `/work/company-a/lifesim` and `/work/company-b/lifesim`: one overwrites the other before any view gets a chance to show the conflict. Events from another same-named repo can be attributed through the basename fallback. The observation boundary loses identity, and owner commands subsequently use the surviving project path. This is not A.F09's ask-generation race; it is repository selection failure before ask selection.

Target:

```python
ProjectId = StableRepoKey
Project(id: ProjectId, label: str, path: CanonicalRepoPath)
World.projects: dict[ProjectId, Project]
# Commands and event joins use id; basename is display-only.
```

Migration: add stable IDs beside existing labels; emit both in API and browser keys; reject ambiguous legacy label requests; migrate retained UI selections; remove basename joins. Do not make the label longer and leave it as the authority key.

Proof: two registered repos with identical basenames remain visible with separate runs/events/asks. Submit a command to each ID and assert the exact corresponding path; an ambiguous old basename must refuse, never pick a winner.

### M10 — P2, refuse-and-redo: the delegate state transaction executes process reaping under its machine-wide lock

Evidence: `G/app/lease.py:55` defines the claim transaction and `:56` calls `_live_after_reaping` inside it; `:68` submits it through state update. `_live_after_reaping` calls `reap` at `:76` and history append at `:77`. `reap` at `:26` stops a process tree with a three-second grace. The storage lock defaults to ten seconds (`G/contracts/stores.py:27`); history append takes another file lock (`:112`).

The storage callback API accepts arbitrary blocking work and thus exports no bound on machine-wide lock duration. Multiple orphans or a busy history lock can make claim hold the global state lock long enough to block renewals, ref/worker registration and unrelated routing. Those failures then become lock stops or swallowed authority writes (M03). Infrastructure cleanup has been allowed to stall the authority it is supposed to repair. This is a separate mechanism from task-loop's historical twelve-hour slot holds; it creates the same machine-wide infrastructure blast radius.

Target:

```python
LeaseStore.reserve_reap(identity: LeaseIdentity) -> ReapToken
Reaper.stop(token: ReapToken, deadline: Deadline) -> Termination
LeaseStore.finish_reap(token: ReapToken, result: Termination) -> Receipt
# State lock covers only bounded compare/update; history is emitted afterward.
```

Migration: reserve/quarantine stale ownership in one short transaction; reap outside the lock; compare token/process identity before finalizing; append history after committing, through a retryable receipt path. Preserve the reservation across reaper crashes so competing claimants cannot admit the task prematurely.

Proof: block the fake reaper and history writer while a second independent lease renews and registers a ref; those operations must complete. Race two reapers on the same lease and assert only the reservation holder can finalize, with no duplicate task admission. Use barriers, not timing guesses.

## Historical incidents as acceptance pressure

| Incident | Judgment of the relevant boundary |
| --- | --- |
| LANDBRANCH deletes slot worktree | A.F02/D.F04 own this. U for slot/cleanup modules: classification is insufficient without a directory ownership capability. R1 must not bury that capability back in Engine. |
| PID retained while uv changes process topology; 13 beads burned | A.F06/A.F11 own engine/loop identity. M02/M03 add delegate-side registration/termination obligations; a stable PID cannot substitute for either. |
| Newer repo profile crashes older tl/fails bead | A.F04/F05 and D.F10 own schema admission. Current `wire/slots.py:77` reads only the local base hint before decoding the selected profile; do not repeat the obsolete whole-local-profile assertion. |
| “Over its limit” hides engine-only rejection | A.F08 is too soft given the new evidence: the supplied parser at `G/cli/parser.py:62`–`:67` has engine-only but neither only-family nor advisory flags; `T/contracts/delegate.py:63`–`:67` emits the latter. `G/cli/parser.py:34` turns bad flags into typed bad_request. This pair is concretely incompatible for pinned/advisory writes, not just theoretically negotiable. Installed-pair behavior remains untested. Repair under A.F08 with an actual producer/consumer request-capability test, not another duplicate bead here. |
| Follow-up lint ignored; first line parsed; dropped work | D.F03/F08/F09 own durable delivery. Current source now has `FollowupOutbox` (`T/contracts/followups.py:9`) and RunState aliases for leftovers (`T/app/run/state.py:92`). Do not repeat the old assertion that the queue is necessarily only ephemeral. Recovery/idempotency remains untested here. |
| Umbrella/no-op plan closes done | P modules must reject executable no-op conflation. `H/views/phases.py:85` distinguishes NOOP from DONE in display; display correctness does not prove the task transition. Existing A/D discussion owns this historical classification. |
| Paused without wake | A.F07/D.F11 own this. U for pause/persistence/settle boundaries: a policy table is not enforcement until scheduling consumes the same typed episode. |
| Infrastructure failure reserves slots for 12 h | A.F02 owns mutating recovery probes; M10 demonstrates a different infrastructure-lock amplification in delegate. M02 requires explicit quarantine/reaper ownership rather than arbitrary rest duration. |
| Plugin update mid-run breaks execution | A.F04/A.F08 own pair/schema admission; M01 adds the sibling's authority reset under reader skew. Pinning code without pinning readable state is insufficient. |
| Main fast-forward changes running config | A.F05/D.F10 own config revision. M04/M05 additionally require check proof to include admitted execution identity, even with a fixed tree and profile. |

The prior reviews are not immutable truth. The current malformed-profile loader now raises `ProfileReadError` (`T/app/wire/slots.py:55`, `:59`, `:65`) rather than the old empty-default behavior described in A.F01/D.F01. Keep that direction; runtime coverage and the independent local `profile_slots` fallback at `:97` remain untested here. Reading old findings and copying their line numbers would have produced a defective review.

## Top 10

Ranked by unintended writers/authorization first, then cross-machine availability and observation integrity. Existing A/D findings retain their own priorities; this list ranks the additive findings in this document.

| Rank | Priority | Finding / verdict |
| --- | --- | --- |
| 1 | P1 | M01 — refuse empty-on-error delegate authority state |
| 2 | P1 | M02 — refuse release before positive termination or quarantine |
| 3 | P1 | M03 — refuse optional process registration after spawn |
| 4 | P1 | M04 — refuse ID-only delivery authorization over full-key evidence |
| 5 | P1 | M05 — refuse cache identity chosen before actual executor identity |
| 6 | P1 | M06 — refuse shell command-name allowlist as read-only capability |
| 7 | P2 | M10 — refuse reaping/history I/O inside global state transaction |
| 8 | P2 | M07 — refuse timestamp-only health replay cursor |
| 9 | P2 | M09 — refuse basename as repository identity |
| 10 | P2 | M08 — refuse cursor acknowledgment beyond delivered events |

## Beads to file

Proposed titles and scope only; no tracker commands were authorized or run. R1/R2 extend A.F12 and the request-capability work extends A.F08; link those existing findings instead of filing competing copies of the same defect.

* **P1: Delegate authority reads must refuse incompatible or unreadable state** — M01; preserve bytes and block claims/updates instead of initializing empty leases/holds.
* **P1: Retain delegate task exclusion until worker termination is established** — M02; preserve stop uncertainty, quarantine survivors and publish one final disposition.
* **P1: Make spawn-to-lease registration mandatory and recoverable** — M03; separate authority callbacks from telemetry and close every post-claim failure path.
* **P1: Use one full check identity for every delivery authorization** — M04; replace stack/hook/green ID-only queries with strict proof requests.
* **P1: Resolve executor before check reuse and fingerprint actual execution** — M05; distinguish host fallback, resolved image and within-block execution identities.
* **P1: Enforce read-only worker capability independently of shell names** — M06; reject write/exec variants and prove filesystem denial in isolated runner tests.
* **P2: Move orphan reaping and history writes outside the delegate state lock** — M10; tokenized quarantine and compare/finalize preserve exclusion during bounded cleanup.
* **P2: Give health replay a stable ordered event cursor** — M07; equal-time and delayed events must yield partition-independent checkpoints.
* **P2: Preserve canonical repository identity through dashboard queries and commands** — M09; migrate project IDs and refuse ambiguous legacy basenames.
* **P2: Advance live cursors only through delivered events** — M08; paginate backlog and publish generation/gap state explicitly.
* **P2: Replace writable Engine hosts with owned attempt/close/land transitions** — R1, extension of A.F12; migrate one lifecycle owner at a time and delete forwarding/alias scaffolding.
* **P2: Separate pure record contracts from authority stores and read projections** — R2, extension of A.F12; strict reads and query-only dashboard ports must be enforceable.
* **P3: Replace the needs DTO cap split with an attention API family** — R3; preserve wire schema while moving by concept, not remaining line budget.
