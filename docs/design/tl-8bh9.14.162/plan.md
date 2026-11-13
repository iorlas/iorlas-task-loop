# Require a comment for human changes to a task's course

Task: `tl-8bh9.14.162`. Status: planned, 2026-11-13.

Every human restart, hold answer, abandon and clear must have a confirmed task-tracker
comment. Store its author, tracker timestamp and text with the cause, link it to the
attempt it answers or abandons, and show it in the attempt rail and drawer. Restoring
an approval label alone must leave a held task saying **waiting for your answer**.
This document specifies implementation; it does not claim that the behavior is built.

## Current code and prerequisites

Read the foundation plan (`tl-8bh9.8.7`), glossary and justfile. The relevant current
behavior is:

- `hold_status.reingests` accepts a finished hold when the round uses its original
  approval label. `task_status.restartable` combines that with tracker readiness;
  neither reads a person's answer. A returned manual abandon is also restartable
  on readiness alone. `round._admit` uses these rules to select fresh admissions.
- `operations._answered_hold` refuses some manual starts of held tasks but treats
  a round's label as the answer. `StartRequest` carries no reason or comment.
  `operations.release_task` can abandon the land candidate, checks and agent attempt
  without a reason; the CLI exposes only `--abandon`.
- `hold._abandoned` currently releases first and posts the factory's hold comment
  afterwards. `HoldStore` records comment timing, not the comment's identity and
  contents. `clear_holds` removes `held` after a replacement attempt exists.
- `tracker.task_comments` maps comments to author/time/text without a stable comment
  reference. `TrackerHolds.comment` returns only completion/missing/unavailable.
  Human attribution and confirmed comment references need an owning adapter contract.
- `dash_task` and the rail/drawer display inferred repeat/restart reasons. The HTTP
  server in this checkout exposes reads; accept/needs-changes actions are not built.

The owner names `.145` (stored causes), `.121` (human requests) and `.157` (dashboard
accept/needs-changes). Their implementations and design directories are absent here.
Implement this task against the shared operations and records delivered by `.145`
and `.121`; integrate the `.157` actions once that surface exists. Reinspect their
contracts before source work and use their owners rather than adding a competing
request queue, cause table or dashboard decision operation. Their absence does not
make this task a delivery of those whole features. The supplied task description is
the requirements source: the local `bd show tl-8bh9.14.162` returned not found during
planning, so no tracker status, claim or dependency was changed.

## Comment and cause contract

Extend the existing stored-cause and human-request contracts with the confirmed
tracker comment reference and an immutable snapshot of its author, tracker timestamp
and exact text. Preserve the tracker's identity/scope and the target attempt/hold;
when a restart creates a new plan attempt, link that successor to the same cause.
Use a stable tracker comment identifier where available. If the pinned client omits
it, extend the owning client/adapter contract; do not identify comments by parsing
display output or by guessing from matching prose. Discussion stays tracker-owned;
factory.db owns the accepted request, its application and its link to execution.

Validate non-whitespace text before posting or changing execution state. Preserve
the supplied prose rather than replacing it with “restarted at plan”. A validated
reason is still pending until the tracker confirms the comment exists. A label,
task description edit, local reason string or log line is never a substitute.

For a hold answer read directly from the tracker, require a nonempty comment by a
person, strictly newer than the current hold. Use `.121`'s explicit human provenance
contract, mapped by the tracker adapter; merely being a different author string from
`taskloop` is insufficient. Factory/bot comments never authorize a restart. Compare
validated tracker times against the stored hold boundary, including the factory's
hold comment when present; equal or unparseable times do not qualify. Choose the
latest eligible comment deterministically using tracker time and stable identity.

An answer applies only to its current hold/attempt. Accept it once under a current
attempt/revision fence. It cannot authorize a later hold or be reused for a second
restart. A restart after a manual abandon needs a separate restart comment newer
than that abandon; the abandon's own comment does not request restarting it.
No natural-language intent classifier or special comment syntax is required: for
tracker-driven hold answers, the newer human comment plus existing readiness and
approval conditions is the answer the owner specified.

## One application path and durable ordering

Route CLI, round ingestion and dashboard human actions through `.121`'s typed
application operation, attaching `.145`'s cause. Enforce the comment requirement
inside that operation and at the transition fence, not only in a form or parser.
Represent new action/result/reason vocabularies with enums and one edge codec each;
use Pydantic v2 at request, tracker-interchange and database-row edges. Introduce no
new glossary term or general event framework.

For a CLI/dashboard request, record the fenced pending intent in a short transaction,
post the person's comment outside the transaction, reconcile its confirmed tracker
identity, and persist the comment/cause before applying the course change. For an
existing tracker answer, validate and record that comment without posting a duplicate.
Do not claim, reserve a slot, admit a successor, abandon any release half, remove
`held` or mark a human request applied before its comment is confirmed and linked.
Continue to use the existing admission/release operations and their safety checks.

Use the shared outbox/request identity for retry and reconciliation. A crash after
posting but before storing must find and adopt that comment, not post a second one.
If the tracker cannot establish whether posting succeeded, keep the request pending
and execution unchanged. Do not use a lease expiry alone as permission to repost.
Recheck the current attempt and hold after external IO; a stale answer must not
affect newer work. Competing rounds, `tl step next` and dashboard requests can accept
and apply a comment only once. If admission later fails for capacity or another
transient reason, retain the accepted cause for retry against that same attempt.
No external action runs inside a database write transaction; add no compensation chain.

The same invariant covers the automatic abandon used to establish a hold: reuse
the stored factory cause and a confirmed factory-authored tracker comment before
recording its abandon. Adapt the hold comment to describe the intended hold without
claiming a release already succeeded; report the eventual release result through
the owning stored state. That factory comment never counts as the human answer.
A missing/unwritable tracker task cannot produce a successful comment-required
abandon/clear; return a typed explained result and preserve the pending intent.
Ordinary settled releases and observation of surviving executions retain their
existing safety behavior and do not become human restart requests.

## Round and status behavior

Keep `task_status` the single pure decision shared by rounds, CLI and dashboard.
Feed it typed accepted-answer facts from the owning reader; do not add tracker IO
to `restartable`, derive control state from logs, or make board GETs apply answers.
Rounds inspect comments only for tasks awaiting an answer that could otherwise be
admitted, and pass eligible comments through the shared application operation.

A held task remains held without a qualifying comment even if `held` is removed
and `real-run-1` (or the configured approval label) is re-added. Show “waiting for
your answer” in the round explanation, CLI status, board and drawer. A tracker
read failure is an explained unavailable result, never permission to start.

A qualifying comment does not waive tracker readiness, the original approval-label
rule, claim ownership, slot availability or in-flight limits. A different round
label cannot take the task. A hand-added `held` on a task without a factory hold
keeps its existing pause meaning. After the accepted answer admits a successor,
`clear_holds` uses that same recorded answer/cause to remove the old hold label;
it must not erase a newer hold or require a second comment for mechanical completion
of the same request. An explicit human clear needs its own comment-bearing request.

Manual abandonment also stays abandoned until a distinct comment-bearing restart
request is accepted; labels cannot silently undo the person's abandon. Routine
repeats, advances, automatic checks retries and intact-DB process reconciliation
keep their existing causes and do not fabricate human comments.

## CLI and dashboard

Add `--reason TEXT` to `tl step release` and `tl step start`. Require it with
`release --abandon`, and require it when start would create a fresh plan attempt
after an abandon, including a completed hold. Missing/blank reasons fail before
any comment write or execution mutation, including before the candidate/checks
halves of release. Keep ordinary first starts and settled releases available
without a reason. Manual start with a reason after a completed hold is an explicit
answer through the shared operation; an unfinished hold still refuses a restart.
Rerunning a partially applied abandon uses its existing confirmed comment and
request, with the required reason matching that request, rather than posting again.

Dashboard restart, answer, abandon, clear and `.157` accept/needs-changes actions
collect nonempty comment text and submit the same typed request with its target
attempt/revision and retry identity. The server enforces the requirement even for
direct requests. Disable submission of blank text, retain entered text on failure,
show pending versus applied, and reject stale targets explicitly. Reuse `.121`'s
local write protections and actor attribution; the dashboard must not write labels
directly or substitute the factory actor for the requesting person.

Extend the stored-cause read projections used by `dash_model`, `dash_task`,
`dash_board`, `rail.js` and `drawer.js`. Show the action, actual comment text,
author and timestamp beside its held/abandoned attempt and the resulting restart;
make the relationship navigable to that attempt and the tracker comment when the
adapter supplies a link. Render user prose as text. The drawer must show the stored
cause even when live tracker discussion cannot be read; never replace it with an
inferred generic reason. Update CLI help, hold guidance and README examples that
currently say adding the label alone answers a hold. Product wording states the
situation and decision in words, without asking the owner to run a CLI command.

## Implementation and verification

Implement in bounded cuts: extend the prerequisite cause/request contracts and
comment adapter first; enforce transactional comment-before-transition rules next;
wire round/status and CLI consumers; integrate the dashboard actions and projections;
then update affected guidance. Only each feature's owning store touches its tables.
If the schema changes, use the repository's drain-and-discard upgrade boundary;
do not add migrations, reconstruction or compatibility readers. Keep the runtime
version fixed until restart and retain source/function/test size caps.

Use semantic tracker/process/Git fakes and focused pytest behavior tests:

- Removing `held` and re-adding approval across repeated rounds creates no claim,
  reservation or successor and says “waiting for your answer”. Test missing, blank,
  old, equal-time, malformed-time and bot comments, another round label, and tracker
  failures. A newer human comment plus normal eligibility restarts exactly once at
  plan, links old and new attempts to the comment, and clears only the old hold.
- A manually abandoned task does not restart from labels or its abandon comment.
  A separate restart comment does; later holds cannot reuse it. A valid answer that
  initially lacks a free slot retains its cause and succeeds later without reposting.
- Every manual action rejects an absent/blank comment through CLI, HTTP and direct
  application calls before side effects. Exercise completed and unfinished holds,
  the land/checks/agent abandon sequence, ordinary release and initial start.
- Simulate crashes before posting, after posting/before recording, after cause
  recording and between release halves; reopen intact state and prove one comment,
  one applied action and the original attribution. Race competing consumers and a
  newer hold/attempt. Unknown posting results remain pending without duplicate posts.
- An automatic hold links its factory comment before abandon and cannot answer
  itself. Tracker write failure or a missing task produces no uncommented abandon.
- Rail/drawer projections and UI actions show exact author/time/text, distinguish
  abandon from restart, link the targeted attempt, safely render prose and retain
  the stored cause while tracker reads fail. Test `.157` accept/needs-changes through
  the shared request path, including blank and stale submissions.

Update the existing hold/round/status/operation/CLI/dashboard contract tests rather
than cloning their infrastructure; add cross-boundary cases where those suites do
not cover the invariant. Run the relevant focused tests during implementation, then
`just check` and `just test` as defined in the inspected justfile. These use the
successor's own installed package and focused `tests/cli`, `tests/steps`, `tests/rules`
directories. Any manual executable check follows `just install` and uses
`uv run --frozen --no-sync python -I -m taskloop ...`. Do not run live or whole-suite
tests, import baseline code, spawn processes directly or introduce new dependencies.

Acceptance is complete only when all human course changes have their confirmed,
stored and visible tracker comment, label-only changes cannot restart held work,
all entry points share enforcement, and both required gates pass. This planning
change writes only this file; code gates are for the subsequent implementation.
