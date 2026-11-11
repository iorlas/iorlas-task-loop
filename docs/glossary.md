# Glossary

Canonical language for the redesign, new documentation and conversation. Updated 2026-11-11.
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
| attempt | One concrete execution try at an operation, such as a step or an individual check. | A repeat (the step-level retry) makes another attempt. A coordinator restart observing the same surviving execution does not. A new execution continuing the same conversation is another attempt. An attempt can fail before launch. |
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
| host | The machine on which an execution happens. | Do not use this product word for a bundle of collaborators. The successor tree has no `*Host` Protocols; the ports are named for what they do (`StatusPorts`, `EvidenceFiles`, ...). |
| profile | The repo's factory settings in `.task-loop.json`, read by `profile.py` from Git at a commit, never the working tree ([tl-8bh9.14.1](design/tl-8bh9.14.1/plan.md)); `tl profile show` prints it. | Strict keys `setup`, `checks` (name, argv, timeout), `required`, `target`. `setup` and the checks are read at the commit under test (the task branch), like a GitHub `push`/`pull_request` workflow; `required` and `target` from the target (`main`), like branch protection (O1, [self-hosting roadmap](design/self-hosting-roadmap.md) section 7). `setup` runs before an implement agent and before each checks block; the implement agent is told to run every command under `checks` itself, offline; the check step then runs them on X (`required` read from the local `main` at the checks admission). |
| setup | The repo's own command(s), named in the profile, that prepare a slot's environment before the agent starts. | Decided 2026-11-11: run by the factory outside the agent's sandbox, with network, from the same ref as the checks. `just install` when the profile names none (this repository: `just bootstrap`). Not a step. Built (S5e-1): the implement attempt's entry runs it after resetting the slot's ignored files and uv folders (`environment.py`); `tl step show` prints its `Setup:` line. |
| agent folders | The three folders an implement agent may write outside its slot (`access.Folders`), beside the slots under `<slots_root>/<repo_id>/`: the scratch `.t/<slot>` (its `TMPDIR`, at most 64 bytes), `.env/<slot>/uv-cache` (`UV_CACHE_DIR`) and `.env/<slot>/uv-tools` (`UV_TOOL_DIR`). Made (or made 0700 again) by the factory before launch, Codex `writable_roots`; the variables and `UV_OFFLINE=1` go to the agent's shell only (`shell_environment_policy.set`), Codex's own process keeps the person's `TMPDIR`. | Built (S5e-2). Not evidence and not the slot. Each must resolve exactly to its place beside the slot (no link). The scratch is emptied before and after setup and after a slot release (only where it belongs); the uv folders by every reset. A plan agent gets none (`writable_roots=[]`). The preflight's `codex sandbox` probe, run in the emptied scratch, checks the shell gets its variables, the folders are writable and `/tmp` is not. |
| config | Machine-level settings. | Local paths and account settings. Use `profile` for repo settings. |

A GitHub **runner** executes jobs; a slot is not a runner. A separate clone is not a linked worktree.
One primary checkout per repo per machine remains the recorded direction; release and cross-machine behavior are
assessed in the repo/store review. A glossary definition does not introduce a new executor service or process model.

## Checks and delivery

| Term | Meaning | Example / distinction |
|---|---|---|
| check | A named automated validation of the work. | A build, lint command or test command. One check may execute many tests. Decided 2026-11-11: the factory runs checks on the host, before any review, with the agent's scrubbed environment and push bar. As built: a named entry of the profile's `checks` at X, run by the check step (block B4). |
| required checks | The checks that must pass before merging. | Use this phrase instead of a separate "gate" concept. A failed required check prevents the merge. |
| pass | A stored successful check result for its recorded code and inputs. | A failure is a result, never a pass. A missing pass means the check can run again. As built (S6b): a check result `passed` in its checks attempt's latest block, for that attempt's X, profile digest and argv digest; never looked up for another X or attempt (no reuse, D9). |
| check key | The inputs that determine whether a stored pass applies. | Code, command, toolchain and relevant environment/inputs; the exact fields belong to the check design. |
| reuse | Use an existing pass when its validity conditions hold. | An optimization, not required recovery state. Do not give it a separate capitalized name such as `Carry`. The verdict `reused` (below) is a different thing: it names a step whose answer changed nothing. |
| push | Transfer Git objects and update refs on a remote. | Publish `task/tl-123` so another PC can fetch it. `publish` (below) names the factory operation that pushes `task/<id>`; the push itself is the transport. This does not merge it into `main`. |
| merge | Integrate a branch into its base branch. | Squash-merge a completed task into `main`. A direct push is still called a push. |
| land | Finish the task's delivery operation: accepted integration, confirmed task completion and any required task synchronization. | Retry unfinished required actions only. Code can be delivered while task completion remains pending. Merge is integration; push is transport. Publishing an unfinished task branch does not land it. |
| PR | A pull request proposing changes to a base branch. | Use the short form after "pull request" on first use when the audience needs it. |
| merge queue | PRs waiting to merge after their required checks pass. | Detailed queue policy belongs in [its design](design/merge-queue.md), not in vocabulary definitions. The speculative queue remains held. |
| release | A versioned distribution of the software. For freeing a slot see `slot release` (Factory vocabulary as built). | Merging source and publishing a release are different actions. A release candidate is the version being evaluated before release. |

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

## Factory vocabulary as built

Added 2026-11-11 from the successor tree (factory.db v12 since S6a; the check step built through S6e). Each word has one meaning across the code, CLI, database and
logs; use it for nothing else. Words for owner-visible output are listed as the code prints them.

| Term | Meaning | Example / distinction |
|---|---|---|
| phase | How far one attempt's launch has got in factory.db: `admitted`, `dispatching`, `registered`, `captured` (`attempt.phase`). | Not a status or a conclusion. `captured` means the result is stored, not that it is verified or published. |
| admission | The one transaction that reserves a free slot, creates the attempt and takes the tracker claim (`admit.py`); a repeat's takeover of the reservation and an advance, both of which claim nothing, are `admit_chain.py`. | The record is the attempt row at phase `admitted`; the operation is what `tl step start` and each round run. A refusal changes nothing, or returns a claim it took. |
| reservation | The factory.db row tying one slot to one attempt (`reservation`, unique on the attempt). | A slot with a reservation is `reserved`. Ended by a slot release. Not a lock and not a tracker claim. |
| slot custody | The per-slot kernel lock (`slot_lock`, label `taskloop-slot`) held around any Git write on a slot by the entry, verify, repeat or release. | Code names: `custody`, `hold`. Held is `locked`; it is never waited for (`slot_busy`). Not a reservation: a reserved slot is not locked while nothing writes. |
| entry process | The process the factory launches for one attempt, `python -m taskloop.attempt_entry` (a checks attempt: `taskloop.check_entry`); its log is `entry.log`. | Distinct from the agent process and from a Git tree entry. Pick this word; do not say "launcher", "runner" or "entry" alone for the process. |
| launch | Start the entry process (`launch.py`). | Distinct from dispatch. |
| relaunch | Start the entry process again for the same attempt, after it was lost or the machine rebooted. | Not a new attempt: same attempt id, same reservation. |
| dispatch | The entry's permit to run the agent: it records the base commit B and the phase becomes `dispatching`. | The agent runs at most once per attempt. |
| claim | The task tracker's claim on a task, taken at admission and renewed (the bd lease, every 100 s) while a step runs. | A slot release keeps it; `--abandon` returns it. Not a reservation. `renew` here means the lease; see `deadline`. |
| backlog | The configured task scope inside a tracker, named by `--backlog`. | The same as "backlog scope" above. Not inferred from Git. |
| round | One scheduling pass: settle existing attempts, advance claimed tasks whose step is done, admit approved ready tasks into the slots left free, publish verified results. | `tl step next` runs one; `tl step rounds` repeats them. A checks attempt is settled like an agent attempt, through the checks launcher (`operations.relaunch_checks`): relaunched while `admitted` and neither its entry nor a command it registered runs (`<task> check relaunch relaunched <id>`; a check or setup command outliving its entry is waited for, `report running`), released once concluded with its entry gone (`<task> check release released|held:<why> <id>`), reported `running` or `stuck:*`, and once `failed` reported once (`<task> check report failed:<reason> <id>`), never re-run (only `tl step start` re-runs). A failed or stuck checks task never stops other advances or ingestion. Not the dashboard design-round mockups under `docs/design/dashboard/`. |
| move | One thing a round did or saw for one task: one `rounds.log` line. | A round is a list of moves. |
| settle | A round's first part: reading each existing attempt's state and doing its next action (verify, release, repeat, publish). | A settled release is the one that follows a collected result. |
| repeat | A new attempt of the same step after the previous one left the slot unsettled, numbered 1 to 3 within a step (`attempt.number`, `repeat_reason`). | The step-level retry. The CLI, the DB and the log say repeat (`repeat`, `repeats_exhausted`); do not say retry for it. A capture retry (`CAPTURE_RETRIES`) is a DB write retried inside one attempt, not a repeat. |
| verdict | The verifier's judgment of one attempt: `verified` or `rejected:<rule>`. | Not a check pass. `reused` is a verified verdict for a step that changed nothing (`effect` `keep`), distinct from the reuse of a stored pass. |
| disposition | The agent's answer word: plan `planned`, implement `implemented`; both `unchanged`, `incomplete`, `needs_owner`. | A property of the answer. Compare effect. |
| step kind | The few values and functions that make a step that step (`steps.StepKind`): its rules, input, answer schema and decoder, artifact rule and repeat feedback. | A code concept, not a registry or plugin: the kinds are a fixed tuple in order (`steps.STEPS` is `(PLAN, IMPLEMENT)`), reached through `steps.kind(step)`; `steps.next_step` is the one sequencing rule, over `steps.ORDER` (`plan`, `implement`, `check`). The check step is no kind (`steps.is_agent` is False): its attempt is a checks attempt. |
| effect | What the factory does with a disposition: `commit`, `keep` or `none` (`execution.effect`). | `planned` and `implemented` are `commit`, `unchanged` is `keep`, `incomplete` and `needs_owner` are `none`. |
| advance | Admitting attempt 1 of the next step once the task's current attempt is done: verified, released settled (claim kept) and published (`admit_chain.admit_next`); also the `Next` word that asks for it. | One tracker read confirms the task is `in_progress` for `taskloop`; no claim and no label check. The new attempt stores the previous X as `attempt.after_commit`, and its entry refuses `branch_moved` when the task branch no longer contains it. Each round advances automatically, before admitting new tasks, oldest settled release first (`rounds.log`: `<task> implement advance started <attempt>`; a refusal about the task is `<task> plan skip <word> <attempt>`); `tl step start` advances by hand. After implement the next step is check: the advance is a checks attempt's admission (`check_admit`; refusals `commit_missing`, `target`, `target_profile`, `no_required` are skips). |
| agent answer | The agent's structured JSON reply, validated by the answer contract. | Not the owner's answer to an `ask`. |
| execution | One agent run inside an attempt, with its stored facts (`execution` table: exit, usage, evidence paths, answer, session state). | Not an attempt: an attempt has at most one execution. |
| agent process | The OS process record of a running agent (`worker_pid`, `worker_pgid`, `worker_start`, `worker_boot` on the attempt). | The column names mirror the `any_agent` library's `Worker` type. Distinct from the entry process that launched it. Its shell commands run outside its process group by design, each in a new session under `bwrap --unshare-pid --as-pid-1 --die-with-parent`: that PID namespace contains them and ends with its parent (Run S finding 6, Linux), so "the agent is gone and its group is empty" is their stop proof too. Setup processes are never in its group. |
| session state | Whether the agent session reference was captured: `complete`, `pending`, `conflict`, `fault` (`execution.session_state`). | Never the Git push. Not a conversation or a harness. |
| capture | Store the run's result, evidence and session state in factory.db (`Attempts.capture`). | Distinct from publish. Entry.log's `publish=` is the capture retry's DB acceptance, a known leftover word. |
| evidence files | The files kept per attempt behind `EvidenceFiles`: stdout, stderr, answer, diagnostic, `entry.log`, each setup run's `setup-<run>.log` and each check's `check-<block>-<name>.log` (both `CappedLog`: 0600, at most 32 MiB, then one `[truncated]` line). | Control state is never read from them. |
| setup run | One run of the profile's `setup` for an implement attempt, before its agent, or for a checks attempt, before each block (`setup_run`, numbered per attempt; the latest is the highest number): its B, the setup digest, the registered command and its conclusion `passed`, `failed`, `timed_out`, `lingering`, `dirty` or `interrupted`. | Not an attempt and not a step. A passed run is reused only by a relaunch of the same, still admitted implement attempt, never by a checks attempt (its slot is first reset hard to X, `environment.prepare_for`); two failed runs refuse `environment:failed`. A command whose stop left survivors is `lingering`. The entry and the slot release never signal it. |
| checks attempt | The check step's attempt (`checks_attempt`, schema v12, written only by `check_store`): numbered per done implement attempt (a re-run adds one); its own slot, D, deadline and entry; `main`'s commit when the required names were read and those names with their argv digests; `admitted`, then `concluded` `passed` or `failed` with a reason; released, maybe abandoned. | Not an `attempt` row and not a step kind. Admitted by `check_admit` (S6d: the advance after a done implement attempt, or a re-run), its entry process is `taskloop.check_entry` (launched over `CheckStore`) and its release `check_release`. `tl step show`/`list` show it in place of its implement attempt; `tl step start` advances to it, relaunches it or re-runs it; each round advances to it and relaunches it, never re-runs it; `tl step release` releases it first ([tl-8bh9.14.6](design/tl-8bh9.14.6/plan.md) S6a-S6e). Its reason (`Result: collected failed:<reason>`) is `<name>:<conclusion>`, `<name>:not_run`, `setup:<conclusion>`, `profile:<reason>`, `environment:<word>`, `slot:<word>`, `expired[:<name>]`, `main_moved`, `commit_missing` or `claim_lost`. While the latest one of an implement attempt is not abandoned, that implement attempt is not current (`factory_schema.SUCCESSOR`): its abandon refuses `changed`. |
| re-run | `tl step start` on a task whose latest checks attempt concluded `failed` and was released: a new checks attempt of the same implement attempt and X (`number` + 1), the earlier one kept (`Earlier: <id> re-run`). | Not a repeat (an agent step's retry) and not an abandon: same claim, no new plan or implement. The round never re-runs. |
| block | One pass over the profile's checks at X within a checks attempt (`check_result.block`, numbered per checks attempt; the latest is the highest number), after the slot is reset hard to X and set up at X: each check once, in profile order, required or not (`checks.Block`). | Only the latest block's results count. A completed block (every result terminal, or one `lingering` or `dirty` result that stopped it) is never run again; an `interrupted` or missing result repeats it whole. Built (S6b); run by the checks entry (S6c). |
| check result | One check's result in one block (`check_result`): its argv digest and timeout, its registered command and its conclusion `passed`, `failed`, `timed_out` (its own timeout), `lingering` (a process left after any end), `dirty` (a tracked change or HEAD not at X detached; untracked files are only listed in its log), `undefined` (required, not defined at X; no command) or `interrupted` (stopped by the attempt's deadline, or found gone unfinished). | The "attempt of an individual check" is this row, identified by (checks attempt, block, name). Unfinished, `lingering`, `timed_out` or `interrupted` (`check_store.LIVE_AFTER`) names a command whose group must be proven gone before its slot is reused or released. |
| result sink | Where one block's results and logs go (`checks.ResultSink`): a record bound to its owner and clock; `checks.CheckSink` is a checks attempt's (`check_store` and its evidence directory). | The block knows no checks attempt: land (B6) validates its candidate with the same block and its own sink. |
| park | Return a released slot to a detached HEAD at the attempt's start (D in Commit letters). | The slot release's one Git write (`slot_release.park_slot`, shared by the checks release, which first resets a slot listed detached at X back to exactly X: `environment.reset_to`). |
| slot release | Ends an attempt's reservation: parks the slot and keeps the claim (`released`); `--abandon` also returns the claim. | A `held:<reason>` word means the slot stays reserved (`held:setup_running`: the latest setup run, unfinished or concluded `lingering`/`timed_out`, still has a process in its command's group; `held:check_running`: an unsettled check result's command still runs). Not a distribution `release` (above). |
| abandon | The owner deliberately giving up an attempt with `tl step release --abandon`: the slot is freed, the tracker claim is returned and the task becomes ready again. | Never automatic: a network or agent failure is not an abandon. The next admission is fresh and starts the task at its first step, as after a factory.db discard. |
| publish | Push of `task/<id>` to origin, once an attempt is verified (`publish.py`, table `published_branch`). | Never forced, and it does not land. The other sense, storing a result, is called capture. |
| deadline | The instant by which an attempt must end, set by `--minutes` (`attempt.deadline`). | Renewed to now plus `--minutes` once per reboot, at relaunch. Not the claim lease. |
| stuck | A next-action word meaning only the owner can act: `stuck:expired_admitted`, `stuck:entry_lost`, `stuck:hung`, `stuck:uncollected`, `stuck:conflict`, `stuck:setup_failed` (an admitted attempt 1 whose setup failed twice: rounds report it and never relaunch it), `stuck:checks_refused` (a checks attempt relaunched twice without concluding: each relaunchable refusal its entry counts, and each round's relaunch past the deadline, `late_relaunch`; rounds stop relaunching it, `tl step start` relaunches it by hand). | The other `Next` words are `start`, `wait`, `verify`, `repeat`, `repeats_exhausted`, `release`, `publish`, `advance`, `done`, `unknown`. `tl step list --stuck` shows `stuck:*` and `unknown`. |
| reserved / locked / held | `reserved`: a slot with a reservation. `locked`: its custody lock is held. `held:<reason>`: a release word (the slot stays reserved). | A slot can be reserved and not locked. Do not use "held" for the other two. |
| label | The tracker label approving autonomous execution, `auto` (`--label`): checked only when a round ingests a new ready task, never on a claimed task's advance. | The lock label strings passed to `process_lock` (`taskloop-slot`, `taskloop-rounds`) are lock labels, not task labels. |

### Commit letters

Used in the plan documents and in code comments; read the column, not the letter, when the two disagree.

| Letter | Meaning | Column / field |
|---|---|---|
| B | The base commit the entry reads before dispatch. | `attempt.base_commit` |
| D | The slot's HEAD at admission; a released slot parks here. | `attempt.slot_head` (`slot_release.head` once parked) |
| E | Where the previous attempt ended; a repeat starts here. | the previous attempt's `end_commit` |
| X | The attempt's end commit. | `attempt.end_commit` |
| T | The remote tip after a push. | `published_branch.remote_head` (with `commit_sha`, the X pushed). `main`'s commit at a checks admission is "the target" (`checks_attempt.target_commit`), never T; the M2 live-smoke runbook's shell function for `tl` is `TL` (the M1 runbook's `T` predates it, not this letter). |

### CLI flags

The meaning of each flag as `tl <command> --help` gives it. Every step runs through `tl step` (slice S4 of
[the generalization plan](design/tl-8bh9.4.3.1.15/plan.md) replaced `tl plan` in one cut, no alias; the flags stayed).

| Flag | Commands | Meaning |
|---|---|---|
| `--backlog KEY` | `step` (all), `task show` | The task scope inside the tracker; supplied, never inferred. |
| `--tracker-root PATH` | `step start\|next\|rounds`, `task show` | The directory of the Beads tracker. |
| `--checkout PATH` | `step start\|next\|rounds`, `slot adopt`, `profile show` | The person's checkout of the repository (`profile show`: default `.`). |
| `--at REV` | `profile show` | The commit under test whose `setup` and checks are read (default `HEAD`). |
| `--target REF` | `profile show` | The target ref whose `required` and `target` are read (default `main`). |
| `--root DIR` | `config show`, `slot adopt` | The slots root (config `slots_root`); slots live at `<root>/<repo_id>/sN`. |
| `--count N` | `config show`, `slot adopt` | Slot count s1..sN (config `slot_count`). |
| `--every SECONDS` | `step rounds` | Seconds between rounds, at least 5 (config `round_seconds`). |
| `--label LABEL` | `step next`, `step rounds` | Required on `next` and `rounds` (approves a task); not on `start`, whose task is named. |
| `--minutes N` | `step start\|next\|rounds` | An attempt's deadline from now (and its renewal after a reboot). |
| `--model`, `--effort` | `step start\|next\|rounds` | The agent model and effort for the attempt. |
| `--db`, `--artifacts` | most `step`, `config show` | factory.db and the artifacts root, overriding the machine config. |
| `--abandon` | `step release` | Also return the tracker claim and throw the attempt away. |

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
| stage for an engine operation or its code | step | The code says step (`StepRules`, `attempt.step`, the agent input and CLI help); a Git `stage` of files is ordinary Git. A numbered item in an old multi-stage plan needs its meaning checked; do not mechanically equate it with an engine step. |
| run, call or harness invocation for a step execution | attempt | The retired `step run` is an attempt. The agent run inside an attempt is an `execution` (below). A tool call remains a tool call. Existing whole-task `run_id`, process take-up counts and hidden harness retries need explicit mapping before schema changes. |
| worker for the coding assistant | agent | Keep attempt, session, harness and agent distinct. The code says agent (`agent process`); `worker_pid`/`worker_pgid`/`worker_start`/`worker_boot` columns remain and mirror the `any_agent` library's `Worker` type, whose name stays where it is that library's type. |
| gate | required checks, or checks when the context is clear | The code says `checked` and `verdict`; no `gate` identifier remains in this tree. "In flight" counts must state whether they count PRs or individual checks. Do not change queue concurrency semantics with a word replacement. |
| outcome | result (the returned data), conclusion (how it ended) or verdict (the verifier's judgment) | Three comments in `attempt.py` and `attempt_entry.py` still say "outcome"; no identifier does. |
| receipt for successful check evidence | pass | Existing owner-command receipts are idempotent replies, not check passes. Reassess the need for those records separately. |
| RunKey, Carry | check key, reuse | `RunKey` and `Carry` are reference-implementation identifiers; neither exists in this tree. They can be cited literally when discussing that code; a vocabulary change does not authorize weaker pass validity. |
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
