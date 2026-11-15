# Header
Task: tl-8bh9.14.142.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; two owning modules.
Owner decisions: settled; no dependency stated unlanded.
Evidence budget: 12 model calls.
Size: 7 changed files, 2 independent behaviours, about 60 implement model calls.

## Outcome and non-goals
An implement commit includes eligible slot changes omitted from the answer. Typed dirty reads, baseline comparisons and staging fences already exist; selecting and validating the complete set is the gap. No database, merge-resolution or answer-schema changes.

## Settled decisions
- Derive only for implement commit effects; preserve keep and unfinished effects.
- Retain the answer schema, decoder bounds and cross-field checks; its list does not select commit contents.
- Use pinned typed dirty evidence relative to base, never display listings.
- Validate the whole set before staging; refuse unsafe or excess paths without truncation.
- Retain 96-path and file-byte ceilings, plan.md prohibition, factory Git writes, fences and crash adoption.

## Open decisions
- None.

## Change map
- `src/taskloop/factory_commit.py`: `_review`, `_commit`, `refusal`, `leftovers` derive and validate implement paths; preserve public signatures and plan selection.
- `src/taskloop/implement_step.py`: `input_text`, `PLAN_HANDOFF`, `OPENING`, `repeat_instructions`, `failed_check_feedback` align selection guidance; preserve decoder/schema.
- `tests/steps/test_commit_paths.py`: `answer`, `stages` support omitted-change and refusal coverage; adapt shared feedback assertions.
- `tests/steps/test_steps.py`: `test_fixed_input_and_repeat_keep_unfinished_answer_and_saved_work_guidance` and failed-check guidance distinguish plan/implement selection.
- `tests/steps/test_implement_feedback.py`: `test_failed_check_repeat_retains_the_original_implement_policy` updates selection guidance.
- `src/taskloop/steps.py`: consult `IMPLEMENT`, `kind`, `failed_check_feedback`, the answer/rules producer and prompt callers.
- `src/taskloop/slot_state.py`: consult `observe_slot`, `staged`, `bounded`; keep `listing` display-only.
- `src/taskloop/attempt_types.py`: consult `StepRules`, `AnswerState`, `path_allowed`; no stored-field changes.
- `src/taskloop/answer_decode.py`: consult `paths`, `message` for retained answer checks.
- `src/taskloop/verifier.py`: consult `Verifier._settle`, `Verifier.leftovers`, settlement and preview callers.
- `src/taskloop/merge/git.py`: preserve `accepted`'s `unsafe_path` call contract.
- `tests/steps/test_answer_contract.py`: consult implement decoding and bounds cases.
- `tests/steps/test_verifier.py`: consult commit and fresh-leftover callers.
- `tests/steps/test_merge_prepare.py`: preserve keep-effect `settle` caller.
- `tests/steps/test_slot_lock.py`: preserve serialization wrapper's `settle` signature.
- `tests/steps/real/test_commit_real.py`: consult `settle`, `clean_at` callers; no live execution.
- `docs/design/tl-8bh9.14.142.1/plan.md`: new; implement-step instructions.
- `docs/design/tl-8bh9.14.142.1/plan-metadata.json`: new; plan-reuse metadata.

## Read list
- `src/taskloop/factory_commit.py:91-188` — settlement, selection, ignored checks and foreign index.
- `src/taskloop/factory_commit.py:191-222` — unchanged filtering and nothing-written result.
- `src/taskloop/factory_commit.py:246-365` — Git-file protection, file safety and read-only parity.
- `src/taskloop/implement_step.py:27-43` — accepted answer schema.
- `src/taskloop/implement_step.py:76-203` — decoder, initial prompt and both feedback paths.
- `src/taskloop/steps.py:28-74` — rule and answer producer registration, feedback caller.
- `src/taskloop/slot_state.py:122-135` — existing pinned typed dirty read.
- `src/taskloop/slot_state.py:176-196` — display listing versus staged evidence and diagnostic bounds.
- `src/taskloop/attempt_types.py:66-75` — step limits.
- `src/taskloop/attempt_types.py:200-207` — stored answer contract.
- `src/taskloop/attempt_types.py:350-359` — structural path restrictions.
- `src/taskloop/answer_decode.py:13-45` — retained list and message checks.
- `src/taskloop/verifier.py:129-184` — preview and settlement integration.
- `src/taskloop/merge/git.py:78-89` — shared safety helper caller.
- `tests/steps/test_commit_paths.py:21-173` — semantic staging fixtures, unsafe diagnostics and unchanged filtering.
- `tests/steps/test_commit_paths.py:175-239` — baseline safety, foreign index and plan isolation.
- `tests/steps/test_steps.py:287-309` — initial/repeat and failed-check guidance assertions.
- `tests/steps/test_implement_feedback.py:21-35` — failed-check prompt composition.
- `tests/steps/test_answer_contract.py:225-307` — retained implement list contract.
- `tests/steps/test_verifier.py:291-311` — commit and read-only leftover integration.
- `tests/steps/test_merge_prepare.py:155-168` — keep-effect saved-work review.
- `tests/steps/test_slot_lock.py:190-207` — settlement signature and locking wrapper.
- `tests/steps/real/test_commit_real.py:75-98` — existing real-adapter callers; no live execution.

## Contract
Intent: derive a deterministic unique tuple from typed tracked and untracked paths relative to base, including deletions and both rename paths. Keep stored AnswerState unchanged.

Effect: before staging, apply unchanged-file filtering, path_allowed, plan.md prohibition, actual-path count, unsafe_path byte/type/content checks, changed Git-file protection and ignored attributes checks. Exclude unchanged ordinary files, including credential fixtures and over-cap baseline files. A foreign staged edit behind unchanged worktree content must still refuse.

Result: retain Committed, Rejected and Unsettled. Location, plan and count violations use unsafe with a nonempty predicate/limit explanation; ignored retains its meaning. Preview and commit share review. Empty changes retain nothing_written; unknown evidence propagates. Bound diagnostics, never candidate sets. No new vocabulary, schema or shelf API.

Plan commits still select answer.paths. Retain fenced stage/record, answer message and attempt trailer. Every implement prompt explains complete-slot selection and removal/restoration of unwanted edits, retaining required answer-list guidance without claiming it restricts the commit.

## Work packages
1. `factory_commit.py`, `test_commit_paths.py`: derive/review the set; close A1-A4 and A6 with semantic fakes, rename deletion/addition, count boundaries and preview parity.
2. `implement_step.py`, `test_steps.py`, `test_implement_feedback.py`, shared feedback assertions in `test_commit_paths.py`: close A5. Verify focused files, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, with pipeline failure propagation.

## Acceptance behaviours
A1. A valid implement answer listing only one change commits all safe added, modified and deleted slot files, including both rename paths, in one factory commit with its message and trailer.
A2. Answer-only unchanged entries do not stage files or bypass nothing_written; a foreign staged edit behind unchanged worktree content still refuses.
A3. An unlisted forbidden location, plan.md, unsafe type/content or oversized file refuses before staging; 96 actual paths pass the count boundary and 97 refuse without truncation.
A4. Ignored attributes affecting an unlisted changed path refuse, and read-only inspection reports the same refusal as settlement.
A5. Initial, repeat and failed-check implement prompts consistently explain selection from the slot and removal/restoration of unwanted edits; the existing accepted answer-list contract and Git-write prohibition remain.
A6. Planning still commits only its declared paths, while keep-effect saved-work review and factory crash-adoption/fencing contracts retain their existing results.
