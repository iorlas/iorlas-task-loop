# Questions and decisions: backend-neutral options

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

The [settled working design](balanced-design.md) records the conclusion after three further Astra balancing rounds;
it supersedes conflicting exploratory recommendations here. This document remains supporting analysis.

Full-context Astra reconsideration requested by the owner, 2026-11-08. Question handling is design work;
no source implementation or settled storage encoding. Owner product choice: answer in the factory dashboard initially.

## Invariants and distinct facts

- The work task is the entry point for current requirements, acceptance criteria and explicitly linked specifications.
- Question discussion records what was considered and answered; the answer belongs to its question.
- An answer changing requirements must be incorporated into the task/specification and relevant plan. Later agents
  should not reconstruct current requirements by interpreting the entire discussion history.
- Pending work questions and answers survive task sync and a new PC without old factory.db/artifacts.
- Runtime waits, attempt/session association and which response an execution processed are local database state.
- Native task discussion is legitimate work history. Reading it is not rebuilding factory state from runtime logs.
- Plans and warranted architecture decisions are versioned in Git. Not every answer becomes an ADR or another task.

## Alternatives

| Strategy | Benefit | Cost or failure mode |
|---|---|---|
| Plain task comments followed by requirement edits | Natural, little new code, familiar task-manager discussion | A free-text reply is not unambiguously an answer; pending questions and answer applicability are difficult to determine without an explicit action/convention. |
| Task-attached questions with native discussion and small structured state | Retains existing factory choices/gallery/replies, several questions without extra work tasks | Requires stable references and a small adapter convention; copying all history into metadata would become another discussion database. |
| Separate question issues with links/dependencies | Native identity, status, discussion and sometimes readiness blocking | Issue noise; parent/child is not necessarily a dependency; closed does not mean approved; adapters expose different features. |
| Git question/decision files linked from task | Versioned and reviewable | Answering requires branch/worktree/commit coordination; disproportionate for ordinary clarifications and concurrent dashboard replies. |

No option is intrinsically idiomatic for every backend. Select the domain behavior and answering surface first;
backend features inform implementation, not the domain vocabulary. Do not build to the intersection of hypothetical
future backends or require them to implement Beads commands.

## Revised recommendation

For the selected dashboard-first interaction, use task-attached questions by default, with ordinary task discussion
as the decision trail and only the structured facts needed for UI and deterministic readiness. Do not mirror every
reply/history entry into metadata. Keep task operations generic; the existing asks component owns interaction.
Native comments, fields, threads or issue links are adapter representations, not workflow instructions.

Minimal facts include a stable question reference, the content/revision the owner saw, an explicit answer reference
and unresolved/withdrawn/replaced state. Rich choices and visual references still need an unambiguous representation;
whether that is a controlled question payload, native thread data or a small metadata snapshot is not yet selected.
Do not pretend that arbitrary prose can be parsed reliably or that every platform supplies structured choices.
An explicit dashboard answer may contain a selected choice, free text or both. An ask-back reply is not an answer.

Several questions may be open. An ordinary program waits on the relevant questions and schedules a continuation
when input is ready; it does not spend AI tokens polling or ask Beads to inject comments into a session.
The next execution gets the task/plan and relevant response references/text, not every previous exchange.

Subsequent [scenario walkthroughs](scenarios.md) challenge an unconditional all-questions barrier: explicit ask-back
or partial submission must be able to resume clarification/unblocked work while unanswered blockers remain.
Recommended refinement is short rounds and one deliberate Send action, not an automatic execution per answer.
Drafts are not accepted answers. This refinement is proposed, not a claimed implemented contract.

Separate question issues remain an option when independently useful, not the default for every clarification.
Native human labels or gate primitives can help inside an adapter, but are not mandatory task-contract concepts.
Git remains for agreed plans and lasting decisions, rather than every pending interactive exchange.

## Answer received is not requirements updated

### Proposed comment granularity contract

One independently answerable question is one question comment; its options/context/artifact references stay in
that comment. One explicit answer is one answer comment referencing that question and the content revision the
owner saw. Clarification replies also reference the question but do not resolve it. Do not infer relationships
from comment order, question marks or prose such as "the second one".

The UI can show/submit a batch of questions or answers, and the agent can produce a batch in one execution, but
persist each question/answer association separately. Ten independent questions therefore normally produce ten
question comments and, when answered, ten answer comments. Batching does not require ten model continuations;
schedule one continuation when the answers needed by the waiting work are ready.

Substantive question changes explicitly replace the prior question; answer corrections append a new answer that
supersedes the old one. Preserve history instead of silently editing the meaning of an earlier decision. Exact
native comment reference/revision representation remains adapter work. This is the proposed contract for owner
review, not implemented behavior.

If the owner answers blue and the factory stops before updating a green requirement, a new planner must still see
that clarification awaiting incorporation. This is durable unfinished work, not merely local answer consumption.
Preserve an explicit portable indication of response received/pending incorporation, or keep the clarification
unresolved until its requirement is updated. Exact state representation is open; do not add a state machine for its own sake.

The resumed agent interprets the answer, preserves its original wording, updates the authoritative task/specification
and relevant plan, then records incorporation. If unclear, ask a focused follow-up. Current recommended default is
agent incorporation with visible provenance and normal review, not another mandatory owner approval for every answer.
That default is a recommendation; the owner has not been asked to approve a separate approval flow.

A local attempt may separately record which answer revision it used. Correcting an answer preserves prior discussion
and makes affected requirements/work need reassessment; it does not erase history or silently rewrite completed code.
Changed task content is not an invented answer. Closing a question, approving a design and incorporating a requirement
are distinct meanings even if an adapter uses native closed status for one of them.

## Visual example

Q12 presents red and green previews with descriptive context and artifact references. The owner can pick green,
choose green with "darker", answer "use navigation blue instead", or request dark-mode previews before deciding.
After an actual answer, planning continues and incorporates the chosen color into the canonical requirement/plan.
Only a broader semantic-color policy warrants a design decision/ADR. Link that record; do not maintain two current policies.

Attachment references and useful descriptions travel with task data. Old host media bytes need not. Missing images
are explicit; regenerate or clarify when necessary, and replace/revise the question when comparison evidence changes.
Do not commit every screenshot to Git or require artifact migration as a hidden dependency of task portability.

## Verified adapter evidence and limits

Installed Beads human respond writes a response comment and closes the addressed question issue. It must not be
used to answer a question on an implementation issue if closing that issue is unintended. Gate resolve closes the
blocker; rejection text does not supply branching semantics. Parent/child alone does not establish dependency readiness.

Native Beads comments JSON contains id, issue_id, author, created_at and text. The current Comment port omits id,
and the adapter currently returns an empty list on comment-query failure. A discussion/reference design must expose
usable references and distinguish unavailable reads from no discussion. Do not infer a usable port from native capability.
Backend conditional answer updates and multi-write failure handling still need verification; metadata plus a revision
token does not by itself implement atomic conflict detection.

The current full Ask lives in factory.db. Its mirrored LedgerEntry omits choices/artifacts/detail/thread and engine
raises stay DB-only. The ledger cannot recover information never recorded in it. Replace mixed ownership and runtime
ledger reconstruction rather than expand them. Preserve useful gallery/options/free-text and explicit-answer protection.

## Questions and hypotheses for implementation review

Can current primitives store a question and explicit answer durably without a second discussion system? Verify
stable refs, payload rendering, conflict handling and failure windows in the Beads adapter. Do not assume another
adapter has the same metadata or issue-dependency features; require a coherent adapter contract rather than a new platform.

Would substantial blockers benefit from independent issues? Keep that optional until real usage justifies it.
No migration tooling, question-type taxonomy, generic approval engine, automatic ADR promotion or log reconstruction
is required to implement the selected initial interaction.
