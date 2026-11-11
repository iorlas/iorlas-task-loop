# Owner and agent workflows

Review under tl-8bh9.7, 2026-11-08. Design only. Current code names below are quoted literally; target vocabulary
is task, step and attempt. This records actual behavior separately from proposed simplifications.

## Recent history followed by live activity

Owner requirement: open task -> step -> attempt, see the latest ten executed actions/messages immediately, then
receive new activity while that view is open. This is the recent-history plus live-tail pattern, implemented through
a cursor: the initial response establishes the position from which subsequent updates continue.

Retain full available history and conversation behind readers, accessible on demand. Ten visible items is a UI
window, not permission to discard transcript content. Logical actions/messages are not necessarily ten raw stream
fragments. Commands and tool actions should retain available status/output/detail rather than become a lossy summary.
Use the same normalized agent interface for retained and live activity; no private harness parsing in the dashboard.
Workflow state remains in factory.db, independent of whether evidence is retained or readable.

Checked current implementation:

- drawer.js Terminal already keeps ten lines; ui/stage.js limits an active attempt's displayed lines to ten.
- /api/live selects the task's newest logged run, not a supplied step/attempt. It also depends on dbruns/index health.
- LiveRun reads source history into memory before selecting a page. Initial page defaults to 300 events, although
  the terminal retains ten. A bounded display alone does not establish bounded reading or payload size.
- Existing opaque cursors and explicit reset/gap indications are useful. Cursor attempt identity currently follows
  engine process take-up, which differs from the agreed operation-attempt model.

tl-8bh9.7.4 owns this requirement, coordinated with ATTEMPT-LINK and shared conversation readers. No new event bus,
telemetry store or state-reconstruction index is requested. Choose a specific attempt; do not silently move a reader
to the newest attempt as another starts. Initial snapshot and live continuation must not leave a gap or duplicate
actions. Session reuse across attempts must not mix their activity; explicit retained attribution is required.
Handle unavailable/expired evidence honestly. Stop live updating when the view closes. Existing long polling can
satisfy the interaction; no transport replacement is justified by this requirement alone.

## Current end-to-end interactions

| User intent | Current shared operation and writes | Engine/agent effect | Proposed direction |
|---|---|---|---|
| Answer a question or choose an option | Writes.answer -> answer port -> Intake.answer; AskStore answer, task reopen attempt and receipt comment. | Makes work eligible; existing answer handling supplies continuation. | Existing PORTABLE-ASKS design replaces one-current-ask behavior with linked portable questions/responses and deliberate grouped submission. Agent receives relevant submitted responses and incorporates requirements before acknowledgment. |
| Ask for clarification | Browser infers ask-back from final question mark; Intake.ask_back adds thread entry. | Request stays open; no automatic helper answers it in this path. | Ordinary response text must not be classified by punctuation. Preserve explicit Send-to-agent and outstanding questions without a special user-administered state machine. |
| Add an instruction during execution | OwnerVerbs.note posts SignalRows plus task receipt; with no run, stores a task hint. | At step boundary, OwnerRequests takes signals and appends notes to next worker prompt and delta. | Say when the instruction will be delivered. Persist necessary pending incorporation through normal intact-DB restart; no history replay. |
| Pause work after current step | OwnerVerbs.park posts local park request and sets task hold. | At next step boundary engine moves to pause; branch/checkpoint retained. | Say requested/accepted until state confirms pause. Portable hold is work intent; pending run signal is local state. |
| Stop current execution | OwnerVerbs.stop posts stop request and sets task hold. | Beat observes stop, sets halt; step boundary/worker cancellation path applies it. | Say stopping until confirmed. Preserve code and actual process/slot occupancy; do not report freed capacity before it is true. |
| Inspect screenshots and approve/redo | Look port -> Intake.look -> look rows/task changes. Owner-look producer says it is filed after landing. | Good settles review item; redo creates a follow-up task carrying note/screenshots. | Owner chose removal of this dedicated story; future strict/fast design is parked. See decision below. |
| Turn an answer into a lasting decision | stick/prune route through Intake and decision/task helpers. | Can file work for ADR/task text or retire a decision. | Existing human-input design keeps ADR promotion optional. Reuse ordinary decision/task workflows; do not require a special promotion flow for every answer. |
| Mark seen or record failure cause | ack/cause store task metadata and receipt; cause may correct ask record too. | Affects stuck presentation/diagnostic classification. | Optional product features to justify, not prerequisites for answering, stopping or continuing. Host-local acknowledgment should not become portable requirements clutter. |

Dashboard and CLI already share Intake and OwnerVerbs for several operations. Preserve that reuse. The dashboard
should validate/translate the request and render the result; it should not acquire a parallel engine workflow.
Agent-side interaction is through the same workflow: raise a request, wait without polling a model, receive relevant
response context once eligible, update the plan/requirements and continue under ordinary checks/review gates.
Approval and clarification are not interchangeable outcomes, even when their presentation shares one component.

## Correctness gaps and deletion candidates

tl-8bh9.7.5 owns the bounded owner-command review. Current observations:

- Browser holds an answer five seconds for undo, but submitting another flushes the first immediately. This conflicts
  with the agreed deliberate grouped Send-to-agent design; remove auto-flush/timer-as-submission behavior there.
- stop toast claims stopped and park toast claims the slot is freed. Backends return after posting the request,
  before the engine necessarily applies it. Keep accepted and applied distinct in meaning, without making users
  administer another workflow.
- OwnerVerbs can post a signal before task hold/comment work fails. A generic error saying nothing changed can be
  inaccurate. Acknowledge actual effects and keep retry behavior bounded; no distributed transaction framework.
- OwnerRequests.take marks signals taken, buffers notes in process, then prompt_tail clears that buffer before
  worker.run. Inspect a crash in that interval against same-step/session restart. A task receipt may preserve the
  words, but this path alone does not prove automatic redelivery/incorporation after restart.
- Optional command receipts compare only verb/project/task/run, omitting note text, cause or ack value. Current
  browser action helpers send no key. If retained, bind the full semantic request and wire caller identity correctly;
  do not preserve an unused partial mechanism solely because it already exists.
- Receipt is saved after dispatch, with a process-local lock. It does not establish atomic exactly-once effects across
  service writes and a crash. Source comments promising that should be narrowed to guarantees actually implemented.
- Current visual UI claims approval is landing and redo returns to write. Source producer/handler instead describe
  post-land review and follow-up creation. Do not change this product behavior on the strength of a toast alone.
- OwnerVerbs.newest_run filters by log presence and task ID without repository in its own signature. Retain scoped
  repository/task/execution validation and make CLI selection explicit; do not let evidence presence choose identity.

Keep meaningful stale-target checks, bounded waits and HTTP origin/body protections. Removing these is not the
simplification being proposed. Avoid new command journals, generic recovery orchestrators or duplicate fake layers.
Use existing task and execution state owners to record the minimum needed for truthful continuation.

## Verification

Read dashboard writes/looks/liveview and browser actions/api/drawer/stage; launch/dash_ports; asks Intake,
OwnerVerbs, ask_verbs and looks; pipeline OwnerRequests; kernel SignalRows, request records and receipts; run host
prompt insertion. Read selected existing test definitions but ran no behavior tests or real services.
These are source-path findings, not reproduced production failures. Eventual tests should exercise actual request
outcomes, restart boundaries and reader cursors with shared fakes, followed by just check and just test.

## Owner decision: remove visual-only review, defer mode design

Owner answered on 2026-11-08: current visual-only review may be parked and all code specific to that story removed.
This supersedes the earlier recommendation to retain post-land visual review by default. Removal work is
tl-8bh9.5.4. Retain general artifacts/gallery/evidence, screenshot-bearing questions, ordinary acceptance/code review,
mandatory checks and the recent-history/live-tail interaction. Inventory shared callers before deleting a helper.
OwnerLook also gathers unverified nonvisual facts; map those consumers rather than silently lose required context.
Existing user tasks and retained evidence are not automatically closed or deleted as part of removing source support.

Future redesign is held/deferred in tl-8bh9.12 with spike tl-8bh9.12.1. The owner's two candidate modes are:

- Strict factory: review code and result before landing; a required human review belongs before landing.
- Fast factory: continue delivery, review afterward and create change requests.

These are design directions, not implemented modes or an approved default. The spike must settle when automated
review suffices, when owner input is required, and how rejection/continuation works without two parallel pipelines.
No current mandatory code review or checks are removed merely because future fast mode is being explored.

Owner also reinforced one application routine per operation across CLI/dashboard/agent consumers. Existing workflow
similarities should guide reuse. Interface-specific presentation and validation can differ; speculative performance
optimization is not a reason to copy domain actions. Introduce a separate read projection only for a demonstrated need.


## Correlated owner walkthrough, 2026-11-09

The [interaction contract](interaction-contract.md) rechecks the shared operations and duplicate readers against the
accepted actual-attempt, structured-result and local-lifecycle model. It identifies missing dashboard resume, durable
input handoff, exact-content artifact refs and misleading control acknowledgments. A narrow new proposal remains for
stopping during land: reconcile issued actions, defer new settlement effects until resume. Owner choice is still pending.


Manual-control reassessment, 2026-11-09: the owner reopened the need for Stop/Resume. Astra now recommends initial
Pause/Continue through hold/unhold, no separate execution-resume/start-over modes, and deferring immediate Stop.
See the final section of [interaction contract](interaction-contract.md). This recommendation awaits selection; the
earlier stop-during-land question is deferred with that feature rather than awaiting a separate answer.


Owner accepted minimal controls 2026-11-09: Pause/Continue = shared hold/unhold, defer immediate Stop and omit separate
manual resume/restart modes. Automatic crash continuation and infrastructure cancellation remain required. This decision
supersedes the previous pending-control-surface note above; immediate-stop policy is not part of the initial product.
