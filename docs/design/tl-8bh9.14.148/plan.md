# Preserve held work on the task branch and release the slot

Task: `tl-8bh9.14.148`. Planned against `3787e45427de45fedda96d078fe03f5d4348dc63`.
This is an implementation specification. The owner decision of 2026-11-13 replaces the
rescue-patch proposals in `.46`, `.69` and `.70`.

## Result and decisions

A hold preserves the slot's tracked changes and non-ignored untracked files in a WIP
commit on `task/<id>`, stores that commit's full object id in the hold's reason, and
releases a clean, detached slot during the same operation. No separate WIP ref, patch,
stash, backup directory or deletion is involved. Ignored files remain on disk. A held
task remains held until the existing owner-answer/re-ingestion rule permits another
attempt; releasing capacity does not authorize more work on that task.

The following settle the task's open points:

- A WIP commit preserves work; it is never an implemented result, a verified step
  result, a check input or a land candidate. Saving it does not run checks. A later
  attempt continues from its tree but must produce a distinct normal verified result
  before checks can run. An `unchanged` answer alone cannot promote a WIP commit.
- Normal re-ingestion continues the preserved branch. A hold caused by a land conflict
  restarts from fresh main when the owner answers by restoring the approval label.
  Preserve the old branch as `old/<id>-<sha>`, using the old tip's first 12 hex digits,
  before making the replacement task branch. Holding alone never restarts work.
- Land keeps its existing squash operation. WIP ancestors of a subsequent verified
  implementation are included in that implementation's complete change and disappear
  into the single squash on main. WIP commits themselves are never delivered.
- Capture all tracked changes, including tracked files matching ignore patterns, and
  every non-ignored untracked path. Use repository ignores and worktree-local
  exclusions for junk; do not guess that an unfamiliar untracked source file is junk.
- Saving a WIP commit is local. Existing attempt publication remains the only push
  route: verified result, pinned SHA, non-force push, normal refusal/retry behavior.
  A later published result can carry WIP ancestors. Saving a hold does not publish or
  mark a WIP SHA as published, and remote failure cannot prevent local slot release.

The clean/reusable guarantee applies once existing process-stop and ownership proofs
pass. Unknown or live processes, redirected pointers, foreign branches and failed Git
or database operations retain their truthful pending/refused results. They never
authorize overwriting work or reporting a slot free before preservation is durable.
Dirty work itself is no longer a reason for a hold to retain its slot.

## Current paths that need changing

`hold.hold_task` records the cause and labels, then `_abandoned` calls the shared
`operations.release_task(abandon=True)` and posts the hold comment. That operation
releases a land candidate, checks attempt and agent attempt in order. Its agent
release reaches `slot_release.park_slot`, which returns `slot_dirty` before parking.
`hold_facts`, `hold_text` and `hold_guide` then describe work a person must clean.
This is the capacity failure to remove.

The checks/candidate half needs explicit coverage too: `ChecksRelease._parked` calls
`_reset`/`environment.reset_to` before parking. That reset removes tracked changes,
untracked files and ignored files. A hold must preserve its state before that reset
can happen, and use a release mode that does not run the reset or empty scratch.
Fixing only the agent slot leaves another destructive path reachable from a hold.

`task_hold.reason` currently stores a bounded cause string; readers compare that
string for routing. `prepare._foreign_unpublished` recognizes factory commits by
the existing attempt trailer, and preparation can otherwise refuse an unpublished
WIP as foreign work. `prepare` normally resumes an existing task branch, with local
main as the new-branch default. `land_guide.restart` and `test_conflict_recovery`
currently describe/test manual branch renaming and remote deletion; the new path
must preserve the local branch without copying that deletion protocol.

The declared dependency is already `git-porcelain==0.20.0`. Use the supplied
`Worktree.capture`, `Repo.commit_tree`, CAS `Repo.update_ref`, `Worktree.exclude`
and `park(keep_ignored=True)` for WIP preservation. Use existing shelf reads,
locks and process observations. No factory Git command, subprocess wrapper,
dependency upgrade, fallback or request for another shelf capability is needed.

## One preservation operation and its stored progress

Add a small vertical feature under `src/taskloop/hold/`, moving the current hold
entry module into that package if necessary to retain its import surface. Keep the
new use case and its store separate; do not enlarge `slot_release.py` beyond the
source/function caps or build a general Git transaction framework. Existing release
stores continue owning their reservation/release tables. The hold store owns hold
reasons and the new pending preservation/restart records.

Use Pydantic v2 models at the database boundary for a structured reason containing
the original cause and an ordered collection of saved slot/commit identities.
Preserve the cause independently of these identities so routing never examines a
rendered message or splits a reason string containing a SHA. `HoldStore` owns the
single storage codec. Update all hold consumers to read the cause and saved commits
through typed fields; the displayed/commented reason names every saved full SHA.
Use enums/classes for the closed lifecycle/cause values touched by this feature.
Do not introduce another public domain term.

Persist enough progress to reconcile without files or logs: hold/cause identity,
attempt key and reservation generation, slot identity/path, expected slot HEAD and
task-ref tip, captured tree, produced commit, ref destination, park destination and
completed actions. Validate commit ids and paths at this boundary. The original
cause and save identity are immutable; completion writes are revision-fenced.
Persist commit inputs, including the factory identity, message and supported time
inputs, rather than deriving them from a new clock reading on each retry. Use an
ordinary `WIP: ...` subject and the existing factory attempt trailer plus explicit
WIP metadata, so factory provenance does not imply implementation success.
The Git adapter recognizes that metadata even after deliberate execution-DB
discard; this classifies a commit, without reconstructing execution history.

Changing the schema follows the repository's drain-and-discard upgrade rule:
drain running attempts, stop old entry writers, discard the old execution DB, then
start the new version. Do not migrate execution history or add a legacy reason
reader. Durable task data, branches, worktrees and evidence are not discarded.

## Hold sequence

1. Retain the current cause/current-attempt fences, tracker label handling and
   stop proofs. Before capture, prove the registered entry, agent/group, setup and
   any check commands stopped using their owning ports. Acquire existing custody
   locks non-blockingly and re-read identity, reservation, generation and cause.
   A free lock alone is never a stop proof.
2. Record a preservation intent in a short transaction. Read the slot through its
   validated pointer and pinned hardened Git view. Only the owned task branch,
   the agent's recorded pre-branch detached HEAD, or the expected detached
   checks/candidate HEAD is admissible. An attached foreign
   branch is refused even if dirty; no branch switch or write occurs there.
3. Apply worktree-local exclusions only for established generated junk paths;
   keep repository ignores effective. Never write shared repository excludes or
   `.gitignore` to make a hold succeed. Capture the exact current working tree
   with `Worktree.capture`, including deletions, renames, modes and symlinks as
   Git entries, without following symlinks or executing hooks. The working file
   version wins over an earlier staged version. The index is not a second saved
   tree. Store the captured tree before moving any ref.
4. Make a WIP commit with `Repo.commit_tree`, explicitly parented by the observed
   task-branch tip. Record its SHA before attempting a CAS ref update. Compare the
   target ref against that exact parent; a concurrent movement is a typed refusal
   with an explanation, never a force or a retry against an unexamined new tip.
   For an attempt that failed before creating its branch, create the task ref
   with an expected-absent CAS, parented by its recorded branch start. Do not
   create a commit for a clean slot or one containing only ignored junk: that
   path proceeds to preservation-aware parking without a saved-commit entry.
5. For checks/candidate slots, save their complete detached tree on the same task
   branch before releasing them. Keep the actual detached source HEAD in the save
   record; it is not an implemented result. If multiple reservations have dirty
   work, serialize their saves in the existing release order. Each new WIP's
   parent is the preceding task tip, so every earlier saved tree remains reachable.
   Store each slot's SHA in the reason; do not silently substitute the last tree
   for all previous saved work. A later attempt sees these saved identities and
   must reconcile the work, rather than treating the last snapshot as validated.
6. Confirm the target ref names the recorded WIP and persist that SHA in the hold's
   structured reason before touching the working files. Under the same custody,
   confirm the slot still matches the captured state. Use shelf parking with
   `keep_ignored=True` to normalize the index and detach at the saved tree, then
   park at the existing admission park commit D. The task branch retains WIP.
   Ordinary checkout changes are safe only after the entire saved tree is reachable;
   no reset/clean, unlink, directory removal or scratch emptying belongs to this
   hold path. If parking cannot preserve an ignored-path collision, keep it pending
   with the adapter's explanation instead of removing the file.
7. Confirm detached HEAD, an empty tracked/non-ignored dirty observation and intact
   ignored files. Record the release and free the reservation through its owning
   release store, fenced on the original attempt and generation. Return the claim
   through the existing fenced unclaim. A tracker outage can leave unclaim/comment
   pending while the locally released slot is already available to other tasks.
8. Render the stored cause, saved commit ids and actual release/claim result in the
   hold's comment/status. State that work was saved and the slot released, and what
   owner decision the original cause needs. Never ask the owner to clean the slot
   or execute a CLI command on this path. Preserve the existing comment lease.

Thread a typed hold-preservation context through the shared release operation and
both release implementations. Do not duplicate the reservation, unclaim or release
logic in `hold_task`. The context selects the save-before-park path and suppresses
checks/candidate reset and scratch deletion. Normal successful checks release keeps
its existing behavior. For a labelled failure whose existing cause rule requires
a hold, defer the entry's early automatic release to the hold operation, so dirty
failed work survives until preservation. Apply the same rule to a failed land
candidate before its automatic release. Keep ordinary check-repair eligibility
and successful cleanup unchanged; do not turn a repairable failure into a hold.

Every Git/tracker action runs outside a write transaction: intent, action, result.
After a crash, reconcile by reading refs, trees, slot state, releases and claim
ownership. An already-created object can be reused/remade without adding another
branch commit; a successful CAS with no completion record is adopted when the ref
already names the recorded commit. A slot already parked but still reserved is
finished by its original generation; a released slot now held by another attempt
is never touched. Missing objects or unexpected refs are explicit failures, not
permission to reconstruct progress from a comment, log or worktree age.
Cause fences recognize changes made by this recorded preservation/release itself;
they must not retire a pending hold because its own WIP or first released half
changed the displayed status. External replacement of the attempt remains fenced.

## Continuation, fresh-main restart and delivery

The normal answered-hold route resumes the WIP branch in a fresh attempt/session.
Recognize its factory provenance in the unpublished-branch check without making
foreign commits acceptable. Carry saved commit references into the admitted input,
including snapshots from detached slots. Keep WIP ids separate from `end_commit`,
verification, published-result and check records. An old successful result/pass
cannot become a pass for the new WIP tree. Guard explicit CLI calls as well as round
advancement: neither checks admission nor land can select a saved WIP SHA, and
verification cannot accept `keep` at a WIP SHA as completion.

For an answered land-conflict hold, the existing re-ingestion transition performs
the fresh-main restart automatically, before branch admission. Fetch/read origin's
current main through the existing owning Git port, pin its SHA as the restart base,
and record the old task tip and archive destination in the restart intent. Rename
the old branch using the existing shelf branch API, then create the replacement
task ref at the pinned main using expected-absent CAS. Never update or check out the
person's main. The archive preserves WIP and earlier commits. If the archive name
already identifies that exact tip, adopt it; an existing different tip is a refusal,
not permission to overwrite it. Reconcile both sides of a crash between rename
and replacement creation. Recheck worktree ownership and serialize against other
task branch writers before either action.
An existing exact archive with an absent task ref permits expected-absent creation;
with the task ref already at the pinned new base it is complete. If the archive
and task ref both still name the old tip, CAS the latter from old tip to new base,
since preservation is already proven. Other combinations refuse without writes.

The restarted admission uses the recorded new local branch, not an old
remote-tracking task branch. Its previous attempt/check/plan results confer no
completion on the restarted chain; plan and implement follow their normal rules
from the fresh base. Other answered holds continue WIP by default. This adds no
new CLI command or restart based merely on main moving.

Never delete a remote branch or force a push to make a fresh restart publish.
If a previously published task branch prevents fast-forward publication of the
new history, preserve it and report the existing publication refusal, in words.
Local preservation and slot reuse have already completed. This deliberately
retains the owner's specified existing publish rules rather than copying the
remote-deletion step from the manual recovery test.

## Verification and completion

Use existing shelf semantic fakes and pytest behavior tests importing this slice
and its small ports. Add focused contract coverage for:

- A dirty agent slot with staged and unstaged edits to the same file, additions,
  deletions, renames, executable mode and a symlink: the WIP tree equals the captured
  working state, is on the task branch with the expected parent, is named by the
  stored reason, and the slot is clean/detached and immediately usable by another
  task. The original hold remains in effect and no check was launched.
- Ignored junk alone creates no WIP; mixed ignored/non-ignored work saves the latter
  and preserves the former, including a nested ignored directory. Worktree excludes
  do not affect the main checkout or another slot. Non-ignored unfamiliar files
  are included, and tracked ignored-pattern matches remain tracked in the snapshot.
- Dirty detached checks and land-candidate slots, including multiple dirty
  reservations: every tree remains reachable, every SHA is in the reason, and
  the hold invokes neither the old reset/clean nor scratch deletion.
- Every hold cause that can reach abandon, including exhausted repeats, failed
  execution, failed checks and automatic-land refusal: no `slot_dirty` hold result
  or cleanup advice remains reachable. Retain dirty-slot refusal tests for unrelated
  admission/manual-release paths where appropriate.
- Stop-proof failure, redirected pointer, foreign branch, ref CAS race and archive
  collision: preserve files/refs and reservations, and return a typed explained
  result. No success is claimed from a failed read.
- Faults after intent, capture, commit creation, CAS, reason update, each park,
  release transaction and unclaim: intact-DB restart completes unfinished work,
  adopts external success once, creates no duplicate reachable WIP and never
  touches a newly assigned reservation. Include concurrent hold callers.
- A normal continuation from WIP produces a distinct verified implementation and
  fresh checks; attempts to verify/reuse/check/land WIP directly fail. Publication
  remains non-force and conditional on normal verification. Land squashes a normal
  implementation containing WIP ancestors into one delivered commit.
- An answered conflict hold archives the exact old tip and starts at pinned fresh
  main without losing WIP; interruption between branch actions reconciles. Ordinary
  holds do not trigger this restart. A stale remote task ref cannot change its
  base; a non-fast-forward publish refuses without deleting or forcing anything.
- CLI/dashboard/hold-comment reads expose the stored cause and saved SHA consistently
  and never tell the owner to remove files or run a command to free this slot.

Read the justfile, then run `just check` and `just test` after implementation. These
are the repository's declared focused gates, not permission for whole-suite or live
runs. Run any extra behavior tests only for changed import closures; use the rebuilt
installed package and `uv run --frozen --no-sync python -I ...`. Check line caps,
import contracts, no new subprocess/signal use and no `Any`/cast/ignore escapes.

Completion requires a stored hold reason naming the saved work, an observed-clean
released slot in the dirty-slot behavior test, preserved ignored files, and no
`slot_dirty` result reachable from a hold. A plan commit alone establishes none
of that implementation evidence.
