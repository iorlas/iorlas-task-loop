# First restart-safe agent execution

Task: tl-8bh9.4.3.1, scoped child of AGENT-CONTRACT tl-8bh9.4.3. Proposed implementation specification,
2026-11-09, following read-only Astra consultation. This document records a mechanism recommendation, not new
owner-agreed policy, implemented capability, or permission to implement the whole parent. Source construction
requires independent review of this bounded implementation scope. The [first plan consumer](../tl-8bh9.3.2.1/plan.md) depends on it.

## Required behavior and bounded scope

An intact-factory.db coordinator restart observes and continues the same surviving attempt and native session.
It does not launch a replacement because an acknowledgment, process observation, or session reference is missing.
Factory owns admission, attempt/session associations, reservations and pending actions in factory.db. The owning
agent/process/lock libraries implement execution mechanisms and semantic fakes. Logs, transcripts and artifacts
remain files behind readers; they never restore missing factory control state.

Implement the first Codex execution path only. Retain one existing any_agent.Supervisor in a process whose lifetime
is one admitted attempt, independent of the coordinator. This process consumes harness output, observes deadlines,
publishes session/result facts and holds execution custody. It has no task-selection loop, independent queue,
recovery ledger, remote API or persistent service. Its concrete process justification is preserving the parent
which owns the harness pipes and wait result when the coordinator exits. Do not introduce another supervisor
implementation, agent facade, generic process platform, or optional mode for the old unsafe behavior.

This proposal retains a justified execution-process boundary discussed in the [lifecycle review](../tl-8bh9.3/lifecycle-review.md).
It does not reinterpret the prohibition on a new supervisor as permission for a daemon. If this bounded use of the
existing supervisor is rejected, the current Codex contract cannot supply the required continuation/result guarantee;
that is a concrete blocker, not a reason to substitute receipt files or transcript-derived completion.

## Verified source and limits of inference

The inspected owning checkout is /home/iorlas/Workspaces/wt/shelf-git-porcelain-66, packages any-agent, stream-proc
and process-lock. This is source evidence, not a live harness or process-contract test.

| Current source | Consequence for this slice |
|---|---|
| any_agent/supervisor.py, Supervisor.run: spawn, live.started, hooks.started | A post-spawn callback leaves an unregistered-child window. Moving the callback before the live sink does not close it. |
| Supervisor._wait, unattended parent-change check | This mode kills the execution after parent death; the surviving-attempt path cannot use that policy. |
| Supervisor._pump/finish and procs.spawn | Pipes, parsed result and Popen wait status belong to that process; a replacement coordinator cannot recover them from a PID. |
| procs.spawn calls hold.replay before returning the handle to its caller's cleanup scope | A deferred raising signal can escape after child creation without the caller having a cleanup handle. Registration work must retain protected cleanup across this replay. |
| harnesses/codex.py, thread.started event | Native session identity arrives after launch. The first path must support a temporarily unknown session reference. |
| protocol.LaunchInputs.session and Claude launch arguments | Claude preallocation exists but does not provide durable execution/result collection, and is outside the first path. |
| stream_proc.procfs.read/alive and tree.stop_tree | Unreadable versus absent observations and group-only stop proof need truthful distinctions. |
| process_lock._lock | The descriptor is non-inheritable today; holder metadata is informational, not proof of custody. |

The table records the initial assessment. A subsequent source check on 2026-11-09 found popen_registered and
boot-aware OwnedProcess/observe_owned in stream-proc, now consumed by any_agent.procs.spawn; the first launch seam
has advanced. This does not establish complete attempt-lifetime persistence or whole-workload stop proof.

No caller-token recovery contract or public semantic agent/process/lock fake was found in the initial inspection.
Recheck the actual public APIs before implementation; adopt newly delivered capabilities rather than duplicating them.
Extend the necessary seam in its owner, without moving all delegate behavior or rewriting every harness.

## Launch and persistence protocol

Use a stable opaque dispatch token scoped to one factory attempt. A token is correlation, not proof that an execution
exists. Pass typed values in process. Validate the small necessary process-boundary input; do not add a general RPC
or JSON roundtrip to ordinary Python calls. The factory implements the lifecycle persistence port against factory.db;
the library must not know the factory schema or maintain its own durable control state.

1. Factory commits the admitted attempt, immutable execution input reference/options, slot generation and pending
   dispatch before launch. Admission failure, unavailable DB, or an uncertain claim permits no harness execution.
2. Start the bounded attempt process through the owning process API. Factory conditionally registers its boot-aware
   identity against that token and matching reservation before permitting its entry to execute. Only one registration wins.
   Duplicate bootstrap processes may contend for the same token; a loser exits without launching an agent. Once
   registration has succeeded, another process cannot take it over merely because its acknowledgment was lost.
   Its factory-owned entry validates the reservation, acquires the existing process-lock handle nonreentrantly, and
   performs factory-owned preparation under that handle before invoking the library supervisor. There is no worktree
   mutation before acquisition and no lock handoff from the coordinator.
3. Launch the harness behind a pre-exec registration barrier. The supervisor obtains the child's identity, commits it
   through the factory port, then sends permission to execute. EOF, malformed permission or registration failure
   makes the child exit without executing the harness. Keep launch intent and registered identity distinct from a
   claim that the harness definitely ran; death around permission remains an uncertain dispatch to reconcile.
4. The supervisor consumes typed native session events and persists the session association. It owns the harness
   stdin/stdout/stderr and wait result throughout coordinator absence. It persists typed terminal result, available
   usage, and evidence references before normal exit. Missing native session/usage information remains unknown.
5. Factory restart reads the same attempt, reconciles identities/custody, and either observes it running, collects its
   persisted result, or reports the specific unresolved condition. It never substitutes an agent-list scan or a log
   search for that association. Repeated collection returns the same stored result.

The launch barrier must be executable, not pseudocode relying on a blocked Popen constructor. In particular, a
preexec_fn that waits for the parent's acknowledgment can deadlock: Popen waits for its child exec handshake before
returning the PID. The proposed implementation is a small standard-library-only Python bootstrap launched with
isolated interpreter flags -I -S and an explicit script path. Popen returns after exec of that bootstrap; it then
waits on a private inherited registration channel and exec-replaces itself with the harness after permission, keeping
the PID/start identity. Validate descriptor/argument handling and EOF behavior in stream-proc's real contracts.
This bootstrap is neither another lasting supervisor nor a shell wrapper. Choose an equivalent smaller native
mechanism if demonstrated; do not use threaded Python preexec_fn or private factory subprocess code.

The attempt process composition constructs the same factory-owned application and persistence implementations in
that process and injects the execution persistence port into the library. Preparation, Git policy and failure/release
decisions remain factory-owned; they do not move into any_agent.Supervisor. This keeps one application owner/API
even though two processes use it. No coordinator
callback reachable only through an in-memory object can satisfy the restart contract. Necessary startup data is
passed through the owning launch API; no separate startup-file authority is introduced.

## Minimum typed seams

Names below describe obligations, not a prescribed class hierarchy. Implement only the public operations needed by
the plan consumer; do not add a second synchronous facade alongside a competing recovery path.

Source mapping checked with Astra on 2026-11-09 against released any-agent 0.2.0: reuse RunHooks.started for the
registered identity, RunHooks.ref for the native session and returned RunOutcome for terminal facts. The surviving
factory attempt entry can persist that return value; no new finished callback or library execution-process framework
is required. Current Codex output-schema forwarding does not validate returned answer text. The concrete missing
library seam is strict structured-answer parsing/validation and an owning semantic fake of the same execution call.
Factory supplies its result schema/decoder; answer validity and successful execution remain separate facts.

A direct raising database callback is unsafe in RunHooks.ref: it runs in the output pump and its exception currently
terminates that thread. Use bounded non-raising publication composition, or repair that existing hook's error contract
if actual composition requires it. Never block stream consumption with unbounded persistence retries. Volatile pending
session input is not an accepted DB fact or a durable fallback. Existing pump joins do not prove complete output drainage;
worker return alone does not prove stopped descendants, and absent reported cost remains unknown rather than zero.

| Seam | Required input/result |
|---|---|
| Factory admission | One actual execution request, attempt/token and reservation generation; accepted immutable request or explicit refusal/uncertainty. |
| Conditional lifecycle registration | Token, expected generation/revision and supervisor/child identity; accepted, already-recorded-same, conflict or unavailable. No blind overwrite. |
| Session/result publication | Matching execution identity and typed native session/result facts; idempotent acceptance or explicit conflict/unavailable. Final results cannot be rewritten by a stale writer. |
| Execution observation/collection | Retained identity plus factory lifecycle record; running, pending start, completed with typed result, confirmed not started only with proof, or unresolved/unavailable with reason. |
| Process observation/stop | Opaque identity including boot identity, PID and start identity; live, confirmed absent/different identity, or unknown. Stop reports complete proof, surviving identities, or limited/unavailable proof. |
| Execution custody | Existing nonreentrant acquire/release in the attempt process for this reservation; keep its handle through preparation/execution and safe release. No informational holder record is authoritative. |

The library owns structured-output validation and reports a malformed result as such. Factory owns the plan result
schema and workflow decision. The first path performs one actual harness execution: no schema-correction launch,
fallback, fresh-session retry, or resume hidden inside it. Any later correction/resume launch needs a new factory
admission and actual attempt; reuse of a conversation does not reuse an execution identity. Do not build that retry
ladder as a prerequisite for this first path.

## Custody and failure boundaries

Mechanism recommendation, source-checked 2026-11-09; this is not a new owner policy decision: acquire the worktree
lock in the attempt process before preparation, using existing ProcessLock.acquire(reentrant=False). Keep that same
handle through preparation, agent execution, result acceptance and factory-owned final worktree checks/safe release.
The coordinator never owns this descriptor, so its death cannot release it. No new lock-transfer API, inheritance
option or pass_fds extension is needed. Use a stable lock path outside the managed checkout and never unlink it as
stale cleanup. Add no factory lock polling registry, holder hints or holder sidecar.

Preparation failure publishes a typed failed attempt with agent execution not started and no native session, when
those facts are established. Preserve unresolved custody if preparation tools may have surviving descendants;
agent-not-started does not mean workload-stopped. Library mechanisms report observations; the same factory operation
decides whether result persistence, whole-workload stop and clean intended state permit normal release.

Fatal attempt-process death normally releases its kernel lock. This proposal does not claim otherwise or transfer
custody automatically to a harness. An inherited descriptor would not prove that every descendant retained it either.
Test the supported launch path and retain unknown custody when tree membership cannot be proven.
A free kernel lock, a dead leader, a completed result and a clean worktree
are separate observations; none alone authorizes reuse. Factory reservations remain held while liveness/custody is
unknown, even when an OS lock has disappeared. No stale-owner timeout, PID-name search, detach/reset or new writer
can bypass that state. Full descendant containment is not silently claimed or replaced with a new monitor service.

The source check also found pre-registry failure cleanup gaps in process-lock._lock, including holder-read failure
after contention and metadata-write failure after successful flock. The existing API repair is tracked separately
as shelf-7c34. It must close its unowned descriptor on every acquisition failure; successful ownership stays unchanged.
That library fix and its real contender contracts do not belong in factory source or imply a new custody primitive.

The guarantee here covers coordinator restart while the attempt process survives. If the result-collecting process
also dies after the harness starts but before persisting its result, a replacement process cannot generally obtain
the old parent's wait result. Preserve the attempt and worktree, expose unavailable result/custody, and reconcile
what can actually be proven. This is not permission to call it completed, reconstruct it from a transcript, or
relaunch automatically. Host reboot and unavailable process tables follow the same truthful-proof rule.

On lifecycle persistence failure, do not acknowledge progress that was not committed. Before launch this means no
execution; during execution retain supervision/custody and report inability to publish, without starting another
attempt. Normal worker exit follows accepted result persistence. A fatal worker failure can still leave an explicit
unresolved attempt; do not invent a durable fallback to avoid that limit. Bound harness execution by the admitted
deadline; persistence retry cannot authorize more model work or become an independent scheduler.

## Minimal factory data and ownership

Use the corrected STORE owners, not a new table family for a library ledger. Exact columns are implementation detail:

- Attempt identity/revision, step/task binding, dispatch token and current dispatch phase.
- Admitted immutable input/options reference, deadline, fresh/resume intent and nullable native session reference.
- Slot/worktree reservation generation and associated supervisor/harness boot-aware identities.
- Execution status, terminal conclusion/result, available timing/usage and file-reader evidence references.
- Specific pending dispatch/result-acceptance/release actions needed by this path, atomically advanced by their owner.

References to prompt/evidence artifacts are legitimate inputs/outputs behind readers, not an alternative control
record. A missing required input is an error, never permission to reconstruct it from history. Keep secrets out of
ordinary stored request metadata. factory.db unavailable or unusable means refusal, not empty execution state.

## Implementation order and acceptance

The first independently useful implementation is smaller than this complete contract: gated registered spawn in
stream-proc, consumed by existing any_agent.procs.spawn and RunHooks.started. It closes execution before registration,
provides a boot-aware identity at the gate, and keeps deferred signal replay inside guaranteed child cleanup. Prove
registration-before-exec, rejected registration/EOF, callback failure and deferred-signal cleanup with harmless real
children. Do not expand that change into full tree observation, lock transfer or an execution-service framework.
It does not by itself provide coordinator-restart continuity or eventual result collection.

Subsequent bounded changes establish truthful process observation/proof under .4.4 and verify existing lock lifetime
under .4.5, then supply the missing validated-result/semantic-fake contract in any-agent for this actual consumer.
The surviving supervisor composition and terminal persistence belong to the factory attempt entry, reusing existing
library calls. That entry acquires its own existing lock before preparation; no speculative transfer feature is a
prerequisite. The independent shelf-7c34 acquisition cleanup repair stays with process-lock. Introduce the semantic
execution fake at the agent boundary when that consumer contract exists; do not start with FakePopen or a generic
process platform. Wire the factory's narrow STORE .26.3/.4/.5 consumers and the plan operation only after the needed
real/fake APIs exist. Status reconciliation uses .4.2. These remain prerequisites before registering the plan CLI;
the first launch fix is not a claim that the entire restart contract passed. Do not implement unrelated parent
capabilities, account-routing changes or other harnesses.

Owning-library contracts exercise real bootstrap/lock/process mechanics with harmless controlled children, not real
model calls. Factory tests use those libraries' semantic fakes plus in-memory SQLite. Required cases are: duplicate
dispatch token; death before registration; death before/after execution permission; coordinator death during output;
coordinator death during preparation with the worker's lock still excluding an external contender;
session arriving after restart; completion while coordinator is absent; lost result acknowledgment; worker death with
surviving/unknown descendants; unavailable DB/process table; PID reuse/reboot; stale generation; malformed structured
result; and a proven stopped clean execution allowing release. No unknown observation may become absence/success.

Acceptance requires demonstrated same-attempt/same-session continuation and collection after coordinator restart,
single launch for a contended token, truthful uncertainty, and retained custody on every incomplete proof path.
Run required focused gates in each affected owner after reading its instructions. Factory gates are just check and
just test; no whole-suite/live run. This document itself changes no source, config, tests, task state or Git state.

## First-stage review receipt, 2026-11-09

An independent review read both scoped plans, the accepted lifecycle/delivery policy and the actual Supervisor,
RunHooks, procs and signal-hold code. No blocking design issue was found for the first registered-start stage.
Source is tracked in tl-8bh9.4.4.1 and owning shelf-4426. The later lifetime, observation, persistence and custody
requirements remain prerequisites for the real plan command; approval of this stage does not mark them implemented
or authorize publication of another library branch or release.
