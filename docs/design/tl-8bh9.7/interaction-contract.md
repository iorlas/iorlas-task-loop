# Owner controls and evidence: one walkthrough

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

Task: tl-8bh9.7, existing .7.1-.7.5 plus EVIDENCE-READERS .7.6. Review with Astra, 2026-11-09.
This applies agreed typed ownership, portable asks and lifecycle rules. The owner reopened the manual control surface
on 2026-11-09, then accepted initial Pause/Continue through hold/unhold and deferral of immediate Stop.
The earlier stop-during-land proposal below is deferred with the immediate Stop feature, not an outstanding narrow choice. No source/runtime/Git operations or implementation tests performed.

## One path for actions and one owner for each read

CLI and dashboard already share Intake and OwnerVerbs. Preserve them as application operations with typed results;
transport validates/translates and presentation renders. The engine applies retained intent through the same runtime
owner. Do not build another owner-control service, command queue framework or event journal.

| Owner action | Contract / observed gap |
|---|---|
| Open a task | Show task-service requirements and authoritative local operation/step/attempt progress, including exact reason for waiting. Missing evidence does not make valid runtime state disappear. Current runprojection depends on log-index freshness and some views require has_log; replace only after retained fields have direct owners. |
| Select an attempt | Pin actual task/step/attempt identity, session/execution refs and usage breakdown. Initial latest ten logical actions/messages plus opaque continuation cursor; expand details/history on demand. Current /api/live follows newest logged run, not supplied attempt. Never silently jump to a new attempt. |
| Inspect conversation | One shared-agent reader normalizes retained/live conversation; attempts sharing a session retain their own execution/segment attribution. Dashboard never parses private harness storage. Keep all available content behind the reader; ten visible items is not retention. Unavailable/expired history is explicit. |
| Inspect artifact | Artifact owner lists/serves a typed reference for actual attempt and exact registered bytes. Bytes stay outside the slot and DB. Current dashboard repeats sidecar traversal/file-serving rules, and its validity rules differ from store.listing; consolidate preserving the stricter relevant checks. |
| Answer questions | Draft independent responses and explicitly Send to agent. Support options by stable ID, free text, media, partial submission, clarification and corrections. Persist response/question links and report individual saved/failed items. Current timer/second-answer flush and punctuation classification are removed under the approved portable-asks design. |
| Pause task | Persist owner hold/intention, finish current step, then stop advancement. Report pausing until boundary applied. If land is current, pause-after-step allows that entire land step to finish. Clean committed slot release follows ordinary lifecycle; do not claim freed before it occurs. |
| Stop execution | Persist stop intent and fence new action admission, cancel owned execution and reconcile actual liveness. Report stopping until confirmed. Protect dirty/live/uncertain work and preserve committed refs. Already-issued/admitted external effects may complete despite cancellation; observe their actual result. |
| Resume task | Use the shared application operation to remove only the owner pause/stop hold, then re-evaluate dependencies, approval, questions, limits, claims and unfinished execution. Current CLI hold --release exists, but dashboard WRITES has no resume. Resume can make work eligible/waiting; it does not mean a worker already started. |

Intentional owner pause/stop survives intact-DB restart; crash restart must not undo a deliberate hold. An answer saved
while stopped remains saved without resuming. A completed task is not reopened by response arrival or resume; deliberate
new/reopened work is a separate explicit task action.

## Scope and acknowledgments

A task pause/resume changes work intent; an execution-specific cancellation names the actual attempt the owner observed.
Retain current identity checks and use task scope/RepoId from their owning binding. A stale execution target is refused
or reported already ended, never silently redirected to a newer attempt. Task-level action is explicit, not inferred
from whichever historical attempt drawer happens to be open.

Use existing pending-operation state to distinguish accepted (durably recorded intent), applying/waiting, applied and
refused/blocked. Report actual partial effects and current reason; a network error after local cancellation or task hold
is not evidence that nothing changed. Admission and control intent are serialized locally; already admitted/in-flight
external effects are reconciled, not promised reversible. No DB/network transaction is implied.

Current Writes.receipted dispatches before saving its receipt and fingerprints only verb/project/task/run. Browser action
helpers supply no key. Correct the existing mechanism: full semantic payload and target/revision identity, durable intent
before effects, same-request retry/reconciliation rather than blind repetition. Do not promise exactly-once external
side effects. Do not add a second receipt/state authority or retain an unused partial idempotency branch as protection.

## Delivery of owner input

Current SignalRows.take marks notes consumed, OwnerRequests keeps them in memory, then prompt_tail clears them before
worker dispatch. This is a crash window: consumed is not incorporated. Retain submitted input references and the receiving
execution/input revision until durable handoff is established. Same-session continuation uses the retained input; a new
actual execution creates an attempt under normal admission. Receipt prose/logs are evidence, not redelivery state.

Portable responses belong to their question in task-associated discussion. Keep local dispatch/incorporated revision
only in runtime state. If transport fails after saving, query identified response state before repeating missing writes.
A later correction remains outstanding even if an older execution finishes. An explicit partial Send can request further
clarification; it does not waive unanswered blocking requirements or force implementation to proceed. No AI polling.

## Earlier stop-during-land proposal: deferred with immediate Stop

Recommendation: after stop, observe/record results of already-issued external actions and perform necessary process/
resource cleanup, but issue no new publication, merge or task-closure action until resume. Stop fences new admission;
already admitted actions are canceled where possible and reconciled without pretending the remote side effect is atomic
with the local stop. Do not undo delivered code or repeat a known merge.

Example: remote squash merge succeeds while stop is being applied. Show code delivered, owner-stopped, task completion
pending when those are the facts. Land remains unfinished. Resume re-evaluates admission and finishes only remaining
closure/synchronization. Pause-after-current-step differs: it allows land to finish because land is the current step.
This boundary is proposed, not inferred owner approval.

## Exact artifact references, not mutable filenames

store.add currently replaces the same name and records a SHA-256 in ArtifactMeta. Dashboard Item/URL retains the name
and legacy stage-attempt coordinates but omits content identity. Thus an earlier question can show changed bytes at the
same URL. Bind a reference to actual attempt and registered content identity/hash. Serve those bytes or explicit
unavailable/changed; preserving every past version is not required. No new blob DB, global index or immutable-store service.

Use one artifact read/list/serve contract, including registered-file/metadata agreement, path/symlink/type restrictions
and truthful availability. Dashboard currently performs some validity checks the package reader lacks; do not replace
its code by a weaker call blindly. Registration returns a structured reference when a caller needs one, not a message
that another component must parse. File/directory/batch producers keep their agreed publication path; no wrapper per script.

Same-host retained evidence can survive worker/slot/dashboard restart. A fresh PC does not promise old local artifacts.
Missing essential media needs recreation or clarification, not guessed approval. Evidence retention never deletes or
hides runtime state; task references can remain informative even when their local media has expired.

## Source evidence and bounded implementation

Read asks/owner_verbs.py, asks/intake.py and ask_verbs.py; pipeline/requests.py; kernel/signalrows.py and dash.py;
dash/api/writes.py, liveview.py and artifacts.py; dash/static/js/actions.js; dash/readers/runprojection.py and logs.py;
artifacts/store.py, server.py and rules.py. This verifies current source paths, not a live demonstration of every race.

Existing ownership: .7.1 attempt links; .7.2 direct state; .7.3 task refresh/errors; .7.4 selected recent/live activity;
.7.5 controls/resume/acknowledgments; .7.6 artifact reader/reference consolidation. PORTABLE-ASKS and TASK-CONTRACT own
question/response semantics. Corrected STORE .26.3/.26.6 own actual-attempt/local-control progress. Shared agent/process
interfaces must provide truthful collection/cancellation before claiming complete recovery. No parallel implementations.

Use focused fake-backed scenarios: stale target; accepted stop with surviving/unknown worker; paused task plus response;
crash after input consumption/before launch; partial answer submission and later correction; completed checks across
clean slot handoff; cursor reconnect without switching attempt; missing evidence with valid runtime state; replaced
artifact filename; and in-flight land result under stop. Required just check/just test apply when source changes.


## Reassessment: minimal initial control surface

Owner response 2026-11-09 asked whether manual stop/resume/start-over is needed at all, while preserving automatic
continuation after a factory restart. A further Astra consultation recommends one task control: Pause / Continue,
implemented through the existing shared hold/unhold application operation. Denis accepted this minimal surface on 2026-11-09. It supersedes the earlier proposed separate resume API and the narrow stop-during-land choice.

- Pause prevents the next step from starting and lets the admitted step finish normally. Show pausing while it drains.
  If the current step is land, it can finish delivery/task closure; do not manufacture a paused completed task.
- Continue removes only the owner pause intent. Normal scheduling rechecks other holds, dependencies, approval, questions,
  limits and existing work before continuing. It is not a command to launch, resume a chosen session or restart a step.
- An intact-DB factory restart reconciles actual executions automatically. Reconnect to live work; do not duplicate or
  cancel it merely because a hold exists. If continuation needs a new execution while held, wait for Continue. Draining
  does not promise to relaunch a crashed step against the owner's hold. Same surviving execution keeps its attempt;
  a genuine relaunch is a new attempt under the existing session policy.
- Deliberate DB discard/new PC uses normal evaluation of Git plus synced tasks. Preserve code, plan and interrupted edits;
  no routine discard-first/start-over path or manual history restoration mode.
- Defer/remove immediate per-task Stop from the initial successor UI/API and omit manual restart-attempt/session/from-
  scratch variants. Do not add a duplicate manual resume controller; CLI hold --release and dashboard Continue call
  the same operation. Current legacy Stop behavior is not a required retained feature merely because its code exists.
- Keep underlying cancellation/liveness for timeouts, failures and supported factory shutdown. No weakening of survivor
  protection or change to the separately agreed factory shutdown/draining boundary is implied.

Cost tradeoff: Pause cannot immediately cancel one mistaken/expensive live execution; it may wait for the current step's
time limit. Add immediate Stop later only for a demonstrated operational need. Do not mislabel Pause as cancellation.
Observation, exact-attempt live/retained evidence, portable responses and durable owner-input incorporation remain part
of the walkthrough regardless of this smaller control surface.


## Owner decision: minimal controls accepted, 2026-11-09

Initial task controls are Pause / Continue through one shared hold/unhold operation. Immediate per-task Stop and manual
restart-session/attempt/from-scratch modes are deferred. The preceding broader control table and stop-during-land example
describe existing code/earlier proposals, not required successor UI/API. Pause allows the admitted step (including land)
to finish, then prevents next-step admission. Continue clears only owner pause intent and re-evaluates normal eligibility.

Automatic intact-DB reconciliation and required timeout/failure/factory-shutdown cancellation remain infrastructure.
No immediate-stop-dependent process API is a prerequisite for the hold/unhold presentation itself; actual execution and
slot safety still require those interfaces through their owning runtime tasks. No source changed in recording this decision.
