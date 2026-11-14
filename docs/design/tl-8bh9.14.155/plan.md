# Hand-started tasks and recoverable land conflicts

Task: `tl-8bh9.14.155`. Revised 2026-11-14 against `58c8ac3b`, including
the unfinished implementation saved there. This is an implementation plan,
not a result. Selection and presentation have partial code; conflict recovery
is still to be built.

## Decisions

1. Under the profile's `land: auto`, rounds own delivery of every eligible task
   already claimed by this factory in the selected backlog and repository. The
   stored admission label does not decide who lands it. An explicit hand start
   authorizes that task's normal progression, including automatic delivery under
   the repository's policy. Labels continue to authorize admission of new tasks.
   Do not guess an approval label from the task or manufacture one for old rows.
2. Resolve a textual land conflict within the existing land step, using an agent
   attempt and a reserved slot. Preserve the completed plan, implementation and
   checks as history. Do not restart at plan or replay implementation wholesale.
   Use a merge, rather than a history-rewriting rebase, through the pinned shelf
   APIs. The final delivery remains a single squash commit on origin's `main`.
3. Resolution edits are untrusted until the factory validates the resulting land
   candidate. Semantic ambiguity, unsupported conflicts or exhausted attempts
   cause a durable hold with an explanation. Nothing silently accepts changed
   required checks, configuration or weakened tests.

These decisions use existing terms: land, attempt, session, merge and hold. A
conflict resolution is work within land, not a new scheduler or public step name.
Earlier landing remains useful, but cannot replace recoverable conflict handling.

## Current behavior and available mechanisms

- Before this branch, `round_land._waiting` required `label is not None` while
  status promised "Landing next round" independently of label and even when
  policy was unavailable. Saved work now shares `task_status.waiting_for_land`
  with round selection, accepts unlabelled attempts, and supplies typed
  `LandPolicy`/`LandState` presentation through CLI, board and drawer.
- Saved work adds repository identity to attempt reads and filters round work by
  repository and backlog, and refreshes views after settlement. Keep repository
  fencing for effects, but correct admission capacity accounting: `max_running`
  remains per backlog, including other repositories, as the existing contract
  states. `round_land` still calls the same `land.land` as CLI.
- `land_target.squashed_onto` uses object-only `Repo.squash`, returns `conflict`
  before creating a candidate and includes `land_guide.restart` advice. Rounds
  hold that refusal. Saved work permits unlabelled land holds and omits removal
  of a nonexistent approval label. Its generic hold operation still abandons the
  original attempts; it does not yet own a resolution slot or preserve a merge.
- `hold_status.reingests` recognizes reapproval only through the original stored
  label. There is no implemented general tracker-answer workflow or unlabelled
  land continuation to reuse. The saved "explicitly approve another attempt"
  wording does not itself supply that operation.
- The checkout already pins `git-porcelain==0.21.0` at shelf commit
  `c6384f0bf870a430b7bffe826f9f42b6138d7d44`. Its real and fake `Worktree`
  provide `start_merge`, `merging`, `finish_merge`, `abort_merge`, `unmerged` and
  staging. `start_merge` stops before committing, leaves refs unchanged and puts
  conflicting files at conflict markers; `finish_merge` requires a resolved
  index and makes a two-parent commit. A detached slot keeps task refs unchanged.
  No dependency change, factory Git command or further shelf API is required.

Read `7172ef37` (the first plan) and `58c8ac3b` (the task-specific
`Task-Loop-Wip` commit). Retain the latter's source, tests and documentation as
unfinished inputs: its label-independent delivery and policy presentation fit
the task, but its holds, capacity accounting and conflict route need the work
below. Do not treat its preservation commit as a verified implementation result.
The inherited WIP trailer in `78696b90` belongs to `.160`; retain that unrelated
work. This planning revision changes only this plan and does not approve the
saved source as complete or remove it.

## One selection and presentation rule

Factor the small typed policy needed by round selection and status consumers:
the task belongs to this factory's repository/backlog, has released passing
checks, is not abandoned or held, and is eligible for the existing land operation.
An admission label is not a condition. Keep claim and exact task-branch checks in
land immediately before effects; do not treat a stale status view as authority.

Keep the existing policy source: rounds fetch origin's `main`; dashboard reads
its known remote-tracking commit without causing Git writes. Include that policy
commit in structured presentation where needed. Missing/unreadable policy is
unknown, never an automatic promise. Readers cannot guarantee a round is running;
say "Waiting for the factory to land it" under automatic policy rather than
promise that the very next round will finish it.

The board, drawer and CLI status must convey the same decision:

| Situation | Presentation and round behavior |
| --- | --- |
| Auto, eligible, labelled or unlabelled | Factory will land it; selected oldest released checks first. |
| Manual, labelled or unlabelled | Waiting for a person to land it (manual policy); rounds do not land it. |
| Policy unreadable/unknown | Landing policy is unavailable; no claim that a round will land it. |
| Resolution admitted/running/reconciling | Land is in progress; show its attempt and session. |
| Held or abandoned | Show that state and its cause; no automatic selection. |
| Delivered, tracker close unfinished | Factory is finishing delivery; reconcile close, never resolve again. |

Use enums and a single codec for any changed closed vocabulary. Preserve existing
top-level task status where possible and attach the landing decision as typed
data; do not add several independently computed UI flags. Scope the change to
these consumers, not a general status redesign.

Select at most one task for substantive land work per round, including an active
resolution attempt. Pending land work counts toward the existing in-flight bound
and retains the required slot reservation. Keep separate views for effects in
the selected repository and for admission capacity across the whole backlog;
filtering the first must not shrink the second. Land remains before new admissions;
do not add a merge queue or hold all slots while waiting for an agent. Refresh
affected views after settlement so newly released checks can land in this round
when capacity permits. Ordinary refusals may still be reported without starving
other eligible tasks, subject to the existing one-task land budget.

## Conflict resolution owned by land

Keep `--summary` read-only with respect to resolution: report conflicting paths
and the intended next action, without allocating a slot or launching an agent.
Both an actual CLI land and an automatic round call the same resumable land
operation. Resolution requires the existing minutes/deadline input; the CLI
reports missing input before reserving or launching. `manual` continues to stop
rounds from initiating land.

For a conflicting checked commit X and fetched origin target O:

1. Check the original claim, local and remote task tips at X, repository identity,
   outstanding delivery, drain fence and process liveness. If any candidate was
   delivered, finish its close instead. Reserve one clean, detached managed slot
   and persist the land attempt's immutable inputs before external effects.
2. Prepare the slot environment using the established setup operation and profile
   at O, before placing unresolved files there. Setup must not consume a
   half-merged profile. Persist its inputs/results as usual. If setup changes
   tracked files or fails, stop with a precise typed result.
3. Under slot custody, put that detached slot at X and call `start_merge(O)`.
   Persist the observed result. Clean merges use the same completion route;
   `UpToDate` is reconciled against the recorded inputs. Conflicts use structured
   paths and index observations, never parsed tool output or marker-count regexes.
4. Launch an agent through the existing owning agent/process interfaces. Resolve
   its settings through the existing per-step settings machinery for land and
   record the selected settings. Extend that fixed supported-step set for the
   already-defined land step where necessary; do not create a parallel resolver.
   Record each execution attempt, session, process identity, deadline and evidence
   references. The prompt contains task requirements, committed plan, X, O,
   conflict paths and both sides' context. Ask for the smallest resolution that
   preserves both intended changes, or a clear explanation that the owner must
   decide. The agent edits files and returns a validated structured answer with
   paths and explanation; it does not stage, commit, push or choose delivery policy.
5. Validate the answer and all actual edits using the existing path, file type,
   size and repository protection rules. Include deletion and rename conflicts.
   Automatically merged changes are retained; declared resolution edits must
   account for other changes. Unsupported binary, submodule or other non-textual
   conflicts stop for a decision. Stage the accepted resolutions through shelf,
   require `unmerged()` to be empty and call `finish_merge` under custody. Inspect
   the resulting parents: the recorded starting commit (X on the first merge,
   the latest resolved commit after a target move) and O. Record that commit and
   its provenance before advancing. The agent claiming completion is not proof
   of a valid resolution.
6. Squash the resolved merge onto the recorded O with the existing candidate
   message/provenance rules. During automatic recovery the task branch remains X: no force push,
   ref rewriting or fabricated new implementation result is needed. Store the
   resolved merge alongside the candidate's original checks/X link, so subsequent
   land calls use it rather than squashing the unresolved X again. Always run
   fresh candidate validation, even if an existing tree-equality shortcut would
   otherwise reuse X's pass. Run setup/check commands from S and required names
   from O, and retain the existing changed-check/configuration/test protections.
7. Deliver S through the existing non-forced push/reconciliation and tracker-close
   operations. Check claim, branch and target again as required by those owners.
   The final land message identifies the original checked X, resolved merge and
   validation evidence; status can explain why it differs from the checked tree.

If origin moves before delivery, retain the previous candidate and resolution as
history. Observe whether delivery happened before doing anything else. If it did
not, merge the new target into the latest resolved work, preserving earlier edits,
and validate the new S. Never start again from plan. Permit at most three agent
executions for an unfinished land, including executions prompted by target moves;
persist this bound across coordinator restarts. Existing implementation repeat
counts are neither consumed nor reset. Exhaustion or an owner-needed answer
holds the task once. Transient IO failures and intact-DB resumption do not consume
another agent execution unless a genuinely new execution is launched.

## Persistence, ownership and interruption

Implement new conflict behavior vertically under a land feature directory, with
separate use-case modules for admitting/resuming an attempt and accepting its
resolution. Its store alone owns its new tables. Retain existing public land
entry points and existing candidate/check/push/close owners; do not copy their
SQL or construct a second orchestration service. Use pydantic v2 for stored and
agent-boundary models, enums for phases/reasons, and typed in-process results.
Extend `LandResult` and the round's landing port with an explicit in-progress
result for admitted/running resolution. Launch and return to the round rather
than blocking scheduling until the agent finishes. Count that task as the round's
land work, without treating it as landed or held. Status reads this persisted
attempt even before a land candidate exists; a later call resumes it.

Persist at least the original checks and implementation identities, X, each O,
slot/generation and park point, attempt order, settings, input digest, deadline,
session/process identities, action intents, captured result/evidence references,
resolved commit and candidate association. Logs are evidence, never control state.
Integrate reservations, liveness, drain and release with their existing owners.
A schema change drains running old attempts, then discards the old factory DB as
the repository requires; there is no compatibility reader or reconstruction.

Each Git, process and tracker effect follows intent transaction, external action,
result transaction. Reconciliation must cover crashes after reservation, merge
start, launch, answer capture, merge completion, candidate creation, push and
close. Inspect actual merge state, HEAD/parents, owned process and remote refs;
adopt completed work. Do not call `start_merge` over an existing merge or launch
again while the recorded execution may survive. Unknown process state keeps the
reservation and waits for an observable decision. No write transaction spans IO.

Interruption leaves resumable work and the reservation intact. Resume an existing
session where supported, recording a new attempt for each new execution. A final
abandon/hold must first preserve owned resolution edits and commits through the
owning preservation operation. `wip.save` captures working files into a
single-parent preservation commit on the task branch and performs a mixed reset;
it cannot be assumed to retain merge state or detached merge ancestry. Extend
that owner narrowly to retain the recorded merge inputs, accepted merge commits
and the captured working tree before any reset/abort. A terminal hold may advance
the task branch to a marked preservation commit; X and completed checks remain
immutable history, and that saved commit is never a land candidate or a pass.
Test the capture of unresolved index entries and conflict-marker files with the
pinned shelf API. If preservation cannot finish, keep the slot reserved and
report the pending preservation instead of discarding work. Only after durable
preservation and confirmed process stop may the owning release call `abort_merge`
when a merge is still present, then park the slot. Never abort merely because a
process or slot is old. An intact-DB restart continues
this work, without replanning or decoding logs.

Extend the existing hold operation narrowly to accept land causes for unlabelled
attempts. Add `held`, record the typed cause and write one explanation; omit the
approval-label removal when none was stored. Preserve other labels and claims
according to the existing hold rules. Other hand-started failure behavior stays
outside this change. Ordinary textual conflicts enter automatic resolution,
not this terminal hold route. Exhaustion, semantic ambiguity and unsupported
conflicts remain explicitly held with their preserved evidence and the decision
needed; a comment is not a state mutation. Exclude these new resolution holds
from generic label reingestion so readding a label cannot silently restart plan
or reset the three-execution limit. Do not promise a working unlabelled approval
path that does not exist. A general tracker-answer operation and owner-authorized
continuation after a terminal resolution hold are outside this bounded change;
they require a separate explicit decision. The factory finishes recoverable
textual conflicts itself, and reports terminal holds in words without asking
the owner to run a CLI command. A missing label must not make the same refusal
recur forever.

## Implementation sequence and verification

1. Review and finish the saved eligibility/presentation changes across
   `round_land`, round capacity, CLI status, board and drawer. Retain unlabelled
   land holds; fix backlog-wide capacity and the manual-policy wording above.
   Update the glossary and relevant help/documentation during implementation to
   remove the old round-taken-only and full-restart descriptions.
2. Add land-owned persisted attempts and narrow Git/agent ports; implement merge
   preparation, resolution acceptance, reconciliation, preservation and release.
   Wire composition and drain, then route conflicts from `land_target` through
   the same land operation for rounds and CLI.
3. Feed resolved work into existing candidate validation and delivery; update
   summary, evidence reads, round moves and owner-facing explanations. Remove
   restart/CLI-command instructions from these land/conflict messages. A message
   states what happened, what the factory is doing and which decision is needed.

Use focused pytest behavior/contract tests with owning shelf fakes:

- A hand-started task with `label=None` passes checks, is selected under auto,
  lands and closes exactly once, without another plan or implement execution.
  Test labelled/unlabelled x auto/manual/unknown policy in shared status and UI
  data, plus repository/backlog isolation, abandonment and explicit holds.
- Oldest-first selection, newly released checks, one-task land budget, free-slot
  reserve, backlog-wide in-flight bound across repositories, and non-starvation
  when a different task is held. Repeated rounds observe an active resolution
  without selecting a second task for substantive land work.
- A real textual conflict under FakeRepo: the agent sees both sides at conflict
  markers, resolves them, the merge has the expected parents, S contains both
  changes, fresh required checks pass and the existing delivery closes the task.
  Original plan/implement/check history and task branch X remain inspectable.
- Unresolved index entries, unlisted/unsafe edits, unsupported conflicts,
  needs-owner, deadline and persisted exhaustion all stop delivery. A failed S
  check or changed validation policy cannot be bypassed by resolution. Test every
  typed refusal has a useful adapter-supplied explanation.
- A target move retains previous resolutions and requires new validation;
  branch/claim loss holds once, including for unlabelled attempts. Manual mode
  prevents round-initiated resolution; summary launches nothing. Terminal
  resolution holds stay held under repeated rounds, comments and label changes;
  they never trigger fresh planning or reset the execution bound.
- Inject crashes at each intent/action/result boundary above. Assert no duplicate
  surviving agent, merge, push or close; reservations and preserved edits survive
  interruption; unresolved liveness cannot release a slot. Include preservation
  before abort and a drained schema replacement test.

Use the shelf real/fake merge contract already supplied; add only a focused real
adapter test if factory integration exposes a gap, never factory subprocess code.
Respect 400/80/800 line caps, narrow test import closures and existing policy AST
and import-linter contracts. Run `just install`, `just check` and focused installed
package pytest selections for changed behavior. Read the justfile first:
`just test` currently selects all CLI/steps/rules tests, so the prohibition on
agent whole-suite runs takes precedence; run its relevant selections explicitly
and report that scope. Do not run live tests.

Completion requires the reported hand-start reproduction to land automatically,
truthful policy/status in all consumers, a textual conflict to finish without
replanning, and crash/hold/validation tests proving that delivery safety remains
owned by the existing land operation.


## Saved implementation assessment (unfinished)

Commit `58c8ac3b` contains the selection/presentation portion: rounds select released
passing checks without requiring an admission label, scope existing work to the
checkout repository and backlog, and refresh landing views after settlement.
CLI, board and drawer share a typed landing decision including unknown policy and
the immutable policy commit. Land refusals about unlabelled work can be held once;
the tracker adds `held` without removing another label. The schema interpretation
version is 21 because older readers cannot read these unlabelled holds; the
existing guard requires drain under matching code before database discard.
Saved focused tests cover single delivery/close, the policy matrix, isolation,
newly released checks and holds; their presence is not a passing result from this
planning revision. Retain and verify them during implementation, adding the
backlog-wide capacity regression and correcting manual wording.

The conflict-resolution portion is **not implemented**. In particular there is no
persisted land agent attempt, merge preparation/acceptance, three-execution bound,
resolution reconciliation, preservation/release integration or continuation after
an owner answer. The last item is now explicitly outside this task rather than
assumed to be available. Existing conflicts still follow the old refusal/restart
route. The revised decisions above are the intended implementation; these partial
changes do not complete this task and must not be reported as an implemented result.

This revision was checked against the saved diff and current land, status,
round, hold, settings and preservation owners. Only this design file changes;
no source gates or live tests were run for the planning revision.
