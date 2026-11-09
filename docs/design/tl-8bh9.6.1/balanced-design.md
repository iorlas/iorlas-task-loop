# Human input: settled working design

2026-11-08. The owner requested several critical balancing rounds with Astra, a strong recommendation, then moving
on. Three further rounds produced this baseline. It is delegated design judgment, not a claim of source implementation
or a verbatim owner approval of each API detail. It supersedes conflicting exploratory recommendations in plan.md,
options.md and scenarios.md. Existing agreed portability, restart and task-specification principles remain in force.

## Opinion

Use one human-input interaction in the existing asks component. A request presents what needs input, with optional
choices and artifacts. A response is explicitly submitted human input: a choice, free text, a question back or a mix.
Existing domain handlers determine what the input means and where its consequences belong. Neither the owner nor
the agent selects a storage destination. No configurable consumer registry, new HITL service or workflow DSL.

Use response as the general word, answer for responding to a question, decision for an actual choice, and result
for execution output. Do not create separate durable types simply to enforce those ordinary language distinctions.
An actual execution approval still requires an explicit typed outcome and exact execution/allowance scope; free
text such as looks good does not authorize spending or actions. Submission alone means authentic input, not approval.

## Ownership

| Meaning | Authority |
|---|---|
| Current task requirements | Work task and explicitly linked specification |
| Work request, relevant submitted responses and historical discussion | Task-associated portable work data through task adapter |
| Outstanding incorporation of a work response | Portable task-associated work state |
| Local execution wait, attempt/session, processed input and operator permission | factory.db |
| Agreed task approach | Git plan |
| Lasting architecture rule | Existing Git design decision or ADR |
| Media bytes | Existing artifact store; references/descriptions can travel with task data |

Discussion and the resulting specification are different facts. Preserve original owner wording, and update current
requirements so later work need not interpret every old comment. An ADR is downstream documentation of a warranted
rule, not another generic response store. No automatic separate ADR-writing task for every response.

## Interaction and continuation

- Prefer a few high-leverage questions per presentation, without a hard product cap. Avoid questions that an earlier
  decision may render irrelevant. A round is UI grouping, not a new persistent workflow entity.
- One independently answerable request/comment and explicitly linked response comments remain the initial granularity.
  UI submission can batch several responses; do not promise atomic multi-question persistence if the backend cannot.
- Drafts are presentation state, not authoritative answers or authorization. One Send to agent submits a deliberate
  response and requests one continuation. No AI invocation per selection, draft save or poll.
- Allow partial submissions and ask-back. The resumed agent can explain/investigate or advance unblocked work, while
  outstanding required inputs remain blockers. Do not require all questions answered before the agent can explain one.
- Work responses need not be machine-classified as answer versus ask-back. The agent interprets their meaning; the
  factory validates explicit request/response references and outcomes rather than guessing from prose.
- The next attempt receives relevant requests/responses since incorporation and sufficient discussion context.
  Latest response only can be insufficient: darker blue depends on the earlier use blue. Do not replay all task history.

Actual schema-format repair remains inside the agent interface. Human ambiguity is not malformed structured output
and does not trigger automatic schema re-asks. Normal checks/review assess the interpreted work against requirements.

## Minimal durable state and resolution

Keep a canonical current typed presentation payload: request prose, stable choice IDs/labels and visual references.
Keep explicit request revision/response references and enough portable outstanding-work information for fresh planning.
Do not copy whole discussion history or runtime transitions into metadata. Native discussion can remain canonical
history; exact payload/index encoding is an adapter investigation, not another owner design question.

An outstanding request with no submitted response is awaiting input; one with an unincorporated response needs work.
The owner need not manage separate received/incorporated states. Record which response revision was incorporated;
a later correction makes affected work outstanding again rather than being erased by an older resolution.

Interpretation and proposed requirement changes are agent work. The factory/coordinator applies task mutations via
its typed task port; workers do not need direct Beads-write permission. Update the task/specification and relevant
plan before resolving the processed response revision. If interrupted between writes, ordinary continuation can
inspect the saved work and finish; do not add a distributed transaction or history reconstruction service.

With intact factory.db, resume the unfinished step/session normally, using a new attempt only for a new execution.
After DB discard/new PC, planning reads current requirements and outstanding work requests/responses directly.
Operator stop wins over response arrival; responses remain saved. Quota waits do not reopen questions. Missing
essential media requires recreation or clarification; no mandatory artifact migration or automatic Git images.

## Reuse existing components

- Raiser creates a request with appropriate task/work context and typed presentation.
- Intake validates explicit submission, persists it through its owner and reports actual success/conflict/failure.
- Existing asks flow supplies outstanding work context and incorporates responses through normal task/spec changes.
- Task adapter exposes adequate comment references, read failures and real update/conflict guarantees.
- Scheduler/session machinery owns continuation, local waiting, cancellation, attempts and budgets.
- Dashboard/artifact readers render the request/response and previews. Do not add a view/handler for every edge case.

Remove or simplify the mixed one-current-Ask-per-task lifecycle, operational comment-ledger rebuilding, mandatory
stick classifications and unsupported task-edit-as-answer behavior. Similarity, cause taxonomy and citation tallies
are not essential to this interaction; retain extras only when their purpose justifies their cost. Native question
issues/gates remain adapter options when useful, not required concepts or a task per trivial question.

## Implementation risks to verify

1. A portable response can be saved before local dispatch. Restart must compare current submitted responses with
   waiting work and resume normally, without runtime-ledger replay or model polling.
2. Posting a comment is not necessarily completed submission: the authoritative request/response association must
   also be persisted. Define the acknowledgement point and report partial writes accurately; do not invent atomicity.
3. Resolution must use the response revision actually processed, so concurrent corrections remain outstanding.
   Late discussion on a completed task must not silently reopen implementation.
4. Verify task adapter comment IDs, unavailable reads, update guards and question-presentation encoding. Session
   resumption and launch acknowledgement remain the existing agent/restart contract review, not another service.

These are bounded implementation questions. They do not require another generic architecture round before moving
to other codebase areas. Scenario walkthroughs remain the validation cases for the chosen implementation.
