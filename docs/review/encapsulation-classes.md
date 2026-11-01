# Encapsulation review: classes and functions

Static review, 2026-11-01. Verdict: **refuse-and-redo**. Engine has been divided into files without dividing authority. Too many objects still mean “here is the engine; change whatever you need.” A Protocol listing that arrangement does not repair it.

This adds to [architecture.md](architecture.md) and [dataflow.md](dataflow.md). Their findings are cited as A.Fxx and D.Fxx. Their already-reported cleanup, fencing, profile-selection, checkpoint-version, pause-wake, and follow-up-delivery failures are not new findings here. This review identifies the classes that make those repairs fragile, plus additional local defects. References are to source lines read in this tree. No tests, project executables, git commands, network operations, credential files, or installed plugin state were used. Runtime behavior is **untested**; the tests below are acceptance requirements, not claimed results. Only this document was written. Beads are proposed at the end because running the tracker was prohibited.

P1 means a credible path to accepting work against the wrong execution context. P2 means broken ownership, recovery, concurrency, or operator policy. P3 means an interface that makes those mistakes unnecessarily easy. Severity is attached to a concrete contract failure, not to the number of lines in a class.

## Fifteen classes/functions to refuse

### C01 — P2 — Engine: construction is an execution phase disguised as object allocation

**Verdict: refuse-and-redo.** `src/taskloop/app/run/engine.py:121` takes 17 inputs excluding `self`, including three mode booleans and two `Any` dependencies. At `:149` and `:153` construction takes handover/pause state; at `:161` it opens the run layout; at `:172` it builds another dependency bundle; at `:177` it gives Checker the entire engine; at `:178` it resolves delegate. At `:189` the engine becomes a factory for parts that receive that same mutable object. This constructor does work that can fail after earlier startup effects have happened. There is no return value identifying which startup obligations were acquired.

**A.F12 is too soft:** calling Engine a composition root excuses the central defect. A composition root should assemble capabilities. This one also consumes recovery inputs, owns mutable run policy, exposes command execution, posts comments, and manufactures land/close authorities. Its `sh` and `ai` forwarding interfaces erase argument types (`engine.py:262`, `:306`). Moving another method to another host wrapper will reproduce the same design.

Target interface:

```python
def admit(request: RunRequest, ports: AdmissionPorts) -> Admission: ...
def assemble(admission: Admission, ports: RunPorts) -> RunDriver: ...
class RunDriver:
    def advance(self, event: RunEvent) -> RunTransition: ...
```

Migration: first introduce an explicit admission result containing run identity, selected configuration, and recovery disposition. Next move startup effects behind `admit`, with explicit cleanup on failed admission. Then assemble stage objects with operation-specific ports and remove Engine forwarding methods as their callers migrate. Each step can retain the existing command entry point.

Proof: inject failure after each admission acquisition and assert the recorded acquisitions are either retained for recovery or released, with no stage dispatch. Assembling an already admitted run must consume no recovery pointer and perform no delegate call. This tests a lifecycle boundary, not constructor field equality.

### C02 — P2 — StateField / carries_state: writable aliases make every collaborator a state owner

**Verdict: refuse-and-redo.** `src/taskloop/app/run/state.py:51` returns the actual stored object; `:54` accepts any replacement. `carries_state` at `:100` installs these descriptors for every eligible field. `StateAttrs` at `:58` duplicates the declarations to satisfy static typing. The result is three spellings of the schema and no boundary around mutation. `e.accepted.append(...)` changes the persistent-state candidate without calling the descriptor setter, a transition validator, or a persistence operation.

This is the class-level enforcement missing from A.F12, not another report of its import-layer issue. `tests/run/test_state.py:111` explicitly requires alias identity with `assertIs` at `:115`: it protects unrestricted aliasing. A new state field automatically enlarges the write surface of every component holding Engine. That is the wrong default for future recovery obligations.

Target interface:

```python
class RunStateOwner:
    def snapshot(self) -> RunSnapshot: ...
    def apply(self, command: StateCommand) -> StateRevision: ...
```

Migration: first give consumers immutable snapshots while keeping aliases for existing writers. Next move acceptance, writer-session, and follow-up changes to typed commands with one owner. Finally delete `StateAttrs`, the descriptors, and their identity tests. Do not merely replace descriptors with public setters.

Proof: retain a snapshot, apply acceptance and writer changes, and assert the retained snapshot is unchanged. Reject acceptance without the required review/check evidence. A collaborator handed the snapshot must have no storage handle or mutable list through which to alter the owner's state.

### C03 — P2 — RunState.start_again: a fresh state shares yesterday's mutable queue

**Verdict: refuse-and-redo.** `src/taskloop/contracts/checkpoint.py:108` constructs a new RunState using `getattr` values at `:112`. The retained fields include `leftovers` and `followup_ids` (`:111`), declared as mutable list/dict at `:104` and `:105`. The two RunState objects therefore share those collections. The retained BriefSnap also contains lists/dicts (`:46`). A new outer object is not an independent snapshot.

The failure is directly demonstrable from the function: append a pending item or set a receipt on the returned state and the original state's value changes too. Any retained old state used for comparison or rollback stops describing the old attempt. This is additional to D.F03/D.F09: persisting the queue does not establish ownership of its in-memory representation.

Target interface:

```python
def restart_state(old: RunSnapshot, cause: RestartCause) -> RunSnapshot: ...
```

Migration: first copy retained mutable values recursively and add an independence test. Next represent pending work and receipts with immutable records/collections. Finally replace the string whitelist with an explicit constructor that states which bead obligations survive each restart cause.

Proof: restart a state containing nested follow-up items and a BriefSnap, change every retained collection in the successor, and assert the predecessor remains byte-for-byte equivalent to its original serialized value. Also assert the pending obligations survive; independence must not become accidental deletion.

### C04 — P2 — Checkpoints: “one writer” exposes its document and mutates its host

**Verdict: refuse-and-redo.** `src/taskloop/app/run/state.py:110` accepts `Any`. Public `doc` at `:114` returns the storage object; `writer` at `:117` returns it again. This is a persistence authority that hands out the persistence mechanism. `keep_filed` at `:190` first changes `e.unfiled` and `e.leftovers`, then writes the checkpoint, then invokes an outbox operation. `keep_pending` at `:200` both merges policy, rewrites engine state, writes the outbox, and amends the checkpoint (`:212`, `:215`, `:216`).

The additional defect is the interface's failure semantics: a refusal or write error after the in-memory append leaves a changed host even though the method failed. Callers cannot tell which proposed state was accepted. A.F03 already owns the fencing race; returning `Doc` remains an encapsulation failure even after that race is repaired. D.F03/D.F09 are also insufficient specifications for this class: the current code has a pending queue and outbox, so repeating “add an outbox” would miss its present responsibility tangle.

Target interface:

```python
class RunJournal:
    def load(self, bead: BeadId) -> JournalRead: ...
    def commit(self, expected: StateRevision, change: StateChange) -> CommitResult: ...
```

Migration: first hide document access behind journal operations. Next make follow-up merge produce a proposed immutable change without editing Engine. Then commit that proposal and publish the accepted state to the driver; make any remaining multi-record obligation explicit in the journal result. Do not promise a transaction across files without implementing recovery for it.

Proof: fail checkpoint and outbox writes independently, including a fenced refusal. The caller's previously accepted snapshot must remain unchanged, and recovery must identify the pending operation. No consumer should be able to obtain a `write`/`delete` document from the journal API.

### C05 — P2 — CloserHost: the sum of narrow Protocols is still the whole engine

**Verdict: refuse-and-redo.** `src/taskloop/app/run/closer_host.py:94` unions eight host interfaces. `CloseAllCheckpoints` at `:86` and `CloseTree` at `:90` recombine their authorities. `src/taskloop/app/run/closer.py:180` then constructs every step with the identical object. Annotating a parameter as a smaller Protocol does not produce a smaller object or allocate state ownership.

CloseHost itself exposes mutable disposition/kind/fingerprint fields (`closer_host.py:39`) alongside tracker, git, checkpoint, clock, and stop machinery. `Closer.resume` restores decision fields on the host (`closer.py:121`), while `finish` reads those shared values and dispatches effects (`:126`). The flow has an implicit calling order and a shared result register. Its small step protocols are useful shapes; their reunion into a super-host defeats their purpose. This sharpens A.F12; D.F07 remains the separate settlement-acknowledgment finding.

Target interface:

```python
def decide_close(input: CloseInput) -> CloseDecision: ...
def plan_close(decision: CloseDecision) -> tuple[CloseEffect, ...]: ...
class CloseExecutor:
    def apply(self, effect: CloseEffect) -> EffectReceipt: ...
```

Migration: first make Decide return the complete decision instead of assigning host fields. Next pass that value to the existing close planner and persisted end record. Then construct effect handlers from separate tracker/tree/journal capabilities and delete `CloserHost` and its capability unions. Retain the existing effect ordering until explicit tests authorize changing it.

Proof: a recovered persisted CloseDecision must produce the same effect sequence without reading mutable Engine outcome fields or rerunning decision policy. Give the notes handler only its filing port and verify it cannot obtain tree mutation or source settlement capabilities.

### C06 — P3 — RunContext.open: twenty parameters, then a second home for the same references

**Verdict: refuse-and-redo.** `src/taskloop/app/run/context.py:41` takes 20 parameters excluding `cls`: identity, layout, stores, mutable counters, callbacks, two output flags, and an optional second clock. The record stores `store`, `route`, `clock`, and `traces` as `Any` (`:34`). Engine immediately copies five context members onto itself (`src/taskloop/app/run/engine.py:176`). Both objects now advertise ownership of the same services.

The clock is especially avoidable ambiguity: `open` defaults `now` to `clock.now` (`context.py:65`), but Engine supplies `self.now` (`engine.py:174`), whose implementation uses `time.time` (`:343`). An injected Clock does not by itself determine every timestamp/budget clock. Tests must know which clock each subsystem actually reads. Grouping all twenty arguments into a generic ContextConfig would just conceal the same defect.

Target interface:

```python
def open_telemetry(identity: RunIdentity, layout: RunLayout,
                   ports: TelemetryPorts, options: OutputOptions) -> RunTelemetry: ...
```

Migration: first use the Clock port consistently and remove the optional `now` override. Next extract telemetry construction from tracker/delegate ownership. Then give the driver one telemetry member and migrate callers off duplicate Engine aliases. Identity should carry RunId and typed worktree/repository identity, rather than another bare run string.

Proof: drive the fake clock and assert step timestamps and budget elapsed time agree without patching global time. Construct telemetry with no tracker or delegate dependency. Replacing a context object must not leave a second set of Engine aliases pointing at the old services.

### C07 — P1 — WorkerCall.attach: a prompt hash is not an execution identity

**Verdict: refuse-and-redo.** `src/taskloop/app/run/worker_call.py:197` keys recovery by call coordinates and a truncated SHA1 of `c.full` (`:201`). It immediately adopts a memoized answer at `:205`, or a returned envelope at `:211`. Call coordinates are constructed from step/node and `at` at `:186`. Cwd, tree, effective request policy, and producer compatibility are not part of this recovery predicate.

This permits the same prompt and coordinates to select an answer produced for a different checkout state or cwd. Shape validation at `:346` checks answer data, not whether the write/check work it describes occurred in the current tree. The effective request is built later (`:241`); family restrictions and engine-only recipes come from `worker_request.py:21` and `:22`. Recovery can therefore happen before the current request contract has even been constructed. This is a separate defect from D.F12's consumed/memo write ordering and A.F08's version negotiation.

The surrounding `Call` constructor (`worker_call.py:50`) has 13 inputs, an untyped coordinate tuple, independently mutable full/delta prompts, resume booleans, and `state: Any`. `Ops` at `:35` makes all six callbacks `Any`. There is no typed object representing the precise operation being recovered.

Target interface:

```python
def prepare_call(input: NodeInput, context: ExecutionContext) -> PreparedCall: ...
def recover(call: PreparedCall, journal: CallJournal) -> RecoveryDecision: ...
def execute(call: PreparedCall, ports: WorkerPorts) -> WorkerAnswer: ...
```

Migration: first build the effective request before recovery and persist its semantic identity. Next include worktree/tree identity and relevant policy/schema digests; distinguish “resume an interrupted thread” from “reuse completed effects.” Finally replace Call's freely combined resume fields with explicit fresh/resuming/returned phases. Preserve compatibility handling for old records explicitly; do not silently manufacture a valid identity for them.

Proof: save a successful writer envelope, retain prompt and coordinates, then change cwd or tree. Recovery must require revalidation or execution rather than silently using the envelope as proof of current work. Change only a nonsemantic log destination and permit reuse. Change engine-only/family policy and demand an explicit compatibility decision. This tests execution identity, not merely a different prompt hash.

### C08 — P2 — RunId: a hashable identity object with a public writable identity

**Verdict: refuse-and-redo.** `src/taskloop/contracts/ids.py:40` permits assignment to `text`; the public constructor at `:42` performs no validation. `parse` at `:53` validates only callers that choose it. Hash and equality depend on that writable field (`:77`, `:80`). A RunId can be inserted into a set and then mutated so lookup no longer uses the bucket where it was inserted. `RunId("garbage")` also bypasses the advertised parser.

This is primitive obsession with a wrapper painted over it. Downstream `RunContext.run` is still a bare string (`context.py:27`) despite explicitly mentioning RunId. Keep the distinct BeadId/CheckId/TreeSha vocabulary (`ids.py:10`); refuse the assumption that declaring nominal types while converting them back to strings establishes identity invariants. No PID fix from A.F06/A.F11 is duplicated here.

Target interface:

```python
@dataclass(frozen=True, slots=True)
class RunId:
    text: str
    def __post_init__(self) -> None: ...  # validate every construction
```

Migration: first enforce construction validation and immutability while preserving wire spelling. Next pass RunId through RunContext and call/journal identities. Convert to strings only at filesystem/wire adapters. Keep process identity and run identity separate types; never use this ID as a PID substitute.

Proof: every invalid constructor input is rejected, reassignment fails, and a valid value remains findable as a mapping key through serialization round trips. A type check must reject passing a bead/check ID where a RunId is required.

### C09 — P2 — Shell.run: command facts are returned partly in a tuple and partly in the host

**Verdict: refuse-and-redo.** `src/taskloop/app/run/shell.py:19` accepts nine arguments excluding `self`, including `check` and `pin` booleans and the behavioral string `what`. It returns `(rc, tail)` but publishes termination facts through `e.killed`/`e.wall_hit` (`:39`, `:72`). `Attempts.run` reads those fields after `_once` (`src/taskloop/app/checks/attempts.py:45`); `_once` invokes further callbacks and evidence handling after shell execution (`:66`, `:68`, `:81`). Correct classification therefore requires reading hidden “last command” state before another operation overwrites it.

RunFields uses ThreadFlag (`src/taskloop/app/run/fields.py:23`), so claiming these flags are an ordinary cross-thread boolean race would be wrong. Thread-local storage still does not attach a fact to the invocation that produced it. Nested commands in the same thread can replace the evidence. `what == "check"` also changes stop behavior (`shell.py:30`, `:49`); a label has become an execution-policy switch.

Target interface:

```python
def execute(spec: CommandSpec, cancellation: Cancellation) -> CommandResult: ...
def require_success(result: CommandResult) -> None: ...
```

Migration: first return exit, stop origin, timeout kind, survivors, and output reference together, adapting tuple callers. Next replace `pin` with an explicit execution environment and replace `what` policy branches with command policy. Finally remove the host flags after Attempts and CheckExecutor consume CommandResult directly.

Proof: execute a timed-out command, then a successful nested command, and classify the first from its returned result. It must still be a wall timeout. Distinguish a program exiting 124 from an engine wall timeout and a lane cancellation from an external signal.

### C10 — P2 — CheckHost: supposedly read-only checks receive a tree writer and the entire store bundle

**Verdict: refuse-and-redo.** `src/taskloop/app/checks/host.py:66` mirrors the Engine rather than a check operation. It exposes full EngineConfig (`:78`), Stores (`:86`), command execution with flags (`:98`), Git (`:110`), and `tree_writer` (`:107`). The TreeWriter comment at `:53` says the right belongs to Fixer alone. The aggregate CheckHost gives that right to every consumer typed as CheckHost anyway.

Checker sends the same host into Fixer (`src/taskloop/app/checks/runner.py:68`), BaseCheck and Attempts (`:129`), and CheckExecutor (`:130`). A method-level structural rule can catch a known spelling of a tree write; it cannot make this interface accurately describe authority. The interface also forces a standalone check harness to impersonate a run's step book, output controls, and storage layout. This is the concrete host-Protocol problem behind A.F12.

Target interface:

```python
def apply_fixes(plan: FixPlan, writer: IndexWriter) -> FixResult: ...
def run_checks(plan: CheckPlan, context: CheckContext,
               ports: CheckExecutionPorts) -> CheckBlockResult: ...
```

Migration: first construct a restricted execution adapter with no index writer and only results/durations ports. Next pass IndexWriter solely to Fixer. Then make Checker operate on captured CheckContext and typed options, deleting CheckHost and the storage-path discovery it imposes on consumers.

Proof: run the same prepared CheckPlan through standalone and engine entry adapters and compare captured identities/results. A compile-time negative fixture must reject tree staging or access to unrelated checkpoint/ask stores from CheckExecutionPorts. Existing execution tests must continue to prove actual cancellation behavior; a smaller Protocol alone is insufficient.

### C11 — P2 — CheckExecutor._decide: decide, launch, cache, publish, and race under one name

**Verdict: refuse-and-redo.** `src/taskloop/app/checks/executor.py:77` is not a decision function. It queries prior work, writes reuse receipts (`:92`), launches commands (`:106`), updates shared memo state (`:109`), and publishes producer environment (`:110`). `_reused` at `:163` promises each command runs once per block, but reads `memo.ran` before launch and records the result only after launch.

Different lanes share the executor (`executor.py:49`); `Lanes.run` starts their threads (`src/taskloop/app/checks/lanes.py:46`). `CheckPlan.lanes` groups only by lane name (`src/taskloop/domain/checks/plan.py:25`). Two distinct check IDs with the same command/environment in different lanes can both observe a miss and execute. `RunMemo.lock` protects retention pruning (`src/taskloop/app/checks/cache.py:180`), not command reservation. This is a check-then-act contract violation, separate from D.F02's gate-evidence identity.

Target interface:

```python
def decide_step(input: StepInput) -> StepDecision: ...
class CommandRuns:
    def acquire(self, identity: CommandIdentity) -> RunOrJoin: ...
def apply_step(decision: StepDecision, ports: StepPorts) -> StepReceipt: ...
```

Migration: first introduce atomic per-command in-flight reservation/join behavior within a block. Next extract a pure decision over explicit prior results, due policy, and resource facts. Finally execute decisions and publish receipts separately. Define timeout-extension and cancellation behavior for joiners; a mutex around dictionary access alone leaves duplicate launches possible.

Proof: place identical commands under different IDs in two lanes, synchronize both at the first lookup, and assert exactly one subprocess invocation and two correctly attributed results. Cancel the owning execution and ensure the joining lane receives a cancellation/result according to explicit policy rather than hanging or claiming a pass.

### C12 — P2 — Settle.count_slot: English wording decides whether reset is safe

**Verdict: refuse-and-redo.** `src/taskloop/app/loop/settle.py:65` identifies another branch's unsaved work by exact prefix and suffix of `v.why`. That string decides whether `ready_for("")` is called (`:67`). It also influences the streak that can trigger a default 720-minute hold (`src/taskloop/contracts/config.py:144`; `settle.py:76`). The safety distinction is not represented in Verdict's typed `slot_fault`; `src/taskloop/app/loop/verdict.py:101` collapses every `fault_slot` report to `slot_broken`.

`tests/loop/test_slot_infrastructure.py:93` embeds the same sentence and asserts reset is not called at `:106`. It verifies today's punctuation, not the semantic boundary. Add a diagnostic suffix, rephrase the message, or wrap the error, and the protected path changes. A.F02 owns the released-slot mutation race. This finding is the independent stringly typed precondition deciding whether that mutation is attempted. Incident 8 demands this classification remain stable while diagnostics improve.

Target interface:

```python
def classify_slot(facts: SlotFailureFacts) -> SlotDecision: ...
def settle_slot(decision: SlotDecision, owner: SlotOwner) -> SlotReceipt: ...
```

Migration: first add a structured unsaved-foreign-branch cause through RunReport and Verdict. Next use that cause for reset eligibility and quarantine decisions, preserving human text solely for display. Finally make recovery consume an owned slot capability as required by A.F02, replacing the CLI-shaped SimpleNamespace hold request at `settle.py:48`.

Proof: keep structured facts fixed while changing the complete diagnostic text, including multiline context; reset eligibility and hold accounting must remain identical. Infrastructure failures must never become slot-breakage streaks. Foreign unsaved work must never be touched by a diagnostic recovery attempt.

### C13 — P2 — EngineConfig: a wire record masquerading as validated execution policy

**Verdict: refuse-and-redo.** `src/taskloop/contracts/config.py:169` combines delivery, queue selection, budgets, checks, resources, worker restrictions, review policy, images, and slot environment. `areas` is `dict[str, Any]` at `:199`. Most collections are mutable even though the enclosing Rec defaults to frozen (`src/taskloop/contracts/wire.py:37`). CheckSpec likewise contains mutable argv, dependencies, and environment (`config.py:88`).

Graph validation is explicitly performed once at load (`config.py:322`); it rejects cross-lane reads at `:338`. After loading, `cfg.checks.append(...)` or a nested dependency-list edit can invalidate that result. CheckExecutor separately captures its gate IDs at construction (`executor.py:36`) while continuing to read the shared configuration. The model allows a consumer and a captured index to disagree without a new configuration revision. This is an in-memory contract failure, not a repeat of A.F05/D.F10's choice of profile source revision.

Target interface:

```python
def compile_profile(raw: RepoProfile) -> ValidatedProfile: ...
class ValidatedProfile:
    checks: CheckRegistry
    execution: ExecutionPolicy
    scheduling: SchedulingPolicy
```

Migration: keep the served repository's `.task-loop.json` wire shape stable first. Compile it into deeply immutable registries/policies, including a typed area specification. Then migrate checks, worker requests, loop selection, and delivery to their own projections. A new profile must produce a new validated value; no consumer may mutate the admitted one.

Proof: load a profile with dependent checks in one lane, attempt nested mutation, and assert it is rejected or cannot change the compiled registry. Every projection must name the same configuration identity. Invalid cross-lane reads must be rejected before a worker or check launches. Cover unknown future fields through explicit compatibility tests, not by weakening validation after incident 3.

### C14 — P2 — delegate Run._run: lease lifetime begins before its exception boundary

**Verdict: refuse-and-redo.** In the read-only sibling copy, `_delegate/src/delegate/app/run.py:99` claims a lease at `:110`, starts renewal at `:113`, builds hooks at `:114`, observes git at `:119`, and resolves transcript size at `:120`. Its `try/finally` begins only at `:121`; release is at `:130`. Exceptions in the intervening operations bypass that finally. The git adapter uses `subprocess.run` without an OSError handler (`_delegate/src/delegate/adapters/git.py:8`), so this is not just a theoretical unreachable branch.

RunLease's renewal thread continues until its event is set (`_delegate/src/delegate/app/lease.py:92`), and release sets it at `:110`. Process exit may eventually bound the leak; the function itself provides no such guarantee. Separately, `_hooks` dynamically installs `self.keep_ref` (`run.py:153`), which `_finish` later assumes exists (`:227`). Startup order creates a method as a side effect. Decision/result dictionaries and the 11-input `_finish` at `:213` hide the resulting lifecycle further.

Target interface:

```python
def execute_run(plan: LaunchPlan, ports: LaunchPorts) -> RunCompletion: ...
class HeldRunLease:
    def __enter__(self) -> LeaseSession: ...
    def __exit__(self, *error: object) -> None: ...
```

Migration in delegate: first put every post-claim operation under a context-managed lease. Next return a typed callback/session object from hook construction instead of installing `keep_ref` on Run. Then replace decision/result mutation bags with LaunchPlan and RunCompletion at the orchestrator boundary. Task-loop must continue using the public run/status protocol; do not import these delegate classes into Engine.

Proof: inject exceptions immediately after claim, during hook construction, and during the pre-launch git observation. Assert release is attempted exactly once, renewal is stopped, and no worker is launched. A completion path must receive its ref recorder explicitly, without requiring an earlier hidden method installation.

### C15 — P2 — delegate Settler.apply: result rewriting and lane policy share a mutable Case bag

**Verdict: refuse-and-redo.** `_delegate/src/delegate/app/settle.py:72` takes ten inputs excluding `self`, mutates `res`, probes/classifies network status, chooses a reason handler, and lets that handler mutate both the wire answer and lane state. Case at `:30` carries three different mutable/loosely typed objects (`res`, `o`, `d`) plus optional reset/login facts and a boolean extracted by destructive `pop` at `:74`.

There is a concrete state-transition defect: `_rate_limited` reads previous lane state at `:103`, calculates the next guess count, then performs a separate state update through `mark_out` (`:107`, `:62`). Concurrent workers can read the same old count and overwrite one another's escalation. `_network` can also remove the lane's out-state (`:126`) based on one result's answer flag. The code has no expected lane revision tying either action to the state it judged. This is newly inspected delegate behavior; A.F07's consumer wake-policy finding is not its substitute.

Target interface:

```python
def judge_stop(facts: StopObservation, lane: LaneSnapshot) -> StopDecision: ...
def commit_stop(expected: LaneRevision, decision: StopDecision) -> StopCommit: ...
def render_stop(commit: StopCommit) -> RunResult: ...
```

Migration in delegate: first separate immutable observations from output rendering. Next compute and commit guess escalation against lane state under the same locked transition, with retry on a changed revision. Finally render the committed stop and preserve the original observation/cause separately. Keep wire compatibility at the adapter boundary, including the reason facts task-loop consumes.

Proof: synchronize two rate-limit observations after reading one prior guess and require two committed transitions with the correct progression, rather than two overwrites of one progression. Interleave a new lane-out decision with a recovered network answer and assert the older observation cannot erase newer lane policy. Check original cause plus rendered stop, not just the English sentence.

## Supporting judgments and incident standard

Every supporting seam inspected receives a verdict. These are not additional entries competing with the fifteen targets above.

| Inspected seam | Verdict and reason |
| --- | --- |
| `RunFields` / `land_fields`, `src/taskloop/app/run/fields.py:22`, `:70` | **refuse-and-redo under C01/C02.** Public fields mix persistent state, run-local output, caches, test overrides, route identity, and land bookkeeping. Move each to its owning state/port during those migrations; do not preserve a common mutable superclass. C01/C02 acceptance tests must cover the migrated fields. |
| `Closer`, `src/taskloop/app/run/closer.py:69` | **refuse-and-redo under C05.** Keep the explicit closed effect dispatch at `:150`, but remove the shared outcome register and whole-host construction. The persisted-decision replay test is the proof. |
| `Checker`, `src/taskloop/app/checks/runner.py:46` | **refuse-and-redo under C10/C11.** `run_items` has three boolean controls at `:80`; round history, planning, execution, persistence, and reporting share the host. Migrate to CheckContext/options and result publication; standalone/engine equivalence and concurrent command tests are required. |
| `Attempts` and `StageChecks`, `src/taskloop/app/checks/attempts.py:38`, `src/taskloop/app/run/stage_checks.py:29` | **refuse-and-redo under C09/C10.** Hidden last-command state and broad host access remain despite typed final exceptions. Consume CommandResult and restricted ports; nested-command classification is the proof. |
| `RunMemo`, `src/taskloop/app/checks/cache.py:96` | **refuse-and-redo under C11.** Public `ran` is shared execution coordination disguised as a cache. Move command reservation/join into CommandRuns; the simultaneous-miss test proves the repair. Keep the explicit environment/tree/base components in result keys (`:124`). |
| `CheckPlan` / `Step`, `src/taskloop/domain/checks/plan.py:10`, `:20` | **keep the pure planner boundary.** Explicit dependency coordinates and absence facts make decisions inspectable without execution. Its lane partition at `:25` is not a concurrency guarantee; CommandRuns must own that guarantee under C11. Nested Check values still require C13's immutable compilation. |
| `Lanes`, `src/taskloop/app/checks/lanes.py:37` | **keep its per-lane Round copies and owner join/cancel boundary** (`:44`, `:56`); **untested** for the duplicate-command interleaving in C11. Do not infer whole-executor isolation from copied Round objects. |
| `Verdict`, `src/taskloop/app/loop/verdict.py:28` | **refuse-and-redo under C12.** A frozen outer dataclass still carries string kinds, generic replace fields at `:60`, and inadequate slot-cause precision. Introduce structured causes, then delete text-driven classification; diagnostic-invariance tests prove it. |
| `RunLease`, `_delegate/src/delegate/app/lease.py:42` | **refuse-and-redo under C14.** Public claim/renew/release verbs require callers to maintain lifecycle order manually. Add HeldRunLease and migrate the orchestrator; failure injection must stop renewal at every acquired phase. Keep PID plus process-start checks in orphan classification (`:19`). |
| `Blocked`, `src/taskloop/app/run/blocked.py:11` | **keep the ask/spec invariant at `:17`.** **refuse-and-redo the `blocked_for` helper at `:32` under C07/C09:** string enum names, a `fix` boolean selecting exception class, and `Any` stop payload erase what the exception constructor checked. Replace with typed stop/fix constructors during those migrations; invalid ask-kind combinations and preserved structured causes must be tested. |
| `BeadId`, `CheckId`, `TreeSha`, and `Version`, `src/taskloop/contracts/ids.py:10`, `:87` | **keep distinct identity vocabulary and numeric version parsing.** **untested** for consistent use across app boundaries. C06/C08 require carrying those types instead of reverting to interchangeable strings; parsing a type once is useful only if the type survives. |
| Baseline review documents | **keep their named failure references; refuse treating old source descriptions as current proof.** For example, current `RunState.leftovers` is present at `checkpoint.py:104`, and `Checkpoints.keep_pending` exists at `state.py:200`; D.F03's original omission is not evidence that the current tree still lacks those fields. Their historical fixes remain context, not a license to repeat stale findings. |
| `.importlinter:16` | **keep import direction as a dependency check; refuse it as proof of encapsulation.** It does not restrict members of a passed host. C05/C10 need capability tests as well as import rules. |
| `README.md:67`, `:80` | **refuse-and-redo the unqualified “read-only server” description** while the same description advertises park/stop/note actions. Under A.F09, describe query and command capabilities explicitly and verify the documentation against the command-port API; no new dashboard implementation defect is asserted here. |
| `CLAUDE.md:92`, `:102`; `docs/dev/integrations.md:62` | **keep the public delegate boundary; refuse stale implementation guidance.** Integration text names `Engine.ai_delegate`/`engine.call_delegate` while the inspected implementation uses WorkerCall. Update that mapping alongside C07, and test the documented public argv contract. This review's sibling-source inspection was explicitly authorized; it is not permission for production task-loop to read delegate storage. |

The incidents are acceptance criteria, not excuses for a general rewrite:

| Incident | Judgment under this lens |
| --- | --- |
| LANDBRANCH deleted a slot checkout | **refuse-and-redo** capability distribution (C01/C05/C10). A.F02 and D.F04 own the actual cleanup repair; another branch/path string parameter cannot prove ownership. |
| uv exec kept a PID but changed the process; thirteen beads burned | **refuse-and-redo** interchangeability of run/process/handover identities (C06/C08). Keep the existing explicit process-start distinction in delegate leases. A.F06/A.F11 own the process-liveness findings. A pure fake of `execve` is **untested** for the real topology. |
| Newer repo profile failed a bead | **refuse-and-redo** use of wire config as executable policy (C13), with admission separated from construction (C01). A.F05/D.F10 own revision selection; current compatibility recovery is **untested** here. |
| “Over its limit” hid engine-only unenforced | **refuse-and-redo** mutable result/stop rewriting (C07/C15). Preserve original observations alongside rendered decisions. New wording is insufficient if the structured cause is overwritten. |
| Follow-ups ignored lint and disappeared behind first-line parsing | **refuse-and-redo** dictionaries and half-published host state (C03/C04). D.F08/D.F09 own delivery/idempotency. A multiline diagnostic is data, not a filing acknowledgment. |
| Umbrella no-op closed “done” | **keep the explicit NOOP ask branch** at `src/taskloop/app/run/closer.py:164`; **untested** end to end. C05's immutable CloseDecision must retain it across recovery rather than re-derive it from generic success. |
| Paused beads had no wake rule | **refuse-and-redo** scattered outcome registers (C05/C12). A.F07 owns durable wake semantics. A typed stop must reach an explicit wake/owner decision; a role string alone is insufficient. |
| Infrastructure sidelined slots for twelve hours | **refuse-and-redo** text-dependent reset eligibility (C12). Keep the structured pre-engine/recovery distinctions already tested at `tests/loop/test_slot_infrastructure.py:35`, `:70`; refuse their use as proof that reworded dirty-branch diagnostics are safe. |
| Plugin update broke a running task | **refuse-and-redo** recovery matched by prompt alone (C07). A.F04/A.F08 own compatibility admission. Completed-envelope reuse must judge the execution context after any admitted update. |
| Main fast-forward changed configuration under a loop | **refuse-and-redo** exposing shared config collections and projections without immutable ownership (C13). D.F10 owns freezing the source revision. Deep immutability is additionally required after that source has been chosen. |

## Top 10

Ranked by acceptance of wrong-context work, uncontrolled mutation, then recovery/operator cost. All fifteen targets above remain required; a low rank is not a keep verdict.

| Rank | Priority | Target | Required change |
| --- | --- | --- | --- |
| 1 | P1 | C07 — WorkerCall.attach | Recover an identified execution, not a matching prompt. |
| 2 | P2 | C11 — CheckExecutor._decide | Reserve/join commands before concurrent execution. |
| 3 | P2 | C12 — Settle.count_slot | Carry structured slot causes through the verdict. |
| 4 | P2 | C04 — Checkpoints | Commit explicit state proposals without exposing storage or mutating the caller first. |
| 5 | P2 | C01 — Engine | Separate admission effects, assembly, and advancement. |
| 6 | P2 | C02 — StateField / carries_state | Replace shared writable aliases with one state owner. |
| 7 | P2 | C13 — EngineConfig | Compile wire input into deeply immutable policies. |
| 8 | P2 | C14 — delegate Run._run | Enclose the complete acquired-lease lifetime. |
| 9 | P2 | C15 — delegate Settler.apply | Commit lane decisions against the revision actually judged. |
| 10 | P2 | C05 — CloserHost | Pass a complete decision and separate effect capabilities. |

## Beads to file

Proposals only; no tracker commands were run. File new class-contract work and link existing A/D findings rather than creating duplicates of their incidents.

- **P1: Bind worker recovery to execution context** — C07: prepare the request before recovery; identify tree/cwd/policy/schema and test same-prompt context changes.
- **P2: Serialize duplicate commands across check lanes** — C11: atomic in-flight reservation/join with cancellation and timeout-extension tests.
- **P2: Replace dirty-branch prose matching with SlotFailureFacts** — C12: preserve structured cause through RunReport/Verdict and prove diagnostic text cannot change reset eligibility.
- **P2: Make checkpoint commits accept immutable changes** — C04: hide Doc, separate follow-up merge from effects, and keep the accepted host snapshot unchanged on failure.
- **P2: Split Engine admission from construction** — C01: represent acquired startup obligations explicitly and inject failures between acquisitions.
- **P2: Remove carries_state and the writable state mirror** — C02: introduce a single transition owner and reject mutation through retained snapshots.
- **P2: Make restart state independent of predecessor state** — C03: copy nested retained obligations now, then migrate them to immutable records.
- **P2: Compile profiles into immutable policy projections** — C13: preserve the repository wire format while preventing post-validation registry mutation.
- **P2: Replace CloserHost with CloseDecision and effect ports** — C05: persist complete decisions and replay them without shared Engine outcome fields.
- **P2: Make RunId validated and immutable** — C08: close constructor bypasses, preserve stable hashing, and carry RunId through app interfaces.
- **P2: Return command termination facts in CommandResult** — C09: remove thread-local last-command dependence and separate execution from failure policy.
- **P2: Restrict check execution capabilities** — C10: give index mutation only to Fixer and narrow persistence to check evidence ports.
- **P2: Enclose delegate's complete lease lifetime** — C14, sibling project: move all post-claim preparation under a managed lease and pass ref recording explicitly.
- **P2: Commit delegate stop policy against lane revisions** — C15, sibling project: eliminate mutable Case output bags and test simultaneous escalation/stale clearing.
- **P3: Replace RunContext.open's parameter bundle with telemetry construction** — C06: one clock, typed identity, explicit output options, and no duplicate service aliases.
