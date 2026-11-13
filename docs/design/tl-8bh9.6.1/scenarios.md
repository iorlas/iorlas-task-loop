# Question-flow scenario walkthroughs

Status: **design**. Accepted decisions and pending proposals are distinguished below; historical source observations are not a delivery receipt. Explicit holds remain in force except where superseded.

The [settled working design](balanced-design.md) records the conclusion after three further Astra balancing rounds;
it supersedes conflicting exploratory recommendations here. This document remains supporting analysis.

Task: tl-8bh9.6.1. Owner requested realistic scenarios with Astra, 2026-11-08.
These are proposed design walkthroughs, not runtime tests or claims that current code passes them.
The owner selected the factory dashboard as the initial answering surface. Backend encoding is still open.

## Working model being evaluated

A task is the entry point for requirements/specification and question discussion. Each independently answerable
question has its own reference, revision, typed options/visual references where needed and answer association.
One readable question/answer comment per association remains the baseline; UI submission can batch many together.
Question presentation is stored once; ordinary discussion is not copied into a second full-history metadata store.

The factory records the current step, conversation, execution attempt and outstanding input references locally.
Owner answers and pending incorporation into the requirements are portable work data. Runtime answer-processing
bookkeeping is not. Git carries code/plans/lasting design decisions; local evidence bytes need not move machines.

## Important revision to the fixed-batch proposal

Waiting for a complete round is efficient when the owner can answer it. It cannot be an unconditional barrier:
ask-back and conditional questions require additional agent work before all answers exist. Recommend short rounds
and deliberate submission, rather than automatic execution after every selection or a question dependency graph.

The owner composes choices/free-text answers and clarification requests, then uses one Send to agent action.
An explicit partial submission may request explanation, investigation or progress on unblocked work. It does not
answer the remaining questions or remove their completion barriers. Preserve/revise outstanding questions explicitly.
Each actual continuation is another attempt in the same unfinished step/session when available.

Unsent edits are drafts, not authoritative answers. Saving a draft must not make it apply after DB loss/new-PC
planning. Accepted answers become portable on explicit submission. Draft retention/encoding is UI implementation
work, not another task-question lifecycle. Do not introduce accepted-but-not-applicable saved answers without a
concrete need. No execution per field selection, text edit, draft save, poll or ordinary discussion comment.

## Scenario matrix

| Scenario | Owner experience | Factory flow and invariant | AI execution |
|---|---|---|---|
| 1. Three independent answers | Choose/type answers, send once. | Persist explicit question/revision associations, then request one continuation. | One continuation. |
| 2. Twenty questions, five drafted | See progress and which remain; keep working on answers. | Drafts do not resolve questions or launch execution. Large questionnaires should be justified, not the prompt default. | None until submission. |
| 3. Submit five answers deliberately | Send the available answers and ask for useful next work. | Persist those answers; resume with unanswered references still visible. Do not invent the other fifteen answers or complete blocked work. | One requested continuation. |
| 4. Q2 depends on Q1 | First choose SSO versus email login; provider questions follow only when relevant. | Ask high-leverage questions in successive rounds. Supersede irrelevant questions with a reason. No generic question DAG. | One per useful round, not per keystroke. |
| 5. Ask back while other questions remain | Submit Q2 answer plus request explanation of Q1. | Resume to explain/provide evidence while Q1 remains open. Full-batch barrier would deadlock this. | One clarification attempt. |
| 6. Custom alternative | Type neither red nor green; use navigation blue. | Preserve exact answer, interpret it and incorporate the requirement. Suggested options are not exhaustive. | Normal continuation. |
| 7. Ambiguous answer | Write use blue unless the customer prefers the other one. | Preserve the answer and ask a focused follow-up. Human ambiguity is not malformed JSON or a schema-repair loop. | One justified clarification. |
| 8. Question changes before answer | Old tab shows an outdated comparison. | Reject stale question/revision submission; preserve any explanatory draft for owner correction. Do not apply it to changed options. | None merely for conflict. |
| 9. Answer corrected before execution | New answer becomes current; old wording remains visible. | Use latest applicable revision and coalesce queued continuation where possible. | One useful continuation. |
| 10. Answer corrected during execution | Show correction pending incorporation. | Keep one writer. Reconcile at a controlled boundary, or use existing explicit stop if owner requests interruption. Do not accept affected work against a superseded requirement. | Existing attempt, then necessary continuation. |
| 11. Double click/concurrent conflicting answers | Repeated submit returns saved result; conflicting answer asks for refresh/correction. | Use supported conditional update/idempotent submission semantics. Verify adapter guarantees; do not claim read/write/read is CAS or provider execution is exactly once. | At most one intended scheduling action. |
| 12. Task changes while waiting | Show that relevant work changed. | Reassess affected questions. Unrelated title/label edits need not invalidate all answers; a changed brief is never an answer. | Reassessment on requested continuation. |
| 13. Answer saved, spec not yet updated, then crash | Answer remains visible as awaiting incorporation. | Durable work state prevents fresh planning overlooking the response. Local attempt-consumption state alone is insufficient. | Resume or new-PC normal planning. |
| 14. Waiting factory restarts with intactDB | Same pending round/session remains; no duplicate questions. | Restore current step/input references; wait or dispatch an already submitted response without replaying runtime logs. | None merely for restart. |
| 15. Crash with a surviving agent | Show the existing attempt still running; new input queued. | Discover existing execution through agent interface before dispatch; same execution keeps its attempt. Unavailable status is not no worker. | No competing launch. |
| 16. Execution finished before crash | Previously saved result is collected. | Keep its attempt/result; collection is not another try. Unknown launch/result state remains explicit. | None merely to collect output. |
| 17. New PC, only Git and tasks | Discover current requirements, outstanding questions and submitted answers. | Start normal planning; incorporate outstanding responses. Old DB/session/history/slots/artifacts are not prerequisites. | Normal workflow can repeat. |
| 18. Missing preview on new PC | Clearly unavailable with useful description. | Use sufficient text, recreate evidence or clarify. No mandatory media migration or implicit selection. | Only if recreation/reasoning needed. |
| 19. Preview changed after display | Old selection clearly refers to old evidence. | Materially changed comparison requires revision/replacement and explicit reassessment; do not reinterpret second screenshot. | Only needed clarification. |
| 20. Quota/account unavailable after submission | Answers saved; separate execution waiting reason shown. | Wait locally without reopening questions, auto-answering or losing inputs. If session cannot resume, report replacement explicitly and preserve context. | No polling/keepalive model calls. |
| 21. Ordinary native comment | Teammate says green might work in discussion. | Display discussion; do not infer an explicit owner answer or trigger execution from prose. | None automatically. |
| 22. Ignore/defer/delegate | Leave open, explicitly defer, or say choose for me. | Silence is not an answer. Explicit delegation allows judgment within task scope; deferral does not silently remove a real requirement. | Only requested work. |
| 23. Response arrives after task completed | Preserve discussion and show completed status. | No automatic reopen or new implementation; changed scope needs explicit reopen/follow-up decision. | None automatically. |
| 24. Stop races with response | Response remains saved; factory stays stopped. | Work information does not override operator execution control. Next explicit start can use submitted responses. | None while intentionally stopped. |
| 25. Persistence partially fails | Show which submission was saved versus refused, retain input for retry. | Never launch against answers not durably accepted. Acknowledge actual adapter failure/atomicity limits; no fabricated complete batch. | None until intended input is durable. |

## Experience conclusions

Use a few high-leverage questions per round as agent guidance, not a hard product limit. Long legitimate forms can
exist; avoid speculative questions that an earlier answer will make irrelevant. Show outstanding questions and
draft/submitted/incorporation progress without asking the owner to administer a complicated state machine.

One Send action can carry answers and ask-back messages. Submission intent is explicit: an answer and a request
for more information are not inferred solely from arbitrary prose. Exact field/button arrangement remains UI design;
do not add a separate button, question kind or backend feature for every scenario.

The resumed agent receives exact relevant questions, revisions, answers and clarification messages, plus code/plan
and evidence references. It does not guess from the last comments or replay the full discussion. Factory code can
wait, queue and deduplicate scheduling without using AI to poll.

After a definitive response, the agent updates authoritative requirements/plan and records incorporation. Pending
incorporation remains portable. Approval, if required, has an explicit outcome; closed/answered alone does not mean
approved or implemented. ADR promotion remains deliberate for lasting design rules, not part of every response.

## Engineering questions still to verify

Verify native stable references, typed question-presentation storage, real conflicting-update behavior, acknowledgement
and multi-write failure windows, and scheduling deduplication with the existing task/agent interfaces. Reuse current
gallery/choices/free-text, task operations and execution state. No question DAG, global approval platform, new daemon,
generic migration/recovery system, whole-discussion JSON mirror or automatic comment interpretation is proposed.

The above rules are recommendations from scenario review, not owner-approved source changes. Record owner choices
in the task and existing design before scoped implementation and focused tests.
