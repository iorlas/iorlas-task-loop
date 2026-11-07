# Encapsulation review: layers

Static review of this tree, including the supplied `_delegate/` copy, on 2026-11-01. **Verdict: refuse-and-redo.** The dependency graph regulates package names. It does not reliably regulate effects, mutation authority, or who decides policy. A green architecture check would not establish those properties.

This is additive to [architecture.md](architecture.md), cited as **A.Fxx**, and [dataflow.md](dataflow.md), cited as **D.Fxx**. Their ownership races, checkpoint loss, configuration revision mixing, and follow-up delivery failures remain theirs; this document does not count them again. In particular, **A.F12 is too soft:** calling the layer problem P3 understates an executable escape route through the supposed foundation. L04 specifies the missing boundary and enforcement. References below were read with numbered source output. Earlier reviews' line numbers are not assumed current.

No tests, linters, application commands, git operations, network requests, or credential reads were performed. Runtime correctness and current gate results are **untested**. Proposed tests below are acceptance criteria, not claimed results. P1 means possible loss of work or required policy; P2 means broken recovery, admission, or operational authority; P3 means a structural guarantee the implementation does not earn.

## Layer verdicts: claimed rule versus actual behavior

The claimed order is `cli/hook > app > stores > domain/adapters > contracts` (`.importlinter:16`). Domain and adapters occupy independent positions in the same level; this is not permission for domain to import adapters. App slices have a second ordering (`.importlinter:116`). README.md:96 names the layers, and CLAUDE.md:83 identifies import-linter and Ruff as their enforcement.

| Layer | Claimed rule and actual behavior | Judgment |
| --- | --- | --- |
| domain | Pure decision code is the local claim in `src/taskloop/domain/checks/lint.py:1`. Yet `command_problems` asks an effectful probe at lines 96 and 100. Its real implementation starts `just` at `src/taskloop/adapters/check_probe.py:40`. `src/taskloop/domain/interpret.py:43` invokes effects and line 44 commits their ledger; its checkpoint ledger suppresses a fencing exception at line 68. The import order permits all of this through protocols and contracts. | **Refuse-and-redo, P2 — L04.** Passing an effect as an argument does not make executing it pure. Keep value transformations, move execution and persistence decisions to app. |
| app | Owns orchestration and may call stores, domain and adapters. The slice graph is enforced, but `run`, `wire`, and `launch` are deliberately broad composition points (`.importlinter:135`). `CheckHost` exposes stores, spawner, shell, index writer and the full Git port (`src/taskloop/app/checks/host.py:86`, `:88`, `:98`, `:107`, `:110`). | **Refuse-and-redo, P3 — L05.** Slice acyclicity is useful; a host carrying every authority defeats the advertised capability split. |
| contracts | Lowest layer, records and protocols; its specific effect bans are selected imports (`.importlinter:39`, `packages/kernel/src/tlkernel/ruff.toml:6`). `JsonStore.read`, `write` and `delete` perform filesystem effects (`packages/kernel/src/tlkernel/stores.py:90`, `:115`, `:118`). `runlife.reconcile` writes lifecycle state (`packages/kernel/src/tlkernel/runlife.py:64`). `contracts/locks.py:13` probes real processes through `stream_proc`. | **Refuse-and-redo, P2 — L04.** The foundation is also a storage implementation, process adapter and application service. Its package name is laundering their authority. |
| ports | There is no separate source ports package in the inspected layout. The protocols reside in `packages/kernel/src/tlkernel/ports.py`; its docstring at line 3 promises typed seams with real/fake implementations. `Git` combines reads, staging, reset, branch changes and push (`:175`, `:327`, `:338`, `:360`). `Delegate` is not the execution interface the worker actually uses (L07). | **Refuse-and-redo, P2 — L01/L07; P3 — L05.** Protocol declarations are neither proof of failure semantics nor narrow capabilities. |
| stores | Prohibited from importing domain (`.importlinter:87`); intended to supply persistence. `FileDocSet.of` merely returns the concrete contracts-layer store (`src/taskloop/stores/files.py:27`). `FileTickets.line` decides process survival, deletes tickets and sorts admission order (`:65`). `Stores` hands callers an entire bundle, including checkpoints and locks (`src/taskloop/stores/bundle.py:19`). | **Refuse-and-redo, P2 — L09; L04 for misplaced persistence.** Queue recovery policy is buried in a reader. Atomic file replacement is worth keeping as an implementation primitive, not as an ownership claim. |
| adapters | Should translate external protocols and perform I/O. `RealGit._ask`'s implementation erases failures (`src/taskloop/adapters/git_base.py:78`); `RealGit.commit_all` also chooses branch creation, staging scope and hook bypass (`src/taskloop/adapters/git.py:45`). Delegate's adapter synthesizes recovery-significant stop facts (`src/taskloop/adapters/delegate.py:204`). | **Refuse-and-redo, P1 — L01; P2 — L07.** Error normalization belongs here; choosing what failure means for admission must be explicit above it. `commit_all`'s convenience policy is included in L05's capability redesign, not counted as a separate incident. |
| cli | Cannot directly import domain/adapters (`.importlinter:76`), but may import lower stores/contracts. `src/taskloop/cli/land.py:19` implements receipt, lifecycle, cleanup and logging orchestration itself. `cli/wait.py:33` invokes effectful reconciliation through contracts. | **Refuse-and-redo, P2 — L06/L04.** A forbidden import does not make the verb a presentation adapter. |
| hook | Hot modules cannot import engine records or application code (`.importlinter:49`); this supports plain Python startup. Pre-push consequently owns another profile reader and delivery judge (`src/taskloop/hook/prepush.py:25`, `:63`) and explicitly allows hook failures (`:87`). | **Keep, P3, the lightweight startup constraint. Refuse-and-redo, P1 — L02, its independent policy authority.** Startup cost does not justify a second gate definition. |
| dash | Imports only contracts from taskloop (`.importlinter:94`); CLAUDE.md:88 says the server only reads. Its `Ports` docstring says read-only while supplying full `Beads`, answer, park and stop capabilities (`src/taskloop_dash/env.py:83`, `:89`, `:90`, `:94`). Launch constructs those callbacks from application code (`src/taskloop/app/launch/dash_ports.py:150`). | **Refuse-and-redo, P2 — L10.** Separate query and command authority. The known wrong-ask race remains A.F09, not a new finding here. |

**Keep:** `packages/kernel/src/tlkernel/plancheck.py:14` and `:25` express distinct check variants as values. `packages/kernel/src/tlkernel/config.py:169` expresses the served repository's engine schema, including its check registry at line 189. This is an appropriate contracts responsibility. **Refuse-and-redo:** the consumers do not establish a common effect/configuration boundary merely by sharing those types. A.F01/A.F05 and D.F01/D.F10 own the existing loader/revision defects; L02 concerns the independently authoritative hook.

## Ranked findings and concrete redo

### L01 — P1 — Refuse-and-redo: the Git adapter converts failure into permission

**Evidence:** `src/taskloop/adapters/git_base.py:84` runs the read; line 85 maps every nonzero result to `""`, and line 86 passes that value to memoization. `src/taskloop/adapters/git.py:39` turns that into `dirty=False`; line 51 turns it into an absent branch; line 66 obtains worktrees through the same helper. The port's reads section claims typed failures at `packages/kernel/src/tlkernel/ports.py:187`, while its slot-method preamble promises errors at line 142. The application at `src/taskloop/app/slots/reset.py:67` skips WIP preservation on a false dirty result, then reaches checkout and clean at lines 57–58.

**Failure:** a failed `git status` can masquerade as a clean checkout. If later commands succeed, nonconflicting untracked work can reach `clean` without the WIP commit that should have preserved it. Git's own protection against overwriting tracked files does not protect arbitrary untracked files from `git clean`. This is independent of A.F02/D.F04's concurrent cleanup races: the observation is false before any race is needed. Returning empty also makes operational failure indistinguishable from detached HEAD, missing ref, or no checkouts.

**Target interface:**

```python
dirty(checkout: CheckoutId) -> bool                 # raises GitReadFailure
branch(checkout: CheckoutId) -> Branch | Detached   # raises GitReadFailure
find_ref(checkout: CheckoutId, ref: str) -> Oid | MissingRef
checkouts(repo: RepoId) -> tuple[Checkout, ...]     # raises GitReadFailure
```

**Migration:** first make `_ask` preserve nonzero status and introduce explicit expected-absence handling per command; next migrate preservation/reset callers to refuse on unknown observations; finally change the fake/real contract suite to require identical failures and cache only successful observations. Each step can ship without changing normal successful behavior.

**Proof:** inject a nonzero status response followed by otherwise successful git operations into actual `ready_for`; assert no checkout, clean or setup occurs and existing untracked work remains. Add a real invalid-checkout case. `tests/ports/git_contract.py:102` checks successful cleaning and `:117` checks fetch failure; those assertions do not establish failed-status semantics. **Keep** those tests for their stated cases; **untested** is the proposed preservation guarantee.

### L02 — P1 — Refuse-and-redo: the lightweight hook is a second, fail-open delivery authority

**Evidence:** `src/taskloop/hook/prepush.py:25` independently extracts checks and base from working-tree JSON. Lines 31–32 turn read/shape failures into no gate. Its `judge` at line 63 owns stack coverage, and `entry` at lines 81 and 87 bypasses checks for an environment marker or hook exception. `src/taskloop/adapters/git.py:94` attaches that marker to the generic push method. The real hook test deliberately proves an ungreen, dirty push passes with the marker (`tests/hook/real/test_prepush.py:112`); its fake tl at line 20 stamps trees without executing the real check service.

**Failure:** the hook's exception policy authorizes a push when the gate service cannot be consulted. The typed application gate and this plain-JSON judge are different authorities. A.F01/D.F01 already explain malformed application profiles; this adds the hook's separate decision and the fact that a generic git adapter can assert engine authority without receiving gate evidence. This is a correctness boundary between cooperating tools, not a security claim against an owner who can use `--no-verify`.

**Target interface:**

```python
judge_push(repo: RepoId, tips: tuple[PushTip, ...]) -> PushDecision
PushDecision = Allowed | Refused | Unavailable
hook_entry(stdin: str) -> int                      # serialize, invoke tl, map result
push_checked(receipt: GateReceipt, target: PushTarget) -> PushResult
```

**Migration:** first add one application command that evaluates the entire push request; next make the stdlib hook pass stdin to it and refuse `Unavailable`; finally replace generic marker injection with the checked delivery operation and document any intentional owner override separately. Preserve the hook's lightweight import rule throughout.

**Proof:** run the installed hook against the real application judge with a valid profile, then make the judge unavailable and the profile undecodable; both must refuse before remote mutation. Test that ordinary Git transport cannot mint checked-delivery authority. **Keep** the existing real-hook tests for hooks-path and stdin plumbing. **Refuse** their use as proof that application gate policy is shared.

### L03 — P1 — Refuse-and-redo: delegate persistence decides that unreadable authoritative state is empty

**Evidence:** `_delegate/src/delegate/contracts/stores.py:59` returns `None` for both read and JSON errors. `StateStore.load` at lines 84–89 substitutes `StateDoc()` for decoding failure. `transaction` at lines 93–96 then writes that substitute back. `_delegate/src/delegate/contracts/state.py:97` stores lane exclusions, leases, resume references and owner holds together. `app/decide.py:128` loads that state before routing, and line 136 builds `HoldBook` from it.

**Failure:** a malformed, unreadable or incompatible state file is converted into permission to route without the stored holds/leases. A later ordinary update can replace the original record with defaults. These are authoritative reservations and owner decisions, not disposable usage caches. The lock serializes the wrong decision perfectly. The previous reviews did not inspect delegate implementation, so this is new sibling evidence, not a claim that A.F04 already established it.

**Target interface:**

```python
read_state() -> Present[StateDoc] | Absent | Unreadable | Incompatible
admit_route(state: Present[StateDoc], request: CallArgs) -> Decision
update_state(expected: Revision, change: StateChange) -> Revision
```

**Migration:** first expose distinct read outcomes in a persistence adapter and preserve the file on error; next refuse routing/admission on unreadable or incompatible authority while permitting genuinely absent first-run state; finally separate regenerable usage caches from holds/leases/references. No legacy-format migration is required to refuse safely, so this does not depend on overriding the sibling constitution's no-migration rule (`_delegate/docs/dev/constitution.md:8`).

**Proof:** put a live lease and owner hold in state, damage the JSON or supply a foreign version, then attempt routing and an unrelated update. Require zero worker launches and unchanged original bytes. **Untested:** the supplied sibling copy's runtime and regression coverage.

### L04 — P2 — Refuse-and-redo: effects cross the supposedly pure foundation through permitted names

**Evidence beyond A.F12:** `src/taskloop/domain/checks/lint.py:100` calls `recipes`; `src/taskloop/adapters/check_probe.py:40` implements that call with a process and a 20-second timeout. Thus even the domain module explicitly described as pure can execute an external command during a decision. `src/taskloop/domain/interpret.py:43` executes effects; its `CheckpointLedger.mark` at line 68 decides to suppress lost fencing authority. `packages/kernel/src/tlkernel/runlife.py:64` is an application reconciler. `packages/kernel/src/tlkernel/locks.py:13` is a process probe. These are different responsibilities hidden behind legal imports, not merely an unfortunate location for JSON helpers.

**Failure:** the layer graph cannot tell a value-only evaluator from a process runner or transaction participant. A caller has to know which innocently named contract helper writes and which protocol callback blocks. Tests must fake the probe/ledger to isolate “pure” evaluation, thereby removing the real timeout, file failures and fencing behavior they would need to prove. A.F12's P3 label is too soft for this combined dependency on execution and ownership policy. A.F03/A.F04 and D.F07 remain the concrete state failures; they are not repeated here.

**Target interface:**

```python
observe_tree(checkout: CheckoutId) -> TreeFacts       # app + adapters
lint_plan(plan: Plan, facts: TreeFacts) -> Problems   # domain, values only
next_effects(state: RunState, event: Event) -> Transition
commit_transition(owner: AttemptToken, change: Transition) -> Receipt
```

**Migration:** move probe acquisition to app and feed immutable facts to lint; move reconciliation and effect interpretation to app, persistence implementations to stores, process probes to adapters; then shrink contracts to records/protocols and enforce a transitive effect prohibition for domain/contracts. Move existing APIs and callers together in small releases; do not add permanent compatibility facades that keep the escape route alive. Include sibling `contracts/stops.py:10` and `:14`, which reads an installation file at import, in the same separation: compiled reason data or startup-loaded validated values belong below decisions, not import-time filesystem access.

**Proof:** domain decision fixtures run with file/process/clock services unavailable and use values, not mocked I/O callbacks. Add dependency tests that plant a domain import of effectful persistence and a contract import of a process helper and require rejection. A real probe test separately proves `just` failure remains an explicit observation failure. **Keep** `JsonStore.read`'s distinct outcomes (`packages/kernel/src/tlkernel/stores.py:90`) as semantics to preserve when moving it; **refuse** treating its package location as purity.

### L05 — P3 — Refuse-and-redo: the check writer rule checks vocabulary while handing out the writer

**Evidence:** `src/taskloop/app/checks/host.py:46` defines `CheckoutView`; line 53 defines `TreeWriter` and claims only Fixer can stage. The same `CheckHost` exposes `tree_writer` at line 107 and full mutable `Git` at line 110 to all consumers. `Git.stage` exists at `packages/kernel/src/tlkernel/ports.py:360`; shell execution is also exposed at `app/checks/host.py:98`. The rule at `tests/rules/test_tree_writer.py:20` recognizes just `stage_all` and `tree_writer`, and the test at line 37 examines the Protocol class rather than the supplied object's complete authorities.

**Failure:** a new check component can call `host.git.stage(...)` and pass that rule. The forbidden capability is present under another spelling. This is demonstrable architecture theatre even without claiming a current executor stages that way. Arbitrary configured check commands can also mutate the tree/index; their effects require observation, not a promise in a Protocol docstring. This is separate from D.F02's gate token identity bug.

**Target interface:**

```python
CheckReadContext = CheckoutView + CheckEvidence + CheckRunner
FixContext = CheckReadContext + IndexWriter
run_checks(ctx: CheckReadContext, plan: CheckPlan) -> ObservedResults
apply_fixes(ctx: FixContext, fixes: FixPlan) -> MutationReceipt
```

**Migration:** split the host values and stop supplying raw Git, global Stores and index writer to check readers; route fixes through the explicit mutation service; then replace the name-only test with capability/type checks and post-execution tree/index observation. Narrow adapter conveniences such as `commit_all` into explicit preservation operations instead of exposing them through every Git consumer. Keep unavoidable check-produced build outputs explicit; do not pretend a Python type sandboxes a build tool.

**Proof:** an adversarial reader attempting either `tree_writer.stage_all` or `git.stage` must fail type/interface validation. A real configured command that unexpectedly stages files must produce a mutation refusal rather than accepted read-only evidence. **Keep** existing Fixer tests for fixes; **refuse** the current rule's claim to exclusive mutation authority.

### L06 — P2 — Refuse-and-redo: CLI land implements its own application transaction

**Evidence:** `src/taskloop/cli/land.py:28` records tracker delivery, line 31 writes a landed receipt, lines 34–36 create manifest/log state, line 42 performs cleanup, and line 44 ends the manifest. There is no enclosing finalization path after creation. It constructs real stores at line 35 despite already receiving typed tracker/git dependencies. `tests/cli/test_land_cleanup.py:50` replaces `record_land`, and line 51 replaces `cleanup.retry`.

**Failure:** an exception during cleanup after manifest creation leaves the standalone command without its terminal lifecycle write. The CLI test removes both stateful application operations, so its success does not prove their ordering, failure settlement or agreement with the engine path. A.F12 identified host wrappers; it did not fix ownership by putting an entire alternative service in a CLI module. A.F02/D.F04 own cleanup safety itself; this finding owns where the use case and its exception lifecycle live.

**Target interface:**

```python
record_direct_delivery(request: DirectDelivery, services: DeliveryServices) -> DeliveryResult
DeliveryResult = Recorded | RecordedCleanupPending | Refused
cmd_land(args: LandArgs, service: DirectDeliveryService) -> int
```

**Migration:** extract the existing direct-delivery sequence unchanged into app; add explicit cleanup-pending/failure finalization and inject stores/clock; make CLI only parse, invoke and print. Share receipt/lifecycle primitives with engine and stack delivery while preserving their different delivery modes. Do not force manual direct land through model planning.

**Proof:** inject an exception immediately after manifest creation and a failed cleanup after a valid receipt; assert the receipt survives, the manifest is terminal, and cleanup remains an explicit obligation. Exercise the CLI through the real application service with fake external ports, rather than patching the use case away. **Keep** existing argument/receipt assertions for their narrow scope.

### L07 — P2 — Refuse-and-redo: the tested Delegate port is not the worker's boundary

**Evidence:** production dispatch calls `dg.call` at `src/taskloop/app/run/worker_call.py:252`; reflection does so at `src/taskloop/app/run/reflect.py:47`. The shared fake/real port tests instead construct `RouteDelegate` (`tests/ports/test_delegate.py:83`), and normally replace its process function at line 76. The two implementations differ materially: `adapters/delegate_route.py:64` uses the instance deadline, whereas `adapters/delegate.py:195` uses the request deadline; missing answers become `crash/needs_owner` in the former (`:72`) and `no_answer` with synthesized facts in the latter (`:212`). `tests/ports/test_delegate.py:130` enshrines the former behavior.

The declared run/status-only boundary is also unenforced: CLAUDE.md:103 says that explicitly, while `src/taskloop/adapters/delegate_route.py:49` calls `contract` and `src/taskloop/adapters/delegate.py:164` calls `net`. The latter is live application wiring (`src/taskloop/app/launch/loop.py:96`). `tests/stores/test_call_state.py:143` explicitly expects that extra command. Ruff's import ban cannot see subprocess verbs.

**Failure:** a contract suite can pass while production uses different deadlines and different recovery-significant failure facts. Additional control verbs can change independently of the advertised integration surface. This is not A.F08's missing feature negotiation; it is two implementations and a test aimed at the wrong one.

**Target interface:**

```python
run(request: RunRequest, brief: str, schema: Schema, sink: EventSink) -> CallEnvelope
status() -> DelegateStatus                         # compatibility/availability facts
CallEnvelope = Answer | TransportFailure           # retain raw diagnostics
```

**Migration:** first run the shared contract suite against the implementation used by WorkerCall; next unify temp-file, deadline, event and failure handling behind one adapter and migrate reflection; delete the spare executor. Remove `contract`/`net` calls from the integration: obtain declared facts through status, or use a task-loop-owned network probe without expanding delegate's API by accident. Fail explicitly when the supported status cannot provide a required fact.

**Proof:** drive WorkerCall and the shared adapter suite through the same stub with short per-request deadlines, malformed output and process failure; assert identical facts and retained stderr. Add an argv recorder that rejects delegate verbs other than `run` and `status`. **Keep** the real-pipe tests at `tests/ports/test_delegate.py:103` for transport mechanics; **refuse** treating a real pipe to the other adapter as production contract coverage.

### L08 — P3 — Refuse-and-redo: delegate's harness adapter decides operational policy, then app decides it again

**Evidence:** `_delegate/src/delegate/adapters/harness/base.py:3` limits harnesses to launch/output facts and disclaims knowledge of lanes/state/router. Yet `adapters/harness/classify.py:29` selects a contract reason: lines 40–46 prioritize watchdog/timeout facts; lines 50–65 decide login, request, quota and network categories. `_delegate/src/delegate/app/settle.py:64` can replace that decision with `network`, then line 77 installs the replacement as the outcome. `_delegate/src/delegate/contracts/stops.py:28` further decides permanence and retry semantics; a supplied retry time changes permanence at lines 33–36.

**Failure:** outcome precedence, network reclassification, and retry/permanence policy are spread across adapter, application and contracts. A harness parser fixture can establish that a vendor emitted a limit, yet cannot prove which final reason/wake contract the consumer receives. Incident 4, where a generic limit hid an engine-only failure, is the standard this split must meet; this review does not assert that exact incident was reproduced. The current pure Router (`_delegate/src/delegate/domain/routing/router.py:1`) is **keep**: its explicit inputs and returned decisions show the boundary the outcome path should also have.

**Target interface:**

```python
parse_vendor(stream: VendorStream) -> VendorEvidence
decide_stop(evidence: VendorEvidence, network: NetworkFact, limits: Limits) -> StopDecision
apply_stop(decision: StopDecision, state: StateRevision) -> SettlementReceipt
```

**Migration:** retain harness parsing/regex extraction in adapters but return typed facts; move precedence and stop/wake decisions into one domain evaluator using an explicit reason table; make app collect network observations and apply the returned changes without reclassifying. Remove contract import-time file reads as specified in L04.

**Proof:** one end-to-end decision fixture containing competing timeout, engine-only incompatibility and vendor-limit facts must assert original evidence, chosen cause, scope and wake. A separate post-answer network fixture must prove the completed answer is retained. **Untested:** sibling test implementation, which was not supplied as a test suite in the inspected copy. No claim that moving a function alone repairs diagnostic loss.

### L09 — P2 — Refuse-and-redo: the ticket store is an admission policy engine with a broken identity test

**Evidence:** `packages/kernel/src/tlkernel/locks.py:51` stores `pid_start`, but `Ticket.alive` at line 54 checks only numeric PID. `src/taskloop/stores/files.py:79` uses that method to retain or delete tickets and line 83 orders them. `src/taskloop/app/slots/line.py:32` does not supply the optional start identity when taking a ticket. Lines 36–38 refuse to take a slot while an earlier ticket remains.

**Failure:** after a waiter dies and its PID is reused, its ticket can remain ahead of real waiters for the unrelated process's lifetime, leaving free slots unused. Conversely, reading the queue performs deletions under persistence's interpretation of liveness. A.F11 describes run-manifest identity; this is a separate admission object, distinct caller and starvation consequence. Incident 2's failed PID assumption should have triggered a project-wide identity boundary, not a local engine-lock exception.

**Target interface:**

```python
read_tickets(repo: RepoId) -> tuple[Ticket, ...]       # no deletion
observe_processes(ids: tuple[ProcessIdentity, ...]) -> ProcessFacts
reconcile_line(tickets: tuple[Ticket, ...], facts: ProcessFacts) -> QueueDecision
apply_ticket_removals(decision: QueueDecision) -> None
```

**Migration:** populate and check process birth identity at creation; move liveness/reap/order policy into the slot application/domain path and keep the store responsible for bytes; handle unknown identity as an explicit bounded recovery condition. Keep link-based exclusive ticket publication (`src/taskloop/stores/files.py:56`) as the storage primitive.

**Proof:** simulate the same PID with a different birth identity and verify the dead predecessor stops blocking the next waiter. Verify reading stored tickets alone deletes nothing, and an unavailable process probe cannot silently remove a live waiter. **Untested:** those admission/reuse cases; no runtime queue was observed.

### L10 — P2 — Refuse-and-redo: dashboard import isolation is being sold as command isolation

**Evidence:** `src/taskloop_dash/env.py:83` calls its Ports read-only, but line 89 supplies all of `Beads`; lines 90–99 supply owner mutations. `src/taskloop/app/launch/dash_ports.py:150` wires these application writers into the process. `src/taskloop_dash/api/writes.py:57` dispatches POST actions. `.importlinter:94` prohibits package imports, not callback effects. `tests/rules/test_runstate_rule.py:79` bans selected writer names, while `tests/rules/test_dash_state_paths.py:51` regulates path spelling. Neither makes `Ports.store` read-only.

**Failure:** a GET builder has access to the same mutation authority as an owner command handler. It can update/close through its permitted tracker object without importing a forbidden package or naming a run-state writer. That is a capability defect, not an assertion that an inspected GET currently does so. A.F09 owns wrong-ask identity; the additional repair is to prevent projections from acquiring any command authority in the first place. CLAUDE.md:88's blanket read-only statement is false for the served process.

**Target interface:**

```python
DashQueries = BeadReader + RunReader + AskReader + ProfileReader
OwnerCommands.submit(command: OwnerCommand) -> CommandReceipt
build_snapshot(queries: DashQueries) -> Snapshot
handle_post(commands: OwnerCommands, request: WriteRequest) -> Result
```

**Migration:** split dashboard dependency construction into query and command objects; pass only queries to readers/views and only typed commands to POST handlers; remove raw Beads and writable storage from query dependencies. Update documentation to distinguish read projections from owner command submission, and preserve expected object revisions through commands as already demanded by A.F09.

**Proof:** build every GET projection using objects that implement only read methods; assert no command callback executes. Command tests must inspect a typed application receipt, not a mutated fake view. Add a type/structural rule that rejects importing command interfaces into readers/views. **Keep** path-placement and registered-verb tests for their actual narrow jobs; **refuse** using them as write-isolation evidence.

## Enforcement audit: what survives a green gate

| Mechanism inspected | Judgment | What it actually establishes, and the violation it permits |
| --- | --- | --- |
| `.importlinter:16`, `:76`, `:87`, `:116` | **Keep, P3**, dependency direction and slice ordering. **Refuse** purity/authority interpretations, L04/L05. | Static imports cannot identify an effectful callback, a writable object hidden behind a Protocol, or policy implemented in a lower package. The existing contract implementations are the counterexample, not a speculative syntax trick. |
| `.importlinter:39`; contracts/stores Ruff configs | **Keep, P3**, selected direct-import bans. **Refuse** the claim that these cover effects, L04. | Filesystem I/O remains legal; `contracts/locks.py:5` imports `stream_proc`. The contracts Ruff file bans `subprocess`, `socket`, `threading`, with an explicit threading type exception at `contracts/ports.py:5`. This is not a transitive process-services prohibition. |
| `.importlinter:49` hot-hook constraint | **Keep, P3**, startup dependency control. **Refuse** duplicate gate policy, L02. | A lean process can still decide the wrong policy. The correct response is a thin RPC/CLI client to one judge. |
| Ruff PLC0415/TID251/D100 configuration (`ruff.toml:10`) and CLAUDE.md:83 | **Keep, P3**, eager imports, selected banned APIs and module documentation. | A docstring can claim pure/read-only while the object performs I/O or supplies writers. The rules enforce the presence of prose, not its truth. |
| `tests/rules/gate_rules.py:46`, `:58`, `:164` | **Keep, P3**, size ratchets and global-placement checks within their scan. **Untested**, execution. | Splitting a host into smaller files can satisfy SLOC without allocating authority. The scan roots exclude the sibling `_delegate` tree; passing the parent gate says nothing about sibling enforcement. |
| `tests/rules/test_state_writers.py:21` | **Keep, P3**, narrow hand-write regression tripwire. **Refuse** “one writer” as a concurrency guarantee. | It recognizes `os.replace` and JSON-naming `write_text` under app. Any number of app actors can call the allowed JsonStore writer; no owner/generation or multi-record transaction is established. A.F03 and D.F07 explain consequences; L04 explains the boundary repair. |
| `tests/rules/test_tree_writer.py:20` | **Refuse-and-redo, P3**, L05. | It passes while the full Git writer is present under `host.git`. |
| `tests/rules/test_env_below_edge.py:28`, `:54`, `:69` | **Keep, P3**, recognized ambient reads, constructor sites and handover spelling. **Untested**, execution. | These regex/AST restrictions do not establish that an adapter and a second adapter share timeout semantics or that callbacks have narrow authority. L07 remains possible. |
| `tests/rules/test_git_ratchet.py:28` | **Keep, P3**, recognized git-call spelling outside approved transport modules. | L01's bad failure semantics reside inside an approved module and pass by construction. Counting call sites does not check what an empty result means. |
| Dashboard state-path/writer-name/verb tests (`tests/rules/test_dash_state_paths.py:51`, `test_runstate_rule.py:84`, `test_dashboard_verbs.py:20`) | **Keep, P3**, path centralization, selected lifecycle writer names and real command names. **Refuse** capability claims, L10. | A view can receive full Beads through a permitted import. Names and paths do not distinguish query access from commands. |

The inspected `pyproject.toml` selects logic tests by default and lists pytest/xdist as dev tools. **Keep** that test-kind separation; **untested** is any claim that this checkout currently passes it. `tests/rules/test_no_os_services.py:9` is **keep** for its explicit service-installation vocabulary ban, but is irrelevant to process identity or delivery correctness. The earlier review documents are **keep** as referenced defect records; A.F12's severity and broad purity framing are **refused** as explained above. Unopened files found by inventory search, runtime installations, the sibling's original CI configuration, and a real served repository such as lifesim are **untested**, not silently approved.

## Sibling delegate layering verdict

| Boundary | Judgment and evidence |
| --- | --- |
| domain routing/holds/health | **Keep** the supplied value-oriented shape: Router takes routing, holds, previous dwell and time (`_delegate/src/delegate/domain/routing/router.py:24`); HealthLedger folds typed history (`domain/health/ledger.py:90`); worker policy returns a Verdict (`domain/policy/worker.py:25`). **Untested** are runtime correctness and sibling structural enforcement. Do not infer a tested guarantee from those signatures. |
| adapters/harness | **Keep** vendor parsing and launch construction as adapter jobs (`adapters/harness/base.py:3`). **Refuse-and-redo, P3 — L08**, the operational outcome ladder located there. |
| app | **Keep** composition of fleet, routing and launch in `app/decide.py:125`. **Refuse-and-redo, P3 — L08**, settlement reclassification; **P1 — L03**, accepting defaulted authority from the state reader. `Settler.mark_out` uses direct `time.time()` despite accepting a clock (`app/settle.py:54`, `:62`): include write time in the explicit settlement input when migrating L08, rather than leaving a second clock authority. |
| contracts/persistence | **Refuse-and-redo, P1 — L03**, authoritative read failure becomes empty writable state. **Refuse-and-redo, P2 — L04**, concrete locks/storage and import-time contract loading share the record layer (`contracts/stores.py:26`, `:59`; `contracts/stops.py:14`). |
| CLI and enforcement | **Untested.** The supplied copy exposes CLI modules but does not supply an inspected runnable sibling test/gate configuration. The parent's import-linter roots name taskloop and taskloop_dash, not delegate (`.importlinter:5`). Do not advertise a shared architectural gate. |

This is a cooperating protocol boundary. Do not repair it by importing `_delegate/src` into task-loop. The parent import ban on `delegate` is **keep**; L07 requires one external adapter whose tests exercise the production caller.

## Incident standard

| Historical failure | Required verdict against the inspected layering |
| --- | --- |
| LANDBRANCH deleted a slot worktree | **Refuse** package-level safety claims. A.F02/D.F04 cover ownership; L01 adds trustworthy observations and L05 explicit mutation authority. A folder called adapters cannot authorize disposal. |
| uv exec changed process identity and 13 beads burned | **Refuse** local PID patches as a general identity model. A.F06/A.F11 own loop/run cases; L09 shows tickets still omit birth identity. |
| Newer repository profile crashed an old engine | **Refuse** independent readers as compatibility boundaries. A.F05/D.F10 own immutable admission; L02 removes the hook's additional policy interpreter. |
| Generic limit hid engine-only unenforced | **Refuse** outcome ladders spread across layers. L07/L08 require original transport/vendor facts and a single stop decision. No claim of reproducing the historical trigger. |
| Follow-ups ignored lint and first-line parsing dropped them | **Keep** current full-output lint extraction at `src/taskloop/adapters/bd.py:113` as an adapter responsibility. **Refuse** calling that delivery proof: A.F10/D.F08/D.F09 own durable filing. L07's production adapter test requirement applies equally to this boundary. |
| Umbrella/no-op plan closed done | **Untested** in this review. D's H5 already distinguishes current NOOP handling from the historical implementation. Do not manufacture a second finding from old behavior. |
| Paused beads lacked wakes | **Refuse** distributed stop/wake ownership. A.F07/D.F11 own the state defects; L08 establishes where the producer's decision must live. |
| Infrastructure reserved slots for 12 hours | **Refuse** duration as cause. D's pause analysis owns the current aside path; L01/L07/L08 require unambiguous observations before selecting slot versus machine recovery. |
| Plugin update broke active work | **Refuse** “same layer/contract number” as installed-pair compatibility. A.F04/A.F08/D.F03 own runtime pinning/state; L03 adds delegate's destructive incompatible-state fallback. |
| Main fast-forward changed active config | **Refuse** reading the current file as admitted policy. A.F05/D.F10 remain the run fix; L02 prevents the hook from inventing its own configuration authority. |

## Top 10

Ranked by loss of work/authority, then unattended availability and misleading enforcement. These are static findings, not reproduced incidents.

| Rank | Priority | Finding | Decision |
| --- | --- | --- | --- |
| 1 | P1 | L01 — failed git reads masquerade as clean/missing state | Refuse-and-redo |
| 2 | P1 | L03 — delegate overwrites unreadable authority with defaults | Refuse-and-redo |
| 3 | P1 | L02 — hook failure authorizes delivery under separate policy | Refuse-and-redo |
| 4 | P2 | L07 — production delegate execution differs from the tested port | Refuse-and-redo |
| 5 | P2 | L09 — PID-only ticket retention can block all later admission | Refuse-and-redo |
| 6 | P2 | L04 — permitted foundation imports and callbacks execute effects | Refuse-and-redo |
| 7 | P2 | L06 — CLI owns a separate delivery/lifecycle sequence | Refuse-and-redo |
| 8 | P2 | L10 — dashboard queries receive command authority | Refuse-and-redo |
| 9 | P3 | L05 — exclusive check writer rule passes with another writer present | Refuse-and-redo |
| 10 | P3 | L08 — sibling adapter/app/contracts split outcome policy | Refuse-and-redo |

## Beads to file

Proposed titles and scope only; no tracker commands were run under this review's read-only command constraints.

- **P1: Preserve Git read failures before slot mutation** — Implement L01's explicit absence/error distinction and prove failed status cannot reach checkout/clean.
- **P1: Refuse unreadable delegate routing authority** — Implement L03 without overwriting holds, leases or resume records on decode/read failure.
- **P1: Make pre-push a thin client of one delivery judge** — Implement L02 and refuse unavailable judgment; remove generic checked-push marker authority.
- **P2: Put production delegate execution under the shared port suite** — Implement L07, remove the spare executor and enforce run/status-only calls.
- **P2: Give slot tickets process birth identity and explicit reconciliation** — Implement L09 and prove a reused PID cannot block later waiters.
- **P2: Remove execution and persistence implementations from the pure foundation** — Implement L04's fact acquisition/decision/commit split and transitive boundary checks.
- **P2: Move standalone delivery orchestration out of CLI** — Implement L06 with terminal lifecycle records and explicit cleanup-pending results.
- **P2: Separate dashboard query dependencies from owner commands** — Implement L10 and reject command interfaces in readers/views.
- **P3: Replace the check writer name scan with actual capability boundaries** — Implement L05 and detect unexpected index/tree mutation from check execution.
- **P3: Give delegate one pure stop and wake decision** — Implement L08 using typed vendor/network facts, original diagnostics and explicit settlement time.
