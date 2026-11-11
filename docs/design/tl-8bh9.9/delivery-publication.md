# Delivery, publication and task completion

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Task: tl-8bh9.9, linked to tl-8bh9.3.2/.3.5 and existing tl-br2.8 SETTLE / tl-br2.19 ACCEPTDONE.
Source review and Astra consultation, 2026-11-09. Strategy accepted by Denis after the clarification below. No source changes,
Git operations, remote publication, real checks or task closure performed in this review.

## Three facts, not three new task statuses

| Fact | Required evidence |
|---|---|
| Published | The configured remote task branch contains the intended committed checkpoint, including its committed plan where applicable. |
| Landed / delivered | The accepted change is confirmed integrated into the configured target branch. A local merge or an open PR is insufficient. |
| Task completed | Required work is satisfied and the task service confirms completion. Delivery and task closure are separate external operations. |

Use the existing glossary word land for integration/delivery; do not invent another workflow step called publication.
Publication is a boundary operation. No slot path, session ID or execution-step ledger belongs in portable work tasks.
Task closure in one local task backend and successful cross-machine task synchronization are also distinct facts;
Git code publication does not synchronize task answers/status. Portability requires both published Git and synced tasks.

## Current source evidence

- `packages/kernel/src/tlkernel/branches.py` derives task/<task-id>.
- `packages/pipeline/src/tlpipeline/run.py` invokes Outbound.wip_push after an accepted old stage, before saving its
  checkpoint. `packages/land/src/tlland/push.py` commits/stages and pushes to the land remote using force-with-lease,
  because existing resume/land paths rebase. Thus remote implementation checkpoint publication already exists.
- `src/taskloop/app/run/parts_plan.py`, publish_plan, only writes local run-directory JSON. Its name does not mean
  the agreed Markdown plan has been committed or remotely published.
- `packages/land/src/tlland/push_judge.py`, judge, gates target-branch pushes, not ordinary non-target branch pushes.
  Obsolete special profile-change approval still affects policy reads; its deletion is already agreed separately.
- `packages/land/src/tlland/forge.py`, push, already pins a commit OID, uses a non-force push and checks the remote ref.
- `packages/land/src/tlland/rebase.py`, Commit.run, soft-resets and squashes the task's commits into one. Mandatory
  branch squashing is existing behavior; removing it is a new proposed cut, not implied owner approval.
- `packages/land/src/tlland/pr_land.py` distinguishes open/merged/closed PRs and stores the pending PR reference in task
  metadata. Its merged path fetches the merge result. Open currently becomes an owner ask; recommend a typed external
  wait for the retained merge policy rather than another clarification question.
- `packages/land/src/tlland/push.py`, Landed.already, inspects Git after an uncertain push; its current commit-title
  convention is coupled to one-commit/rebase behavior. Preserve observation of actual delivery, not that old coupling.
- `packages/pipeline/src/tlpipeline/closing_settle.py`, Settle.run, only warns when task closure fails. Existing SETTLE
  already tracks the discrepancy; reuse it rather than create another recovery or outbox service.

Static source paths establish behavior, not a tested proof of every crash/race case. Shared library capabilities and
actual task-service update/sync semantics still require verification through their owning interface work.

## Proposed publication boundaries

1. Planning produces a usable `docs/design/<task-id>/plan.md`, commits it on the deterministic task branch and publishes
   that commit before the workflow advances to implementation. A local JSON plan is not its portable replacement.
   Built for the plan step in [.4.3.1.12](../tl-8bh9.4.3.1.12/plan.md) (push only; land not built).
2. Every completed implementation/repair step commits intended changes and publishes its new tip before advancing
   through the workflow. Publish unvalidated task work: green checks/review gate target integration, not branch backup.
   Agent feedback about uncommitted files remains same-step continuation, not automatic blind stage_all by the factory.
3. Checks/review do not create commits or pushes merely to record runtime results. If their process discovers needed
   code/plan changes, return to the owning mutating step; the resulting checkpoint follows the same publication boundary.
4. Publish only when the task ref advanced. Linked worktrees already share local objects/refs: do not push into the root
   working checkout for stage exchange or reset its checked-out branch. Remote publication supplies the separate new-PC
   requirement. Use the configured repository remote, not a hard-coded GitHub account or a new intermediate repository.
5. No early draft PR is required. Create/update a PR when land begins in PR delivery mode. A branch already supplies
   portable plan/code progress before that point.
6. Keep append-only published task history: ordinary pushes and no automatic branch rebases or rewrite-squashing of
   the published task branch. Preserve the existing merge/plain-push/final-squash direction: merge target updates into
   task work when necessary, then squash the finished change into the target. A target squash creates a new commit
   without rewriting the task branch. Validate the actual integration result/context and retain its relationship to
   the assessed task tip. This does not require force pushes.

After cloning on another PC, fetch the task branch, read its plan and inspect current code through normal workflow.
No old DB, transcript or execution-history migration is required. The plan can describe already-implemented work;
normal evaluation finds what remains and checks/review can run again. A sudden lost machine can lose work since the
last confirmed remote checkpoint: this policy is not continuous backup of uncommitted edits.

## Publication failures and competing work

Pin the intended commit ID for a publication operation; do not push a moving HEAD. If acknowledgment is uncertain,
query/fetch the remote ref through the owning Git library before retrying. Equality confirms publication; a descendant
contains the checkpoint but requires reconciling newer work before continuing. An ancestor can be advanced by ordinary
push. A missing ref can be created when absence is confirmed. Divergence preserves both histories and stops automatic
overwrite; controlled merge/repair or owner choice resolves it. Failed observation is unknown, not an absent ref.

A network failure leaves local execution complete but publication pending. Preserve commits, retry the publication
operation under the agreed retry/wait policy and do not rerun the agent or consume semantic repair allowance to fix
transport. Do not advance to another mutating step merely by declaring pending work portable. Stopping the factory
must not depend on network success. Dirty or live/uncertain work remains protected against destructive reuse.
A clean committed checkpoint retained in shared Git can allow slot release after owned workers have stopped, even
while remote publication is pending; publication waits should not pin otherwise reusable capacity indefinitely.

## Proposed land and completion contract

| Situation | Behavior |
|---|---|
| Direct-push mode | Merge-only preparation and required validation/review, then conditional ordinary update of configured remote target; confirm delivery. |
| PR mode, auto | Publish assessed candidate, create/update the PR, request allowed merge and confirm the actual head/target/merge result. An accepted request alone is not delivery. |
| PR mode, wait | Keep task open and pending PR reference portable. Wait for merge through ordinary scheduling/forge observations; do not occupy a writer or workspace merely to poll. |
| PR closed unmerged | Not landed/completed. Retain branch and report explicit owner disposition needed; do not silently recreate/reopen it. |
| Target changed | Refresh merge-only candidate and validate changed context as required. Target movement alone is not semantic repair; real conflict resolution follows existing bounded repair. |
| Delivery result uncertain | Observe actual remote/forge state before another integration attempt. No claim of atomicity between network side effect and local DB update. |
| Landed, then task closure failed | Report landed, task completion pending. Retain the minimal pending settlement in existing execution state; intact-DB restart retries settlement without rerunning implementation/integration. |
| Already satisfied on target with no new change | Confirm acceptance through the normal retained workflow; complete with an explicit no-change disposition. Do not manufacture an empty commit/PR. |
| Task service unavailable | Do not claim confirmed task completion. Code delivery remains true if independently confirmed. |

Pending external operation identity/outcome belongs to existing local execution state, under the held STORE ownership
review; no separate ledger, event replay or new service. Retained Git/forge facts and task requirements support fresh-PC
normal evaluation after DB discard. Portable task metadata can keep a useful PR reference; derive branch names rather
than duplicating naming state. Local runtime records track attempts, waits and evidence; logs remain files behind readers.

## Owner choices, subsequently accepted

Approve publication after completed planning and mutating steps, retaining local work on publication failure.
Confirm append-only published task history and ordinary non-force pushes, while retaining final squash into the target.
The previous broad proposal against final squash was withdrawn: target squash and task-branch rewrite are distinct.
The published/landed/completed distinction and failure routing above are proposed as one coherent contract.
These choices do not unhold STORE, introduce a merge queue or change the already agreed required checks/review.

## Owner challenge and corrected contract, 2026-11-09

Denis confirmed that remote/network failure must not reroute land to implementation and asked for self-healing land
that completes all required actions without repeating successful work. He recalled the merge-plus-final-squash direction.
Source recheck confirms this note's parent already recorded merge-only/plain-push/final-squash; Forge defaults to squash.
The earlier broad no-final-squash recommendation was wrong. Astra and this review now distinguish target squash from
rewriting published branch commits. Publication timing remains a proposed choice, not an inferred new owner decision.

### One land operation, one completion condition

Land owns preparing integration, any validation/review required by changed inputs, publishing/integrating the accepted
candidate, completing the work task and any explicitly required task-data synchronization. These are internal actions,
not extra top-level steps or task statuses. Success means the accepted result is confirmed on the intended target,
the task service confirms completion, and any required synchronization confirms that completion propagated. An open PR,
a successful request submission or a local task write alone does not stand for those other facts. No-change completion
still requires the accepted explicit disposition that requirements are already satisfied on target.

Retain only necessary operation progress and external references in existing factory state. On retry/intact-DB restart,
query uncertain outcomes and perform missing actions. This is not an exactly-once transaction spanning Git and a task
service, nor a new outbox/ledger/recovery framework. Normal continuation must prevent duplicate integration/model work.

If merge succeeds and task closure times out, code delivery remains true but land is still finishing task completion.
Query task status first; if the intended closure already succeeded, continue, otherwise retry it when authorized.
If synchronization is required after closure, sync after that closure: a sync performed before closure cannot establish
that the later task status propagated. A nonzero closure result must reach operation status; warning-only success is
insufficient. Required safety cleanup must finish; ordinary nonblocking housekeeping is reported separately rather
than silently converting delivered work back into implementation.

Transient network/service errors use the shared retry/wait policy. Permanent permission denial or invalid task data
becomes an explicit blocked result with its actual reason. Lost claim/failed ownership condition is reconciled and
respected, not blindly retried or bypassed. No program can guarantee progress through permanent external denial.

### PR and branch failure cases without speculative infrastructure

Merging a PR normally closes it; independently closing it without merge rejects the change. In auto mode land requests
merge and verifies the actual result. Required remote checks/reviews, permissions, policy or uncertain responses can
leave the PR pending; continue the same operation later. Wait mode intentionally leaves merging to the configured actor.
No writer/slot is retained merely to poll. A closed-unmerged PR remains an explicit unmet delivery condition.

Claims should normally prevent competing task writers. The minimal guard for unexpected remote changes is ordinary
non-force push plus Git ancestry after a relevant refusal, not a distributed branch-monitoring subsystem. A remote
ancestor can be advanced; a remote descendant already contains our checkpoint but needs newer-work reconciliation;
neither ancestor relationship means unique commits on both sides. Preserve both and use existing merge/conflict handling
when needed. Do not classify permission/network failures as divergence, and do not return every divergence to a model
when ordinary nonconflicting Git integration suffices.

### Dashboard presentation

Expose the same existing operation state through shared CLI/dashboard routines: Land -> prepare integration -> validate
if changed -> push/merge -> complete task -> required sync. Show actual running/waiting/blocked action and its reason.
For the partial-success case show code delivered, task completion pending; never show overall successful land while a
required action is unresolved. Do not derive this state from log text or add a separate monitoring/status authority.

## Owner approval and structured contracts, 2026-11-09

Denis: "Yes, I agree. Record that strategy, including merge plus squash and retrying only unfinished actions."
The corrected strategy above is agreed, including completed plan/mutating-step publication, ordinary task-branch pushes,
final squash into the target, and one resumable land operation that retries only missing required actions.

Every application/library interchange uses explicit typed inputs and results; process/API boundaries use validated
structured representations such as JSON where supported. In-process Python calls pass typed values, without needless
JSON round trips. Status, reason, operation/task/attempt identity and relevant external refs are data, not phrases to
recognize. Presentation renders those facts; "code delivered, finishing task completion" is never a control protocol.
Prefer native APIs, structured CLI output and documented machine-readable Git formats. Necessary text parsing belongs
in the owning adapter/library with narrow contracts/tests; unknown output remains an explicit unknown/error and never
silently falls back to regex-derived success. This is not a universal message bus, new schema service or ban on useful
regex for genuine text matching unrelated to control state.

An open PR can intentionally await human review before merge. Preserve that useful review surface and explicit pending
reason. This does not enable the separately parked strict/fast review modes or add an unconditional new human gate.
CLI/dashboard render the same typed operation state and use the same application routines.
