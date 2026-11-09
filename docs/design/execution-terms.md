# Execution terms: steps, actions and attempts

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

Design review record, 2026-11-08. The [glossary](../glossary.md) is the vocabulary authority.
This note records the reasoning and the remaining design work; it does not describe the current implementation as finished.

## Two design questions

The owner requested durable decision tests on 2026-11-08. Apply these questions to future changes, rather than
choosing storage or adding handover machinery from the current implementation's accidents.

**If we shut down this factory and continue on another PC with only Git and synchronized work tasks, what must survive?**

Keep portable work meaning in the task tracker and versioned code, plans and decisions in Git. The new factory
starts without the old factory.db, slots, process identities, execution history or artifacts. Those are local
execution/evidence, not portable task metadata. Local evidence may remain retained on the old host. Shared code
includes the task branches needed to continue; an unpublished local commit cannot be fetched on another PC.
The same rule covers restarting with an empty local database after controlled shutdown: ordinary steps inspect
saved work and may repeat, without reconstructing prior runtime history.

**If this factory crashes and restarts with its database intact, can it automatically continue the same steps and sessions?**

Owner correction, 2026-11-08: this is the second standing question. A normal factory restart preserves the task's
current step, unfinished work, checkpoint and agent-session association. It must not become a new task execution
from planning or a fresh conversation solely because the coordinator process restarted. Persist the references
needed for ordinary resume rather than reconstructing them from diagnostic logs.

Check whether a worker survived before launching another: a coordinator restart is not permission to run two
agents against the workspace. Where a new harness launch is needed, resume the existing session and record the
actual execution without resetting budgets or pretending that launch did not happen. Session identifiers are not
process identifiers. Unsupported or unavailable session continuation must be explicit, not silently presented as
successful resume. Exact harness supervision and resumption wiring need verification.

The portability question chooses what survives across machines. The restart question chooses what local state
must persist for normal continuation. Database disposability permits deliberate discard after shutdown; it does
not mean throwing away an intact database after every crash. Neither question requires a log-based history rebuild.
These are design criteria, not claims that current code already satisfies them.

The earlier fresh-agent question remains a separate accepted handover criterion: can a fresh agent continue from
the current task, committed plan, code context, next operation and complete evidence references without replaying
the previous conversation? Use it for deliberate feedback handovers or new-machine continuation. It does not
override resuming an unfinished step/session after a normal crash. Local evidence absent on another PC can be
reproduced by ordinary steps from portable work.

## Decisions recorded

| Choice | Source and status |
|---|---|
| Say task tracker, currently Beads. It owns requirements, dependencies, questions, linked answers and discussion; Git owns code/design/plans and selected design artifacts; factory.db owns local execution state; readers own local evidence access. Tracker maintenance owns durable task backup/recovery, with existing exports protected until coverage/recovery is verified. External messages inform tasks/design rather than becoming another authority. | Owner, 2026-11-09: agreed to the division and requested glossary adoption. See [storage ownership](../glossary.md#storage-ownership). Responsibility is agreed; backend guarantees and source migration remain unverified. |
| Use task for the work to accomplish. | Owner, repeated throughout the 2026-11-08 review; agreed. |
| Use step for the task-level operation and its implementation; remove the unnecessary stage/step distinction. | Owner, 2026-11-08: "Yeah, remove that unnecessary distinction." Agreed. |
| A step may group operations serving one purpose. Land owns merge and push; they are not separate steps just because they have names. | Owner, 2026-11-08, clarification after retaining land; agreed. |
| Keep land as the name of the delivery operation, distinct from Git merge and push. | Owner, 2026-11-08; agreed. |
| Individual lint, type and test validations are checks inside the checks step; preserve their separate results and histories. | Agent recommendation responding to the owner's hierarchy challenge; adopted in the glossary draft, not an instruction to flatten their behavior. |
| Attempt means a try at the named operation, not exclusively a whole step. | Owner suggested this refinement, 2026-11-08; the agent adopted this wording in the glossary draft. |
| Action and operation are ordinary descriptions; do not add a generic action entity or workflow tier merely to define attempt. | Agent clarification of the refinement; no new schema or scheduler approved. |
| Planning completes with a usable plan committed on the task branch at `docs/design/<task-id>/plan.md`. | Owner agreed to versioned planning completion and specified the per-task folder and `plan.md`, 2026-11-08. Using only the ID in the folder is the agent's naming recommendation. |
| Factory completion checks, bounded evidence handovers, clean-boundary merge-conflict handling, coordinator filing of follow-ups, and one combined acceptance/code review are agreed. | Owner, 2026-11-08: "yes, I agree with it all"; acceptance review must use the task's requirements. This approves the proposals below; implementation is still outstanding. |
| A valid completion result is properly structured output with the expected result. | Owner clarification, 2026-11-08. Schema validity alone does not make a failure or ask a successful completion. |
| Limit repair cycles to three repair attempts, then ask; avoid full-history prompts and unjustified review of unchanged work. | Owner agreement to the preceding recommendation, 2026-11-08. Exact accounting across steps still needs implementation design; moving between steps must not create an unlimited loop. |
| Write compact check outcomes directly to factory.db; retain output and transition traces in logs. Workflow and dashboard read execution state through the store rather than reconstructing completion from diagnostic logs. | Owner accepted with "good", 2026-11-08. This approves the ownership direction, not starting held STORE implementation. |

## How the concepts compose

One task follows a sequence of steps. A step may need several attempts. For example, one planning attempt may be
interrupted and another may finish in a different slot. An attempt of the checks step can contain several checks;
an individual check can need more than one try. These are different operations using the same word, attempt.
Every record must identify which operation was attempted and its context.

The checks implementation owns how it coordinates its checks. Observing their results, duration, output and retries
does not make each one an independently scheduled factory step. Likewise, a harness session contains messages,
reasoning and tool calls without making those messages workflow steps.

Workflow describes the sequence; it need not introduce another stored execution object. A step is identified by
its purpose and completion condition. The work inside it is not necessarily one command or one harness launch.

## What remains to design

The owner wants each real try inspectable, even when the dashboard initially shows a total. The storage shape and
the association between step attempts, internal check tries and harness launches still need design. Avoid both
hidden retries and counting one execution twice when building totals. An opaque reference returned by the agent
library may be sufficient to associate conversation and usage; a new caller-supplied identifier is not required
merely because the current implementation has a call_id field.

Current code uses run for a whole-task execution and for other counters, stage for numbered plan chunks, and call
for a harness request. Those meanings must be mapped before changing fields or removing records. Code renaming
alone cannot remove the nested planner-defined workflow. The decision to remove the unnecessary distinction
does not settle every existing plan or retry behavior.

## Planning completion

Each task's plan belongs at `docs/design/<task-id>/plan.md` on its task branch. Use the task ID alone for the folder
and put the title inside the document: changing a title should not move the plan. The folder can later contain
other planning artifacts; only `plan.md` is required by this decision. Existing general design documents need not
be moved into task folders merely to follow the new planning convention.

A successful planning attempt leaves a usable plan covering the task's acceptance criteria, proposed work and
validation, committed at that path. A successful harness exit, an empty file or an uncommitted draft is insufficient.
Content quality requires assessment; checking the path and commit alone cannot establish that the plan is useful.
This does not add an obligatory owner approval step.

The planner first reads an existing plan and checks it against the task and current code. It reuses or amends it
instead of starting over solely because local factory state is absent. A saved plan is an input, not proof that
implementation is complete. Publishing task branches between machines remains a separate delivery-policy question.

Current implementation returns structured `PlanData` and publishes run-local `plan.json`; the repository plan is
not yet produced. Implementation must adjust the prompt, choose who writes and commits the file, verify completion,
and reconcile structured execution and dashboard consumers without creating two independent plan authorities.
That work is tracked in tl-8bh9.3.2, alongside the execution design in tl-8bh9.3.1.

## Completion conditions and agent instructions

Owner clarification, 2026-11-08: deterministic completion checks belong to the factory; semantic acceptance belongs
to review. Instructions to read the task, inspect code and implement missing work describe agent behavior, not
completion conditions. The earlier discussion mixed these concerns; this section corrects that framing.

Implementation completion conditions (proposal accepted by the owner): the agent returned properly structured output
with the expected successful result, the checkout is on
the expected task branch, intended changes are committed, no tracked or untracked work remains unresolved, and no
merge is unfinished. A task requiring no further changes need not produce a new commit merely to satisfy completion.
These conditions permit advancing to checks; they do not prove acceptance criteria or code quality. Generic planning
completion checks likewise prove the file/commit/result contract, not the quality of its contents.

Owner requirement: unresolved uncommitted files continue the same step with their actual status, rather than advancing.
Cleanup must not erase work. Resuming an agent session does not excuse hiding additional harness launches from attempt
history. Exact continuation and attempt boundaries remain part of the execution design.

## Work questions, runtime waits and architecture decisions

After the owner's request for further critical balancing with Astra, the
[settled working human-input design](tl-8bh9.6.1/balanced-design.md) supersedes conflicting exploratory interaction
details below. It uses a common request/response interaction in the existing asks component, domain-owned storage
and consequences, explicit submission and response-revision-aware incorporation. Rounds/drafts are UI concepts;
work responses need not be classified by machine as answer versus ask-back. Actual approvals remain typed/scoped.

Owner accepted on 2026-11-08: an unanswered question about the intended work and its answer must remain portable
with the work task. Beads is the present task adapter, not the domain definition. Local quota, capacity and machine
waits stay in factory.db. The dashboard can show both through their owners. Use the question "does this answer
change the work, or merely let this factory execute it?" to choose the state owner.

The owner requested correlation with ADRs. Recommendation awaiting agreement: the task carries the question,
options, answer and context needed to finish the work. Task-specific clarification ordinarily needs no ADR;
update its plan when it affects the approach. A lasting architecture choice constraining other tasks belongs in
an existing versioned design decision or an ADR under docs/adr. Link it from the task and link back for rationale.
Do not copy a mutable policy into two competing records. Once recorded, the versioned decision is the authority
for later tasks; an old task answer is history, not a later override. Superseding a decision is an explicit change.

Do not create an ADR or a separate documentation task for every answer. Record a warranted ADR with the work that
implements the choice where practical. Ordinary acceptance clarifications remain task context. Local execution
waivers and one-host fixes do not automatically become portable architecture decisions.

Existing code already treats docs/adr/NNNN-title.md as the record and caches parsed ADRs in factory.db. It also
tracks plan citations and similar prior asks, and stick.py can file a separate task to land an ADR. Assess this
machinery critically against the smaller purpose rather than rebuilding it. AskStore and ledgercomments.py mix
SQLite ask records with structured task-comment ledger/rebuild; intake.py installs the comment hook. Separate
portable work questions from local waiting/consumption state and remove needless history reconstruction. This
does not prohibit an ordinary derived view of versioned documents; it prohibits competing authoritative state.

Existing ADR task tl-sqd3.26.9 belongs to the held STORE work; record related findings without starting it. The
broader task-service question boundary belongs to tl-8bh9.6. Exact portable question representation remains design
work; do not introduce a second task backend or universal decision-management framework.

## Intentional factory stop

Owner accepted on 2026-11-08: retain the two existing controls rather than adding overlapping pause/cancel commands.
factory stop stops admission and finishes the current task; factory stop --now requests interruption through the
agent interface, preserving work, checkpoint and conversation references. Record an interrupted attempt once its
execution has actually stopped. Neither operation completes or abandons the work task. A later start continues
the unfinished step, resuming its session in another attempt if a new execution is needed. A surviving execution
still occupies its workspace and keeps its attempt; do not launch a competitor. Local quota/answer waiting is
distinct from an intentional operator stop.

## Feedback handovers

Owner requirements, 2026-11-08: failing checks and blocking review findings return to implementation. Land conflicts
also return to implementation. Handovers are agent-facing. Full output, including hundreds of failing tests, belongs
in a readable file rather than being pasted into the prompt.

Handover envelope (proposal accepted by the owner): the reason for returning, affected code commit, next operation and a reference to complete
evidence. Keep the envelope bounded; keep the evidence complete. The receiving slot must be able to read the referenced
file; a path inside a discarded workspace is insufficient. Diagnostic logs stay behind the log reader, outside Git,
and must remain available while the task is active. Do not spend another model call summarizing routine command output.
Use command results and the review's existing structured findings. Infrastructure failures are distinct from code
failures and should not automatically instruct an agent to change code.

Leftovers handling (proposal accepted by the owner): distinguish remaining required work from optional
follow-ups. Agents report out-of-scope follow-ups, the coordinator files tasks and records their IDs,
and an unresolved acceptance criterion cannot become optional merely by filing it elsewhere. Avoid duplicate filings.

## Land conflicts and review cost

Clean-boundary conflict handling (proposal accepted by the owner): land records the task and target commit IDs plus conflict diagnostics,
aborts its failed merge before releasing the slot, and returns to implementation. Implementation explicitly recreates
the merge of that target into the task branch, resolves it and commits. The handover must request that operation;
ordinary implementation would otherwise have no reason to reproduce the conflict. Checks and review then assess the
updated code before land retries. No conflicted index needs to travel between slots. Cleanup releases resources and
ends unfinished Git operations; it does not discard committed work or unresolved agent edits. The existing rebase-based
fix path in packages/land/src/tlland/fix.py does not implement this proposal and needs reconciliation with merge-only land.

Agreed default: one review assesses both the task's acceptance criteria and code correctness, with separately structured findings,
rather than two mandatory model calls. Later reviews verify prior findings and the new changes, including their effects
on acceptance, instead of reopening unchanged code or suppressing regressions outside the changed lines. Reuse applies
only to the code and inputs actually assessed. Existing review prompts already combine these concerns and distinguish
first and later rounds; consolidate their behavior rather than adding a parallel review framework.

Use three repair attempts per failure cycle, then stop for an ask; ask earlier when a decision is required.
Avoid unlimited implement/check/review/land loops. Cycle accounting must not reset indefinitely when a failure changes
steps or is renamed. The exact implementation of this bound remains part of the execution design.

## Agent execution ownership: current evidence and proposal

Checked 2026-11-08: delegate.api already exposes run with a started handle, agents for surviving executions,
cancel for a handle and history for finished executions. The factory's ApiAgent runs that library on a thread;
ApiRunner polls it and uses cancellation on stop. Thus a factory crash also loses the in-memory waiting thread.
A surviving native harness process and a retained session are different from an attached execution result channel.
An intact checkpoint alone does not establish that the restarted factory can collect a survivor's final answer.
Verify this boundary under tl-8bh9.3.4 before adding another daemon or promising seamless live attachment.

Recommendation: the factory owns task steps, their persisted attempts and workflow decisions. The agent interface
owns starting, observing and stopping agent executions, session selection/continuation and access to their output.
Use the same interface after restart to distinguish still running, completed, stopped and status unavailable.
Preserve actual launch/session references when that boundary reports them; do not make the factory interpret
harness formats or build an alternative process supervisor. Exact API changes remain review work under tl-8bh9.4.

Concrete ambiguity: taskloop/adapters/agent.py running_for catches any Exception/SystemExit from api.agents and
returns an empty list. slots/engine_lock.py calls it when checking whether a worker outlived its engine. This
conflates unreadable live status with no surviving worker. Static inspection establishes that conflation, not a
demonstrated concurrent-worktree collision; verify callers and reproduce the admission case in focused tests.
Unknown execution status must not by itself authorize workspace reuse or a second writer.

Owner accepted and expanded this boundary on 2026-11-08: the agent interface owns structured output, schema
validation/parsing, bounded same-session requests to repair malformed output, session continuation and cancellation,
and reporting account credits/allowances, models and harness capabilities. The factory supplies its required result
schema and execution limits and uses returned usage/availability to manage workflow budgets. The interface owns
how supported per-execution limits are enforced across harnesses. Whole-task budgets remain factory decisions.
Format repairs must remain visible and count against the execution allowance; a valid failure/ask is not malformed
output to repair until it becomes success. Unsupported hard limits must be explicit rather than silently advertised
as enforced. These are contract requirements, not proof that each provider supports every limit.

Current delegate/app/run.py _schema already validates and performs one same-session schema re-ask before returning
schema_invalid. Reuse/consolidate that behavior rather than implementing factory-side JSON repair. RunRequest has
wall/idle limits; the current typed request does not expose turn/token/cost limits. Status already contains typed
account windows, freshness and unknown readings. Existing quota task tl-7i9k.16 should be reconciled with this boundary.

Recommended session contract: choose new, or resume an explicit opaque session reference. Factory attempt records
retain the returned reference; native conversation IDs and harness-specific resume/account rules stay inside the
agent interface. Task ID is correlation metadata for finding all associated conversations, not the session ID.
Several sessions may serve one task; continuation and format repair can reuse a session. Preserve these relationships
without defining another work-task store or inventing competing session IDs. Exact API and reference format remain open.

Current threads.py selects a remembered native session using task/thread keys and can choose fresh based on prompt
availability, context and fallback conditions. Assess this against explicit new/resume intent and the agreed crash
resume versus feedback re-entry policy. Do not silently override a required resume and claim the same session continued.

## Session reuse and prompt caching

### Attempt/session cardinality

Owner question, 2026-11-08: attempts and sessions are both associated with a step; what is their cardinality? The
owner requested an Astra review. Astra and the coordinating agent recommend the following, correcting the earlier
proposal that grouped format repair or a replacement execution into one elastic "unfinished logical attempt".
The owner accepted the working model after the second Astra consultation on 2026-11-08; it is not implemented.

A step is the workflow activity. An attempt is one execution of an operation within it, from launch to terminal
outcome. A session is the harness conversation that an agent execution uses. Each attempt uses zero or one session;
a session can serve many attempts. Non-agent attempts have none, and the reference can remain pending until the
harness reports it. Under the agreed session policy a session stays within one step, which may use several sessions.

The owner then asked whether attempt and retry should be the same concept. Recommendation: attempt is the one
record/counting unit; retry is the ordinary action of making another attempt. The first try is attempt 1, the next
try is attempt 2, not an attempt containing a retry containing another execution. A retry reason may explain why
an attempt started; it does not require a Retry entity or separate workflow tier. Low-level transport retransmission
inside an ongoing execution is still not automatically another factory attempt.

If a factory restarts and the old agent execution is still running, recover that same attempt and session without
launching another. If that execution ended, launching a continuation creates a new attempt in the same session.
A schema-repair prompt that starts another harness execution also creates another attempt in the same session.
A fresh conversation means a new attempt with a new session. Preserve all execution outcomes and usage separately.
The restart invariant preserves the step and conversation; it does not require pretending two executions were one.

One agent-interface request may perform bounded automatic repairs and emit/return multiple attempt records. This
keeps repair policy in the interface without hiding executions or making the factory formulate repair prompts.
Do not turn every account wait, tool call, message or HTTP transport retry into a step attempt; the boundary here
is the agent execution, not every diagnostic event. Existing delegate Attempt kinds mix these meanings and require
semantic mapping before fields are renamed.

Sessions and attempts both have step context. Whether step/session ownership is stored directly or derived through
attempt use is an implementation decision, not grounds to reject the owner's conceptual association. Avoid a
competing task-to-current-session authority and duplicate transcript content. Retain references to the relevant
conversation span through the agent reader.

Current delegate.api.run can retry with a fresh session and merge outcomes into one API return; the caller's
request count does not establish attempt or native-session count. Persist the attempt before launch, record
execution/session references as available and verify the launch/acknowledgement crash window. Do not claim exact
recovery from a session ID alone or add a new daemon without evidence that the existing seam cannot support it.

The owner asked Astra again whether a factory crash should itself create another attempt. Both meanings are
coherent: attempt could count actual operation tries, or periods of factory supervision. Astra and the coordinating
agent recommend counting operation tries. If one execution survives a coordinator crash, changing its attempt ID
would require assigning/splitting that execution's cost and output between supervision periods. A restart can also
merely collect an already persisted result; collection should not count as another try. Record factory resumption
as an event on the existing attempt, without another public entity or a second supervisor-history system.

If the old execution stopped and another execution is required, create a new attempt, potentially continuing the
same session. A failed launch may produce an attempt with no execution, but one actual execution should not belong
to multiple attempts. Unknown launch acknowledgement remains unknown until checked through the agent interface;
neither an empty status result nor a new attempt number may justify a competing launch. Budgets never reset on
factory restart. This is the accepted working rationale following that consultation.

For conceptual clarity, state the ownership directly: a step owns its attempts and its sessions; an agent attempt
uses zero or one of those sessions, and a session may be used by several attempts. Ownership and use are different
relationships. This does not require storing a separate current-session pointer on the task.

Owner clarification, 2026-11-08: a normal factory crash/restart with intact local state resumes the same unfinished
step and session. The fresh-session default below applies to feedback re-entry after a completed step, not to a
coordinator restart. Attempt finalization or slot release must not discard the context required for that resume.

Owner concern, 2026-11-08: resuming a large implementation conversation after checks, review or land may resend costly
history when the vendor cache is cold. Always starting fresh can also waste context gathering and lose useful detail.

Owner accepted this default on 2026-11-08, explicitly allowing later revision: resume for immediate continuation
within an unfinished step, including resolving uncommitted files.
When a completed implementation step is revisited after checks, review or land, start a fresh session with the task,
versioned plan, current code and bounded evidence handover. This is a simple default, not a claim of minimum cost for
every provider. Preserve the old transcript for inspection rather than copying it into the new prompt. Do not add
cache keepalives or a vendor-specific expiry scheduler. A fresh session must read relevant evidence; short prompts
do not by themselves guarantee low total token use.

Session identity is not a cache guarantee: cache reuse depends on an eligible matching prompt prefix and provider
conditions. A fresh session can also reuse a shared prefix. Cache expiration removes the relevant input discount;
it does not mean all historical output tokens are billed again as new output. API cache documentation does not
establish the billing or allowance treatment of each harness subscription.

Sources checked 2026-11-08: [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
documents model-dependent cache lifetimes and prefix matching;
[Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) documents
five-minute and one-hour cache lifetimes. These do not establish a universal idle timeout for our harnesses.
Any harness-specific reuse optimization belongs behind the agent interface. Reuse existing per-attempt usage
reporting for evidence before introducing more policy; do not build a separate cache monitoring subsystem.

## Finding conversations from a task

Owner requirement, 2026-11-08: use the task ID to locate its session transcripts, including multiple sessions used
across feedback transitions. The lookup is scoped to the repo so identical task IDs in different repos cannot collide.
Expose the associated step and attempt, the session reference and access to its retained conversation. Sessions can
span attempts, and an attempt can need multiple launches; do not force a one-to-one relation or duplicate transcripts.
The association describes actual executions, including explicit absence when a session never started.

This is normal attempt/session attribution, not a new transition-history service. Factory metadata links to the
agent interface's conversation reader; factory code does not interpret harness storage formats. The requirement
applies while retained data and its index are available. Deleting factory.db may lose the old attribution index,
as already accepted; task lookup does not introduce automatic history reconstruction or a file fallback. Retention
expiry or missing evidence must be reported explicitly. Implementation is tracked in tl-8bh9.7.1.

## Minimum handover contents

Owner accepted the minimum handover proposal on 2026-11-08, then requested visible transition reasons.

Generate the envelope from existing execution results, not another model call. Include the repo/task, receiving
step, reason for returning, relevant code commit and (for an integration conflict) target commit, conventional plan
path, and references to complete findings or command output. Include only unresolved instructions and necessary
decisions, not every previous round. Runtime handovers and logs are not additional committed planning documents.

A fresh agent uses those inputs to read the current task and plan, inspect relevant code and evidence, then act.
Prior transcripts remain available by task for investigation, but reading all of them is not a handover requirement.
Evidence must identify the code it assessed so old failures are not mistaken for observations of newer changes.
Exact evidence access and the structured envelope format remain implementation design, not a new public entity.

## Why a step returned to another step

Owner requirement, 2026-11-08: task history must show a return such as land to implement and its specific reason.
Record actual source step/attempt, destination step, timestamp, a structured cause plus short explanation, relevant
commit references and complete-evidence reference. The receiving attempt may not have started yet; do not fabricate
an execution or session just to attach a transition. Normal forward progression uses the same representation.

Placement: the completed attempt's result and chosen next step/cause are execution state in factory.db,
read by the dashboard and task history through the store. Full command output and transcripts remain files behind
the log reader. Owner clarification, 2026-11-08: also log transition events for tracing; extensive diagnostic logs
are welcome. These serve a different purpose from queryable execution state and are not a fallback source for the
dashboard. Emitting a trace does not prove the database update succeeded; preserve that distinction in diagnostics.
A state update and its corresponding transition outcome should be committed together. Exact tables belong to the execution/store design; a new event
store, event-sourced scheduler or independent transition-history service is not required by this request.

Example: land attempt 2 selected implement because merge_conflict, with task commit, target commit and diagnostics
reference. The implementation attempt that later starts is linked to this reason. This is runtime state, not
tracker comments. Discarding factory.db may discard this history, consistently with the accepted disposable-state policy.

## Review purpose and useful improvements

Owner accepted this concise review rule on 2026-11-08: find reasons this task cannot safely land, without turning
it into an unlimited improvement project. Findings should be grounded in the task requirements, applicable repo
rules or a concrete failure scenario. Deterministic grounding may be added later; it is not a prerequisite now.

The owner also encourages doing useful adjacent work during implementation rather than filing a task for every
small improvement. Preserve that discretion: make the work good while doing it, without expanding it indefinitely.
Review remains read-only and returns necessary fixes to implementation. Existing follow-up reporting is available
for substantial deferred work, but noticing an optional improvement does not automatically require a new task.
Do not add a quadrant classification or another mandatory improvement workflow to express this principle.

## Checks: current evidence and next design proposal

Read on 2026-11-08 in the glossary review worktree; no checks executed in this documentation review:

- packages/gate/src/tlgate/domain/specs.py builds configured repo checks and additional planner-proposed acceptance
  commands. References to registered checks do not add another execution; ad hoc commands are not persistently cached.
- packages/work/src/tlwork/write/check_round.py runs checks through the engine, accepts requested engine checks,
  returns code failures to the writer and distinguishes timeout handling. Existing retries/replanning still need
  reconciliation with the agreed bounded feedback loop.
- packages/gate/src/tlgate/cache.py and packages/kernel/src/tlkernel/runkey.py already identify reusable passes by
  command/config, code/base or declared inputs, toolchain, environment, execution context and producer dependencies.
  packages/land/src/tlland/carry.py separately proves reuse when the base changes using a merged tree and input closure.
  These observations establish existing mechanisms, not proof that every validity condition is correct.

Recommendation awaiting owner review: keep required repo checks defined once in the profile and executed by the
factory. Agents can request checks and propose task-specific validation, but cannot waive required checks or treat
their own claim of success as execution evidence. Focused debugging during implementation remains useful; it should
not duplicate the factory's expensive registered checks by default. Existing requested-check behavior is a starting
point, not a reason to add another runner.

Checks prove the automated conditions they actually execute. Review still judges the task's acceptance criteria;
not every criterion must become an invented command or metric. A check failure caused by code returns to implement;
infrastructure failures are classified separately. Every result distinguishes executed passes, reused passes,
failures, skips and unavailable validation. A skip is not silently equivalent to a pass. Required validation must
have valid evidence or an explicit applicable not-required decision before land.

Reuse is the next focused review question. Keep one pass store and one validity decision; the separate base-change
proof deserves assessment for its benefit and complexity. Do not discard it or build a replacement merely to rename it.

Owner clarification, 2026-11-08: checks is a mandatory workflow step, not an optional service triggered by agent
requests. The prior recommendation's wording conflated this with an existing optional diagnostic mechanism.
Current code accepts a structured `run_checks` list of opted-in registry IDs after a write, with admission caps,
and classifies commands as writer-runnable or engine-only. See write/write_round.py, write/briefing.py and
gate/domain/writer_split.py. This is evidence of current behavior, not agreement to preserve that protocol.

For the target design, recommend ordinary focused debugging commands during implementation, subject to repo rules,
and mandatory workflow-controlled checks afterward. `just check` and tests are ordinary commands; their permission
and appropriate timing depend on repo policy and the current engine-only guards. Do not instruct agents to evade
those guards. Assess whether optional request fields, caps and prompts have a real distinct use case before keeping
them. No new request API is needed merely to express the mandatory checks step.

The owner explicitly requested verification of pass-reuse correctness and code organization. That review is now
tracked as a child of tl-8bh9.5; it must inspect existing identity/reuse bug fixes and shared ownership before proposing
consolidation. This does not approve a new cache design or removal of base-change proof.

## Unity feedback: request protocol versus guarded commands

Owner context, 2026-11-08: the request mechanism addressed a real limitation: Unity could not run in the coding
agent's sandbox. Agents still needed execution feedback during implementation. Critically assess whether the later
custom-tools/command-allowlist strategy supersedes it. Preserve the idea and purpose in task history; do not retain
code merely because it might be useful later. Investigation is tracked under tl-8bh9.4.

Checked current code: factory worker_request.py passes the product boolean writer_exec. Delegate api.py resolves
writer identity and grants from its routing settings. delegate/app/codex_policy.py constructs a CodexOverlay and
guarded command invocations; domain/policy/exec_allow.py bounds full argv using pinned binaries and the host grant.
The guard executes an admitted command and returns its process exit status through its own stdio. This is evidence
of an implemented synchronous route, not a live demonstration that Unity works on the owner's current Mac.

Closed tl-auky records the original allowlist feature; later isolation moved the detailed grant out of factory.
However, the guard still checks engine_only rules. WriterSplit classifies requestable and gate commands as engine-only,
so authorizing a recipe in a grant does not automatically allow it through. Reconcile these policies before deleting
the old request path; do not bypass the guard to make both paths appear interchangeable.

Closed tl-7y6.11.3 explicitly simplified the proposed rich engine.tools schema to repo commands plus timeout.
No current engine.tools registry was found in the kernel config or factory consumers searched. A repository script,
a guarded Bash invocation and a harness custom tool are distinct; the old task's status does not prove all three exist.

Recommendation: one minimal synchronous way for the implementing agent to execute authorized project commands and
receive feedback, alongside mandatory factory checks. No extra model-return/request/next-round protocol unless the
direct route lacks a required capability. Verify Unity execution, output/artifacts and shared resource coordination
before selecting the cut. Authorization and machine resource limits have concrete purposes; dynamic duration-based
command classification and optional request plumbing must independently justify their continued existence.

Owner correction and direction, 2026-11-08: prefer repository-defined custom tools injected into harnesses through
a tiny MCP server, rather than treating command allowlists as the destination. A versioned repo file describes a
tool's purpose, executable/script and parameters. The agent interface adapts that definition into each harness's
MCP configuration. Exact manifest path, schema and implementation remain open. This work is not urgent; keep it
in the backlog rather than building a framework during this review. Task tl-8bh9.4.1 records this direction.

Historical evidence found after that correction: docs/design/spike/artifact-add.md reports a successful per-call
stdio MCP artifact_add tool on Claude, Codex and OpenCode (tl-jvpm.20, 2026-11-05). In that experiment the server
ran outside the command sandbox, so a tool could write to the artifact store without opening the worker's command
sandbox. This is a recorded experiment, not a rerun or proof that Unity execution and current harness versions work.
Resume, concurrent executions and Mac startup overhead were explicitly untested. delegate/contracts/wire.py has a
ToolServer type whose comment says it is carried but not wired; verify production injection rather than inferring it
from the spike. The earlier search for engine.tools alone did not establish the absence of this MCP design.

The 2026-11-05 visual-work decision tl-jvpm.10 limited the injected tool to artifact registration and retained
request-in-answer for capture. Today's direction extends repository-specific tools to project execution, replacing
that request route when the required capabilities are verified. It does not erase the earlier decision history.

The manifest declares a tool; execution outside the command sandbox depends on how its server is launched, not the
presence of a JSON file alone. Expose named operations with validated parameters and deliberate execution grants,
not an arbitrary shell tool disguised as MCP. Keep mandatory workflow checks and their evidence independent of an
agent choosing to invoke a project tool. Reuse logging/artifact/resource mechanisms where needed; avoid a second
runner or unnecessary tool registry service. Remove superseded request/allowlist policy only once the replacement
actually covers its needed behavior. This records a design direction, not permission to change host grants now.

## Progress artifacts during execution

Owner purpose, 2026-11-08: agents create screenshots and examples to inspect their work, and intermediate evidence
should appear in the dashboard while execution is still active. Tool calling itself is not the product requirement;
the experience should be smooth and guided. Do not wait until an agent exits to expose its progress artifacts.

Checked current code: tlartifacts.server provides artifact_add, tlartifacts.store.add copies the file then atomically
writes its metadata sidecar, and the dashboard artifact reader lists published files from known attempt folders.
An arbitrary file without the sidecar is deliberately not a published artifact. Factory worker_call.py attaches an
artifact_tool binding to each invocation and the adapter carries it into delegate. The delegate ToolServer contract
still says not wired, and no tool injection consumer was found in delegate app/CLI in this read: do not mistake
factory-side wiring or the successful spike for end-to-end production support. Verify that boundary first.

Recommendation awaiting agreement: project tools that produce viewable outputs should publish those outputs as
part of the same operation, through the existing shared artifact writer, with task/attempt binding supplied by the
factory. The agent should not need a second registration call after taking a screenshot. Keep artifact_add for
files the agent creates by other means. This is one publication path with convenient producers, not two stores.
Do not add whole-worktree watching or auto-publish every intermediate file merely to avoid one explicit call.
A designated drop-folder alternative can be considered if a concrete producer needs it; it is not required now.

The dashboard should refresh its artifact view during active work, and published artifacts must survive slot cleanup.
Prompt guidance can invite useful progress evidence without making a screenshot mandatory for every attempt.
Review evidence should identify what code or state it shows; an intermediate image is not proof of final acceptance.
This extends tl-8bh9.4.1 and existing artifact/dashboard work, rather than creating another artifact service.

Owner refinement, 2026-11-08: advertise artifact capabilities briefly in the injected implementation instructions,
with token cost in mind. Keep artifacts in the task's local runtime folder alongside its logs. This runtime folder
is distinct from the Git-versioned docs/design/<task-id>/plan.md folder; exact runtime layout belongs to the storage
review. Minimal metadata is delegated to the implementer. The owner favors one-call capture/publication where it
can be made reliable and explicitly questioned relying on a sandboxed producer to publish itself.

Correction to the earlier recommendation's mechanism: the agent-facing tool server should own both running a
declared capture command and publishing its outputs, through the shared artifact writer. The screenshot script
does not independently need access to the durable store or a second MCP call. The server supplies a known output
location, checks the resulting file and publishes it with attribution bound by the factory. A failed command may
still produce useful evidence; report its exit result separately from whether an artifact was successfully published.
Do not publish a partially written file as successful evidence. Keep one-call completion outcomes explicit rather
than treating natural-language claims from the agent as proof of publication.

For a file created by an ordinary sandboxed command, artifact_add remains the explicit bridge: the server validates
and copies that file from the allowed workspace into the same task runtime store. Metadata should derive task,
step and attempt from the execution binding, and kind/size/time from the file and publication. Ask the agent only
for information that cannot be inferred, such as an optional useful caption or before/after intent. Do not add another
metadata database, retention subsystem or duplicate publication path for this refinement.

Example short injected instruction: "Use the project tools to inspect your work. Capture tools publish to the task
gallery automatically; use artifact_add for other useful files. Share progress evidence when it helps."
Exact wording and tool descriptions should be kept short without removing parameter contracts. Tool replies return
compact status, artifact references and an output-log reference rather than embedding images or long command output.
Verify production server placement/permissions and real Unity behavior; if a host cannot execute the command, return
an explicit capability failure rather than assuming that MCP itself bypasses every execution restriction.

Owner clarification, 2026-11-08: a screenshot is often the output of an ordinary Unity/script command, which may
accept its destination as a command-line argument. Accommodate that producer directly: supply its declared output
argument, wait for completion and publish the resulting file. Do not require screenshot generation to implement MCP
or understand the artifact store. An ordinary command remains usable outside the factory; its tool wrapper supplies
the publication behavior. Exact output argument and produced filenames are part of the repo tool definition.

## Remove redundant validation before choosing a cache

Owner challenge, 2026-11-08: successful-check reuse may be compensating for unnecessary executions across planning,
implementation, checks, review and land. First map actual executions and remove repetition; then assess whether a
generic pass cache is necessary at all. A candidate simpler design retains incremental/affected tests, runs the
other required checks normally, and drops general pass caching. This is a hypothesis to assess, not an approved deletion.

Static evidence: plan/probe.py can execute registered checks before implementation; write/briefing.py explicitly
tells writers to run fast checks and says the engine reruns them; look/judge.py can run static checks before rendering;
write/check_round.py runs the normal checks plus optional requests; land/gate.py and land/rebase.py have validation
paths, including after an integration/fix. Review receives check evidence but briefing.py also permits non-writers
to run a linter or test. These are conditional paths, not a claim they all execute for every task.

Test selection and result reuse are distinct. dev/affected.py computes affected tests from the change and dependency
graph; it also supports a successful-test ledger. dev/runtests.py enables that ledger only with TL_GREEN_LEDGER,
and land/stackgate.py sets it. Thus removing the generic check cache does not automatically remove test-level reuse.
Neither mechanism may silently skip tests whose relevant dependencies changed.

Read-only local evidence sample: 40 latest engine logs contained 66 check_end records, of which 61 said passed,
2 failed and 3 cached. Records are not equivalent to subprocess starts: checklog.py emits start/end pairs even for
cached/skipped results. Available run_start modes across local logs were stage:check and stage:land-stack, with some
unknown; no full task-associated pipeline histories were found by this scan. This is not a representative Unity
factory frequency or savings measurement and must not be used to justify retaining or deleting the cache.

Update tl-8bh9.5.1 to prioritize a phase/caller inventory and representative execution evidence before cache redesign.
Count actual command execution separately from result reuse, skipped records and repeated display. Distinguish
debugging from formal validation and unchanged candidates from changed code/integration inputs. Use existing logs
and transcripts, not another monitoring subsystem. Keep minimal evidence binding to what was checked even if the
generic cross-attempt cache is removed. Land must validate changed integration candidates; that is not automatically
redundant validation. Review should ordinarily consume evidence rather than repeat the same check suite.

## What a tool wrapper means: proposed concrete boundary

The owner requested a concrete mechanism, not an unspecified wrapper. No replacement Bash/shell, command interception,
new hook system or generated per-command script is proposed. A named MCP tool maps to a repo-defined executable
and validated arguments. A small server handler invokes that existing executable as an argv list, supplies its
declared output argument, waits for the process, and passes completed outputs to the shared artifact writer.
This handler is what earlier text called a wrapper. The command itself is unchanged and can run independently.
Delegate/its agent-library successor owns harness injection and execution capability; factory supplies task context.

For a command run directly through Bash, no handler automatically intercepts it or publishes its output. The agent
uses artifact_add afterward. For a named capture tool, command execution and publication happen in the one tool call.
Both publish through the same store. The minimal manifest, injection wiring and host execution behavior still need
design/verification in deferred tl-8bh9.4.1; do not implement both a new shell mechanism and an MCP mechanism.

## Astra brainstorm: arbitrary producers and batch publication

Owner challenge, 2026-11-08: ten scripts may generate different screenshots; agents must also be free to write ad hoc
scripts and produce intermediate artifacts. Requiring a registered tool or wrapper for every producer is unwanted
coupling. The owner explicitly requested a brainstorm with Astra. This section records the resulting recommendation,
subsequently accepted by the owner with "ok" on 2026-11-08: file/directory publication is the baseline, named execution
tools are optional capabilities, and automatic collection is deferred. Implementation remains outstanding.

Correction to the earlier emphasis: predefined capture tools are an optional execution convenience, not the general
artifact contract. Separate file generation from publication. Existing or agent-written scripts produce files in
the workspace using ordinary paths; they need no factory-specific copy/publish code, task identifiers or metadata
generation. Recommend extending the existing artifact_add tool to accept a file or directory/batch. One call can
publish many completed outputs through the shared writer, with attribution from the server's bound context.
Current implementation only accepts one file with mandatory caption/role/name; directory publication and optional
metadata are proposed changes, not capabilities already available.

A suggested workspace output folder can make discovery easy, but is a convention, not a required script API.
Outputs elsewhere inside the allowed workspace can also be published. Durable copies remain beside task logs,
outside the disposable workspace. Infer basic metadata and make semantic captions/roles optional unless the task
needs them. Do not infer final acceptance from a progress image or copy filesystem attribution fields into prompts.

Short proposed instruction: "Publish useful previews and results with artifact_add(path); use a file or directory."
Publication after a useful batch gives dashboard updates during the agent session without requiring another model
to summarize or register each file separately. It does not give continuous visibility during one long command.

Automatic collection of a designated folder is an alternative with a concrete cost: completion signaling, repeated
collection and lifecycle handling. A file whose size stopped changing is not necessarily complete. If continuous
mid-command visibility becomes necessary, assess a narrowly scoped collector and an explicit completed-file
convention, rather than promising automatic collection without that work. Do not introduce whole-worktree watching
or select this alternative merely to avoid a single publication call. The owner accepted the explicit-publication
baseline; continuous automatic collection remains deferred.

Named MCP execution tools can publish their outputs in the same call when useful, and a Unity execution capability
could run an agent-written project script without a new registered tool definition for that script. Execution
permissions are a separate question from artifact publication; do not add a generic unsandboxed shell to solve it.
This recommendation supersedes any suggestion that all generating commands must have tool definitions.

Implementation work is tracked in tl-8bh9.3.1. Vocabulary inventory and adoption are tracked in tl-8bh9.10 and
tl-8bh9.10.1; these tasks link existing work rather than making this document a second task tracker.

## Removal and consolidation decisions, 2026-11-08

Owner accepted the review recommendations and clarified that built-in web-link checking is unnecessary.
Remove the checker and special review/config routing (tl-8bh9.5.3); a repository may configure a normal check when
needed, but a replacement checker or shelf extraction is not required. Remove obsolete old-layout migration modules
and command blocking (existing tl-9un.44 repurposed), superseding earlier migration preservation policy. Removing
source support does not mean deleting user files, retained evidence or worktrees during this review.

One shelf-owned agent interface is the preferred target; migrate necessary reusable delegate capabilities and remove
competing ownership, rather than preserve both interfaces. Current delegate already uses any_agent for harness mechanics;
account/session/result policy gaps still need mapping before the API can replace delegate completely.
RepoId and storage ownership are reviewed together; STORE implementation remains held.

Follow-on source assessments are recorded in the [runtime helper review](tl-8bh9.4/plan.md),
[dashboard read/write map](tl-8bh9.7/plan.md) and [repository binding review](tl-8bh9.1/plan.md).
Dashboard direct state writing, removal of log-index dependencies and adapter-owned task refresh are review proposals
under existing single-owner/state-versus-logs principles, not claims that their implementation has landed.

Owner clarification, 2026-11-08: remove the current dedicated visual-only review workflow (tl-8bh9.5.4) and park
redesign in tl-8bh9.12 / spike tl-8bh9.12.1. Explore strict pre-land code/result review versus fast post-land feedback
and change requests later; no default or duplicate pipelines chosen now. General artifact publication, live activity,
questions/approvals and ordinary checks/code review remain. This supersedes the proposal to retain post-land visual
review by default. CLI and dashboard share application routines; different consumers do not justify duplicated workflow.

Owner scheduling decision, 2026-11-08: remove areas (tl-8bh9.3.6). Take highest-priority automation-approved tasks
whose dependencies are satisfied and which are not held/already claimed, up to available slots. Independent children
of an epic may run concurrently. Retain task claims, workspace ownership and scarce-command permits; no group-based
task exclusion. Additional manual queue and epic-order policies are assessed, not yet all approved for deletion,
in [the selection review](tl-8bh9.3/selection-review.md), task tl-8bh9.3.7.

Owner subsequently approved manual-queue/epic-order removal and accepted Astra's hierarchical priority contract:
own task priority first, then direct parent, then successive ancestors to root, then natural task ID. Missing priority
and absent ancestor levels compare as P2. No multiplier or inherited-priority writes. This supersedes earlier open
choice/recommendation wording. The [ordering contract](tl-8bh9.3/hierarchical-priority.md) records required results;
implementation is not permitted to substitute root-first, weighted scores or incidental discovery order.

Owner decision, 2026-11-09: remove the whole profile-change-specific approval mechanism. No replacement DB grant,
special profile authorization flag or audit-log delivery gate. Configuration changes follow normal implementation,
checks, review and land. Profile source/revision selection is a separate question under explanation, not permission
to reinstate that gate. See [the configuration review](tl-8bh9.1/configuration-review.md), task tl-8bh9.1.3.

Owner accepted configuration strategy on 2026-11-09: new-work admission reads a resolved target-branch profile;
task checks read the exact candidate revision's profile. Each operation keeps an immutable source snapshot until
it ends; normal restart retains that active execution's snapshot and admitted limits. Machine accounts/credentials/
actual capacity remain local, and candidate edits do not enlarge a running grant. Changed configuration uses ordinary
checks/review/land with no special profile approval. This supersedes earlier open source-selection wording.

Owner accepted on 2026-11-09: one repository target branch, replacing independent engine/slot base settings;
semantic delivery settings (push or PR, remote/target, supported auto/wait policy), replacing raw engine.land Git argv.
Shared Git operations perform delivery. Timeout and check-workspace policy remain under explicit review rather than
being implicitly chosen by those simplifications.

Owner accepted on 2026-11-09: retain task budget, agent-execution timeout and command timeout, consolidating overlapping
knobs. Prepared committed slots are the default; fresh candidate worktrees only on explicit requirement. Owner wants
no initial spending/token budget setup and suggested approximately two hours per task. Initial working policy after
Astra validation is 120 active task minutes, no enabled cost/token caps, and execution/command limits inheriting the
remaining task allowance unless explicitly narrowed. Usage remains observable; future tuning follows real work.
See [limit/workspace contract](tl-8bh9.1/timeouts-workspaces.md). New check-pipeline recommendations are separately
recorded in [candidate checks](tl-8bh9.5.1/candidate-checks.md), with generic pass-cache deletion still undecided.


Owner decision 2026-11-09: accepted the Astra-reviewed discussion roadmap and check-pipeline simplifications. Remove
historical pass cache/carry proofs, agent check-request machinery, stage/gate/both selection, routine duplicate checks
and automatic base-red/unchanged-input exemptions. Keep current-workflow validation completion and repository-owned
affected testing/incremental tooling. Required failures block; unavailable capacity waits. Revisit successful-check
caching only on demonstrated need. See [candidate checks](tl-8bh9.5.1/candidate-checks.md) for the authoritative contract
and [discussion roadmap](tl-8bh9/plan.md) for the accepted review order. This is a design decision, not implemented code.


Owner approved delivery/publication strategy 2026-11-09: merge plus final squash into target, ordinary append-only
task-branch publication after completed plan/mutating steps, and resumable land retrying only unfinished required
actions. PRs may intentionally await human review. Internal progress/decisions are typed data, not parsed display
phrases: validated structured interchanges, JSON where appropriate, necessary text quirks encapsulated by the owning
adapter/library. No redundant in-process serialization or new protocol framework. See the
[delivery contract](tl-8bh9.9/delivery-publication.md). No source implementation has been made.


Owner accepted local lifecycle defaults 2026-11-09: one shared local database authority for instances managing the same
slot pool; run the repeatable repository-owned setup/ensure-ready command on preparation, with warm incremental work
owned by repository tooling rather than factory fingerprints/probe ladders. See
[workspace lifecycle](tl-8bh9.2/lifecycle.md). STORE implementation remains held.


Owner accepted the correlated task/branch/worktree/slot and local repository/backlog identity contract on 2026-11-09.
STORE parent and ten open children now have corrected retained scope; its design hold is lifted only for those slices.
The previously closed child remains closed. Explicit prerequisites preserve identity, agent/task guarantees and safe
reader replacement. No old migration/compatibility plan is unheld. See [corrected STORE scope](tl-sqd3.26/plan.md) and
[shared interface assessment](tl-8bh9.4/shared-interfaces.md). No source implementation started.


Owner accepted minimal task controls 2026-11-09: Pause/Continue through hold/unhold. Let an admitted step finish, then
block next-step admission; Continue rechecks normal eligibility and retained progress. Defer immediate per-task Stop
and manual restart-session/attempt/from-scratch modes. Keep automatic intact-DB reconciliation and timeout/failure/
factory-shutdown cancellation. See [owner interaction contract](tl-8bh9.7/interaction-contract.md).


Owner selected fixed executable version per running factory on 2026-11-09. Installed updates/pin changes apply on next
start; no live switching or automatic bad-version fallback. Explicit owner pin is local configuration, not disposable
execution state. See [operations review](tl-8bh9.8/operations.md); its reduced release scope remains a recommendation.


Owner clarified lightweight skill purpose 2026-11-09: explicit help with setup, maintenance, compliant task authoring,
asks and requested factory operations. It is not a second autonomous engine or policy/state store. Astra recommends
retiring task-loop session hooks and managed Git-hook overlay, with retained runtime guarantees owned directly by normal
operations. Repository Git/LFS hooks and execution-adapter mechanisms remain separate. See the final section of
[operations review](tl-8bh9.8/operations.md); no source hook removal was performed.


Owner decision 2026-11-09: remove automatic post-task AI reflection and the daily digest/improvement-task filing
path. Keep normal typed outcomes/usage, retained evidence and explicit analysis when requested; preserve grounded
implementation/review findings without automatic retrospective task generation. tl-8bh9.5.5 owns deletion of the
model calls, scheduler, private state/config and intake path, not replacement with another automatic summarizer.
The [final coverage and implementation sequence](tl-8bh9/coverage.md) distinguishes superseded task scopes from
delivered code, records unverified areas and orders bounded successor slices. Source implementation remains pending.


Owner direction 2026-11-09: remove factory Git memoization by simplifying operation data flow, not by accepting
repeated Git processes or relocating the cache to shelf. Pass already established identity, pinned inputs and
mutation results; observe current state only where the operation requires it, with conditional mutation protection.
Operation-level traces verify redundant reads are gone. See [Git strategy](tl-8bh9.9/plan.md).


Clarification 2026-11-09: derived task branch names and already established operation values can remain in ordinary
memory without a Git memo subsystem. Mutable Git observations do not become valid for the entire factory lifetime;
required unfinished-operation references still survive normal restart in factory.db. Retired planner preflight
probes are separate from the agreed minimal plan completion contract, implemented with the actual plan step.


Owner accepted 2026-11-09: remove proactive RAM-threshold admission initially, retain a small lifetime-scoped
keep-awake capability for an unattended running factory (including waits), and retain correct-checkout binding
while removing redundant guard/probe machinery. Planner probe retirement, minimal plan completion checks and
migration removal remain agreed. None of these features is implemented by the CLI-only foundation.


Owner accepted 2026-11-09: repository checks use the host’s normal networking. Remove factory-managed
check network isolation and its settings/exceptions/probes. Harness sandbox permissions are separate.
