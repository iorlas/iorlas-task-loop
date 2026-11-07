# Architecture review

Static review of the repository on 2026-11-01. Evidence below is from repository files, with line numbers re-read before writing. No runtime commands, tests, git operations, external repository reads, or network access were used. Delegate implementation behavior is not assumed: findings at that boundary concern what task-loop requests and verifies. P1 means potential work/state corruption or bypass of required checks; P2 means incorrect recovery, repeated expenditure, or misapplied operator intent; P3 means a structural defect that weakens enforcement.

## State ownership

“One writer” must mean one authority that serializes a transition against its current generation. One Python class that replaces a JSON file is not that authority. The following table distinguishes the physical writer from the actors allowed to invoke it; the gaps are detailed in the numbered findings.

| State | Writer(s) | Readers | Required invariant | Enforced where / gap |
|---|---|---|---|---|
| Bead | `BdStore`, called by engine close, loop claim/reopen/refusal, Intake, reconciliation, standalone CLI verbs and dashboard ports | queue, entry, engine, dashboard, reports | Only the current claimant may finish or release work; owner commands target the object actually reviewed | `contracts/ports.py:106`, `app/run/entry.py:387`, `app/run/closer_settle.py:53`, `app/loop/run.py:96`; fencing is advisory and close is two commands (F03) |
| Run | `RunLocator`: engine/stage lifecycle and reconciler; standalone land also creates and ends runs | engine resume, dashboard, reports, owner-request gate | One active attempt; liveness identifies that execution rather than another process | `contracts/locator.py:139`, `:159`, `:165`, `:173`; liveness uses PID alone (F11) |
| Attempt | `RunLocator.take_up` increments `RunManifest.attempts`; Engine chooses reuse after exec/network pause/unfinished close | logs, engine recovery, dashboard headers | An attempt identifies one execution and fences its predecessor | `contracts/locator.py:139`, `contracts/run.py:194`, `app/run/engine.py:149`; count is not an ownership token (F03, F11) |
| Slot | slot bead claim and held metadata via `Slot`/marks; loop/engine release; hold/expiry/reconciler paths | loop, run admission, cleanup, dashboard | Claim, generation, engine lock and physical directory describe the same owner until mutation ends | `app/slots/pool.py:47`, `:74`, `:175`; reset/probe does not acquire ownership for its entire mutation (F02) |
| Worktree | `owned.create`, slot reset, engine checkout/land, cleanup, standalone land-stack, worktree/prune verbs | engine, slots, cleanup/reconciler, dashboard via records | Creation, adoption, reset and removal require the current ownership capability; persistent slots cannot be removed as disposable task trees | `app/slots/owned.py:33`, `:99`, `app/slots/reset.py:39`, `app/land/cleanup.py:34`; branch/OID checks and slot classification do not serialize directory lifecycle (F02) |
| Lock | OS locking adapter; loop and run-task both replace `engine.lock`; engine updates child identities and removes it | admission, slots, running/recovery, cleanup | Exclusive ownership includes process birth identity and authenticated handoff; release cannot erase a successor's lock | `app/slots/engine_lock.py:63`, `:76`, `:115`, `:132`; separate loop/run identity and PID-based state addressing survive outside this guard (F06, F11) |
| Lease | bd heartbeat, driven by both loop and run-task `Lease` threads; sweeper releases expired claims | bd, reconciler, slot pool | Renewal and release apply only to the generation originally acquired | `app/slots/lease.py:18`, `:35`, `app/reconcile/leases.py:11`; heartbeat receives bead ID, not a generation; fencing is a separate read (F03) |
| Claim | bd atomic claim plus a separate `fence.take` metadata update; manual close/block use `fence.hand` | close, block, checkpoint, land | Claim and generation acquisition are one transition; every side effect atomically checks that generation | `contracts/fence.py:71`, `:81`, `:87`, `app/run/entry.py:387`; no conditional generation field in `BeadPatch` (`contracts/ports.py:72`), and unreadable ownership permits action (F03) |
| Checkpoint | `Checkpoints` writes through `Stores.checkpoints`; all engine parts can mutate aliased in-memory `RunState` | entry preview, Engine construction, resume, close recovery | Durable cursor and effect receipts are never confused with absence; only the current attempt may replace them | `app/run/state.py:38`, `:96`, `:113`, `:118`; uses lossy `get`, with no version negotiation before exec (F04, F12) |
| Profile | Person/repo changes `.task-loop.json`; task-loop chooses local/base source and reconstructs typed config | loop, entry, slot wiring, dashboard profile readers, checks/land | One admitted run uses one explicit profile revision and schema; unreadable config cannot disable requirements | `app/wire/slots.py:42`, `:65`, `:78`, `app/run/entry.py:195`; malformed input becomes defaults and different consumers select different revisions (F01, F05) |
| Park | engine close invokes `parks.paused`/`ended`; entering on an answer drops it | queue, entry, loop settle/candidate scheduling | Every pause has a durable reason and explicit owner/clock wake; no consumer substitutes its own policy | `app/asks/parks.py:23`, `:39`, `:45`, `:60`; owner-required delegate pauses are excluded from persistence (F07) |
| Ask | `AskStore` under per-bead lock, called by raiser, Intake, sweeps and engine close; dashboard reaches Intake through ports | engine, queue/park gate, CLI, dashboard, ledger | Answer, amend and consumption compare the exact ask ID shown to the owner | `contracts/stores.py:406`, `:417`, `:451`, `app/asks/intake.py:95`; dashboard loses the ID before the locked answer (F09) |

Paths in this table are under `src/taskloop/` unless explicitly qualified. These are several writer actors, not one engine writer. The design needs a transition authority for each shared object, including owner and maintenance operations, rather than treating CLI verbs as exceptions to lifecycle ownership.

## Findings

### F01 — P1: malformed profiles silently remove configured gates

**Evidence:** `src/taskloop/app/wire/slots.py:42` resolves the profile commit, but lines 47–49 return `{}` on both malformed JSON and `SlotGitError`. Lines 50–53 do the same for a malformed or unreadable local file. `packages/kernel/src/tlkernel/config.py:164` defaults delivery to `git push origin HEAD:main`, while line 181 defaults checks to an empty list. `cfg_source` at `app/wire/slots.py:65` decodes those defaults as a usable profile.

**Failure:** A committed syntax error or failed profile read is indistinguishable from deliberately having no checks. The engine can lose the repository's required checks, preparation, selection rules and custom delivery command while retaining a default push command. This occurs before the schema-error handling that recognizes a newer profile, so that handling cannot contain it.

**Fix:** Represent absent, unreadable, malformed and incompatible profiles separately; only a deliberately absent profile may select defaults. Refuse admission before any claim when the selected profile cannot be read or decoded, recording its exact commit and error.

**Past incident prevented:** none; this is a separate fail-open path adjacent to incident 3.

### F02 — P1: slot recovery mutates a directory after giving ownership away

**Evidence:** `src/taskloop/app/loop/loop.py:331` stops the lease, drops the engine lock and releases the slot before calling `self.settle.apply` at line 339. `src/taskloop/app/loop/settle.py:67` then calls `SlotPool(...).named(name).ready_for("")` as a diagnostic probe. `src/taskloop/app/slots/reset.py:39` only samples busy/hold state at lines 41–47, then preserves/commits work, fetches, checks out, cleans and runs setup at lines 51–59. `src/taskloop/app/slots/pool.py:70` forwards directly to that function without taking a slot or directory lock.

**Failure:** After the old loop sees “not busy,” a second loop can claim the released slot and begin reset/startup while the first loop continues its “probe.” The first loop can commit the second loop's files, detach its task branch, clean its directory or run setup concurrently. A probe that performs the full recovery transition defeats the ownership guards it is meant to diagnose.

**Fix:** Finish recovery and classification while the original slot lease and exclusive directory capability are held, or reacquire both before probing. Make the health probe read-only and require all reset/cleanup entry points to hold the same directory lock throughout mutation.

**Past incident prevented:** none exactly; this addresses the remaining ownership class behind incidents 1 and 8, not their already-described triggers.

### F03 — P1: the fence permits unknown owners and does not fence the final mutation

**Evidence:** `packages/kernel/src/tlkernel/fence.py:15` converts `BdFailure` to `None`; `stale` at lines 87–98 treats unreadable or absent bead/slot state as permission. `take` at lines 74–75 increments generation by separate read/update. `src/taskloop/app/run/state.py:113` checks ownership before returning a document that is written later. `src/taskloop/adapters/bd.py:249` implements guarded close as a conditional same-value update at line 254 followed by an unconditional close at line 255; labels use the same pattern at lines 260–263.

**Failure:** A stale engine can replace local checkpoint state during a bd outage because inability to establish ownership is accepted. Independently, a release/retake between the guarded update and `bd close` lets the old engine close the new owner's bead; generation changes by the same actor are not checked by the bd mutation at all. A preliminary read or same-value update is not a fencing token on a subsequent effect.

**Fix:** Fail closed on unknown ownership and acquire/bump generations through a conditional transition. Require the final bead mutation to compare actor and generation atomically; where bd cannot supply that primitive, keep a shared transition lock across the guard and operation and forbid uncoordinated retakes, including local checkpoint replacement.

**Past incident prevented:** none; the supplied incidents do not describe a stale-owner close race.

### F04 — P1: automatic exec and rollback can discard the checkpoint they promise to resume

**Evidence:** `src/taskloop/app/run/reload.py:68` selects an installed version and calls `switch` without probing its checkpoint reader. The handover at lines 90–97 records counters and version names, not a negotiated schema range. `src/taskloop/app/loop/run.py:79` falls back to the old install after an early crash. Both `read_checkpoint` and `Checkpoints.read` use `.get()` (`src/taskloop/app/run/state.py:38`, `:118`); `JsonStore.get` collapses torn/foreign records to `None` at `packages/kernel/src/tlkernel/stores.py:104`. Record readers reject unknown fields (`packages/kernel/src/tlkernel/wire.py:38`) as well as foreign `v` (`:88`); `Checkpoint` is v3 (`contracts/checkpoint.py:160`). `Resume.point` treats an absent checkpoint as fresh planning (`app/run/resume.py:48`–55).

**Failure:** A hop to a version unable to read the current checkpoint can plan afresh. Conversely, a new version can write a changed checkpoint and then crash inside the fallback window; the old version can read that checkpoint as absent and lose accepted-stage progress, unfinished-close intent and applied-effect receipts. Even adding a defaulted field is not backward compatible with an older reader that rejects unknown keys. The cutover procedure in `docs/cutover.md` is not checked by this automatic path.

**Fix:** Probe the candidate with the actual checkpoint, profile and handover before releasing control, and permit a move only with explicit supported reader/writer ranges. Use strict checkpoint reads and retain an immutable pre-hop checkpoint plus a reversible migration boundary; otherwise pin the active run and update only after it ends.

**Past incident prevented:** 9; schema admission also prevents the version/profile mismatch class in 3.

### F05 — P2: engine, slot and resumed-run configuration have different revision owners

**Evidence:** `src/taskloop/app/wire/slots.py:65` first decodes the entire local profile to obtain `engine.base`, then reads the committed profile. `profile_slots` at lines 78–83 reads local checkout contents instead. `src/taskloop/app/run/entry.py:195` loads engine config, but later slot discovery/take paths re-read slot config (`:268`, `:291`, `:324`). A hop re-enters that same config load. Resume's world at `src/taskloop/app/run/resume.py:71` compares branch/head and bead/answer facts, but carries no profile revision. The loop explicitly fetches and reloads config every pass (`app/loop/loop.py:155`).

**Failure:** Fast-forwarding the main checkout can change slot paths, setup and slot identification while an engine still holds its original config. A local unknown engine key can block reading an otherwise compatible committed profile merely because base discovery decodes the whole local document. After a hop, the same run can use new limits/checks without an admission decision explaining whether prior accepted stages remain valid.

**Fix:** Admit a run against an immutable profile snapshot, identified by commit/content hash and explicit schema version, and use it for slot resolution as well as engine policy. Discover the base without decoding unrelated engine keys; adopt new configuration through a deliberate next-run or revalidation transition.

**Past incident prevented:** 10; explicit schema admission would also contain 3.

### F06 — P2: loop exec still assumes the PID survives `uv run --script`

**Evidence:** `src/taskloop/app/launch/loop.py:182` execs `childenv.script_argv`, which builds `uv run --quiet --script` (`src/taskloop/adapters/childenv.py:123`). `Loop.maybe_move` claims PID-keyed state carries over at `src/taskloop/app/loop/loop.py:353`. The new loop instead builds `LoopState(pid=env.pid, ...)` (`:80`; `env.pid` comes from `os.getpid()` at `app/launch/loop.py:255`). `LoopFiles` keys files by PID (`app/loop/files.py:32`), accepts a live numeric PID at lines 49–64, and addresses stop commands by `(pid, started)` at lines 77–91. Loop teardown removes only `self.env.pid` (`app/loop/loop.py:113`).

**Failure:** Under the incident's uv topology, the old Python PID becomes uv and the new Python child publishes another state file. The old file remains “live” while uv waits, producing a phantom loop and reserved worktree. A stop command written for the old `(pid, started)` before the handover is ignored by the successor's new PID. The engine-specific `TL_REEXEC` lock exception does not migrate loop command targets or loop state files.

**Fix:** Give the loop a stable execution ID independent of PID and atomically transfer its process identity and pending commands on takeover. Track process birth identity and remove/retire the predecessor record under the loop lock after the successor acknowledges it.

**Past incident prevented:** none exactly; this is incident 2's PID-identity mistake at the loop layer, not a claim that the old engine-lock bug remains unchanged.

### F07 — P2: owner-required delegate pauses fall back to automatic lane retries

**Evidence:** `src/taskloop/domain/lanes/pauses.py:42` classifies `engine_only_unenforced`, setup and contract violations as `needs_owner` (also lines 49–51 and fallback at line 82). `src/taskloop/app/asks/parks.py:45` refuses to persist a non-transient pause at lines 51–52, except for the separately handled no-op case. `src/taskloop/domain/lanes/policy.py:214` maps machine/owner stops to `PAUSE_LANE`. `src/taskloop/app/run/lane_acts.py:160` retains the reason but stores a role for every Yield at line 164. Without a Park record, `src/taskloop/app/loop/settle.py:94` substitutes a role wake or timer, and after repeated pauses substitutes a rest timer.

**Failure:** A delegate request that requires an owner fix can reopen and re-enter as soon as its role is usable, even though no corrective input arrived. Unknown future stop reasons have the same gap: the pause table's “owner” fallback is not durably enforced. This can repeatedly spend admission/planning effort or churn beads on a machine-wide incompatibility.

**Fix:** Persist every pause, including owner-required ones, with a typed wake condition and original stop facts. Have loop scheduling consume that single decision instead of reconstructing permanence from outcome/role/timer fallbacks; a machine-wide owner pause should gate claims at machine scope.

**Past incident prevented:** 7; it also prevents repeated retries of the owner-fix condition in 4.

### F08 — P2: delegate answer-version checking does not establish request compatibility

**Evidence:** `packages/kernel/src/tlkernel/delegate.py:52`–67 serializes flags including `--engine-only-advisory` and repeated `--only-family`. `src/taskloop/app/run/worker_request.py:19` enables advisory mode whenever a pinned write has engine-owned recipes. `src/taskloop/adapters/delegate.py:105`–113 checks only numeric contract equality. The vendored contract's `about` says flag changes require a bump (`tests/fixtures/delegate3/skills/delegate/contract.json:3`), but supplies no advertised request capabilities. Tests assert argv construction (`tests/contracts/test_delegate_wire.py:56`, `:62`), which cannot prove an older installed CLI accepts it. `Delegation.route` can switch installs on every call (`src/taskloop/app/run/delegation.py:11`–24).

**Failure:** Two installations that both advertise contract 3 can disagree about a newly introduced flag. Task-loop admits the pair and discovers incompatibility only after dispatch, potentially after earlier steps have already mutated work. The current repository provides no negotiation that proves that pair is safe; a fixture and a contract integer cannot establish the installed parser's capabilities. This is a boundary risk, not a claim about unread delegate code.

**Fix:** Negotiate required request capabilities before claiming work, including advisory semantics and family restrictions, or enforce an explicit minimum producer version for each feature. Record the admitted task-loop/delegate pair and re-negotiate before any per-call switch or resumed thread crosses versions.

**Past incident prevented:** 9, when an update changes request features; none for the exact diagnostic loss in 4.

### F09 — P2: dashboard answers can act on a different ask than the owner saw

**Evidence:** `src/taskloop_dash/api/writes.py:113` resolves `req.ask` and derives its option action/text, but the call at line 127 passes only repo and bead. `AnswerAsk` has no expected ask ID (`packages/kernel/src/tlkernel/ports.py:39`–43). `src/taskloop/app/launch/dash_ports.py:50` forwards that reduced request to `Intake.answer`. Intake re-reads the current ask at `src/taskloop/app/asks/intake.py:97` and submits that new `ask.id` to the locked store at line 104.

**Failure:** Between the dashboard's validation and Intake's re-read, the engine can replace ask A with ask B. An action chosen from A's options can answer or amend B and reopen its bead. The store's expected-ID guard cannot reject this because the adapter substituted B's ID. The dashboard is a state-changing actor even though its package imports only contracts.

**Fix:** Carry the expected ask ID through the port and Intake and compare it inside the store's lock; reject superseded requests without reopening the bead. Keep dashboard projections on read-only ports and expose owner commands through an explicitly versioned command interface.

**Past incident prevented:** none.

### F10 — P2: follow-up creation and its receipt are not one recoverable operation

**Evidence:** `src/taskloop/app/land/followups.py:60` creates a bead, then appends its key and saves the checkpoint at lines 62–64. Ordinary follow-ups are deduplicated only against `e.filed` by `src/taskloop/domain/review/followups.py:62`; the external lookup at `app/land/followups.py:43`–49 is limited to unchecked-item follow-ups and matches a title prefix. `NewBead` carries no idempotency key (`packages/kernel/src/tlkernel/ports.py:58`–68). The enclosing FileNotes effect is replayable from the checkpoint (`src/taskloop/app/run/closer.py:116`, `:166`).

**Failure:** A process killed after successful bd creation but before checkpoint persistence replays creation on restart. It can create duplicate follow-up beads and exceed the intended cap across replays. The docstring's “a kill after a create loses no key” (`app/land/followups.py:53`) is false in precisely that gap. Multiline lint parsing repairs do not establish durable delivery.

**Fix:** Persist a stable follow-up intent/key before dispatch and use that key for tracker-side idempotent creation or exact lookup/reconciliation after an ambiguous result. Store the created bead ID with the key; do not infer identity from a title prefix.

**Past incident prevented:** none; incident 5 is a different failure in this same boundary.

### F11 — P2: run liveness identifies a process by numeric PID alone

**Evidence:** `packages/kernel/src/tlkernel/run.py:180` defines run ownership as host/PID, with `attempts` at line 194 and PID at line 197. Creation and takeover write `os.getpid()` without its birth identity (`packages/kernel/src/tlkernel/locator.py:133`, `:145`). `packages/kernel/src/tlkernel/runlife.py:49` refuses to call a stale run lost whenever any process is alive at that PID. `src/taskloop/app/run/requests.py:46` uses that decision before posting owner requests. Engine lock liveness separately uses a start identity (`src/taskloop/app/slots/engine_lock.py:71`).

**Failure:** PID reuse leaves a dead run marked live indefinitely while an unrelated process holds its old number. The dashboard can show a live execution and owner commands can be accepted into a request file no engine will consume; automatic loss reconciliation cannot repair it. Run and engine-lock readers can disagree about the same dead execution.

**Fix:** Store host/boot identity, PID and process start identity in the attempt record and share one liveness rule with locks and loop state. Treat an unreadable identity as an explicit uncertain state with bounded reconciliation, not permanent proof of life.

**Past incident prevented:** none exactly; incident 2 is an exec/parent-child identity problem rather than PID recycling.

### F12 — P3: the layer graph hides effects and shared mutable ownership inside “contracts” and host wrappers

**Evidence:** `.importlinter:16` places contracts below domain/adapters and stores, but `packages/kernel/src/tlkernel/stores.py:90` performs filesystem reads, `:115` writes, `contracts/fence.py:71` mutates bd, and `contracts/runlife.py:64` reconciles manifests. There is no separate source `ports/` package: effects and pure protocols share `contracts/ports.py`. `Engine` constructs parts over itself at `src/taskloop/app/run/engine.py:189`; `Checkpoints` accepts an `Any` host (`app/run/state.py:106`). `carries_state` dynamically installs writable aliases at `app/run/state.py:96`, so every part holding Engine can change checkpoint state. The nominal `stores/files.py:27` document factory returns the lower-layer concrete `JsonStore`.

**Failure:** Passing the import rules does not prove “domain has no I/O”: a domain module is allowed to call effectful contracts. Splitting Engine into host wrappers also does not allocate ownership; a field write through an alias and a later checkpoint replacement remain a cross-module transaction, with no type-level declaration of its writer. This makes the missing serialization in F02/F03/F04 difficult to localize or enforce.

**Fix:** Move concrete persistence, bd transitions and reconciliation out of contracts, leaving records and narrow protocols below pure domain code. Replace mutable whole-engine hosts with explicit transition inputs/results and an owner that commits state; delete forwarding/alias layers that add no invariant.

**Past incident prevented:** none directly; this removes the structural escape hatches that conceal the concrete failures above.

## Boundaries, deletion test and duplicate policy

The actual dependency order is CLI/hook → app → stores → domain/adapters → contracts (`.importlinter:16`), with domain and adapters independent siblings. App slices are additionally ordered (`.importlinter:116`). F12 is the failure of that order to encode effects: importing only “contracts” does not mean a component is pure or read-only. Dashboard mutation callbacks are assembled from engine code (`src/taskloop/app/launch/dash_ports.py:135`) and execute bd operations in-process. A source import prohibition therefore cannot define a dashboard write boundary.

Apply the deletion test to the following concrete seams:

| Module/seam | What disappears if removed/inlined? | Required architectural action |
|---|---|---|
| `app/run/engine.py:95` and `:99`, `land_with_engine` / `close_with_engine` | Only one-call forwarding names; construction still happens in `lander_over` / `closer_over` | Inline the forwarding functions; do not count them as a lifecycle boundary (F12) |
| `app/run/state.py:43`–99, `StateField` / `carries_state` | A second writable spelling for each `RunState` field | Remove aliases and make state ownership visible at the call site; the persistence writer should accept explicit transitions (F12) |
| `app/slots/pool.py:70`, `Slot.ready_for` | A forwarding method; no lease/lock guarantee is lost | Either make it acquire/require the mutation capability or inline it and place that requirement at the real reset boundary (F02) |
| `stores/files.py:20`, `FileDocSet` | A path/type-to-document factory and key enumeration | Move keyed document construction into the persistence implementation rather than use a “stores” layer to wrap effectful contracts (F12) |
| `app/run/state.py:102`, `Checkpoints` | Fencing, cursor persistence, effect receipts and resume-related state updates | Its obligations require one real transaction owner; do not replace it with raw writes scattered through host components (F03/F04/F12) |

The repeated logic that changes behavior is pause policy: wire scope/permanence → lane action (`domain/lanes/policy.py:214`) → durable pause lookup (`domain/lanes/pauses.py:23`) → persistence eligibility (`app/asks/parks.py:51`) → role/timer fallback (`app/loop/settle.py:94`). F07 is an actual disagreement between these authorities. Slot identity is likewise reconstructed from current profile, ownership documents and bead metadata (`app/wire/slots.py:142`, `app/slots/pool.py:141`), while lifetime is controlled separately by engine locks and leases; F02/F05 show why the join must have one revision and owner.

## The run-task front door and mutation paths around it

`tl run-task` enters `app/run/entry.main`, selects a worktree/slot, obtains the engine lock, admits the bead, claims it, builds a fence and constructs Engine (`src/taskloop/app/run/entry.py:313`, `:365`). It is the engine entry, not the only state mutation authority. The verb registry explicitly exposes the following other routes (`skills/task-loop/tl.py:398`–437):

| Entry/path | State it can mutate outside run-task |
|---|---|
| `claim`, `bd` passthrough, `queue` | claims, bead fields/metadata, arbitrary tracker operations; passthrough reaches `adapters/bd.py:190` |
| `close`, `block`, standalone `land` | bead disposition, land receipts, manifests/logs and branch/worktree cleanup; standalone land invokes cleanup directly (`cli/land.py:19`–44) |
| `land-stack`, `land-lock` | delivery/git operations, delivery records and land lock participation |
| `slot init/take/release/reset/setup/hold`, `worktree`, `worktrees` | slot claims/metadata, engine lock removal in forced paths, setup stamps, worktree directories and ownership documents (`app/slots/pool.py:74`, `app/slots/reset.py:39`, `app/slots/owned.py:99`) |
| `loop`, `stop`, `factory` | loop state/commands, claims, refusal labels, slot lifecycle, process and factory state; loop also starts prune/reconciliation/chores (`app/loop/loop.py:201`) |
| `ask`, `answer`, `hint`, `hold`, `override`, `park`, `note`; dashboard POST verbs | asks/ledger, owner metadata, ADRs/look follow-ups and run requests; `app/asks/intake.py:95`, `app/run/requests.py:139`, dashboard `api/writes.py:73` |
| `check`, `gate`, `selftest` | standalone run lifecycle/evidence/cache; selftest executes an engine flow (`contracts/locator.py:122`, `app/run/stage_run.py`) |
| `prune`, doctor/wait/report reconciliation | run data, worktree cleanup, claim/slot release and lost manifests; read-looking verbs can invoke `contracts/runlife.py:64` |
| `pin`, `rollback`, release/update tooling, usage/lanes/register/hooks/handoff/reflect | installed-version selection, release records, usage/status caches, repo/session indices, hooks and generated handoff/reflection artifacts |

This is the repository-visible mutation surface, not a claim that each route always writes on every invocation. Read-only projections and explicit owner overrides need separate capabilities, but both must share the relevant state transition guards. A direct land receipt, cleanup retry or recovery probe cannot be exempt because it did not start an AI worker (F02/F03/F09).

## Delegate contract and installed-version skew

The outbound request includes role, brief/schema paths, cwd, unattended, parent/task/title, resume/authored-by/call ID, timeout/idle, engine-only recipes, advisory mode and allowed families (`packages/kernel/src/tlkernel/delegate.py:32`). The inbound contract includes `stop` facts, open reason string, scope/permanence/retry, worker termination/survivors, denial and usage facts; decoding is in `src/taskloop/adapters/delegate_wire.py:84` and `:179`. The adapter synthesizes a timeout/no-answer when execution does not yield an answer (`adapters/delegate.py:197`). Those are distinct authorities: the producer reports facts, while task-loop chooses the resulting state transition.

F08 concerns outbound feature admission, and F07 concerns that transition after a valid stop. A pair can agree on the answer's integer and still disagree on flags; a consumer can parse `needs_owner` and still schedule a timer retry. Re-resolving delegate each call (`app/run/delegation.py:11`) and task-loop each safe point (`app/run/reload.py:68`) permits both installed versions to change within one run without an admitted pair. Per-call path logging records the change after selection; it is not a compatibility decision. The requested fix is a negotiated pair and a durable stop/wake record, not more stop-reason wording.

## Test seams that conceal these failures

Tests were inspected, not run. These are limitations of the assertions shown, not a claim that the repository has no other tests.

| Evidence | What the test can pass while the real operation breaks | Required discriminating check |
|---|---|---|
| `tests/slots/test_engine_handoff.py:20` patches PID, liveness and lock reads; `tests/launch/test_reload.py:115` injects returning exec; `tests/loop/real/test_loop_installs.py:49` patches `os.execve` | No real uv parent/child topology, predecessor state retirement or pending stop-target transfer is exercised by these checks (F06) | Real script exec chain, observe both process births, issue stop across takeover, assert one logical loop and no predecessor reservation |
| `tests/contracts/test_delegate_wire.py:62` checks the advisory flag string | An older contract-3 parser rejects that flag (F08) | Run the request compatibility handshake against the oldest supported delegate CLI, or reject the missing advertised feature before dispatch |
| `tests/ports/beads_contract.py:96` checks stale owner before close; fake close mirrors the sequential update/close (`tests/support/fakes.py:150`) | Retake between guard and unconditional close is not represented by checking ownership only before the operation (F03) | Deterministically interleave retake immediately after the guard and demand that the old close cannot change the bead |
| `tests/track/test_fence.py:66` explicitly expects an unreadable bd to fence nothing | The test enshrines the fail-open ownership policy (F03) | Outage during checkpoint/land ownership verification must preserve state and pause the attempt |
| `tests/loop/test_profile_ahead.py:76` injects `SystemExit(EX_CONFIG)` from the profile supplier | Malformed JSON is swallowed before it reaches that injected error seam (F01/F05) | Exercise the actual repository profile loader with malformed committed/local data and assert zero admitted work and retained diagnostics |

The pure-domain test boundary also needs an enforceable dependency rule: no file/process/stateful contract implementation should be reachable through a permitted domain import (F12). Port fakes cannot expose a protocol property the port does not express, such as a conditional generation mutation or the exact ask ID being answered.

## Top 10

Ranked by corruption risk, blast radius and unattended recovery cost; full evidence, failure, fix and incident mapping are in the named findings.

| Rank | Priority | Finding | Concrete repair |
|---|---|---|---|
| 1 | P1 | F01 — malformed profile becomes a gate-free default | Refuse unreadable/malformed selected configuration before admission |
| 2 | P1 | F02 — recovery resets a released slot | Hold the directory capability through recovery; make probes read-only |
| 3 | P1 | F03 — advisory/non-atomic fences | Fail closed and condition the actual mutation on actor and generation |
| 4 | P1 | F04 — hop/rollback can forget durable progress | Negotiate checkpoint/schema compatibility and preserve a rollback snapshot |
| 5 | P2 | F05 — mixed profile revisions within one run | Freeze one versioned profile for engine and slot lifecycle |
| 6 | P2 | F06 — loop PID changes strand state and stop targets | Stable loop identity plus acknowledged process takeover |
| 7 | P2 | F07 — owner-required stops become timer/role retries | Persist one typed wake decision and honor its scope |
| 8 | P2 | F08 — request flags have no capability admission | Negotiate required features and record the admitted installed pair |
| 9 | P2 | F09 — answer is applied to a replacement ask | Preserve expected ask ID through the final locked transition |
| 10 | P2 | F10 — replay duplicates follow-up creation | Durable intent and tracker idempotency/reconciliation by stable key |
