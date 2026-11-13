# Repository binding, lifecycle and STORE ownership

Status: **design**. Accepted identity/lifecycle contract and retained scope, not completion of every listed owner.
See the [index](../INDEX.md) for built slices and the current [README](../../../README.md) for commands.

Task: tl-8bh9.1, existing REPOID tl-sqd3.18 and STORE tl-sqd3.26. Reviewed with Astra, 2026-11-09.
Owner accepted this contract and explicitly lifted STORE's design hold for reconciled scope only on 2026-11-09.
See [corrected STORE scope](../tl-sqd3.26/plan.md); old migration slices are not authorized as formerly written.
No source/schema/Git/process changes or implementation tests were performed.

## One picture, no extra workspace entity

| Concept | Meaning / lifetime |
|---|---|
| Work task | Requirements and acceptance in a configured task-service backlog. Outlives local executions and machines. |
| Task branch | Derived task/<task-id> reference to committed plan/code in the selected local Git repository. Not a directory, lock or session. |
| Git worktree | Physical checkout with files, index and HEAD; linked worktrees share repository objects/refs. |
| Slot | A configured reusable managed worktree plus local reservation/readiness state. Not a portable tracker task or an agent. |
| Working directory | The directory given to an execution, normally the selected worktree. External APIs may call it workspace; do not create another factory entity with that name. |
| Step / attempt / session | Workflow operation / actual execution try / agent conversation. Actual executing attempt uses a reserved worktree; different steps can use different slots. |

The person's primary checkout remains theirs. The factory manages its own slots/worktrees through the shared Git API;
it never resets or detaches the person's checkout to make a task branch available. The already approved one-authority
rule applies to processes sharing a managed pool; a SQLite row does not replace actual lifetime exclusion.

## Correlated lifecycle

| Event | Task and Git | Slot / runtime |
|---|---|---|
| Admission | Read approved, dependency-ready task and obtain its real task-service claim. Resolve/fetch deterministic branch rather than overwriting existing work. | Short local reservation; failed claim releases only this reservation. External IO is outside allocation transaction. |
| Preparation | Check out the task branch; create from configured target only when no existing task branch needs continuation. Keep published/local committed progress. | Confirm exclusive ownership/stopped previous workers, then run approved repeatable repo setup. Preserve warm build files; no blind cleanup. |
| Planning | Commit docs/design/<task-id>/plan.md and publish checkpoint. | Local step/attempt/result/session references in factory state; task intent remains in task service. |
| Implementation / repair | Commit intended changes and publish updated task branch. Branch need not be green to be published. | Uncommitted completion returns to same step for commit/remove/ask. Network publication failure retries transport, not implementation. |
| Checks / review | Complete candidate-bound validation/review against pinned code and required inputs. | Keep actual outcomes/evidence refs. Completed validation does not require occupying its physical worktree forever. |
| Pause / clean release / handoff | Keep task branch and commits reachable. A pending publication still prevents advancing that task past its publication boundary. | After confirmed worker stop and clean intended work, detach this managed slot at current HEAD and release matching generation. Do not reset to target, delete branches or erase ignored files during release. |
| Next step / resume | Use the same task branch in an available slot. Same unfinished live execution/session retains its original association until reconciled. | Preparation checks actual state and runs repo setup. A branch is not checked out in two linked worktrees concurrently; admission also prevents competing task writers. |
| Land | Merge target updates when necessary, validate changed candidate/context, final squash into configured target and confirm actual delivery. Published task branch is not rewritten. | Resume one land operation and retry only unfinished required actions. Remote/PR waits need no occupied writer/slot. |
| Completion | Task service confirms completion, then required task sync. Code delivered but closure pending is not successful overall land. | Keep minimal pending settlement/control locally. No DB/log reconstruction on a fresh PC. |
| Later cleanup | Branch/worktree deletion is separate housekeeping, conditioned on confirmed delivery/completion and preservation of required plan/code references. | Ordinary release never deletes a branch. Recheck actual ownership/ref identity before any deletion; cleanup policy belongs to its review. |

Dirty, conflicted or liveness-unknown work is protected, not detached/reset for another task. Unrecorded worktrees after
DB discard require inspection/adoption, not automatic ownership by naming convention. No automatic WIP commit of
unexplained edits, foreign-worktree removal or stale-branch replacement is part of normal recovery.

### Completed validation versus unfinished execution

Correct the earlier overbroad custody wording: a completed check result belongs to the exact assessed candidate and
current workflow. Clean release, detaching HEAD, or review in another slot does not erase that result. Revalidate when
candidate, required policy or relevant validation inputs change, or when completion/identity was never established.
An interrupted execution still needs liveness/custody reconciliation before continuation/relaunch. Recording the setup/
executor used is provenance, not a requirement to keep that directory occupied. No arbitrary historical pass lookup or
cross-candidate carry is restored by this rule. This resolves the otherwise contradictory repeated checks on every slot handoff.

## Accepted repository identity contract

Resolve one local repository binding through the owning Git library and pass it to consumers. Its RepoId is scoped to
canonical Git common-directory identity; exact opaque key/hash encoding is implementation detail. Named projections
provide storage key, common Git directory, registered checkout path and display information. They do not rediscover
identity independently. No source module parses .git/config or commondir as a competing authority.

- Linked worktrees share RepoId; symlink spellings resolve consistently.
- Independent clones have different local RepoIds even with the same remote. Moving a checkout may require explicit
  re-registration/new local binding; no portable path identity or rename-recovery framework is needed.
- Changing origin does not change local repository identity. A missing origin is not missing local identity; publication
  requiring an unconfigured remote fails explicitly rather than inventing one.
- Remote host/project is explicit delivery/display data. owner/name alone is not globally unique and cannot key storage.
- A task reference is scoped by its configured adapter/backlog namespace, not a Git URL guessed by factory. The adapter
  supplies/validates that namespace; task/<id> is scoped by its selected local repo. No universal forge-ID/UUID registry.
- Unavailable/invalid binding discovery is a typed refusal, not fallback to whichever caller path was supplied.

Accepted scope: independent clones can be registered/inspected, but one execution binding per backlog is enabled
within the shared local factory authority. Parallel work uses linked slots of that binding. This follows the recorded
one-primary-checkout direction without building cross-clone scheduling. Switching the enabled binding requires no active
or unresolved executions for that backlog. Do not claim atomic cross-PC exclusion from separately synced task databases.

Current code evidence: ids.loop_key hashes real checkout path; check_files.repo_key derives from common-dir parent and
falls back to caller path; reponame privately reads Git files and drops forge host; ReposStore keys registrations by that
display name and rejects collisions/another clone. Reconcile these through the one binding rather than layering aliases.

## STORE means retained runtime ownership, not a wholesale SQLite migration

Current RunRows already uses short transactions and writes manifest/indexed projections together; current runtime has
DB-owned lock/worktree/checkpoint/wait rows. Preserve useful behavior and remove stale moves from task scope. A typed
record plus indexed columns updated by the same owner/transaction are not competing facts merely because values repeat.
Conversely, real_stores still gives check rounds a JsonStore and current attempt rows represent coordinator take-up,
not all actual operation attempts. Those remaining boundaries need concrete reconciliation.

| Authority | Retained responsibility |
|---|---|
| Task adapter/service | Requirements, dependencies, approval/holds, real work claims, portable linked questions/responses. |
| Git library/repository | Committed plans/code, refs and integration results. |
| factory.db through narrow owning stores | Resolved local bindings/provenance; slot reservations/generations; step/actual attempt/session/execution associations; limits/usage; next operation/reason; current validation completion; required waits/response incorporation; pending publication/delivery/settlement/owner controls. |
| Log/transcript/artifact readers | Raw diagnostic/conversation/media bytes, retained by age. Never fallback runtime authority. |
| Shared mechanism libraries | Real process exclusion/cancellation/liveness, resource permits and SQLite primitives, with their real/fake contract tests. |

One store owner/API per fact and short atomic local transitions; not one giant store class or another central kernel.
CLI/dashboard consume that same typed authority. Update local intent/ownership before an external side effect and
reconcile uncertain outcomes before repetition; no external process/network/agent work inside a SQLite transaction.
No transaction can atomically commit both SQLite and Git/forge/task-service side effects. Persist only the progress
needed for intact-DB continuation, not an execution-event ledger reconstructed from logs.

Factory DB unavailable/corrupt/schema-unusable means explicit refusal to admit/alter work, not empty-state success,
a file fallback or automatic deletion. Controlled discard stops admission and establishes worker safety, then normal
workflow restarts from Git plus synced tasks. No factory backup/restore, old-shape reader, historical replay or importer.

## Existing STORE task reconciliation required before admission

The old sqlite-store-plan.md prescribes dual readers/import/export, compatibility periods and factory real-process
kill tests. STORE .26.5 names old slot-ticket/file migration paths; .26.8 waits a release before removing old readers;
.26.2 still names retired storm behavior despite superseding notes. These are historical scope, not successor requirements.

Before release of the implementation hold, revise affected existing slices to retained behavior and dependencies;
mark already delivered portions only after verifying them; remove obsolete migration/compatibility acceptance. Do not
close held work solely because design is agreed. Replace generic "one current attempt and every pending effect" with
specific single-writer, stale-holder, actual-attempt and unfinished-action invariants (internal checks may run concurrently).
Factory tests use owning-library fakes for meaningful transition/interruption cases; real SQLite/process/Git mechanisms
are verified by their owning library contracts. Existing just check / just test remain gates, no full/live suite.

## Owner decision recorded

Denis accepted the local binding/task-backlog scope, one enabled execution binding per backlog and correlated
lifecycle/release policy, then authorized reconciliation and release of corrected STORE scope. Existing parent/children
now reflect that contract; prerequisites still gate their actual dependents. Historical migration scope is superseded.
Table names/key encoding/module layout are implementation decisions. Source construction still follows the agreed
implementation/cutover scope; no source implementation was started in this review.

Concrete capability checks remain implementation prerequisites: survivor-safe library exclusion/cancellation and typed
unknown liveness, task-adapter namespace and conditional-claim semantics, and narrow atomic-store interfaces. File these
as specific missing contracts if verified absent; do not design a new supervisor, global ID service or distributed lock.
