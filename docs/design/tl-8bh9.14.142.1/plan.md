# Header
Task: tl-8bh9.14.142.1
Base: 8458045eea670bf77b98fd6f57dba379e30c024c
Depth: medium; three owning modules.
Decisions: settled; no unlanded dependency.
Evidence budget: 12 model calls.
Size: 14 files including tests/artifacts; 3 independent behaviours; ~60 implement calls.

## Outcome and non-goals
Slot selection and guidance exist; verdict membership still rejects safe changes omitted from implement answers. Complete verification and repair affected tests. No schema, shelf, merge-resolution or publication changes.

## Settled decisions
- Implement selection uses typed slot status against base; answer.paths remains accepted but does not restrict implement commit contents.
- Plan commits retain per-attempt answer-path membership throughout their chain.
- Preserve unsafe, ignored, count and byte refusals, preview parity and factory-owned Git writes.
- Preserve chain ancestry, modes, artifacts, fencing, crash adoption and existing answer-list contracts.

## Open decisions
- None.

## Change map
- `src/taskloop/factory_commit.py`: retain `_review`, `_commit`, `_foreign`, `leftovers`; audit complete selection and pre-stage refusals.
- `src/taskloop/implement_step.py`: retain `COMMIT_SELECTION`, `input_text`, `repeat_instructions`, `failed_check_feedback` and schema.
- `src/taskloop/verdict.py`: `judge`, `_link`, `_changes` require answer membership for plan links, allowing reviewed implement changes omitted from answers.
- `tests/steps/test_commit_paths.py`: `answer`, `stages` and selection cases retain complete-set safety, limits and preview coverage.
- `tests/steps/test_verifier.py`: `test_judge_rules_the_verify_path_cannot_reach` and commit cases cover implement omission acceptance and plan rejection.
- `tests/steps/test_repeat_dispatch.py`: cover implement chain omissions and retain plan membership/ancestry checks.
- `tests/steps/test_check_repeat.py`: `repair_agent` and repair cases verify omitted safe changes through fresh checks; correct exposed assumptions.
- `tests/steps/test_steps.py`: prompt and `attributes` cases retain selection guidance and plan policy.
- `tests/steps/test_implement_feedback.py`: failed-check assertions retain complete-slot guidance.
- `tests/steps/test_agent_launch.py`: input/feedback assertions retain policy across launch paths.
- `tests/steps/test_input_context.py`: `settle` caller retains digest freshness and post-commit leftover fixtures.
- `tests/steps/real/test_commit_real.py`: `settle`, `clean_at`, `judge` callers retain pointer, safety and omission coverage with local fixtures.
- `src/taskloop/verifier.py`: consult `Verifier._settle`, `Verifier.leftovers`, settlement and judgment callers.
- `src/taskloop/steps.py`: consult `IMPLEMENT`, `PLAN`, `kind`, `failed_check_feedback`, rule/schema producers and prompt dispatch.
- `src/taskloop/check_repeat/repair.py`: consult the `failed_check_feedback` caller.
- `src/taskloop/slot_state.py`: consult `observe_slot`, pinned typed status and display listing boundaries.
- `src/taskloop/attempt_types.py`: consult `StepRules`, `AnswerState`, `ChainLink`, `path_allowed`; retain stored shapes.
- `src/taskloop/answer_decode.py`: consult `paths`, `message`; retain decoder bounds.
- `src/taskloop/merge/git.py`: consult `accepted`, the shared `unsafe_path` caller.
- `tests/steps/test_answer_contract.py`: consult implement decoding and bounds cases.
- `tests/steps/test_merge_prepare.py`: consult keep-effect `settle` caller.
- `tests/steps/test_slot_lock.py`: consult wrapped `settle` signature and serialization coverage.
- `docs/design/tl-8bh9.14.142.1/plan.md`: revise contract and read list.
- `docs/design/tl-8bh9.14.142.1/plan-metadata.json`: record preparation commit and consulted paths.

## Read list
- `src/taskloop/factory_commit.py:121-214` — commit, selection, index fence and ignored checks.
- `src/taskloop/factory_commit.py:300-394` — unsafe-file review, clean-tree and preview.
- `src/taskloop/implement_step.py:92-210` — initial, repeat and failed-check guidance.
- `src/taskloop/verdict.py:17-97` — chain assembly and membership/mode/blob rules.
- `src/taskloop/verifier.py:129-190` — preview and settlement-to-judgment callers.
- `src/taskloop/steps.py:28-74` — step identity, rules and prompt dispatch.
- `src/taskloop/check_repeat/repair.py:55-72` — failed-check input producer.
- `src/taskloop/slot_state.py:122-137` — pinned typed observation.
- `src/taskloop/attempt_types.py:66-77` — path and file caps.
- `src/taskloop/attempt_types.py:200-365` — answer/chain contracts and path restrictions.
- `src/taskloop/answer_decode.py:13-46` — retained decoder checks.
- `src/taskloop/merge/git.py:78-89` — safety helper consumer.
- `tests/steps/test_commit_paths.py:237-353` — plan isolation and complete-slot safety cases.
- `tests/steps/test_verifier.py:291-361` — factory commit and saved-work integration.
- `tests/steps/test_verifier.py:430-497` — plan membership, limits and unknown reads.
- `tests/steps/test_repeat_dispatch.py:285-318` — per-attempt membership and ancestry.
- `tests/steps/test_check_repeat.py:88-184` — repair producer and fresh checks.
- `tests/steps/test_steps.py:287-330` — prompt assertions.
- `tests/steps/test_implement_feedback.py:21-35` — failed-check policy.
- `tests/steps/test_agent_launch.py:111-139` — launch policy.
- `tests/steps/test_input_context.py:256-285` — digest and post-commit leftovers.
- `tests/steps/real/test_commit_real.py:273-353` — local-adapter omission and verdict cases.
- `tests/steps/test_answer_contract.py:225-307` — implement schema bounds.
- `tests/steps/test_merge_prepare.py:155-168` — keep-effect settlement.
- `tests/steps/test_slot_lock.py:190-207` — serialization wrapper.

## Contract
Intent: distinguish membership by existing step identity. Keep public signatures, AnswerState, ChainLink and StepRules; add no stored data or vocabulary.

Effect: select unique sorted tracked/untracked paths against base, filtering byte-identical ordinary files. Review all changes before staging, including deletions and both rename paths. Retain path/plan.md, credential/type/content, ignored-attribute, count/byte and foreign-index checks. Bound diagnostics only; preserve unknown-read and fencing handling.

Result: judge passes step identity through private validation. Plan links require declared paths; implement links permit omissions. Retain location, deletion, mode, size, ancestry/artifact rules, existing result types, reuse/keep, crash adoption and clean-tree checks.

## Work packages
1. `verdict.py`, `test_verifier.py`, `test_repeat_dispatch.py`: distinguish membership by step; close A2 with single/multiple-attempt omissions and unchanged plan regressions.
2. `factory_commit.py`, `test_commit_paths.py`, `real/test_commit_real.py`: retain and verify selection/refusal boundaries; close A1.
3. `implement_step.py` and mapped guidance/repair tests: close A3 and fix exposed failures. Run focused installed-package tests, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, with pipefail; preserve unrelated assertions.

## Acceptance behaviours
A1. An implement answer omitting safe added, modified, deleted or renamed paths commits the complete reviewed slot set with its message and trailer. Unsafe/ignored omitted changes and excess paths/bytes refuse before staging; preview agrees. Unchanged entries, foreign index content and unknown evidence retain their handling.
A2. Those implement commits verify across initial/repeat attempts, including failed-check repair followed by fresh passing checks. Plan commits still reject changes absent from that attempt's paths. Ancestry, modes, sizes, artifacts, keep and recovery constraints remain enforced.
A3. Initial, repeat and failed-check inputs explain slot-derived selection and removing/restoring unwanted edits. The accepted answer-list schema and factory Git ownership remain intact.
