# Lens 5: leaking behaviours

Static hostile review, 2026-11-01. **Refuse-and-redo:** execution requirements become suggestions, command strings become evidence identities, and presentation text becomes permission to recover infrastructure. These are misplaced authorities, not naming problems.

This is additive to [architecture](architecture.md) and [dataflow](dataflow.md), read before examining the implementation. Their findings are cited as A.Fxx and D.Fxx; new findings are L.Fxx. References below were re-read in this tree. `_delegate/` is the supplied sibling copy, not evidence of the installed delegate version. No credentials, external files, network, git commands, tracker commands, application commands or tests were accessed or run. Runtime reproduction and proposed tests are **untested**. P1 means possible corruption or certification of work without the required execution; P2 means wrong authority, recovery, expenditure or operator diagnosis; P3 means an enforcement/documentation defect.

“Keep” below approves only the named behaviour and its stated boundary. “Refuse-and-redo” requires the referenced repair. “Untested” refuses to certify a claim that static evidence cannot establish. This is not a whole-repository certification.

## Behaviour boundary table

| Behaviour and judgment | Where it lives today (file:line) | Owner today | Owner it should have | Incident or likely incident |
| --- | --- | --- | --- | --- |
| **Refuse-and-redo, P1:** substitute host execution for a required container; L.F01 | `src/taskloop/app/checks/container.py:26`, `:48` | Container argv builder | Execution admission, with an explicit required environment | Missing Docker becomes a green host result; subsequent checks can trust the wrong environment. |
| **Refuse-and-redo, P1:** equate checks by command and manufacture another check's pass; L.F02 | `src/taskloop/app/checks/cache.py:128`; `src/taskloop/app/checks/executor.py:87` | In-block memo shortcut | Evidence owner comparing resolved execution specifications | Host smoke check certifies an unexecuted container check. |
| **Refuse-and-redo, P1:** candidate code decides which gate obligations disappear; L.F03 | `src/taskloop/app/checks/gateplan.py:91`, `:99` | Gate-plan program in the task checkout | Admission-pinned selection policy; candidate producer may propose | A broken change to `tools/gate_plan.py` skips the checks that would reject it. |
| **Keep:** malformed producer output requires checks; it must not authorize omission | `src/taskloop/app/checks/gateplan.py:102`; `src/taskloop/domain/checks/specs.py:83` | Check selection | Check selection | Preserves refusal on invalid output. L.F03 concerns valid but unauthorized omission, a different problem. |
| **Keep:** built-in diff check is outside the producer's registry skip authority | `src/taskloop/domain/checks/specs.py:24`, `:83` | Engine | Engine | The producer cannot skip `diff-check` merely by naming it; the `repo` guard matters. |
| **Refuse-and-redo, P2:** family preference silently selects advisory enforcement; L.F04 | `src/taskloop/app/run/worker_request.py:21`, `:38` | Worker request builder | Independent enforcement policy admitted against delegate capabilities | Trying a pinned writer weakens the very guard implicated in the “engine-only unenforced” incident. |
| **Refuse-and-redo, P2:** reduce an engine-owned command to a bare recipe name; L.F04 | `src/taskloop/domain/checks/writer_split.py:37` | Command spelling recognizer | Executor capability keyed by a registered operation | `just build` is guarded; `just --justfile ci.just build` or a Python check has no corresponding recipe prohibition. |
| **Untested:** the supplied delegate accepts task-loop's current pinned/advisory request | `src/taskloop/contracts/delegate.py:63`; `_delegate/src/delegate/cli/parser.py:62` | Two independently evolving CLIs | Negotiated request protocol | This copy has neither `--engine-only-advisory` nor `--only-family` in its run parser. A.F08 applies; no installed-version assertion is justified. |
| **Refuse-and-redo, P2:** use English to decide whether touching a slot is safe; L.F05 | `src/taskloop/app/loop/settle.py:65` | Loop settlement | Typed checkout recovery disposition | Reworded dirty-branch error stops suppressing the reset probe; infrastructure can again set slots aside for 12 hours. |
| **Refuse-and-redo, P2:** infer engine disposition from exit code and log punctuation; L.F05 | `src/taskloop/app/loop/verdict.py:82`, `:89` | Parent loop | Child admission/result protocol, with a separate transport-failure case | A new EX_CONFIG cause is reported as “profile newer”; an unreadable outcome becomes a task failure. |
| **Refuse-and-redo, P2:** manufacture repository acceptance text after lint rejects a follow-up; L.F06 | `src/taskloop/adapters/bdcreate.py:8`, `:34` | Tracker adapter | Repository task authoring contract | Missing acceptance/reproduction is filled with a placeholder; creation success masquerades as a usable follow-up. |
| **Keep:** extract missing-section names before clipping tracker diagnostics | `src/taskloop/adapters/bd.py:109` | Tracker adapter | Tracker adapter until bd offers structured errors | The historical first-line-only parser is not this implementation. Keeping multiline extraction does not authorize invented task content. |
| **Refuse-and-redo, P2:** treat the word “restore” as authority to repair and repeat a writer; L.F07 | `src/taskloop/app/write/prepare.py:66`; `src/taskloop/app/run/stages.py:326` | Diagnostic substring matcher | Prerequisite state machine | “Do not restore” can force preparation and an extra call at the same write-attempt number. |
| **Keep:** repository declares opaque prerequisite argv and input files | `src/taskloop/contracts/config.py:154`; `src/taskloop/app/write/prepare.py:24` | Repository workflow contract | Repository workflow contract | Declaring `dotnet restore` is repository knowledge. Interpreting model prose as a repair command is not. |
| **Refuse-and-redo, P2:** profile encodes factory implementation choices | `src/taskloop/contracts/config.py:129`, `:178`, `:190`, `:211` | Served repository's combined profile | Repository owns operations/inputs; factory owns retry, family and enforcement policy | New factory knobs widen the served-repo schema compatibility blast radius. R4 and L.F04/L.F07 define the split. No lifesim profile was supplied or inspected. |
| **Refuse-and-redo, P2:** overwrite recorded run state with an observer's LOST judgment; L.F08 | `src/taskloop_dash/readers/world.py:101`; `src/taskloop/contracts/runlife.py:59` | Dashboard reader using host process probes | Recorded lifecycle owner plus a separately labelled observation | A header says LOST although the manifest still says live; an operator cannot tell which is recorded. |
| **Refuse-and-redo, P2:** display all phases as done merely because bd is closed; L.F08 | `src/taskloop_dash/views/columns.py:106` | Dashboard view | Evidence projection with explicit unknown/skipped phases | Manually closed or no-code work displays check/review progress that was never recorded. |
| **Keep:** derive board placement from explicit typed facts | `src/taskloop_dash/views/columns.py:50` | Dashboard presentation | Dashboard presentation | Column ordering is a view concern. It must not be promoted into a completion receipt. |
| **Refuse-and-redo, P2:** names decide execution class; L.F09 | `src/taskloop/domain/checks/specs.py:30`; `src/taskloop/domain/checks/plan.py:55` | Regex over check ID/command | Explicit check registry metadata | Renaming `compile` to `verify` changes what conflict-fix checking runs. |
| **Refuse-and-redo, P2:** producer compresses rejection causes into a single primary stop; L.F10 | `_delegate/src/delegate/domain/routing/router.py:91`, `:117` | Router's stop/warning formatter | Router reports per-candidate facts; engine decides its own next action | “Over its limit” can remain the explanation for a non-quota rejection. |
| **Refuse-and-redo, P2:** consumer rewrites timeout facts as lane overrun; L.F10 | `src/taskloop/app/run/worker_call.py:287` | Engine call wrapper | Append-only producer evidence plus separate consumer decision | `ans.raw` and `ans.res` describe different stops; terminal diagnosis loses provenance. |
| **Refuse-and-redo, P3:** delegate integration exceeds its documented boundary | `src/taskloop/adapters/delegate.py:157`; `docs/dev/integrations.md:55`, `:72` | Loop's network probe adapter | Explicit machine-health port, or an expressly versioned delegate extension | The stated run/status-only surface also invokes `route.py net`; changing an undocumented command breaks network recovery. R6. |
| **Refuse-and-redo, P1, inherited:** cleanup owns checkout lifetime | `src/taskloop/app/land/cleanup.py:34` | Land cleanup | Checkout lifecycle authority | A.F02 / D.F04; repair R1. Do not file a duplicate finding. |
| **Refuse-and-redo, P1, inherited:** settle recovers a slot after release | `src/taskloop/app/loop/loop.py:331`; `src/taskloop/app/loop/settle.py:69` | Parent loop | Checkout lifecycle authority holding the lease | A.F02; repair R1. |
| **Refuse-and-redo, P1, inherited:** ownership read permits later unguarded mutation | `src/taskloop/contracts/fence.py:71`, `:87`; `src/taskloop/adapters/bd.py:253` | Fence helper and tracker adapter | Conditional transition authority | A.F03 / D.F05; repair R2. |
| **Refuse-and-redo, P2, inherited:** loop address is its PID | `src/taskloop/app/loop/loop.py:353` | Process launcher/state-file naming | Logical execution identity | A.F06; repair R3. The retained-PID uv incident is the required handoff test. |
| **Keep, limited:** engine admission already checks process start identity and explicit predecessor handoff | `src/taskloop/app/slots/engine_lock.py:71`, `:90` | Engine lock | Engine lock | Do not claim the historical TAKEN failure is unchanged here. This does not fix A.F06 or A.F11. |
| **Refuse-and-redo, P2, inherited:** run liveness equates PID existence with execution identity | `src/taskloop/contracts/runlife.py:49` | Shared liveness helper | Attempt identity authority | A.F11; repair R3. |
| **Refuse-and-redo, P1, inherited:** draft planner answer becomes execution cursor | `src/taskloop/app/plan/planner.py:44` | Planner wrapper | Plan admission owner | D.F06; repair R5. |
| **Keep, limited:** no implementation and no prior work yields NOOP instead of “done” | `src/taskloop/app/plan/planner.py:169`; `src/taskloop/app/asks/parks.py:48` | Planner wrapper plus close policy | Lifecycle owner, accepting a planner proposal | The umbrella/no-op incident has an explicit guard and owner wake here. This does not prove every empty-plan path safe; R5 removes the planner's lifecycle authority. |
| **Refuse-and-redo, P2, inherited:** owner-required stops can lack a durable wake | `src/taskloop/app/asks/parks.py:51` | Pause persistence filter and loop fallback | Lifecycle owner | A.F07 / D.F11; repair R5. |
| **Refuse-and-redo, P2, inherited:** profile and install changes alter active-run contracts | `src/taskloop/app/wire/slots.py:97`, `:196`; `src/taskloop/app/run/state.py:122` | Each consumer reloads its own view | Run admission/version owner | A.F04 / A.F05 / D.F10; repair R4. |
| **Keep, limited:** selected engine-profile read failures are explicit | `src/taskloop/app/wire/slots.py:49`, `:59`, `:77` | Profile loader | Profile loader | A.F01 / D.F01 are stale for this path: read/parse failures now raise ProfileReadError and base discovery reads a hint. Slot-profile fallback at `:101` still needs R4. |
| **Keep, limited:** planner queues pending follow-ups durably | `src/taskloop/app/plan/planner.py:67`; `src/taskloop/app/run/state.py:200` | Checkpoint/outbox writer | Follow-up delivery owner | D.F03's assertion that this plan queue exists only in memory is stale. End-to-end filing and replay remain untested here; no claim that A.F10 / D.F08 / D.F09 are all solved. |
| **Keep, limited:** gate run binds returned evidence to checked identities before minting | `src/taskloop/app/land/gate.py:159`, `:173` | Gate | Gate | D.F02's described mint-after-reread defect has an explicit comparison now. L.F01–03 attack the evidence supplied to that gate, not the old race. |
| **Keep:** reject invalid check dependency graphs at profile admission | `src/taskloop/contracts/config.py:322`, `:398` | Profile validator | Profile validator | Duplicate IDs/environment names, missing dependencies, cross-lane reads and cycles are rejected. This does not distinguish same-argv execution environments in L.F02. |
| **Untested:** name-killing hook is a complete process-ownership boundary | `src/taskloop/hook/rules.py:19`; `src/taskloop/hook/pretool.py:8` | Bash text hook | Process capability authority | The inspected code is a bounded shell-token check and allows unreadable input. Keep it as a narrow guard; refuse any claim it proves arbitrary tools kill only owned processes. R3 supplies the ownership boundary. |

## Ranked additional findings

### L.F01 — P1 — Refuse-and-redo: the container adapter overrides the execution contract

`src/taskloop/contracts/config.py:392` rejects container checks without a container specification. That admission rule is then undermined by `src/taskloop/app/checks/container.py:30`: unavailable Docker/image returns the original host argv at line 32. Lines 48 and 53–57 turn the downgrade into a warning. `src/taskloop/app/checks/attempts.py:76` runs that argv, and `src/taskloop/app/checks/executor.py:204` remembers a successful result under the check's requested key. `src/taskloop/domain/checks/inputs.py:91` keys the requested container boolean, not the environment actually selected by Box.

An unavailable environment is not permission to change the test. A missing compiler/library on the host can change what a command does; a host-specific pass can satisfy a check declared for a container. Worse, that pass can be reused after Docker returns. This is a separate evidence defect from D.F02. A.F12 is too soft: “effects hidden in contracts” misses an adapter actively overruling a declared execution requirement.

Target interface (make it impossible by construction):

```python
resolve(check, admitted_env) -> ReadyExecution | EnvironmentUnavailable
execute(ready: ReadyExecution) -> ExecutionReceipt
accept(requirement, receipt) -> Satisfied | Refused
cache_key(ready: ReadyExecution) -> ExecutionKey
```

Only admission may approve a fallback, as a different requirement with a different identity. A ReadyExecution names actual host/image digest and toolchain. An unavailable requirement cannot reach execute or mint a pass.

Migration: (1) return typed unavailable instead of host argv for container checks; retain host execution for explicit host checks; (2) record actual environment in every receipt and key, invalidating older ambiguous container passes; (3) add an explicit owner-selected fallback policy if required, separate from automatic recovery.

Proof test: request a container check with Docker unavailable and a host command that would pass. Assert zero host launches, an environment-unavailable disposition, and no pass record. Restore Docker and require a real container execution. Separately change the admitted image digest with unchanged source/argv and require a cache miss. Runtime status: **untested**.

### L.F02 — P1 — Refuse-and-redo: command deduplication launders another execution's result

`src/taskloop/app/checks/cache.py:130` deliberately blanks config, toolchain, inputs and selected-test identity in command_key. Environment hashing at line 109 includes engine/check env, but not the later per-check values injected by `src/taskloop/app/checks/attempts.py:73`. `src/taskloop/app/checks/executor.py:87` consults this weaker identity before normal cache lookup or resource admission; lines 90–92 save the reused result under the second check's full key. `_reused` at line 170 changes ID/group/lane without executing the second requirement.

Concrete counterexample: two registry IDs in one lane, identical argv/env, first on host and second in a container. Profile graph validation checks IDs/dependencies, not duplicate argv (`src/taskloop/contracts/config.py:325`). The host pass is reused as the container result, and a container-keyed pass is persisted. This is possible even with Docker available; L.F01 is not required. The same shortcut ignores declared execution differences and check-specific runtime identity. D's cache discussion at `docs/review/dataflow.md:88` misses this promotion from a weaker key into a stronger receipt.

Target interface (make it impossible by construction):

```python
resolve(check, inputs, dependencies, environment) -> ExecutionSpec
reuse(spec: ExecutionSpec) -> Receipt | None
run(spec: ExecutionSpec) -> Receipt
record(receipt: Receipt) -> None
```

A receipt carries the exact resolved specification digest. Recording cannot relabel a receipt with a different specification. Runtime env, actual execution location, selected tests and dependency evidence belong in resolution; a display command does not identify an execution.

Migration: (1) disable command reuse across distinct registry IDs/execution settings; (2) replace command_key with the resolved specification key and reject old ambiguous receipts; (3) restore safe deduplication only for provably identical specifications, preserving the original evidence identity instead of rewriting it.

Proof test: configure same argv in host/container checks with different IDs and deterministic ordering. Make host pass and container fail. Require two launches, a failed second result, and no container pass. Add same-argv cases distinguished by injected step identity and dependency receipts. Runtime status: **untested**.

### L.F03 — P1 — Refuse-and-redo: the candidate chooses its own gate exemptions

`docs/dev/integrations.md:37` explicitly suggests a repository script as plan_cmd. `src/taskloop/app/checks/gateplan.py:91` executes it in the checkout being judged. Lines 99–101 accept every syntactically valid run:false decision, with command/output hashes but no independent authorization of why that obligation may disappear. `src/taskloop/domain/checks/specs.py:83` applies the decision to registry checks; `src/taskloop/app/checks/runner.py:109` uses it to determine gate-green.

The candidate can change the selection program, its imported helpers or recipe, and have that changed code decide that the relevant registry gate checks need not run. No malicious worker is needed: a defective optimizer returning a valid all-skip document suffices. Hashing its output proves which waiver was printed, not who was entitled to waive verification. The built-in diff check survives; it cannot detect missing acceptance verification. D.F02's corrected tree comparison cannot repair this authority inversion.

Target interface (make it impossible by construction):

```python
admit(base_revision, registry) -> SelectionPolicy
propose(candidate, changed_paths) -> SelectionProposal
select(policy: SelectionPolicy, proposal) -> RequiredChecks
verify(required: RequiredChecks, receipts) -> GateDecision
```

SelectionPolicy is loaded from an immutable admitted revision, including implementation dependencies. Candidate proposals cannot remove its minimum obligations. A change to the selector or policy inputs forces verification under the admitted selector or an explicit full-check rule. Repository-owned selection remains possible; candidate-owned authorization does not.

Migration: (1) when the selector's dependency closure is unknown or changed, disregard its skips and require registry gate checks; (2) execute selection from a pinned, read-only policy artifact with the diff supplied as data; (3) admit policy revisions between runs and retain policy digest plus obligation receipts.

Proof test: change tools/gate_plan.py to emit valid run:false for every registered gate check while introducing a failing acceptance change. Assert those obligations still run and land is refused. Include an unchanged wrapper importing a changed helper, and a valid selector that lies in its base/full metadata. `tests/checks/test_gateplan.py:63` proves exact-diff recording; `:87` explicitly expects candidate cwd. Neither assertion proves authorization. Runtime status: **untested**.

### L.F04 — P2 — Refuse-and-redo: a routing preference weakens enforcement

`src/taskloop/app/run/worker_request.py:38` derives engine_only_advisory solely from a family pin plus recipes. There is no independent owner choice to relax enforcement. `src/taskloop/domain/prompts/write.py:6` admits the harness may not deny the recipes. `src/taskloop/domain/checks/writer_split.py:43` only exports commands of exactly two tokens beginning with just. Command wrappers and other check runners disappear at this boundary even when engine_only(cmd) is true.

A.F08 is too soft: compatibility negotiation addresses whether a flag is accepted; it does not justify coupling a model-family choice to weaker enforcement or throwing away command identities. The supplied delegate's router treats enforcement as a lane capability (`_delegate/src/delegate/domain/routing/router.py:34`). Its copied parser at `:62` in `_delegate/src/delegate/cli/parser.py` lacks the advisory/family flags, so this copy also makes the compatibility problem concrete. Do not pretend that proves the installed parser's version.

Target interface:

```python
WorkerPolicy(families, enforcement, permitted_operations)
admit_worker(policy, capabilities) -> WorkerAdmission | Refusal
dispatch(admission, brief) -> WorkerResult
```

Migration: (1) stop deriving advisory mode from family; require explicit enforcement policy; (2) key permissions by registered operation and execution capability, keeping any legacy recipe guard clearly limited; (3) negotiate that independent policy before claims, as A.F08 requires.

Proof test: pin a family without a required guard and assert admission refusal with no worker. Repeat equivalent operations as bare just, just with flags, and Python argv; changing spelling must not change admitted ownership. `tests/contracts/test_delegate_wire.py:62` only verifies serialization. Runtime status: **untested**.

### L.F05 — P2 — Refuse-and-redo: the parent loop interprets sentences as state

`src/taskloop/app/loop/settle.py:65` recognizes a dirty foreign branch by exact prefix/suffix, and that recognition suppresses ready_for at line 69. `src/taskloop/app/loop/verdict.py:89` recognizes an unreadable profile by exact English punctuation. Other EX_CONFIG causes become “profile newer” at line 92. Unreadable/incompatible outcome data becomes Result.FAILED at lines 93–97.

The parent is allowed to observe child death. It is not entitled to invent a task verdict or decide safe mutation from diagnostic wording. A.F02 already owns the released-slot reset race; the additional defect is that even the decision to enter that recovery path depends on wording. An editor improving an error sentence can change physical recovery behaviour. This is the same contract failure class as the first-line lint incident, applied to a more dangerous effect.

Target interface:

```python
ChildEnvelope(admission, execution, disposition, recovery, diagnostic_ref)
observe_child_exit(pid, envelope) -> ChildObservation
schedule(observation) -> SchedulingDecision
```

Migration: (1) add typed dirty-foreign-work and profile-error fields to startup envelopes; write them even when the engine never starts; (2) represent missing/foreign envelopes as unknown execution, preserving the original task disposition; (3) delete English recognition and let R1's authority accept/reject typed recovery requests.

Proof test: change all display wording and add multiline diagnostics; assert identical dispositions and zero reset for foreign dirty work. Missing/foreign-version envelopes must not fail or close the bead. Replay a transient infrastructure sequence and assert no unjustified 720-minute slot hold. Runtime status: **untested**.

### L.F06 — P2 — Refuse-and-redo: tracker transport writes task meaning

`src/taskloop/adapters/bdcreate.py:8` supplies generic acceptance, unknown touches and explicitly unrecorded reproduction. After a lint refusal, line 34 retries creation with these sections added. A rejected content contract has become a formatting exercise owned by the adapter.

The first-line parsing incident was real; the current multiline parser at `src/taskloop/adapters/bd.py:113` is not that old bug. But satisfying required headings with “the follow-up named in the title is done” does not recover missing acceptance. This criticism is separate from A.F10 / D.F08 idempotency and D.F09 delivery. A durable outbox delivering a useless task is still wrong.

Target interface:

```python
validate_followup(repo_contract, proposal) -> ValidTask | MissingFacts
create(task: ValidTask, intent_key) -> Created | Rejected
retain(missing: MissingFacts, intent_key) -> PendingAuthoring
```

Migration: (1) preserve lint-rejected proposals without adding acceptance/reproduction filler; (2) obtain repository authoring requirements before generating follow-ups and validate against them; (3) route missing facts to bounded authoring/owner resolution while retaining the durable intent.

Proof test: repository requires concrete reproduction and acceptance. Return a proposal lacking both and multiline missing-section diagnostics. Assert no placeholder retry creates a bead; the exact proposal remains pending until valid content or an explicit waiver arrives. Runtime status: **untested**.

### L.F07 — P2 — Refuse-and-redo: model/check prose commands prerequisite recovery

`src/taskloop/app/write/prepare.py:69` uses case-insensitive substring matches, including default restore/NU1 triggers declared at `src/taskloop/contracts/config.py:156`. A match forces coordinator execution and repeats the write without a new attempt number (`src/taskloop/app/run/stages.py:326`). `tests/write/test_prepare.py:55` explicitly enshrines two writes counted as one.

“Do not restore” and “the restore bug is fixed” match the same command trigger as a genuine missing-assets diagnosis. This is not an unbounded-loop allegation: prepare_retried limits the path within that StageState. It is still a worker-generated sentence authorizing a coordinator operation and hiding an extra physical call behind one logical attempt. The repo should describe prerequisite operations and inputs; the engine should decide whether state requires them.

Target interface:

```python
PrerequisiteProblem(operation_id, observed_input_digest, evidence_ref)
decide_repair(problem, current_state) -> Repair | Refuse
record_physical_call(logical_round, call_id, repair_episode) -> None
```

Migration: (1) count/log every physical call and retain legacy matching as an explicitly provisional hint; (2) require structured prerequisite problems corroborated by input state or a registered diagnostic; (3) remove word triggers and resume the same repair episode durably.

Proof test: negative/quoted restore text performs no repair; a typed stale-input report triggers exactly one repair, two distinct physical-call records, and one logical round. Restart between repair and write must not spend another unrecorded repair allowance. Runtime status: **untested**.

### L.F08 — P2 — Refuse-and-redo: the dashboard turns observations into recorded facts

`src/taskloop/contracts/runlife.py:59` computes observer liveness using local host/PID state. `src/taskloop_dash/readers/world.py:101` substitutes RunState.LOST in a RunHeader while retaining the manifest's other fields. `src/taskloop_dash/readers/runlogs.py:25` similarly replaces projected life. Separately, `src/taskloop_dash/views/columns.py:112` sets every phase dot to done when bd is closed, even without a visited phase.

A.F11 already covers PID identity; do not duplicate it. This finding is provenance: the UI field does not distinguish recorded LOST from observed stale/dead, and “closed” supplies nonexistent phase evidence. Column placement from typed facts is legitimate presentation. Invented verification history is not. A manually closed umbrella bead must not look as though review/gate executed.

Target interface:

```python
RunView(recorded_state, observation, observed_at, source_revision)
PhaseView(phase, evidence_state, receipt_ref)
project(recorded_facts, observations) -> RunView
```

Migration: (1) add observation/provenance alongside recorded state without substituting it; (2) derive phase dots from receipts, with unknown/skipped distinct from passed; (3) move lifecycle decisions to R3 and keep the dashboard a consumer of both recorded and observed facts.

Proof test: a live manifest plus a dead-process observation retains recorded live and shows a labelled suspicion; it does not acquire a recorded LOST reason/time. A manually closed bead with no check receipts has unknown/unexecuted gate dots. Runtime status: **untested**.

### L.F09 — P2 — Refuse-and-redo: check names secretly program execution

`src/taskloop/domain/checks/specs.py:30` derives tags from ID plus command. `src/taskloop/domain/checks/matchers.py:48` identifies Unity by substring and build/compile by word pattern. Those tags drive Unity ordering (`src/taskloop/domain/checks/plan.py:47`) and which repository checks survive conflict-fix selection (`:56`). Writer permission also defaults to a slow-looking name when no timing exists (`src/taskloop/domain/checks/writer_split.py:35`).

Renaming a check for readability changes execution and permission defaults. Calling a compile wrapper verify removes it from conflict-fix checking; calling an unrelated command unity-report moves it into the expensive Unity class. The final land gate is a separate safeguard, so this is P2 rather than a claim of automatic unsafe delivery. Repository owners cannot review policy that exists only as engine regex folklore.

Target interface:

```python
CheckPolicy(cost_class, conflict_fix_required, worker_execution)
RegisteredCheck(id, argv, policy: CheckPolicy)
schedule(checks, measured_costs) -> CheckPlan
```

Migration: (1) expose the resolved inferred policy in diagnostics and warn when relying on names; (2) add explicit policy fields and migrate registrations while preserving effective behaviour; (3) remove name inference, leaving measured duration only as a scheduling estimate, never permission.

Proof test: rename IDs and executable wrappers while preserving explicit policy. Require unchanged conflict-fix set, scheduling class and worker permissions. Runtime status: **untested**.

### L.F10 — P2 — Refuse-and-redo: cause facts and consumer decisions share one mutable stop

The supplied router collects rejected lanes at `_delegate/src/delegate/domain/routing/router.py:44`, but only replaces the primary reason with engine_only_unenforced when the later stop has no reason (`:92`). Its `_family_state` falls back to “over its limit” whenever the first lane exists and is not marked out (`:117`–127), without proving quota caused unusability. These are concrete producer-side sources of the incident's misleading diagnosis; they are not just downstream text truncation.

Task-loop then adds another authority: `src/taskloop/app/run/worker_call.py:299` constructs a new lane/transient overrun stop and line 303 replaces the interpreted result while preserving the original raw envelope. `note_result` at line 317 publishes a clipped first_error/say. D's delegate cause-loss table describes this rewrite but is too soft: a consumer policy decision must not replace producer stop facts. The owner needs both why no candidate was admitted and what task-loop elected to do about it.

Target interface:

```python
ProducerStop(reason, candidate_rejections, evidence_ref)
ConsumerDecision(action, policy_rule, source_stop_ref)
CallResult(producer_result, transport_observation, consumer_decision)
```

Migration: (1) retain/display all candidate rejection codes and stop synthesizing quota claims from “not out”; (2) append overrun/reroute as consumer decisions pointing to immutable producer results; (3) carry the evidence reference through report/park/terminal projections so summaries do not replace the diagnosis.

Proof test: combine guard rejection, a held/disabled lane and real quota exhaustion. Assert distinct structured causes survive routing, engine timeout policy, pause and final display. An engine-overrun decision must leave producer reason/scope intact. Runtime status: **untested**.

## Existing findings: repair contracts, not duplicate tickets

These capsules supply concrete interface, releasable migration and proof obligations for inherited refuse-and-redo rows. They extend the cited findings without renumbering or repeating their failure narratives.

**R1 — P1 — Checkout lifetime, A.F02 / D.F04.** Land records delivery; checkout ownership authorizes detach/reset/remove. A boolean is_slot callback (`src/taskloop/app/land/cleanup.py:20`) is insufficient authority.

```python
acquire_checkout(path, expected_generation) -> CheckoutLease | Busy
probe(lease) -> CheckoutHealth
reset(lease, target) -> RecoveryReceipt
retire(lease, expected_head) -> Kept | Retired
```

Migration: first make health probing read-only; next require the lease at each mutation entry; finally remove direct cleanup/reset git access. Proof: interleave land cleanup and another run's checkout acquisition; no foreign detach/remove/reset is possible. Include a persistent slot and an ad-hoc worktree. This is the “make it impossible” repair for the inherited P1 cleanup rows.

**R2 — P1 — Conditional state transitions, A.F03 / D.F05.** A preliminary fence read is not a write capability (`src/taskloop/contracts/fence.py:87`).

```python
claim(bead, expected_revision) -> ClaimGeneration
transition(claim, expected_revision, change) -> Applied | Stale | Unavailable
checkpoint(claim, expected_revision, cursor) -> Applied | Refused
```

Migration: refuse unavailable ownership first; add atomic generation allocation/conditional mutation at the tracker boundary next; then remove unguarded transition paths. If the external tracker cannot supply it, enforce a shared serialized transition authority rather than promise CAS it does not have. Proof: retake between authorization and close/checkpoint; stale holder changes nothing. This is the construction constraint for the inherited P1 fence row.

**R3 — P2 — Execution identity, A.F06 / A.F11.** The existing engine predecessor exception is retained, but it must not serve as the universal identity model.

```python
ExecutionId(run, attempt, nonce)
ProcessIdentity(host, boot, pid, birth)
handoff(execution, successor, pending_commands) -> AcknowledgedTransfer
observe(execution) -> Live | Dead | Unknown
```

Migration: add execution IDs beside existing PID files; dual-read during deployment; transfer stop targets on acknowledged takeover; retire PID-addressed state after migration. Proof: real uv exec chain, PID reuse, owner stop during takeover and surviving worker. Assert one logical run/loop and one preserved stop command. The text hook remains defence in depth, not process ownership.

**R4 — P2, with inherited P1 version-state risk — Admission contract, A.F04 / A.F05 / D.F10.** Keep repository-provided plan/prepare/check operations. Refuse the undifferentiated RepoProfile coupling them to factory timing, retry and family internals (`src/taskloop/contracts/config.py:129`, `:178`).

```python
RepoWorkflow(version, operations, checks, input_rules)
FactoryPolicy(version, limits, routing, retry_policy)
admit(workflow, factory, installs, saved_state) -> RunContract | Refusal
resume(contract_id, checkpoint) -> AdmittedResume | MigrationRequired
```

Migration: freeze a combined effective snapshot first, including slot configuration; then introduce separately versioned workflow/factory inputs with a compatibility adapter; finally negotiate new code/profile/checkpoint readers before transfer. Unknown state is a refusal, never absence. Proof: fast-forward main and update plugins while active; effective paths/requirements remain pinned, incompatible hops preserve the predecessor checkpoint, and subsequent runs explicitly admit the new contract. This makes the inherited P1 upgrade loss impossible at the resume boundary rather than hoping safe-point naming is enough.

**R5 — P1 for plan admission; P2 for wake policy — Lifecycle owner, D.F06 / A.F07 / D.F11.** The current NOOP guard stays; Planner returns proposals and cannot publish an executable cursor or request source closure directly.

```python
PlanProposal(stages, question, completion_claim, followups)
admit_plan(proposal, evidence, contract) -> ValidatedPlan | Noop | NeedsInput
finish(validated_evidence) -> CompletionDecision
pause(cause, episode) -> ParkWithWake
```

Migration: first persist drafts distinctly and accept only validated cursors; then route empty/completion proposals through lifecycle policy; finally make every pause episode carry an explicit owner/event/time wake consumed unchanged by scheduling. Proof: kill after draft save, submit an umbrella/no-op plan, and pause for an owner-only delegate error. None executes unvalidated stages, closes “done” without evidence or wakes on an unrelated role timer. This is the construction repair for the inherited P1 planner row.

**R6 — P3 — Integration surface.** `src/taskloop/adapters/delegate.py:164` builds a net command beyond the stated run/status-only contract. It is not made legitimate by describing every delegate invocation as worker-run.

```python
MachineHealth.probe(targets) -> NetworkObservation
Delegate.run(request) -> WorkerResult
Delegate.status() -> RoutingObservation
```

Migration: first declare the existing extra dependency accurately; next inject MachineHealth independently or negotiate the delegate extension; finally test that only admitted commands are invoked. Proof: a run/status-only delegate remains sufficient for worker dispatch and status, while network recovery uses its separately configured port. Runtime status: **untested**.

## Top 10

Ranked additional work; inherited P1s remain blockers under their existing A/D IDs and repair capsules above. This ordering does not downgrade them.

| Rank | Priority | Judgment | Finding |
| --- | --- | --- | --- |
| 1 | P1 | Refuse-and-redo | L.F01 — required container silently becomes host execution |
| 2 | P1 | Refuse-and-redo | L.F02 — same-command reuse manufactures a stronger pass |
| 3 | P1 | Refuse-and-redo | L.F03 — candidate selector authorizes its own gate exemptions |
| 4 | P2 | Refuse-and-redo | L.F04 — family pin weakens enforcement; command ownership loses identity |
| 5 | P2 | Refuse-and-redo | L.F05 — sentences and exit codes control recovery/task disposition |
| 6 | P2 | Refuse-and-redo | L.F10 — routing causes and consumer policy overwrite one another |
| 7 | P2 | Refuse-and-redo | L.F06 — tracker adapter manufactures missing task meaning |
| 8 | P2 | Refuse-and-redo | L.F07 — prose triggers prerequisite repair and undercounts physical calls |
| 9 | P2 | Refuse-and-redo | L.F09 — check names secretly choose execution policy |
| 10 | P2 | Refuse-and-redo | L.F08 — dashboard observation/closure becomes invented execution evidence |

## Beads to file

Proposals only; no tracker commands were run. Link existing A/D issues for R1–R5 instead of filing copies. Recheck their repaired portions before reusing old acceptance criteria.

- **P1: Refuse unavailable required check environments** — Implement L.F01's resolved environment receipts and prohibit automatic host fallback/cache certification.
- **P1: Deduplicate only identical resolved executions** — Implement L.F02; a host receipt must never certify an unexecuted container/dependency-specific requirement.
- **P1: Pin gate-selection authority outside candidate control** — Implement L.F03 with immutable selector dependencies and mandatory checks when selector changes are untrusted.
- **P2: Separate worker-family choice from enforcement admission** — Implement L.F04 and link A.F08; operation identity must survive command spelling changes.
- **P2: Replace loop prose recognition with child dispositions** — Implement L.F05 and link A.F02; missing reports remain execution uncertainty, not invented bead failure.
- **P2: Preserve delegate rejection facts beside engine decisions** — Implement L.F10 with per-candidate codes and immutable producer evidence through terminal reporting.
- **P2: Retain incomplete follow-ups for repository-aware authoring** — Implement L.F06 without placeholder acceptance/reproduction; link existing delivery/idempotency work.
- **P2: Make prerequisite repair a typed durable episode** — Implement L.F07 with independently counted physical calls and corroborated repair requests.
- **P2: Declare check scheduling and conflict policy explicitly** — Implement L.F09; renaming IDs/commands must not change policy.
- **P2: Separate dashboard observations from recorded lifecycle/evidence** — Implement L.F08; closed tasks cannot invent executed phase receipts.
- **P3: Enforce the documented delegate integration surface** — Implement R6 or explicitly version the additional net dependency and test its admission.
