# Task questions, answers and local waits

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

> STORE scope update, 2026-11-09: Denis accepted the identity/lifecycle contract and lifted its design hold for
> [reconciled STORE slices](../tl-sqd3.26/plan.md) only. Earlier blanket-hold statements below describe prior review history.
> Explicit dependencies still gate affected actions; historical migration/compatibility scope and unrelated holds remain excluded.

The [settled working design](balanced-design.md) records the conclusion after three further Astra balancing rounds;
it supersedes conflicting exploratory recommendations here. This document remains supporting analysis.

Task: tl-8bh9.6.1. Full-context Astra review requested by the owner, 2026-11-08.
The portable-work/local-wait boundary is agreed. The detailed API and simplification strategy below are recommendations
for owner review, not an implemented system or a commitment to the exact method names.

Later review correction: the full-discussion-in-metadata proposal below overreaches. The owner supplied native Beads
human-question capabilities and requested a deeper Astra review independent of backend features. The owner then
selected factory dashboard initially for answering. [Options and revised recommendation](options.md) supersedes
the earlier default of copying complete question discussion/history into structured metadata. Storage encoding
remains an adapter investigation; do not implement the earlier proposal as a settled schema.

## Purpose

Preserve useful planning and implementation decisions with the work task, including choices, screenshots,
clarification discussion and free-text alternatives. A task may have several questions. A question is neither
another work task nor automatically an ADR. Keep local execution waiting/answer-application state separate.

## Canonical ownership

| Fact | Owner |
|---|---|
| Question, context, choices, attachment references, replies and answer history | Task service port; Beads adapter initially |
| Which step waits and which answer revision its attempt incorporated | factory.db |
| Screenshot/media bytes | Existing artifact writer/reader; retained on the original host |
| Resulting task approach | Committed docs/design/<task-id>/plan.md |
| Lasting architecture rule affecting other work | Existing versioned design decision or docs/adr |
| Quota, capacity, account and local machine waits | factory.db |

The task-service port is the existing domain boundary, not a new network service. Task lookup should expose its
questions directly, rather than require reading factory history or identifying a single current ask.

## Small question model

Each question has its own stable task-local reference, self-contained text/context, optional choices with stable
IDs and optional attachment references. Replies and answers retain attribution and timestamps. Answers accept
a selected choice, free text or both; choices are suggestions rather than an exhaustive answer schema.

Distinguish a clarification reply from an answer. "Show both options in dark mode" keeps the question open;
"Neither, use the existing navigation blue" answers it. Several questions may be open concurrently. An execution
may need answers to a subset; do not keep the current one-document-per-task limitation as the domain model.

Start with open, answered and withdrawn meanings. Preserve prior answers when corrected. If a question's substance
changes, replace it explicitly and link the old question rather than silently changing what an old answer meant.
Use an expected revision/reference to reject stale or conflicting submissions. The adapter must actually enforce
conditional updates or report a conflict; read/write/read is not proof of atomic comparison.

## Suggested question-component operations

Boundary refinement after owner discussion: owning questions as task-associated work data does not require the core
task-backend contract to implement interactive question behavior. The existing asks component should own that API
and compose ordinary task-port operations for fields, comments and metadata. Beads remains an adapter for those
primitives. The following are conceptual question operations, not requirements to add all of them to Tasks itself.

```text
questions(task)
question(task, question_id)
ask(task, text, context?, choices?, artifacts?)
reply(task, question_id, text, artifacts?)
answer(task, question_id, expected_revision, choice_id?, text?)
withdraw(task, question_id, expected_revision, reason)
```

Exact signatures and batching remain implementation design. Address questions explicitly, not as "answer whatever
ask is current". A UI option click and a free-text answer use the same answer operation. Persist the answer before
dependent execution can use it. Ordinary comments are not execution commands and are not parsed back as a ledger.

Prefer complete structured records using native task-backend metadata or an equivalent supported adapter mechanism.
Human-readable comments can render questions/answers for ordinary tracker use, but do not become a second state
authority. Verify Beads payload/update guarantees before selecting its encoding. Do not create a work task per
question, event-source workflow bookkeeping in comments, or make Git commits part of answering a question.

## Execution and continuation

An agent can return a valid needs-input result carrying one or more work questions; that is not malformed output
requiring schema repair. The factory persists the question through the task port and records its local step wait.
Answer application is local execution metadata; it must never hide or delete the answer from later planners.
Resume the unfinished step/session with explicit answer references and text, using a new attempt for a new execution.
After DB discard or on a new PC, normal planning reads the task's questions/answers without replaying old runtime events.

An owner reply asking for additional examples may require another planning attempt to supply them while the question
remains open. Do not treat that clarification request as a final choice. Planning may need authorized evidence tools
without permission to change product source; inspect current role/tool capability restrictions before assuming this
already works. No separate helper-agent service is required by this interaction.

Ask when missing information materially changes the work or needs owner judgment. Use sensible reversible defaults
for routine implementation choices. Blocking is a relationship to unfinished work, not a large taxonomy of question kinds.
A task edit is not an answer; inspect relevant changes rather than automatically consume every unanswered question
when the task brief hash changes.

## Visual example and portability

Question Q12 asks whether the primary button should be red or green, with labeled screenshot references. The owner
can select green, select green with "make it darker", answer "use navigation blue", or request dark-mode previews.
Keep the full exchange with Q12. Update the plan with the chosen task design. Do not create an ADR unless the choice
establishes a broader rule such as repo-wide semantic color usage.

Attachment references and descriptive captions travel with task data; local artifact bytes need not. The UI must
show unavailable evidence explicitly. On a new PC, use self-contained text when sufficient, otherwise recreate
evidence or ask a focused clarification. Changed comparison evidence may require a replacement question; do not
apply a choice to a different image silently. No universal regeneration engine, automatic Git image commits or
mandatory artifact migration. Portable attachments can remain a future adapter capability.

## Existing code: keep, replace and assess

Installed CLI verified on 2026-11-08: Beads exposes comments, task description/acceptance/design/notes fields,
labels/status, arbitrary JSON metadata and per-key metadata updates. The first help check missed human respond:
the subsequent installed-CLI check confirms human list/respond/dismiss/stats, with respond adding a comment and
closing that issue. Gate resolve is equivalent to closing its blocker, not an approval verdict. The existing Beads
port already exposes comments and metadata operations; its patch currently omits
an acceptance-criteria field even though the CLI supports it, so assess that ordinary field update gap.
CLI condition guards cover assignee/status; they do not establish arbitrary question-revision compare-and-set.
Use native primitives without claiming Beads has a ready-made interactive question subsystem.

Verified source: kernel/ask.py already represents options, detail, thread, artifacts and typed answers;
dash/static/js/ui/ask.js renders gallery/choices/own-words input. Preserve these useful interactions.
AskStore currently keeps one current full ask per task in factory.db. ledgercomments.py mirrors selected owner
LedgerEntry actions into task comments, but LedgerEntry lacks options/artifacts/detail/thread and engine raises
remain DB-only. The mirror cannot preserve the full question after DB loss. intake.py installs its comment hook.

Replace that mixed authority and comment-ledger rebuilding with complete task-owned question records plus local
execution waits. Preserve explicit question identity and first-answer/stale-answer protections. Inspect or remove
owner-cause taxonomies, mandatory stick classifications, similarity matching, citation tallies and separate ADR
writing tasks where their purpose does not justify the code. Do not turn them into a replacement generic framework.

ADRs remain deliberate versioned documentation. Link a relevant question to a warranted decision document; do not
make every answer an ADR. The held STORE ADR task tl-sqd3.26.9 is related and remains unstarted.

## Verification scope

Before source changes, verify task-adapter storage/atomicity and the actual dashboard/workflow read paths. Focused
tests should cover concurrent/stale answers, several questions, free-text alternatives, clarification replies,
answer corrections, DB-loss/new-PC task context, missing visual evidence and runtime answer application. Use existing
artifact and task ports. Normal repo gates apply to implementation; no full/live suite is authorized by this review.
