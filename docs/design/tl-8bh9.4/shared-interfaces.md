# Shared interfaces: available mechanisms and remaining gaps

Task: tl-8bh9.4 with tl-8bh9.6.2 and corrected STORE dependencies. Source review with Astra, 2026-11-09.
Evidence is the vendored library snapshot and current factory/delegate source, not latest shelf HEAD. No source edits,
process/Git execution or implementation tests were performed. Inspect owning shelf source before extending a package;
never hand-edit installed/vendor cache copies to supply missing APIs.

## Boundary contract

Factory owns workflow, task/step schema, admission/allowances and fresh-versus-resume intent. Libraries own necessary
execution/Git/lock/task-client/SQLite mechanisms and their semantic fakes. Every boundary carries typed inputs/results;
wire boundaries use validated structured forms where supported. In-process calls need no JSON serialization. Display
strings/logs are never workflow control. Unavoidable external text quirks remain inside the owning adapter/library,
with explicit unknown/error instead of guessed success. No universal RPC/message bus, schema registry or supervisor.

## Capability assessment

| Boundary | Available in inspected source | Remaining work | Owning task |
|---|---|---|---|
| Git | git_porcelain Repo.identity, typed refs/ancestry/worktrees/push results and FakeRepo/FakeWorktree/FakeRemote. | Adopt instead of private factory parsing. Verify canonical linked paths/symlinks/clones and origin absence versus failed observation; identity metadata refresh after remote changes. No new Git parser/global ID service. | REPOID tl-sqd3.18 and tl-8bh9.9.1/.9.2/.9.3. |
| SQLite | sqlite_store short begin_immediate, rollback and caller-transaction CAS; RunRows already writes owned manifest/indexed fields together. | Correct application entities/ownership and ambiguous readers, not another transaction framework. One revision/generation-aware reservation and runtime progress owner. | Corrected tl-sqd3.26 slices. |
| Agent execution | Typed RunRequest/RunResult, session resume, structured-output correction, start handles and cancellation exist in delegate/any_agent. | Invoke factory admission before EVERY actual execution, including correction/fresh/canary/retry; report each real execution/session/usage during the call. Remove competing delayed retry ladders. No second agent facade. | tl-8bh9.4.3 plus RETRY-OWNER. |
| Execution recovery | PID/start/session/lease records, agents/history/cancel APIs exist. | Public typed reconciliation and eventual result collection for one uncertain dispatch is not established. agents list is not a recovery handle; unknown observation must not become no workers. | tl-8bh9.4.2/.4.3, actual-attempt/pending-action STORE consumers. |
| Native concurrency | Harness launch inputs already include explicit cwd/environment. | delegate.api.run mutates process-global os.environ and has a one-call-per-process constraint. Threading concurrent calls through that API is unsafe. Make execution context explicit/reentrant before removing justified per-task process isolation. | tl-8bh9.4.3/.4.4. |
| Process termination | stream_proc PID/start identity, process-tree stop, timeout, cancellation and survivor reporting. | Verify descendants, post-crash observation and partial proof: unavailable process table can reduce proof to group-only. Surface unknown/limited proof so workspace release never assumes full stop. | tl-8bh9.4.4/.4.2. |
| Locks/resources | process_lock timeout/holder metadata/nonreentrant acquire; any_lease capacity, cancellation and ordered multi-acquire cleanup. | Actual workload lifetime can outlast acquiring coordinator; ownership integration needs proof. Retain mechanism and remove duplicate polling/sidecars only after one lifetime-safe path. | tl-8bh9.4.4/.4.5 and SLOT-STATE. |
| Task service | beads_client JSON records and typed claim failure distinction. | Factory raw return-code claims and swallowed comments errors discard those guarantees. Namespace/stable question-response IDs and actual conditional backend mutations need contracts. Guarded close is currently check-then-close, not atomic. | tl-8bh9.6.2; upstream tl-r2g4 for generation/conditional primitive. |
| Test doubles | Git has public semantic fakes; task client has scripted CLI replies. In-memory SQLite can test local transactions. | No public semantic agent/process/lock/resource fake found in the inspected snapshot. Verify current owning shelf before adding one. Scripted CLI output alone does not prove concurrency/cancellation/claim semantics. | tl-z6np / shelf-69pz and owning boundary tasks. |

## Concrete source anchors

- packages/delegate/src/delegate/api.py: run(request, started=...), process-global environment mutation, fresh-session
  fallback and agents/history/cancel. started is post-spawn, not permission to launch. Multiple internal launches sharing
  a run ID do not substitute for distinct actual attempts.
- packages/delegate/src/delegate/app/run.py and vendored any_agent/supervisor.py: launch/schema/retry paths and started hook.
- src/taskloop/adapters/agent.py: running_for catches status exceptions and returns []; this is not evidence of no workers.
- vendored stream_proc/tree.py: group-only proof fallback and survivor reporting. Existing API documentation is not a
  demonstrated cross-crash lifetime guarantee; owning contract tests must establish the needed behavior.
- vendored beads_client/client.py: claim distinguishes contention from failure; close(if_assignee) performs update then
  unconditional close. src/taskloop/adapters/bd.py bypasses claim handling and swallows comment-read errors.
- vendored beads_client/records.py: Comment exposes author/text/time without stable comment identity/revision.
- vendored git_porcelain/api.py and real_read.py: identity already exists, is memoized and reads origin with check=False.
- vendored sqlite_store/transaction.py and cas.py: necessary transactional primitives already exist.

## Strict implementation rules

1. Before each external agent execution, library asks the injected factory admission function. Factory persists allowance/
   intent/attempt identity; callback failure or uncertainty means no launch. Library owns schema validation/correction
   prompts. Delayed retry returns typed wait. Lifecycle reporting makes every admitted actual execution inspectable.
2. Dispatch intent is not proof of spawn. Observe a retained execution identity and collect its actual result, or return
   running/unknown/unavailable/confirmed-not-started as appropriate. Do not reconstruct completion from transcripts or
   blindly launch a replacement. Same surviving execution is the same attempt; relaunch/correction is another.
3. Concurrency context must be per call, including cwd/environment/session/limits. Keep an existing necessary process
   boundary until the replacement has proven cancellation and no shared environment/state race. Native Python first
   does not mean exposing an unsafe API concurrently.
4. Namespace and conditional task mutations are real adapter guarantees, not a remote URL guess or local lock around
   two remote calls. Unsupported primitives block the affected action. Do not represent service outage as empty backlog,
   empty comments, lost claim or closed task. Followup responses reference the actual question, not its position in text.
5. Existing SQLite/Git APIs are adopted through narrow factory ports, not hidden behind new mechanism implementations.
   Libraries own their real/fake behavior; factory tests use them. Missing shared fakes are added to their owner after
   verifying the current package. Do not write a second SQLite implementation: in-memory SQLite is sufficient.
6. The approved initial policy is time-only with usage recorded; it does not require activating speculative financial/
   token budget machinery. Do not remove broader reusable library capabilities merely because factory starts with caps off.

## Dependencies and discussion outcome

The corrected STORE tasks carry prerequisites only for affected actions. Repository binding and local SQLite ownership
can advance without waiting for agent recovery. Pending external actions require agent/task contracts; portable asks
requires stable task discussion identity; obsolete readers are deleted only after their replacement exists.

No additional product preference is required for these already agreed guarantees. Verify uncertain library/backend
capabilities in their owning contracts and implement the demonstrated missing seam. If unsupported, report the concrete
technical blocker rather than quietly weakening the contract or inventing another service.
