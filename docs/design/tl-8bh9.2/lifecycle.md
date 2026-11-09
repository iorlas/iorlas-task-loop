# Workspace lifecycle and state ownership

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.2 / tl-8bh9.2.1. Source review and Astra consultation, 2026-11-09.
Refinements built on agreed local-slot ownership, prepared-slot default and restart rules. On 2026-11-09 Denis
accepted one shared local database authority per managed pool and repository-owned repeatable setup on preparation. No source, schema,
workspace or running process changed. STORE remains held; this is behavior review, not authorization to implement it.

## Purpose and lifecycle

A slot is a reusable configured workspace, not a work task. A task can use different workspaces across separate steps;
an unfinished live execution retains its actual workspace association. Resource capacity such as Unity is separate.

1. Select dependency-ready, approved work under the settled priority rules. Make a short atomic local workspace
   reservation with unique identity/generation. Obtain its real work-task claim through the task adapter outside the
   allocation critical section. If claiming fails, conditionally release only this reservation. Do not hold a global
   allocation transaction/lock over external IO, preparation, network, setup or model work.
2. Under exclusive workspace ownership, inspect current Git and actual execution state. Resume retained unfinished work
   without resetting it. Before switching tasks, confirm workers stopped, task commits remain reachable and no unresolved
   dirty work/unfinished Git operation would be lost. Ownership, not a filename or directory pattern, authorizes changes.
3. Prepare the selected task branch and run the repository-owned repeatable setup/ensure-ready command through the shared
   command interface, applying ordinary task/command limits and declared scarce-resource permits. Success establishes
   readiness for this context; exit failure, cancellation and inability to observe are explicit outcomes.
4. Associate each actual agent/command execution with the task, step/attempt and workspace reservation. Exclusion covers
   the real execution lifetime, including a child that survives its coordinator. Verify library support; do not assume
   a coordinator-held lock automatically protects surviving descendants.
5. At release, reconcile/cancel as needed and confirm owned workers stopped. Preserve commits, evidence and unresolved
   edits. Only the current matching reservation generation may release ownership. An old holder cannot free a retaken slot.
6. Reuse only after inspecting actual state. An expired heartbeat, absent DB row or empty result after a failed query is
   not proof that a physical workspace is safe to reset. Normal warm reuse need not delete generated build caches.

Dirty work stays protected and returns to the owning execution for commit/remove/ask. Unexplained leftovers are preserved
for explicit continuation/inspection, not blind stage_all, automatic WIP commit, reset or cleanup of another worktree.
A clean committed workspace with preserved task refs can be released during publication, PR review or owner waits once
its workers stopped. Release of workspace does not complete those pending task operations or discard their state.

## One owner per kind of fact

| Owner | Facts |
|---|---|
| Committed repository configuration | Setup/check commands, declared capabilities/resource requirements and delivery policy. |
| Local machine configuration | Workspace locations and actual machine capacity/capabilities/credentials. Resolve existing config overlap once; no portable host slot records. |
| Task service | Work requirements, dependencies, automation approval, portable holds/questions and actual work-task claims. No internal slot tasks. |
| factory.db | Local reservations/generations, preparation outcomes, active step/attempt/execution/workspace associations and pending control/actions. Exact schema follows required behaviors and held STORE decision. |
| Git through owning library | Actual checkout/branch/commit/merge facts and committed plans/code; derive task branch from task ID. |
| Evidence files through readers | Full logs/transcripts and artifact bytes; not fallback state or a source to reconstruct reservations. |
| Shared process/lock/resource libraries | Actual process identity/liveness/cancellation and exclusion/permits. Factory uses their typed APIs and fakes instead of duplicating mechanisms. |

A necessary OS/process lock is a lifetime mechanism, not a second work-task database. Do not mirror a library permit's
mutable authority into a second factory claim. Factory state associates executions and reservations; the owning mechanism
must prevent conflicting actual use. Manual/repository tools that use the shared permit API participate in that limit;
unmanaged direct Unity launches cannot be counted by merely changing factory DB rows.

## Evidence and proposed deletions

| Verified source | Problem / proposed smaller contract |
|---|---|
| tlslots/pool.py take/take_any -> aside.probe -> reset.ready_for/setup | Slow recovery/setup under the shared take lock can block unrelated allocation. Reserve briefly; perform preparation under that workspace's ownership outside the global lock. |
| tlslots/aside.py check | ready_for can run setup and check then forces setup again. Remove duplicate execution and independent recovery-probe ladder; use one setup outcome and shared justified retry policy. |
| app/loop/take.py Taker.prepare | Immediately retries slot_broken, then may execute setup against base to classify a failure. Remove blanket retry and automatic base diagnostic run; record the actual candidate/context failure. |
| tlslots/reset.py setup | Success stamp hashes declared input-file contents but not argv; changed recipe can be skipped. Recommend remove generic factory setup fingerprint/stamp and let repeatable repository setup own warm incremental behavior. |
| tlslots/reset.py ready_for(force=True), pool.py release(force=True) | Drop a busy marker before reset/release without confirming termination. Force becomes stop-and-confirm through the owner, or refusal; never override a live or unknown writer. |
| adapters/agent.py running_for | Exceptions return an empty list, while engine_busy uses it for surviving workers. Return typed unavailable/unknown and preserve exclusion. |
| app/loop/loop.py work finally | Unconditionally drops engine lock, whereas EngineLock.release tries to retain survivor protection. One ownership-aware quiesce/release path must govern both. |
| tlslots/reset.py keep_work/free_branch | Automatically commits leftovers and can detach/remove another worktree to free a branch. Preserve unexplained work and respect actual ownership; branch conflict does not authorize modifying user/foreign worktrees. |
| tlslots/machine.py slot_env.run_setup | Passes setup through spawner with no explicit timeout argument at this seam. Integrate the agreed limits/cancellation contract; do not assume the current seam proves bounded descendant termination. |

These are source-confirmed paths and design risks, not a reproduced concurrency failure or proof that every current
call loses protection. Retain meaningful existing stale-generation and worker-survival tests; no new watcher/service
or general allocation/lease framework is justified solely by historical incident proposals.

## Setup recommendation

Invoke a repository-owned, safe-to-repeat ensure-ready command once per actual workspace preparation. The command may
reuse installed dependencies and warm outputs; changing a candidate does not require rebuilding everything. Factory
records its outcome for operation progress/status, not a generic dependency-cache claim valid for future checkouts.
No configured setup means no command to execute; ordinary checkout/readiness requirements still apply.

The owner accepted this setup contract on 2026-11-09; existing repository scripts may need adjustment. Required failure means setup
failed for this candidate/context; do not label every such failure a permanently broken physical slot. Known unavailable
capacity waits. Retriable infrastructure failure uses shared retry policy; invalid recipe or necessary code changes have
explicit blocked/repair routing. Do not infer those categories from arbitrary console text.

Unity/tool permits remain distinct from workspace ownership and task dependencies. Setup and managed tool commands
using the same scarce capability must use the same shared permit mechanism. Do not guess resource needs from argv names.
The permit must not be released while its actual owned process is alive, even if the coordinator exits.

## Typed results and presentation

Use narrow typed result variants for ready, contention/capacity wait, setup failure, preserved dirty work, ownership loss
and unknown liveness. Required identities/context accompany the appropriate variant; an unknown result cannot be used
where stopped/ready is required. Wire forms are validated structured data, not strings selected with regexes.
For example, illustrative wire data (final field names remain an implementation choice):

```json
{"kind":"blocked","reason":"liveness_unknown","workspace_id":"s1","execution_id":"execution-ref"}
```

The dashboard renders that result into a helpful explanation. It cannot invent readiness by finding READY in output,
convert query failure to an empty worker list, or treat every nonempty error string as a single slot-broken category.
In-process calls pass typed Python values; no universal JSON/message-bus abstraction is required.

## Restart, disposal and owner choices

With intact DB, reconcile and continue the same unfinished step/session in its retained context. Liveness-unavailable
keeps exclusion; an unrelated task cannot take the workspace simply because coordinator PID or heartbeat disappeared.
Controlled DB discard stops admission and confirms relevant workers stopped before new admission. Retain Git and evidence.
Existing unrecorded worktrees require inspection/adoption; do not infer their ownership from the new empty DB.

Owner accepted one local configuration/database authority for factory instances managing the same workspace pool on a host.
This allows multiple schedulers using one reservation protocol, not a new daemon. Independently synced task databases
are not an atomic global lock. Separate authority roots must not automatically manage overlapping physical workspaces.
Shared library exclusion capabilities and real task-service claim semantics still require verification before promising
cross-instance guarantees. No distributed coordinator is proposed.

Both defaults are now agreed: shared-local-authority scope and repository-owned repeatable setup replace factory
setup fingerprint/probe caching. Existing local slot DB ownership and resource/work-task separation remain agreed.
RepoId/store shape follows this lifecycle and supported clone bindings; this note does not silently unhold STORE.
