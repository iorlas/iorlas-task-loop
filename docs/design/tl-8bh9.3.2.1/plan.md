# First one-shot plan execution

Task: tl-8bh9.3.2.1, scoped child of PLAN-FILE tl-8bh9.3.2. Proposed implementation specification, 2026-11-09.
This is a bounded consumer of the [agent execution contract](../tl-8bh9.4.3.1/plan.md), not new owner-agreed policy
or a claim that the successor already executes tasks. Only repo/task inspection is implemented in the inspected
successor. Do not register a plan CLI command until the application operation has the real behavior below.
Exception (owner, 2026-11-10, [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 2), for that surface only: `tl plan
start/show/list/verify` are registered for the attempt alone, labelled "attempt only: no task branch, publication or release".

## Result and limits

Execute one explicit task's plan operation through the same application entry that future CLI/dashboard callers
will use. The first real path uses Codex. It reads the task and current code, produces or updates a usable plan at
docs/design/<task-id>/plan.md, and leaves it committed on task/<task-id>. The operation can be observed/continued
after coordinator restart without duplicating a surviving execution. It neither implements the task nor closes it.

The result identifies the actual task, attempt/session, task branch, commit and plan path. Successful harness
exit alone is insufficient. An empty/uncommitted plan or a success-shaped message without verified Git evidence is
insufficient. Meaningful content covers acceptance, relevant existing behavior, proposed bounded work and validation;
unresolved decisions are explicit. The planner reads an existing plan first and reuses/amends it when appropriate.
An already suitable committed plan need not produce an empty commit.

The [accepted publication policy](../tl-8bh9.9/delivery-publication.md) requires the committed checkpoint to reach
the configured remote task branch before the plan step completes. Implement that effect and its narrow retry path
through the owning Git API. Expose local execution completion and publication pending distinctly; do not claim the
step is finished, portable or ready to advance without confirmation. Linked worktrees already share local refs and
objects, so no push into the person's checkout is needed for local handoff; that fact alone does not satisfy the
accepted remote publication requirement. A missing required destination is an explicit configuration refusal, not
a new local-only mode. Use the resolved existing delivery configuration, with no bypass setting or guessed remote.

Implementing/testing this effect does not itself authorize a development-session push. Tests use the owning Git
fake; an actual publication requires the runtime operation's authority and configured destination. This child does
not implement land, task closure or task sync, and local Git authority does not authorize those operations.

## Prerequisites and application boundary

Adopt the existing typed repo/task inspection results and shared Git/task clients. Extend only the missing fields
and operations needed for actual admission; read-only TaskInspection is not itself an admission decision. Resolve
one enabled local repository binding for the configured backlog, one managed task worktree and one task identity.
Do not infer backlog identity from a remote URL or select an arbitrary checkout.

- .3.5 owns authoritative atomic initial task claim and admission. A claim is not a second execution. Respect
  requirements, dependencies, explicit holds and existing ownership; tracker unavailability is a refusal.
- STORE .26.5 owns the local reservation/generation; .26.3 owns this step's actual attempt/session; .26.4 owns the
  specific pending dispatch and boundary actions. Identity/binding uses the agreed existing repository owner.
- .4.3.1 supplies the real/fake single-execution contract; .4.2/.4.4/.4.5 supply truthful observation and custody.
  Their proposed APIs must actually exist and pass owning contracts before this consumer claims restart safety.
- .3.2 supplies the plan content and committed-file completion requirement. No standalone claim CLI, general
  scheduler, slot-pool expansion, generic workflow engine or bulk STORE schema is a prerequisite.

Initial claim uncertainty remains a pending admission action: do not launch until authoritative acquisition or
reconciliation establishes ownership. Matching assignee text alone is not a universal proof of the same acquisition.
Claim contention differs from tracker outage. Never compensate by unconditionally clearing another actor's claim.
The tl-r2g4 conditional final-mutation gap does not block this slice because it performs no final tracker mutation;
leave the work task claimed/open and report that fact. Later unclaim/close/block actions remain gated by their actual
conditional mutation contract, rather than being smuggled into plan cleanup.

## One operation, with durable progress

1. Read the task through the configured actor and inspect the selected repository through the owning Git API.
   Reject invalid/unavailable bindings and unauthorized or blocked work. Atomically reserve the managed worktree
   generation locally, then acquire the actual initial task claim outside the SQLite transaction. Persist the
   pending action before an external effect; release only this reservation on a proven failed acquisition.
2. Persist the plan attempt and admitted immutable inputs, including task/input provenance, deadline and reservation
   generation. Start its bounded process through the owning registered-launch API before preparation. The process
   constructs the same factory application/store ports, validates its token/generation, and acquires existing
   ProcessLock(reentrant=False) itself. The coordinator holds no worktree lock to transfer. No worktree mutation
   occurs before acquisition and confirmation that prior workers are stopped.
3. Under that same handle, perform factory-owned preparation using the deterministic task branch. Continue existing
   committed/local task work rather than recreating it from the target. Never reset the person's checkout, erase
   unexplained dirty work, overwrite an existing branch or adopt an unrecorded worktree merely because its name
   looks managed. Run only already-approved repeatable setup required here. Then start one Codex execution through
   .4.3.1 in this process's existing supervisor, which publishes native session and execution/result facts into
   factory.db. Preparation and failure policy remain factory code; factory source/tests contain no subprocess mechanism.
4. Give the planner the actual requirements/acceptance, existing plan and repository context. Its authorized work is
   the requested plan and necessary selected design artifacts; it writes and commits those intended files on the
   task branch. Instruct it to leave unrelated work intact and report unresolved work or decisions explicitly. Do
   not use an automatic factory stage-all/commit operation to turn unexplained changes into apparent completion.
5. Consume the agent interface's validated structured result. Factory supplies the domain result schema, including
   disposition, plan path, reported commit reference and concise explanation. The shared agent interface owns
   parsing/structural validation; factory owns the workflow meaning. Malformed output or an unmet condition returns
   a typed unsuccessful/unresolved result. This first path contains no automatic model repair or hidden second launch.
6. Reconcile actual Git evidence through its owning API and record the local plan result against the exact commit.
   Persist the pending publication with that pinned commit, configured destination and deterministic task ref. Carry
   out the ordinary non-force publication and confirm its result; an uncertain acknowledgment is observed before
   retry. Publication failure retries transport only, never the planner or its commit. After confirmed whole-workload
   stop and a clean intended state, perform final factory-owned checks/detachment at current HEAD under the same
   lock handle, then release only the matching reservation generation and that handle. Unknown custody,
   dirty/conflicted work or unresolved edits retain the reservation; completion does not override safety.

No agent invocation, task-client request or Git operation occurs inside a SQLite transaction. Durable transitions
are short and conditional. The caller's process lifetime does not own the harness's output collection or worktree
lock. CLI formatting renders the shared result and cannot run a separate launch or cleanup engine.

The attempt-process acquisition placement is a mechanism recommendation, source-checked 2026-11-09, not a new
owner decision. Existing process-lock acquire/release supplies it; no new lock-transfer API is needed. Its separate
pre-registry failure-cleanup defect is tracked as shelf-7c34 and is repaired in that library, never copied into the
factory. A preparation failure records a typed failed/not-started agent result when established. Possible surviving
preparation processes retain unresolved custody even though no agent session began. Fatal attempt-process death
can free the kernel lock; that fact never clears an unresolved factory reservation or proves descendants stopped.

## Publication continuation

Use the existing semantic target remote/branch configuration, as described by the
[configuration review](../tl-8bh9.1/configuration-review.md). Do not retain raw push-argv configuration or introduce
an alternative destination mechanism for this slice. The task branch is task/<task-id>; it is not the target branch.
Store only the pinned checkpoint and pending effect necessary for restart, not a generic outbox.

Observe the configured remote task ref through the owning Git API. Equality confirms publication. An ancestor can
be advanced by an ordinary non-force push; confirmed absence allows creation. A descendant contains the checkpoint
but requires reconciling the unexpected newer work before advancing. Divergence preserves both histories and stops
automatic overwrite. Unknown observation is neither absence nor success. No automatic rebase, force push, new
integration workflow or model repair is needed to handle a failed observation.

Transient failure leaves this same plan operation at publication pending. A later invocation/restart retries only
that pending effect after observation; already successful execution and plan verification are retained. Permanent
permission/configuration refusal is explicit. A successful push followed by a lost DB acknowledgment is reconciled
against the remote ref before repetition. Clean worktree release can proceed once workload stop is proven, even
while publication waits; network transport need not occupy a writer slot. The step is complete only after required
publication and safety cleanup are confirmed. There is no automatic next implementation step in this one-shot path.

## Completion evidence and semantic limits

The factory deterministically verifies the configured task branch/repository, the pinned commit's relationship to
that branch, the required tracked plan blob at the exact task path, intended committed changes, and absence of
unresolved tracked/untracked work. Ref observation failure is unknown, not missing. A returned arbitrary commit or
plan from another task/repository cannot satisfy the operation. Preserve allowed ignored build files; clean release
does not mean deleting them. Do not blindly rewrite or force-update task history.

Content quality requires assessment, as recorded in [execution terms](../execution-terms.md). File existence, a
heading count or nonempty text cannot establish useful planning. Preserve a representative meaningful plan in the
consumer's acceptance evidence and have the ordinary implementation review assess the prompt/result contract and
its coverage of task acceptance. Do not add a new runtime AI evaluator, planner probe or mandatory owner-approval
loop. Runtime structural/Git checks must not be presented as independent semantic review of the plan.

If an existing committed plan is reused, assess it against the current task/code inputs; historical file presence
is not an automatic pass. The plan remains the single Git-owned planning artifact. Structured completion output is
execution evidence referencing it, not a separately authoritative JSON plan stored in factory.db or run directories.

## Restart and failure acceptance

| Interruption/failure | Required behavior |
|---|---|
| Preparation fails before agent launch | Record a typed failed attempt with agent-not-started/no session when proven; preserve actual claim/worktree facts and unresolved preparation descendants. Release only proven safe local ownership. |
| Coordinator exits during preparation | The same factory attempt process retains its own lock and continues the operation; no transfer or second preparer is required. |
| Dispatch acknowledgment is lost | Reconcile the same dispatch token; no blind replacement execution. |
| Coordinator exits while Codex runs | Same surviving supervisor, harness, attempt, native session and reservation continue; restarting the command observes that operation. |
| Native session arrives after restart | Record it on the same attempt through the owning lifecycle port; do not invent a session from PID/log path. |
| Agent finishes while coordinator is absent | Collect its persisted typed result; do not parse transcript/log history for completion. |
| Result collector dies or process table is unreadable | Explicit unresolved result/custody; no new writer, automatic retry, detach/reset or success claim. |
| Structured output is invalid | Report the actual failure while preserving Git work; no hidden correction launch. |
| Agent reports success without a committed plan | Local completion fails; retain the actual evidence and work for an explicitly admitted later attempt. |
| Commit exists but factory acknowledgment was lost | Inspect Git's authoritative branch/commit/path and reconcile the pending plan verification; do not rerun a completed agent to repeat its commit. |
| DB unavailable/corrupt/schema-unusable | Refuse admission/control changes; no deletion, backup restore, log replay or file fallback. |
| Stale caller tries to finish/release | Conditional attempt/reservation revision rejects it; another generation's state remains intact. |
| Local plan is committed but not published | Report local completion/publication pending; do not advance to implementation or claim task completion. |
| Push acknowledgment is lost | Observe the pinned remote task ref, confirm or retry only the unfinished publication effect. |
| Remote ref diverges or cannot be read | Preserve both histories and report divergence/unknown distinctly; no force push or planner rerun. |

Git evidence can establish a committed plan effect after a lost acknowledgment; it cannot manufacture an execution
result or native session for an attempt whose collector failed. Keep those facts distinct. A later actual launch
continuing the same conversation is another attempt and must pass admission again. This slice does not implement
automatic retry policy simply to avoid reporting an unresolved case.

## Focused verification and completion of this child

Factory tests use owning-library semantic agent/process/lock/Git/task fakes and in-memory SQLite. They exercise a
meaningful committed plan, existing-plan reuse, initial claim contention/outage, lost dispatch acknowledgment,
coordinator restart during preparation/execution, preparation failures with known/unknown custody, completion while
absent, invalid structured output, missing/uncommitted/wrong
plan evidence, stale reservation release, unknown descendants, publication pending/retry, lost push acknowledgment
and remote-ref divergence/unavailability. Tests assert observable transitions and retained work, not each private
helper or copies of the implementation.

Real process/lock/bootstrap behavior is proved in owning shelf contracts with harmless children; no live model call
or whole-suite agent test is part of factory verification. Read justfile, then run required focused just check and
just test after implementation. Verify only supported CLI commands are registered and the new operation reports
typed failures non-interactively. An independent review checks plan production, checkpoint publication and their limits.

This child is complete only when the real one-shot operation and restart path work through the owning contracts,
produce a usable committed task plan, publish/confirm its checkpoint, preserve uncertain work, and truthfully retain
pending publication on failure. It does not establish completion of all parent PLAN-FILE scope, the wider agent
contract, or the task factory. This design edit itself performs no source/config/test/Git/task mutation and runs no
implementation tests.
