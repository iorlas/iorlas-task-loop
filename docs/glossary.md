# Glossary

Canonical language for the redesign, new documentation and conversation. Updated 2026-11-09.
Use short, familiar GitHub and Git terms where their meanings fit. Keep a factory term when its meaning differs;
do not invent an extra entity to match GitHub's hierarchy. `task` is the owner's choice instead of `issue`.

These definitions name the target concepts. They do not assert that the existing code, CLI, database or dashboard
already uses them. Literal existing identifiers may be cited when discussing that code. A future rename is a hard
cut, with no aliases or old-format readers; coordinate it with the owning redesign task rather than renaming twice.
Ordinary verbs such as "run the checks" remain ordinary English, not additional execution entities.

## Work and execution

| Term | Meaning | Example / distinction |
|---|---|---|
| task | Work to accomplish, with a description, acceptance criteria and status, tracked in the repository's task tracker. | `tl-123`. The tracker backend may be bd; its product name does not name our work. |
| task tracker | The system storing tasks, requirements, dependencies, questions, answers and task discussion. | Currently Beads, accessed through `bd`. A replaceable backend, not another factory service, ChatGPT component or execution queue. |
| design | The decisions about the intended behavior and structure of the system. | A versioned design document records what was chosen and why. |
| plan | The work proposed to accomplish a task and the conditions for completing it. | Planning produces a usable plan committed at `docs/design/<task-id>/plan.md` on the task branch. It is an input to later attempts, not proof that implementation is complete. |
| step | One bounded operation on a task, with inputs, a result and a completion condition. | Plan, implement, check, review, land. Its code is also the step implementation, not a separate "stage" concept. |
| attempt | One concrete execution try at an operation, such as a step or an individual check. | A retry makes another attempt. A coordinator restart observing the same surviving execution does not. A new execution continuing the same conversation is another attempt. An attempt can fail before launch. |
| session | A conversation with an agent, identified by its harness or chat application. | A step can own several sessions. Each agent execution attempt uses one session, which may serve several attempts. Non-agent checks need none. A process ID is not a session ID. |
| agent | The coding assistant asked to perform work through the agent interface. | An agent can plan or implement. An attempt is its execution record; a session is its conversation. |
| harness | The program that runs an agent and exposes its conversation and tools. | Codex CLI, Claude Code or OpenCode. Launching it is an ordinary action, not another product entity named "harness invocation". |
| ask | A question requiring the owner's answer before the task can proceed. | An unclear change needs a decision. The prompt sent to an agent is input, not an ask. |

At the factory level the execution picture is `task -> step -> attempt`. Inside the checks step, individual checks
may also have attempts. The word has one meaning: a try at the named operation, not a new workflow tier.
The record identifies its operation and context; a step attempt can group the results of its internal check attempts.
An attempt refers to its conversation, usage, logs and artifacts where applicable. Sessions may be reused.
Tool calls are actions inside a conversation; they do not automatically become step attempts.
If the agent implementation launches a harness again internally, that try must remain inspectable rather than
being hidden in an aggregate. How those launch records attach is part of the step-attempt design, not a new public noun.

`run` is reserved for literal existing code/CLI names, ordinary English and GitHub's own workflow runs until the
redesign demonstrates a distinct factory concept that needs it. Do not introduce a second name for an attempt.
`job` and `workflow` retain their GitHub meanings when discussing GitHub Actions; they do not add factory entities.

## Repository and machine

| Term | Meaning | Example / distinction |
|---|---|---|
| repo | A registered local Git repository binding, shared by its linked worktrees. | RepoId resolves canonical Git common-directory identity. Remote host/project is display/delivery information; task identity has its own configured backlog scope. Independent clones have separate local bindings. |
| task branch | The Git reference retaining a task's committed plan and code. | Derived as task/<task-id> within its selected repository. It is not a directory, slot or execution; publishing it does not land the task. |
| worktree | A Git checkout linked to a repository, sharing its commits and branches. | Committing in one linked worktree makes the commit available to the others locally; no push is needed for that sharing. |
| workspace | An external or generic name for an execution's working directory; no separate factory entity. | Use worktree for a Git checkout and slot for a reusable managed worktree. Preserve literal names used by external APIs such as GitHub workspace. |
| slot | A managed, reusable worktree reserved for one independently scheduled step attempt at a time. | `s1`. Internal checks may run concurrently. Reservations are local factory state in factory.db; slots are not tracker tasks. Current internal slot tasks are to be retired. |
| factory | The installation that schedules tasks and executes their steps. | It has a dashboard and local execution state; it can serve several repos. |
| host | The machine on which an execution happens. | Do not use this product word for a bundle of collaborators; existing `*Host` Protocols are code names under review. |
| profile | The repo's factory settings in `.task-loop.json`. | Required checks and slot setup. Admission uses the resolved target profile; task checks use the candidate profile, as defined by the agreed configuration strategy. |
| config | Machine-level settings. | Local paths and account settings. Use `profile` for repo settings. |

A GitHub **runner** executes jobs; a slot is not a runner. A separate clone is not a linked worktree.
One primary checkout per repo per machine remains the recorded direction; release and cross-machine behavior are
assessed in the repo/store review. A glossary definition does not introduce a new executor service or process model.

## Checks and delivery

| Term | Meaning | Example / distinction |
|---|---|---|
| check | A named automated validation of the work. | A build, lint command or test command. One check may execute many tests. |
| required checks | The checks that must pass before merging. | Use this phrase instead of a separate "gate" concept. A failed required check prevents the merge. |
| pass | A stored successful check result for its recorded code and inputs. | A failure is a result, never a pass. A missing pass means the check can run again. |
| check key | The inputs that determine whether a stored pass applies. | Code, command, toolchain and relevant environment/inputs; the exact fields belong to the check design. |
| reuse | Use an existing pass when its validity conditions hold. | An optimization, not required recovery state. Do not give it a separate capitalized name such as `Carry`. |
| push | Transfer Git objects and update refs on a remote. | Publish `task/tl-123` so another PC can fetch it. This does not merge it into `main`. |
| merge | Integrate a branch into its base branch. | Squash-merge a completed task into `main`. A direct push is still called a push. |
| land | Finish the task's delivery operation: accepted integration, confirmed task completion and any required task synchronization. | Retry unfinished required actions only. Code can be delivered while task completion remains pending. Merge is integration; push is transport. Publishing an unfinished task branch does not land it. |
| PR | A pull request proposing changes to a base branch. | Use the short form after "pull request" on first use when the audience needs it. |
| merge queue | PRs waiting to merge after their required checks pass. | Detailed queue policy belongs in [its design](design/merge-queue.md), not in vocabulary definitions. The speculative queue remains held. |
| release | A versioned distribution of the software. | Merging source and publishing a release are different actions. A release candidate is the version being evaluated before release. |

A step may own several actions: land owns merge and push. Naming those actions does not make them separate steps
or independent scheduling units. Define a step by its purpose and completion condition, not by every command it runs.
The checks step owns individual checks such as lint, type checking and tests. Those are checks, not a new tier of
"sub-steps" requiring a "stage" above them. Each check still has its own result, timing, output and retry history.
The check implementation may coordinate those operations; the factory sees the step's completion condition.
Action and operation are ordinary descriptions of behavior, not extra mandatory entities, tables or scheduling levels.
Likewise, tool calls inside a session do not become workflow steps merely because they are observable.

**Status** says where execution is: queued, in progress or completed. **Conclusion** says how a completed execution
ended: success, failure, cancelled, timed out or skipped. Completed does not mean successful. Use **result** for
the returned data, including any conclusion and outputs; avoid a competing product term "outcome" for that conclusion.
This distinction guides future contracts; it does not silently change the values of existing enums or tracker statuses.
Task statuses describe the task's lifecycle; an execution status describes an attempt. A task's **labels** classify
it; **metadata** holds structured task facts; **comments** hold discussion and owner answers. Do not call task labels
Git tags or treat an execution log as task discussion. A parent task can group child tasks without adding another
execution entity.

## Conversations, evidence and accounts

| Term | Meaning | Example / distinction |
|---|---|---|
| transcript | The retained record of a conversation, including every message, tool input/result and reasoning output the harness exposes. | A compact dashboard view may collapse content; it must not be mistaken for the retained transcript. |
| log | The chronological record of execution events and diagnostics. | Preparation, a command's output, a retry and the attempt's conclusion. Logs and transcripts remain files behind their readers. |
| artifact | A retained output produced by the work. | A screenshot, PDF, video or report, associated with its producing attempt. A vendor's transcript file is not a screenshot. |
| design artifact | Supporting material deliberately retained with a versioned design. | A selected diagram or screenshot under `docs/design/<task-id>/`; ordinary execution artifacts do not all belong in Git. |
| account | A configured connection with credentials and applicable usage limits. | A subscription or API account. It is not a vendor or a model. |
| vendor | The service supplying models and their usage limits. | OpenAI or Anthropic. One harness may support several vendors. |
| model | The selected model offered by a vendor. | Distinct from the account paying for it and the harness running it. |

Use **live** and **retained** for viewing time, not two competing kinds of conversation. **Normalization** translates
formats into a common representation; it does not authorize truncating the retained content. A native session ref is
opaque to the factory; the agent library provides readable content without exposing its storage format.
Unknown cost is unknown, not zero. A dashboard total is derived from individual attempt records, not a replacement for them.

## Storage ownership

Owner agreed 2026-11-09. This is the target division, not a claim that current source already implements it.

| Owner / location | What belongs there |
|---|---|
| Task tracker | Requirements, task status, dependencies, questions, linked answers and task discussion. An answer that changes requirements must update the task or its linked design, not remain buried in comments. |
| Git | Code, design documents, plans and selected supporting design artifacts. Task design material belongs under `docs/design/<task-id>/`, with the plan at `plan.md`. |
| `factory.db` | Local execution progress, steps/attempts, session references, reservations and pending local operations. Disposable on deliberate discard; intact-DB restart must continue unfinished work. |
| Local evidence storage, behind readers | Transcripts, command output, execution logs and artifacts associated with their attempts. A reference in the database does not move their contents into it. |

The task tracker's maintenance tooling owns protection and recovery of its durable data. The factory does not own
a second task-backup subsystem. Existing task exports remain protected until actual coverage and recovery have
been verified; accepting this responsibility boundary does not prove that current tracker tooling supplies it.
Factory database disposability does not make task records disposable.

Email and other external messages can supply requirements or decisions. Capture the relevant information on the
task or in its linked design; an inbox is not an additional authoritative work store. No email integration is required.

## Retired names and remaining implementation gaps

| Existing wording | Use in new work | Scope / remaining question |
|---|---|---|
| bead, ticket or issue for our work | task | GitHub's actual Issues and the bd backend retain their proper names. Task IDs do not change merely because the noun changes. |
| task service in product/design prose | task tracker | No new service or queue is implied. Literal external API identifiers can retain their actual spelling. |
| stage for an engine operation or its code | step | A numbered item in an old multi-stage plan needs its meaning checked; do not mechanically equate it with an engine step. |
| run, call or harness invocation for a step execution | attempt | A tool call remains a tool call. Existing whole-task `run_id`, process take-up counts and hidden harness retries need explicit mapping before schema changes. |
| worker for the coding assistant | agent | Keep attempt, session, harness and agent distinct; remove aliases in the eventual code cut. |
| gate | required checks, or checks when the context is clear | "In flight" counts must state whether they count PRs or individual checks. Do not change queue concurrency semantics with a word replacement. |
| receipt for successful check evidence | pass | Existing owner-command receipts are idempotent replies, not check passes. Reassess the need for those records separately. |
| RunKey, Carry | check key, reuse | Existing type names and algorithms can be cited literally; a vocabulary change does not authorize weaker pass validity. |
| lane | account, concurrent check group, or scheduler process, according to meaning | The earlier purge had three meanings. Do not introduce the old word again or silently merge its three concepts. |
| piece, node, part, facts, Asked as public entities | ordinary package/module, input, result, as appropriate | These are implementation labels, not additional concepts users need to learn. |

Standard engineering terms such as API, protocol, adapter, lock, lease and cache keep their usual meanings. A lock
serializes access; a lease reserves a resource. Do not collapse the behaviors merely to remove a word.
`Board`, `Slots` and `Decisions` are existing screen names, not extra domain entities. Proposed test tiers and speculative
queue behavior stay in their design notes; including a word here does not approve or implement a feature.

## GitHub references and intentional differences

- [Actions concepts](https://docs.github.com/en/actions/get-started/understand-github-actions): workflows contain jobs,
  jobs contain steps, and runners execute jobs. We borrow familiar words without copying that hierarchy.
- [Run attempts](https://docs.github.com/en/actions/reference/workflows-and-actions/variables): GitHub numbers re-runs
  with `GITHUB_RUN_ATTEMPT`. Our attempt applies to a step, not to a whole GitHub workflow.
- [Check status and conclusion](https://docs.github.com/en/pull-requests/reference/status-checks): lifecycle and terminal
  result are separate. We say check, not "check run", in ordinary product prose.
- [Artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts): retained outputs
  differ from caches, which can be regenerated.

Task, factory, slot, profile, session, harness, pass and land are intentional short local terms where GitHub's words do not
express this system's meaning. See [the earlier vocabulary discussion](https://github.com/iorlas/iorlas-task-loop/blob/claude/adapter-justifications-73e7b1/docs/design/slot-lifecycle.md)
for its recorded owner choices. The glossary names the concepts; the redesign and TASKNAME tasks own implementation.
