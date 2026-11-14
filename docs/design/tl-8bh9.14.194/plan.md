# Depth

Medium: three testable behaviours cover new branch bases, continued branch merges, and free slot parking against current origin main. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total.

## Size

Estimate: 16 changed files, including tests, glossary corrections and this plan; allow up to 22 if shared test fixtures need adjustment. No database schema change. One implement attempt: approximately 65 model calls, including focused verification and the two final gates.

Three independent behaviours and their acceptance criteria:

1. New task branch: after fake origin main advances beyond both local main and its remote-tracking ref, admission fetches it and execution creates the task branch at that fetched commit. The person's main ref, HEAD, index and working files remain unchanged. The same succeeds without a local branch named main.
2. Continued task branch: a retained local branch, or remote-tracking task branch when no local branch exists, preserves its work and receives current origin main through the existing merge preparation. A test asserts both histories survive and local main remains unchanged.
3. Free slot parking: an admitted attempt records the fetched origin main commit as its release park point; its owning release leaves the slot clean and detached there while retaining the task branch's result. Repeating release after interruption converges on that same recorded commit. Subsequent admission refreshes origin again.

These are one bounded implementation, below all implement limits. Checkout preservation is an invariant of all three behaviours, not an additional operation.

## Evidence and terminology

At source commit `3272c80f861544a6529377ccc47bdcccc25f4c6c`, `prepare.branch_refusal` selects local main only when neither task ref exists. `admit.branched` supplies the selected source to input generation but supplies the observed slot HEAD to reservation storage. Release later parks at that stored `slot_head`. Changing only branch selection therefore leaves an obsolete park point.

`land_push.fetched` already fetches only `+refs/heads/main:refs/remotes/origin/main` with an explicit bounded timeout. Continued preparation already fetches and merges origin main, with durable merge intent and crash reconciliation. Admission's shared `branched` caller also serves advances and check repair, outside their write transactions.

Use the supplied definitions of task, attempt, slot, task branch, admission and worktree. Call `refs/remotes/origin/main` origin's **remote-tracking ref**, as the glossary already does. Retain the distinction from the person's `refs/heads/main`; do not redefine the existing `MAIN` constant globally, because checks and factory commit protection also import it. Update the glossary's task-branch rule, which currently explicitly prescribes local main and no fetch, to reflect this task's authorized change. No new glossary term is needed.

The checkout is clean and has no existing task plan or unfinished task commit in the inspected branch history.

## Implementation

1. Refresh origin main on admission after the cheap task/store/free-slot checks and before source selection, input generation or tracker claiming. Use the same bounded fetch operation as land through the existing Repo port; no shell Git or new subprocess boundary. Put reusable source observation in `prepare.py` and keep `admit.branched` a small application wrapper, so `admit.py` fits the 400-line cap (it currently has 401 lines). Fetch stays outside every SQLite write transaction. Fetch is repeatable and observable through the remote-tracking ref; a restart can fetch again before any attempt exists.
2. Use `ORIGIN_MAIN` as the new-branch fallback in `branch_refusal` and in advance's previous-commit containment check. Retain local-first and then remote-tracking task-source precedence, branch-held checks, unrelated-history protection, foreign unpublished-work protection and previous published-commit fences. Keep local main available for its existing protection/read roles. Correct local-main wording in preparation docstrings and refusal explanations. A failed fetch returns the existing unavailable Git outcome with an explanation; missing origin main refuses the target and never silently uses stale local main. Cover failed structured fetch results as well as raised Git errors.
3. Carry the observed free-slot HEAD separately from its intended park commit while admission checks eligibility. Store the fetched origin main commit in the existing attempt `slot_head` field as the release destination, through the normal reservation transaction. Use an explicit name such as `park_commit` for that in-process value instead of overloading `Free.head`. The observation used to establish safety remains the actual detached slot HEAD. Update fresh admission, advance and check-repair consumers together; SQL stays in their owning modules. No additional schema or parallel state owner is required.
4. Free slots return to the fetched tip through the existing owning release operation: reservation intent is already durable before Git changes; parking happens outside the write transaction under slot custody; release records the observed result afterward. Preserve pointer validation, branch and dirty-state checks, stop proof, interrupted-release reconciliation and held-work preservation. A release uses its recorded commit rather than fetching a different target during cleanup. An idle slot from an earlier attempt remains eligible through the refreshed origin history and acquires the refreshed park destination when next admitted.
5. Preserve continued merge preparation, including its independently refreshed target, recorded target on resume, retained work and repeat-leftover bypass. Do not replace it with a branch reset. A later origin move may legitimately be merged before dispatch; the branch's initial base and recorded park destination still come from admission's bounded fetch. Shared admission changes must also work when a failed check starts a fresh implement attempt; takeover of an existing attempt with leftovers retains that attempt's recorded park point.
6. Update the existing semantic fake tests and the one real preparation wiring test that currently advances only local main and supplies no origin. Give the real test a temporary local origin fixture; it remains an offline test, using existing owning Git testing APIs. No new files are expected beyond this plan. Keep source/functions/tests within their line caps, moving source-selection logic into the existing preparation owner rather than growing admission beyond its cap.

## Validation

Use a fake origin initially at A, a checkout whose local main and tracking ref remain at A, and an adopted detached slot at A. Advance only origin main to B without a checkout pull or a test-side fetch. Run real admission and preparation orchestration with semantic fakes. Assert the new task branch initially starts at B, input context is read from B, and local main and the person's checkout state remain at A. Change origin again for a second admission to prove refresh occurs each time.

For continued work, create a factory-owned task commit on A, advance origin to B, and assert ordinary preparation preserves the task commit and includes B. Exercise local and remote-only task-source precedence, previous-X containment, and the existing merge failure/resume cases. For parking, settle an admitted attempt and assert its detached slot returns to the captured B, its task result survives, and repeat release does not fetch or move its destination. An origin move after admission must not substitute the person's main or change the recorded park destination.

Add focused failure coverage for failed fetch, absent origin main and missing local main. Failed refresh must not claim the task, create input evidence or reserve a slot. Preserve existing ownership, redirected-pointer, dirty-slot, unrelated-history and held-work tests. Adjust tests that deliberately assert the superseded local-main contract instead of retaining a fallback for them. Include advance and failed-check repair coverage for the shared admission path.

During implementation, use only focused tests where necessary, with the authorized isolated pytest command form. Finish with exactly one run each, last, of `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, preserving pipeline failure status. No live tests. Planning does not run implementation gates.

## Read list

- `src/taskloop/prepare.py:1-211` — source selection, ref names, branch protection and branch creation integration.
- `src/taskloop/admit.py:93-209` — Free values, fresh admission ordering and input-context source.
- `src/taskloop/admit.py:265-401` — reservation park destination, shared branch wrapper and its transaction consumer.
- `src/taskloop/admit_chain.py:298-395` — advance producer/caller, park destination and previous-X fallback.
- `src/taskloop/land_push.py:28-85` — existing bounded origin-main fetch and its remote-tracking ref.
- `src/taskloop/merge/start.py:110-158` — continued merge refresh, target recording and ancestry fences.
- `src/taskloop/merge/prepare.py:20-83` — preparation orchestration, repeat bypass and recorded slot-base fence.
- `src/taskloop/slot_release.py:104-155` — owning park action and saved-work safety.
- `src/taskloop/slot_release.py:307-355` — release caller, recorded park point and retained-work integration.
- `src/taskloop/slot_lock.py:45-91` — custody and free-slot probe contracts.
- `src/taskloop/git_views.py:22-57` — explicit transport timeout and hardened Repo ports.
- `src/taskloop/composition.py:213-231` — production admission construction if port wiring needs adjustment.
- `src/taskloop/check_repeat/store.py:61-110` — shared source caller and check-repair reservation destination.
- `src/taskloop/checks.py:30-65` — existing local-main consumer that prevents global MAIN reinterpretation.
- `src/taskloop/factory_commit.py:217-237` — existing MAIN consumer for foreign-work protection.
- `tests/steps/test_prepare.py:53-168` — semantic repo fixtures and superseded new-branch contract.
- `tests/steps/test_prepare.py:322-460` — fresh admission fixtures, branch refusal and slot eligibility contracts.
- `tests/steps/test_prepare_main.py:1-90` — current-main eligibility and selected-source protections.
- `tests/steps/test_admit.py:101-143` — admission builder and offline slot fixtures.
- `tests/steps/test_merge_prepare.py:19-136` — continued merge, unchanged local main and fetch-resume coverage.
- `tests/steps/merge_bench.py:1-85` — semantic merge fixture and retained-source setup.
- `tests/steps/test_slot_release.py:166-179` — release destination and idempotent release assertions.
- `tests/steps/real/test_prepare_real.py:55-109` — real preparation wiring fixture that currently advances only local main.
- `tests/steps/test_check_repeat.py:270-321` — shared check-repair admission, interruption and overlapping-start integration.
- `docs/glossary.md:40-50` — task-branch rule and existing remote-tracking terminology to align with the task.
