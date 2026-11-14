# Depth

Medium: three linked behaviours preserve retained work, retain exact ownership, and adopt only the recorded expected checkout after an interrupted abort. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total. Conflict preservation is present in source commit e4f1eecf9928d85e8abe8aa4723f557486ef2258; the earlier discussion's dependency is satisfied.

## Size

Estimate: 9 changed files, including this plan, 2 new source files and 1 new test file; approximately 55 model calls for one implement attempt, including focused verification and the final gates. Ceiling: 60 files, 3 independent behaviours and 100 calls.

The three independently testable behaviours are:

1. Preserve before abort. A terminal conflict with tracked edits, staged edits, deletions and untracked files retains their captured bytes and both merge inputs under the existing conflict ref before any abort. Ignored local files survive on disk. Interrupting before or after abort does not replace the retained tree with the reverted checkout.
2. Fence exact ownership. A changed dispatch token, reservation generation, slot path, repository, Git directory or process identity prevents abort and adoption. The matching reservation remains intact throughout this operation, including failures and restart.
3. Reconcile the recorded checkout. After reopening the intact database, a pending abort retries only its unchanged recorded precondition or adopts its exact recorded postcondition. A checkout with unexpected HEAD, branch, merge inputs, index or file contents is refused; a matching checkout with expected surviving untracked files is adopted. No second agent execution or duplicate preservation is launched.

## Scope and evidence

This implements the abort portion of conflict cleanup in `land_conflict`, building on its landed preservation operation. Parking and reservation release belong to the subsequent split task. Ordinary attempt abandonment in `slot_release.py` is a separate existing caller of Git abort; it is evidence of the interrupted-abort problem, not the owner of a detached land conflict's reservation.

`execute.py` already holds slot custody, reconciles setup, validates the durable admission and runs preservation for completed or terminal merges. `preserve.py` publishes an operation-specific ref and checks its captured tree, but does not abort. `ConflictStore.save` currently permits only monotonic capture/object/ref/complete transitions. `Save` records the pre-abort HEAD and tree, not an abort postcondition. Re-running preservation after an abort would compare against the wrong checkout. The pinned shelf abort wraps `git merge --abort`; its fake restores tracked merge state, and untracked files can survive. A clean-checkout test is therefore insufficient.

Use the supplied glossary's task, attempt, slot, worktree and land meanings. No additional glossary terms or owner terminology decisions are needed.

## Read list

- `src/taskloop/land_conflict/execute.py:45-122` — custody, admission fence, terminal producer and restart dispatch; integrate abort here.
- `src/taskloop/land_conflict/models.py:13-46` — immutable admission and exact key/slot identity.
- `src/taskloop/land_conflict/models.py:80-117` — saved state model and invariants; extend its structured envelope for abort intent/result.
- `src/taskloop/land_conflict/store.py:31-76` — fenced save/load and compare-and-swap transitions; store abort state through this owner.
- `src/taskloop/land_conflict/reservation_store.py:8-18` — exact reservation and current slot predicate used by every store transition.
- `src/taskloop/land_conflict/preserve.py:29-99` — worker stop proof, ownership checks and immutable save inputs.
- `src/taskloop/land_conflict/preserve.py:108-181` — completed preservation, retained-object verification and pre-abort checkout checks.
- `src/taskloop/slot_state.py:102-135` — hardened repository/pointer observation before checkout effects.
- `src/taskloop/slot_state.py:138-158` — structured status decoding for tracked and untracked paths; reuse owning observation rather than parsing display text.
- `src/taskloop/merge/models.py:1-149` — merge identity, terminal reason and explained typed results.
- `src/taskloop/merge/store.py:16-42` — durable merge record and compare-and-swap producer read by execution.
- `src/taskloop/slot_release.py:338-369` — existing ordinary release save/abort sequence; boundary comparison only.
- `tests/steps/land_conflict_bench.py:74-140` — execution ports, semantic Git fake and intact-database restart fixture integration.
- `tests/steps/test_land_conflict_save.py:32-105` — preservation acceptance and retained-bytes assertions affected by abort integration.
- `tests/steps/test_land_conflict_save.py:108-180` — interruption boundaries and reopening tests to extend without duplicate preservation.
- `tests/steps/test_land_conflict_save.py:232-280` — changed-checkout refusals which must remain strict.
- `tests/steps/test_land_conflict_execute.py:35-70` — executor caller and stale ownership tests.
- `tests/steps/test_land_conflict_restart.py:172-201` — terminal hold and foreign/changed checkout regression cases.
- `uv.lock:45-48` — authoritative pinned Git adapter revision.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/api.py:331-379` — read at pinned c6384f0bf870a430b7bffe826f9f42b6138d7d44: reset, snapshot, capture and dirty contracts.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/api.py:460-478` — read at the same pin: merge observation and owning abort API.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/real_merge.py:70-78` — pinned real abort effect and failure semantics.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/fake_merging.py:57-63` — pinned semantic fake abort effect; tests must include untracked survivors explicitly.

All shelf reads use `git show` at the locked revision; shelf is read-only. Additional targeted searches are allowed for changed source or missed callers. New files below are integrated through the listed existing executor, model/store and test fixture files.

## Implementation

Add new `src/taskloop/land_conflict/abort.py` for the one owning abort operation and new `src/taskloop/land_conflict/abort_models.py` for its frozen pydantic inputs/state and enum phase codec. Integrate through `execute.py`, `models.py` and `store.py`; add new `tests/steps/test_land_conflict_abort.py`, and update `test_land_conflict_save.py` and `test_land_conflict_restart.py` where terminal execution now observes an aborted checkout. Together with this plan these are the estimated 9 changed files. Existing `preserve.py` remains the producer of the verified durable save.

Persist abort intent and completion within the conflict slice's existing JSON save envelope. Do not change the SQL schema or its version, add a parallel state owner or reconstruct state from logs. Use typed nested models and a single codec, keeping the original preservation facts immutable. `ConflictStore` alone performs SQL and validates allowed compare-and-swap transitions under `owns`; an abort transition must not change the retained tree, commit, ref or key. A matching save is necessary but not sufficient authorization for an abort.

The abort operation accepts the existing admission, terminal merge and completed save under the executor's slot custody. Confirm stopped resolution workers and settled setup, then recheck admission, reservation, repository, slot path and Git directory. Verify the retained ref still names its recorded commit and the object still matches the recorded preservation inputs. Never abort an accepted completed result, foreign active merge or refusal about changed ownership. A terminal result without an active merge needs no abort; it must still pass its saved-checkout verification.

Before an effect, record both the exact expected precondition and postcondition. Include detached HEAD, repository/slot/Git-directory identity, merge target/state, index identity and captured file identity. Derive the postcondition from the recorded source tree and the pre-abort structured index/status and saved tree: paths restored by abort come from the source; ordinary untracked survivors retain their recorded names, modes and blob identities. Include deletions and staged additions in this accounting. Do not equate the postcondition with `dirty == false`, or substitute the current observation for an expectation after the effect. Preserve ignored local data by leaving it untouched; do not introduce clean, hard-reset, forced-checkout or direct filesystem deletion as abort recovery.

Use existing shelf tree/snapshot/status APIs and narrow owning observation helpers for the comparison. If an unusual state cannot be proven to have the recorded postcondition, return an explained typed refusal with custody retained rather than guessing. The normal tracked-edit and untracked-file cases in the acceptance criteria must be supported. An actual missing shelf capability requires a concrete owner proposal; it does not authorize modifying shelf or adding subprocess calls.

Write intent in a short fenced transaction, close it, re-observe its precondition and call `Worktree.abort_merge()`. Re-observe the world and record completion in a second short fenced transaction only if it matches the previously stored postcondition. Git failure, lost ownership or interruption leaves the intent pending. On restart, inspect a pending/completed abort before invoking `Merge.resume` or preservation: adopt a matching postcondition, retry a matching still-merging precondition, otherwise retain ownership and explain the mismatch. Check this ordering before recomputing save inputs, because those describe the former merging checkout.

Return the existing original terminal result after successful abort reconciliation. Preserve its reason and explanation; observation failures get an explained existing unavailable result. Do not relaunch resolution, clear the terminal hold, move the checked task branch or remove a reservation. A completed abort record is the durable handoff for the later parking/release operation; it is not proof that the slot is free.

## Verification

Use the conflict execution fixture and semantic shelf fakes, reopening the database between interruption and retry. Inject interruptions immediately before abort, immediately after Git changed the checkout, and after the completion transaction. Assert retained ref/commit/tree and both parents remain identical, the checked task branch is unchanged, worker calls do not increase, and the exact reservation remains.

Exercise tracked conflict edits, partial staging, deletion, newly staged files, ordinary untracked files and ignored local data. Inspect saved bytes in the retained object rather than expecting reverted tracked checkout files to equal the saved tree. Assert untracked survivors are included in the recorded expected checkout and survive retry. Mutate one postcondition fact at a time after interruption: HEAD, branch, merge target, index, tracked bytes, untracked path/content, Git directory and reservation token/generation/path. Each must refuse adoption without another abort, a new save or a reservation change. Cover capture/ref failures preventing abort and a successful accepted merge bypassing abort.

Preservation interruption tests must continue proving that a pending save cannot be replaced by later edits. Keep the generic attempt-release regression tests passing without redirecting their ownership to the conflict slice. Use pytest functions and focused contracts, no live tests, subprocesses, new casts, ignores or Any. Stay within 400 source lines per file, 80 per function and 800 per test file.

Run a focused affected test file when developing with the allowed `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40` form against the installed successor environment. Finish the implement attempt with exactly one run each, last, of `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving command failure status. Both must pass. This planning attempt does not run implementation gates.
