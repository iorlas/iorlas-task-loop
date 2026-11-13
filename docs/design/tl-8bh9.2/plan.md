# Workspace ownership and concurrency

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.2. Design review, 2026-11-08. No workspace reset, deletion or source changes performed.

## Owner decision and portability test

Owner clarification, 2026-11-08, superseding the earlier discussion about retaining internal slot tasks: slot state
is disposable factory state and belongs in the database. Task management is a domain behind a port; Beads is its
current adapter, not a required storage service for factory resources. Actual work tasks and their claims remain
task-management concerns. A slot is a configured reusable workspace; an active attempt reserves it locally.

Use the owner's test for placement: shut down the factory, clone code and synchronize tasks on another PC, and start
with no old factory.db or artifacts copied. Requirements, plans and code remain useful there. Old host slot names,
paths, PIDs, reservations, attempt history and setup stamps are not portable task data. Retained evidence can stay
on the original host; new-PC continuation must not require it. This does not authorize deleting retained evidence.
Portable code must include the required task branches and committed plans, not only main; publication timing is
still a separate unresolved delivery question.

## Target division of information

| Location | Responsibility |
|---|---|
| Work task | Requirements, acceptance criteria, dependencies, meaningful task status, task ownership and concise work context. References to versioned design/plan; native metadata for agreed durable milestones if needed. |
| Configuration | Slot capacity, workspace locations and setup commands. Repo defaults and host-specific settings need their existing profile/config distinction; do not copy old machine paths into work tasks. |
| factory.db | Slot reservations/holds and local executions: step attempts, outcomes, selected next step/reason, timing/usage, session and evidence references, current workspace/process association. Exact schema remains open. |
| Git | Code, plan and design decisions. Derive task branch names rather than maintaining competing naming state. |
| Task runtime files | Complete logs, transcripts and artifacts beside the task's local logs, behind their readers. |

This division preserves the accepted state/log distinction. The task adapter owns a work-task claim; factory.db owns
local resource reservations. An execution refers to its real work task without creating a second work-task system.
Do not introduce competing authorities for the same claim. Decisions belong in versioned design documents; task
comments provide work context. Existing internal slot tasks are current implementation to retire, not target objects.

## Existing safeguards read in code

- slots/pool.py claims a slot task under take_lock and marks its holder and generation.
- slots/marks.py reads the current generation after winning a claim and increments it; release checks the expected
  generation and holder so an old run should not release a newly taken slot.
- slots/lease.py heartbeats both task and slot claims; its stated purpose includes slow slot preparation and workers
  outliving a coordinator.
- slots/engine_lock.py stores a local engine record in factory.db and checks live process identity, including PID
  start time and workers outliving their engine. Admission checks and writes occur under a local worktree lock.
- kernel/fence.py checks task/slot generations before side effects. Its generation update is read/write/read, with
  a comment that the backend lacks compare-and-set. Verify the required serialization across all callers; do not
  treat generation readback alone as proof of atomic ownership transfer.

These observations are static code evidence, not a concurrency stress test or proof that every race is covered.
The original task scope named src/taskloop/app/slots, which is absent; current slot code lives in packages/slots.

## Safety properties to verify

One winner claims a resource; admission to a physical workspace is mutually exclusive; an old holder cannot release
or mutate a resource after another take. Lease expiration alone must not justify resetting a workspace while its
engine or child process still uses it. Use live execution protection in addition to cooperative tracker ownership.

Database disposability does not make a live worktree free: absence of a DB row is not proof that all processes
stopped. Review how process-held exclusion or controlled shutdown protects workspace reuse when local state is
discarded. Do not respond by adding a history reconstruction subsystem. Read-only inspection may continue meanwhile.

Clarify coordination scope before promising cross-machine exclusion. Atomic claims against one authoritative backend
and independently synced local task databases have different guarantees. Remote synchronization alone is not an
atomic global lock. Do not invent a distributed lock service before establishing the actual deployment needs.

## Review outcome sought

Additional storage inventory, 2026-11-08: Beads holds actual work/slot task state in its task database; factory.db
holds engine lease rows (EngineLockRows) and worktree creation/provenance records (WorktreeDocs). Worktree provenance
is evidence that tl created a directory, not another live slot claim. Actual local critical-section exclusion also
uses process lock files via any_process_lock, and scarce-resource leases use the separate any_lease directory from
ConfigDir.leases(). Slot setup fingerprints remain small files under ConfigDir/slots; command scratch persists in
repo-specific slot-state directories. Git retains branches, commits and checkout state. These are several storage
mechanisms today, not a single all-SQLite implementation. Assess necessary derived/cache files separately from
authoritative mutable state; do not call lock files duplicate tracker tasks.

Earlier owner rationale considered tracker claims for coordination between instances; the later portability test
settles local slot state in factory.db. Clarify whether instances share a host/config/database and one authoritative task backend.
Different local databases do not become a real-time mutual-exclusion mechanism merely through sync. A pending
terminology clarification was answered by the owner: "Beads' existing claims". No Redis service is proposed.

Retain useful real work-task claims, process exclusion and stale-holder protection with one owner per responsibility.
Consolidate duplicate orchestration where evidence supports it. Keep logs tracing the same events without making
them fallback state. Normal unresolved agent edits return to the agent; inspect crash-leftover handling separately
from preparing a clean workspace. Coordinate storage changes with the held STORE decision rather than starting it.

## Astra review and implementation questions

Owner explicitly requested a full-context Astra review. Astra agrees with separating task-service work from local
slot reservations and recommends a shared local authority per host/configuration root. That scope is a proposal,
not a new distributed coordinator or additional daemon. Every participating local scheduler must use the same
atomic reservation protocol. A database row alone is not mutual exclusion; acquisition and release need verified
transaction and stale-owner semantics.

Astra recommends controlled disposal: stop admission and terminate/confirm the relevant workers before deleting a
broken database. Do not build history recovery or infer that an empty DB makes live worktrees free. Keep only the
OS/process exclusion necessary for actual lifetime/filesystem safety; a lock path need not become an extra state
store. Confirm whether manual Unity commands must share resource permits before replacing the any_lease mechanism.

Assess remaining setup fingerprints, probe/backoff and observed-flake side files: remove unneeded behavior first;
put retained authoritative runtime state in factory.db. Keep complete diagnostic logs/transcripts and artifact files
behind their readers under the accepted retention policy. The owner's mention of local log files did not clearly
revoke that prior agreement; it must not be used to delete retained conversations.

This document records the design review; task tracking stays in the tracker. Canonical terms are in
[the glossary](../../glossary.md).


## Concrete lifecycle follow-up, 2026-11-09

See [workspace lifecycle](lifecycle.md) for the Astra-reviewed source paths, typed outcomes, proposed removal of
allocation-lock setup/duplicate retries/fingerprint stamps, explicit quiescence before release, and two remaining
owner choices. Owner accepted shared local DB authority and repeatable repository setup on 2026-11-09. Those defaults are settled;
STORE remains held pending the consolidated identity/state review.
