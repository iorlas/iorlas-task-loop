# Architecture review: discussion roadmap

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9. Roadmap accepted by Denis, 2026-11-09, after Astra consultation.
This document organizes the design discussion and its evidence. Work status, ownership and dependencies remain in
the task tracker. It does not approve outstanding proposals or admit held implementation.

## Destination

Reduce the existing product to the behavior its owner wants, with one owner per fact and one shared application
operation per workflow. Reuse proven mechanisms and contracts, remove unnecessary behavior, and move reusable
mechanisms to shelf where justified. This is assessment of an existing product, not permission to invent a new one.

Finish with a dependency-ordered implementation backlog that an agent can execute without reconstructing the chat.
Ticket count is not a target. Reuse existing tasks; do not file one task per helper or retain a feature merely because
its code exists. Agreed behavior, current source behavior and proposed cuts must remain distinguishable.

## One discussion cycle

1. Start from a concrete owner/agent workflow and show a small current behavior/ownership map.
2. Trace its real entry points, callers and IO. Identify duplicate policy, state, reads and mechanisms.
3. Present a small keep/merge/remove/shelf menu with purpose, cost, recommendation and actual behavior changes.
4. Ask Astra to challenge assumptions and realistic failure cases; verify important source claims directly.
5. Ask the owner only for meaningful behavior choices. Record exact agreed rules and expected outcomes; do not
   silently turn Astra's recommendation into owner approval.
6. Reconcile the owning tasks: retained behavior, expected deletions, prerequisites, focused verification and explicit
   holds. Detail source layout/schema only when necessary for a boundary decision or implementation readiness.

Test each proposed boundary against normal success, failure, owner intervention, intact-DB restart, discarded DB/new
PC and relevant contention. These are design scenarios and later focused tests, not a new runtime simulation system.
Stop discussing a topic when no product/ownership question blocks its next bounded implementation slice. Ordinary
implementation choices remain with the implementer; deep questions get a specific spike rather than endless discussion.

## Discussion sequence (reviewed; historical questions below)

Final reconciliation: [coverage, successor mappings and implementation order](coverage.md). The table records the
questions that organized the review; it no longer represents an outstanding discussion queue. Contracts linked in
the topic plans and the final coverage report supersede its historical unresolved/held wording.

| Conversation | Questions to settle | Existing owners / output |
|---|---|---|
| Checks decision recorded | Owner approved historical-cache/carry and request-machinery retirement with current completion evidence and repository affected testing retained. | tl-8bh9.5.1 and .5.2; authoritative contract in candidate-checks.md. Source implementation remains pending. |
| Git delivery and portable progress | When are plans/code committed and task branches published? Which operation owns merge, target refresh, delivery and task closure? What remains recoverable after a fresh clone? | tl-8bh9.9, .3.2, .3.5, .5; reuse SETTLE/ACCEPTDONE. One end-to-end task-branch map and side-effect boundaries. |
| Workspace lifecycle, repository identity and runtime ownership | Walk preparation/setup failure, claim, running work, surviving workers, interruption, reuse and cleanup before choosing persisted facts. Resolve actual clone/repository bindings and deployment scope for claims, exclusion and fencing. | tl-8bh9.1, .2, .3.1/.3.4; existing REPOID and held STORE. Responsibility/entity map and necessary owner decisions before dependent implementation. |
| Agent and task interfaces | Finish unresolved library capabilities for structured results, continuation, cancellation, status, limits and usage; confirm task-service discussion/claims contract supports actual workflows. | tl-8bh9.4 and .6.1; existing agent/asks designs. Narrow shared contracts, not another service or retry framework. |
| Owner experience and evidence | Walk start/observe/question/answer/pause/stop/resume/deliver through CLI and dashboard. Ensure task -> step -> attempt -> session/output/artifact links and last-ten-plus-live behavior. Resolve retained-log ownership/retention and authoritative dashboard fields. | tl-8bh9.7 and artifacts/asks work. One interaction map, one state reader per fact; no log-fold fallback. |
| Distribution, development and tests | Inspect release/install/vendor/pin/doctor/prune/hooks, dev tools and test support. Which operations remain useful, which are obsolete migrations/scaffolding, which belong to shelf? | tl-8bh9.8, shared testkit work and .4 boundary tasks. Small installation/release contract and fake-backed verification ownership. |
| Reconcile and admit work | Check coverage, stale tasks, conflicting old acceptance, dependency order and cutover evidence. Identify slices ready for execution versus explicit holds. | tl-8bh9 and .8.2. Executable backlog plus a clear unassessed/deferred boundary. |

Several conversations build on substantial earlier review; do not reopen settled terminology, scheduling or state/log
rules without a concrete contradiction. Correction, 2026-11-09: Git publication and runtime STORE ownership have now
been decided; the corrected STORE slices are unheld with explicit prerequisites. Their earlier unresolved state is
recorded in the historical table. Implementation order follows coverage.md and actual contract dependencies.

## Coverage map for the final source pass

This assigns source to discussions; it is not a claim that every file has already been reviewed.

| Existing area | Review responsibility |
|---|---|
| packages/pipeline, packages/work; app/run, loop, workers, reconcile, track | Workflow, admission, completion, retries, restart and shared application operations. |
| packages/kernel; src/taskloop/stores, domain | Repository identity, local state/entity relationships, ownership and ports. Assess actual responsibilities rather than copying the central kernel wholesale. |
| packages/slots, packages/areas | Workspace/resource safety and deletion of agreed areas scheduling. |
| packages/gate, packages/land; app/checks, launch | Check execution, integration, delivery, evidence and closure. |
| packages/delegate; process/Git/lock adapters | One shelf-owned agent interface and necessary external mechanisms/fakes. Factory policy remains in factory. |
| packages/asks | Portable work questions/responses and local continuation through the task-service contract. |
| packages/artifacts, packages/dash; app/report | Evidence publication/readers and owner interaction; state versus logs. |
| packages/release; app/doctor, prune; dev, skills/task-loop, hook | Distribution, installation, maintenance, development surface and removal of obsolete migration tools. |
| packages/testkit, tests/support and slice/rule tests | Reusable fakes, retained behavior and architecture checks. Real subprocess/Git mechanisms tested by their libraries. |
| src/taskloop/cli, app/wire, adapters | Adapter-by-adapter assessment recorded in tl-8bh9.4.6/plan.md: actual callers, purpose/cost, dispositions and seven workflow traces. Cross-cutting transport/composition pass: no duplicate application workflow or hidden IO owner. |
| Docs, prompts and instruction files | Final glossary adoption and removal of obsolete behavior instructions; agreed design versus executable task scope. |

## Readiness and stop conditions

Each implementation slice identifies retained observable behavior, its owner, actual consumers, superseded code to
remove, prerequisites and focused acceptance/failure checks. Do not require an exhaustive future schema or a test
for every private function. Shared files and library dependencies determine safe implementation order.

The review is ready to hand off when each current source area is assessed or explicitly unassessed with a reason;
agreed slices have coherent prerequisites; unresolved decisions gate only their actual dependents; and the retained
workflow can be demonstrated through its complete owner/agent path. The old reference remains in Git history,
not in successor runtime fallbacks. Existing curated replacement strategy still governs any later source construction.

No new implementation, release, full/live suite, Git operation, DB migration or held work is authorized by this roadmap.
Do not initiate FILEVERB, speculative merge queue, strict/fast review modes or immediate Stop while their holds remain.
Corrected STORE slices have no blanket design hold; old migration/compatibility scope is excluded.

## Astra challenge and roadmap consistency

Astra supports the order with two refinements: workspace lifecycle precedes schema details, and shared-agent capability
verification precedes claiming intact-DB continuation is implementable. State direction and narrow interface evidence
can be reviewed together. Reuse failure cases in the historical slot-grant design without inheriting its waiter,
watchdog or file/DB parity proposals as requirements of the successor.

The older [2026-11-06 roadmap](../roadmap.md) is superseded as an execution ordering document: it starts STORE and
layout migration and postpones architecture review. Current owner holds and simplification decisions take precedence.
Its historical issue references remain evidence for backlog reconciliation, not ready-work authorization.
Correction, 2026-11-09: release/pruning/bootstrap and the skill/hook surface subsequently received the operations
review in ../tl-8bh9.8/operations.md. Fixed running version and lightweight skill purpose are accepted; reduced
release publication and final hook-retirement scope remain proposals. Individual dev tools and current shelf
guarantees still need verification. See coverage.md for the exact limits; no exhaustive audit is claimed.
