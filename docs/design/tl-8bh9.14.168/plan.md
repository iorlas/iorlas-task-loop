# Continue task branches after main advances

Task: `tl-8bh9.14.168`. Prepared 2026-11-14 against `99655d38`.
This is an implementation plan, not an implementation result.

## Evidence and decisions

No plan existed at this path. `main..HEAD` contains no task-specific commits or
unfinished WIP. The inherited WIP trailer in `78696b90` concerns `.160`; retain
that unrelated work. The slot-local tracker did not contain `.168` or `.155`,
so the requirements here come from the supplied task and the recorded Git design.

`prepare.branch_refusal` currently accepts each candidate slot head D only when
**both** existing local and remote-tracking task tips contain it, or, without
either task ref, local `main` contains it. It refuses when no supplied D passes,
not merely because one candidate fails. `admit.branched` uses that result before
claims/reservations; `NextAdmission` uses it for advances too. `prepare._take`
then independently requires D to be an ancestor of the tip actually taken.
Consequently a free slot at a newer main cannot take an older task branch even
when that branch contains its published plan and all expected work.

The glossary already says existing task branches resume however far main moved,
but its definition of D still requires branch ancestry. Correct that definition
and the preparation/admission documentation with the implementation.

Coordinate with `.155` using its latest plan at
`task/tl-8bh9.14.155:docs/design/tl-8bh9.14.155/plan.md`, including revision
`6bd26fc3` and preservation WIP `b65113b8`. That branch chooses a factory-owned
merge of origin's current main into the retained task work, with typed results,
bounded conflict resolution and preserved history. Its latest saved work still
does **not** implement the resolution operation. Do not assume it is available
because the shelf pin or preservation support has landed.

Use that same merge operation for preparation and land. Merge is an action
within the owning step, not another public step, scheduler or configuration key.
Preparation attaches the accepted result to the task branch; land keeps its
checked branch unchanged and consumes the detached result for candidate creation.
Keep these different continuations explicit. This task owns preparation and the
shared merge behavior it actually needs; `.155` owns land integration, delivery
selection and presentation. Do not transplant its whole unfinished diff.

Choose merging before the ordinary agent starts. Merely telling the plan agent
to merge cannot work: that agent's Git writes are prohibited. Neither a branch
rename nor replaying plan/implementation is a recovery action for main movement.

## Read-only admission rule

Keep the name, ref collision, checked-out-branch and foreign unpublished-work
protections. Keep local-first, otherwise remote-tracking, task-tip selection.
Separate slot eligibility from synchronization with main:

1. Read the selected branch start and known `refs/remotes/origin/main`. For a new
   task retain the existing start at local `main`; D never chooses that start.
2. A clean detached candidate D passes if it is an ancestor of origin's known
   main **or** of the selected branch start. Do not require it to be below every
   local and remote task ref. This also permits slots older than main and slots
   parked at a retained task commit outside main's history.
3. Filter candidates individually. One invalid candidate must not exclude another
   valid one; slots need not be moved to a common parking commit. A detached D
   outside both histories remains invalid. With no passing candidate, the
   existing `branch_diverged` refusal describes that actual ancestry failure.
4. Branch and main having different tips, or neither tip containing the other
   after independent commits, is ordinary merge work. An unrelated task history
   is real divergence, established from structured Git history/merge results,
   never inferred simply from unequal tips or from D not being below the branch.
5. Missing required targets and failed Git reads stay typed target/unavailable
   results. Missing origin-main knowledge is not proof of divergence: when D is
   already below the selected start it can pass this read-only rule; otherwise
   report the missing target knowledge rather than a false ancestry refusal.

Update `_foreign_unpublished`'s known history to include origin's main, not just
local main and the remote task ref. Bringing main into a branch must not turn
main's commits into apparent foreign unpublished task work when local main lags.
Factory-created merge commits carry the existing owning attempt trailer and
recorded merge provenance; genuinely foreign unpublished task commits still
refuse. Do not exempt every local merge commit by its shape or subject.

Admission remains read-only with respect to Git: no fetch, merge or repark in
`branch_refusal`. Refresh origin's main through the owning bounded remote API in
execution preparation, then revalidate against that immutable commit. Do not
silently substitute local main for the origin target when integrating existing
work. Keep the existing local-main rule for creating a new branch distinct from
this integration target; never move the person's main checkout or local main ref.

## Preparation and the shared merge operation

Implement the exercised merge use cases vertically under a small merge feature
directory, with typed inputs/results and a store only for the facts it owns.
If `.155` has landed the operation before implementation, extend that owner
instead of introducing a competing one. On the current tree implement the shared
start/resume/accept operation here using the already pinned shelf APIs; land can
consume it when `.155` is completed. Do not import another task worktree at runtime.

The operation receives immutable source and target commits, task/repository and
owning-attempt identity, slot/generation/D, deadline and resolved agent settings.
Return distinct typed completed, in-progress, unavailable and terminal results,
with explanations. Use enums/classes for changed closed vocabularies and one
codec per stored/displayed vocabulary; pydantic v2 validates database and agent
boundaries. No new dependency or public step name is needed.

For a fresh or advancing clean preparation:

1. Under the existing reservation, custody and process fences, refresh origin's
   main and record its commit. Recheck branch ownership, selected source tip,
   pointer/repository identity and prior published `after_commit` before effects.
   Preserve the current lost-work checks: a branch that lost the previous step's
   commit is `branch_moved`, even if D is safely on main.
2. If main is already an ancestor of the source, complete without a merge. If
   the source is an ancestor of main, use the descendant main commit. Otherwise
   prepare the reserved slot detached at the retained source and call shelf
   `start_merge` with the recorded origin-main commit. Preserve source ancestry;
   never rebase, reset away the task's work or recreate the branch at main.
3. Clean merges finish through shelf `finish_merge`; conflicts enter the same
   typed resolution path as `.155`. Inspect actual merge/index state and parents.
   Unrelated histories are divergence; supported textual conflicts are pending
   resolution, not `branch_diverged` and not a restart trigger.
4. After completion, record the accepted commit and its provenance. Revalidate
   the source ref and branch checkout ownership, then attach the result using
   shelf's expected-old-ref update and normal branch take. A concurrent ref
   change is reconciled or reported as `branch_moved`, never overwritten. A
   remote-only branch is created locally from its retained source/result.
5. Replace `_take`'s post-take D-ancestor requirement with the same valid-base
   rule and recorded source/result checks. An unrelated branch substituted
   during the take must still be caught even when D is on origin main. Verify
   the actual branch, result commit and retained `after_commit`, not just D.
6. Only then record the ordinary attempt's B and launch its agent. B contains
   the retained task work and recorded main; D remains only the release park
   point. Normal setup runs against the completed tree. A pending merge cannot
   dispatch the plan/implement agent or run setup from half-merged configuration.

Use `.155`'s conflict contract: prepare the resolution environment from immutable
target inputs before unresolved files exist; supply requirements, committed plan,
both commits and structured conflict paths to an agent. The agent edits files
and returns validated paths/explanation; the factory validates edits, stages and
finishes the merge. Preserve automatic merge changes; reject unsafe/unaccounted
edits and unresolved entries. Unsupported non-textual conflicts, ambiguity,
needs-owner or exhaustion hold once with the typed cause and explanation.

Record resolution executions/sessions separately from the ordinary step attempt.
Resolve preparation settings through its owning step's existing settings resolver;
land supplies its own settings. Use `.155`'s persisted maximum of three resolution
agent executions per unfinished operation, including executions after target
moves. Coordinator restarts do not reset that limit or spend another execution
merely by observing a surviving process. Existing implementation repeat counts
are not consumed by merge resolution.

Apply preparation before a clean step starts, not over a dispatched attempt or a
repeat's dirty leftovers. Failed-check repair retains its exact checked-source
validation first; if preparation then merges main, record that source-to-result
relationship explicitly instead of broadly weakening `source_checks_id` equality
checks. Repair still produces a fresh implementation result and fresh checks.
Main moving again after the recorded preparation does not restart this step:
later clean preparation and land handle subsequent movement.

Preparation is not publication, verification or delivery. Existing passes remain
history for their exact commits; no pass transfers to the merged tree. The normal
step result, verification and non-forced publication must complete before advance,
and checks run for the resulting implementation commit. Land still validates its
candidate against its own fetched main and enforces changed-check protections.
Preserve the saved-work rule as well: merging a WIP tip must not erase its need
for review or turn preservation into a verified step result. An ordinary valid
keep answer must follow the owning review/commit rule for saved work even when
preparation has added a merge above it.

## Persistence, release and explanations

Persist source/target, owner continuation, slot/generation/D, preparation result,
agent executions and session/process identities, evidence references and pending
Git/ref actions. The merge store owns its tables; consumers use typed methods,
not its SQL. Each external effect has a short intent transaction, action outside
the transaction and short result transaction. Include fetch, slot preparation,
merge start/completion, agent launch and result-ref attachment in reconciliation.
Inspect refs, HEAD/parents, active merge and owned liveness; adopt completed work
after crashes instead of duplicating merges, ref writes or surviving executions.

Do not bypass resumption merely because the slot is already on its task branch:
pending preparation must complete before the ordinary attempt dispatches. Unknown
process state keeps the reservation. Integrate with drain, status and owning
release; a schema change drains old attempts before database discard, with no
compatibility reader or reconstruction from logs.

Use the owning preservation work assessed by `.155` for terminal merge work:
retain immutable inputs, completed merge ancestry and working files before
reset/abort/parking. Current main's single-parent WIP save is insufficient for
an active merge. Bring only the required assessed preservation changes if they
have not landed. If capture fails, keep the slot reserved. Abort only after
preservation and confirmed process stop; release parks at the original D.

Explicit holds remain held. Do not automatically clear today's refusal holds,
reapprove tasks, rename/delete branches or discard factory state. Terminal merge
holds must not enter generic label reingestion that restarts at plan. Reuse the
owning typed hold operation, including `.155`'s unlabelled protection where needed;
do not invent a tracker-answer workflow in this task.

CLI, round and status consumers use the same typed preparation result. Explain
that main moved and the factory is merging it while retaining the task's work;
show pending resolution or the actual terminal decision. Replace `DIVERGED`'s
blanket branch-rename/delete/restart advice. A message describes the situation
and decision in words, without asking the owner to run a CLI command.

## Implementation and verification

First change the admission rule and its semantic tests, then implement/wire the
shared merge operation and durable preparation continuation. Update `prepare`,
`admit`/`admit_chain`, attempt dispatch/setup, failed-check repair and the owning
store/reservation/drain/release/hold consumers as required. Share merge mechanics
with `.155`; keep its land policy/UI work out of this change. Update glossary D/B,
task-branch documentation and affected refusal/help text to match the behavior.

Use focused pytest functions with the owning Git/process/agent fakes. Extend or
split `tests/steps/test_prepare.py` and add feature tests with narrow imports;
respect 400 source lines/file, 80/function and 800/test file. Cover:

- Published plan on an older main, main advances, all free slots at its new tip:
  admission and entry succeed, the implementation starts with the plan and main
  changes, and no new plan execution occurs. Exercise explicit start and round
  advance, local-only factory work, remote-only and both task refs.
- D at old/current main, at task-only history, mixed valid/invalid candidates,
  and no valid candidate. Include local main lagging origin, source already
  containing main, source behind main and ordinary forks needing a merge.
- A stale non-selected remote task tip does not invalidate a usable D. Preserve
  foreign unpublished-work, ref-name collision, checked-out-branch and lost
  `after_commit` protections. Unrelated histories and a branch substituted during
  take still refuse; missing/unreadable targets do not masquerade as divergence.
- Clean merge and textual-conflict resolution preserve both changes and source
  ancestry. Conflict paths, unsupported resolution, bounded exhaustion and
  explanation coverage use typed results. Preparation proceeds independently
  of `land: manual`; that policy still controls delivery, not source preparation.
- A task branch/publication completes normally after preparation; fresh checks
  evaluate the new tree. Failed-check repair retains source fencing. Merging
  saved WIP cannot create a pass or bypass the saved-work review requirement.
  A second admission after merging origin ahead of local main does not falsely
  report main's commits or the factory merge as `branch_unpublished`.
- Crash injection after each intent/action/result boundary adopts the same
  result, preserves reservations and sessions, and launches no duplicate live
  agent. Include already-attached branch resumption, target/ref moves, drain,
  preservation failure, preservation-before-abort and release back to D.
- Already-held work stays held; repeat leftovers are preserved. Sequential main
  landings across several waiting tasks never cause plan replay or repeated
  false `branch_diverged` holds.

Read the justfile before execution. Run `just install`, focused installed-package
pytest selections while developing, then require `just check` and `just test`
to pass. These are the declared successor CLI/steps/rules gates; do not add a
whole-repository or live run. Use `uv run --frozen --no-sync python -I -m pytest`
for focused selections, with no editable baseline install or PYTHONPATH fallback.
Report commands and results in implementation evidence. This planning revision
does not run source gates or claim the acceptance criteria have passed.
