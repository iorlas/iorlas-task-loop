# Header
Task: tl-8bh9.14.159.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; two documentation behaviours.
Owner decision: none. Unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 4 files incl. artifacts, 2 behaviours, ~60 implement calls.

## Outcome and non-goals
Existing `factory_commit.settle` commits or adopts results; `Verifier` adds custody, clean-tree checking and a stored verdict. The glossary entry and naming map remain missing. Runtime renames, schema changes and retry policy are outside this docs-only implementation.

## Settled decisions
- The requested term is factory commit; the short operation/command name is commit.
- Factory commit belongs to its agent attempt, rather than a separately scheduled step or dashboard column.
- Cover keep answers, saved-work review, clean-tree checking, verdict storage and rerun reconciliation.
- Map causes by meaning into `uncommitted:*`, `refused:*` and `waiting:*`; a file problem, refusal and transient wait need distinct explanations.

## Open decisions
- None.

## Change map
- `docs/glossary.md` — terminology and page wording: add factory commit and reconcile Verification wording.
- `docs/design/tl-8bh9.14.159.1/naming-map.md` (new) — glossary-linked table of old name, target, owning symbol/surface and explanation; source entries below are evidence only.
- `src/taskloop/factory_commit.py` — `settle`, `clean_at`, `leftovers`: map cause producers and completion semantics.
- `src/taskloop/verifier.py` — `Verifier`, `VerifyHold`, `verify`, `applicable`: map operation, guards and results.
- `src/taskloop/attempt_types.py` — `Verified`, `VerifyResult`, `VerifyRefused`, `VerifyUnavailable`, `Unsettled`, `StoredExecution.verification`: map typed vocabulary.
- `src/taskloop/attempt_result.py` — `_report`, `judged`: map result words.
- `src/taskloop/operations.py` — `verify_task`, `verify_failure`: map shared operation and cause formatting.
- `src/taskloop/attempt_entry.py` — `_step`, `shown`: map automatic caller and result formatting.
- `src/taskloop/repeat.py` — `StepRepeat`, `Settle`, `verify_failure` caller: map repeat and feedback.
- `src/taskloop/composition.py` — `open_verifier`: map constructor.
- `src/taskloop/cli_step.py` — `verify_task` dispatch: map CLI spelling.
- `src/taskloop/round.py` — `verify_task` caller: map round dispatch.
- `src/taskloop/attempt_status.py` — `Next`, `_stopped`: map next action.
- `src/taskloop/attempt_store.py` — verdict SQL: map storage names.
- `src/taskloop/attempt_loads.py` — verdict joins: map reader names.
- `src/taskloop/factory_schema.py` — verification table: map future storage rename.
- `src/taskloop/dash_verify.py` — `STEP`, `CHECKS`, `verification`: map producer.
- `src/taskloop/dash_model.py` — `Verification`, `VerifyCheck`, `Outcome.verification`: map page fields.
- `src/taskloop/dash_task.py` — `_verification`, `Link`: map projection callers.
- `src/taskloop/dash/static/ui.js` — `VERIFY`, `stepInfo`: map label/id.
- `src/taskloop/dash/static/rail.js` — `verifyTitle`, `verificationButtons`: map navigation.
- `src/taskloop/dash/static/drawer.js` — `VERIFY`, `verifyTitle` consumers: map selection.
- `src/taskloop/dash/static/result.js` — `verification`: map rendering.
- `src/taskloop/dash/static/words.js` — verification/unsettled entries: map explanations.
- `src/taskloop/step_guide.py` — verify/unsettled entries: map completion guidance.
- `src/taskloop/step_refusal_guide.py` — verification explanations: map refusal guidance.
- `src/taskloop/slot_state.py` — `SlotState.problem`: consult propagated causes.
- `docs/design/tl-8bh9.14.159.1/plan.md` — retain bounded scope.
- `docs/design/tl-8bh9.14.159.1/plan-metadata.json` — retain consulted evidence.

## Read list
- `docs/glossary.md:19-31`, `docs/glossary.md:150-194` — existing dashboard and attempt terminology to reconcile.
- `src/taskloop/factory_commit.py:73-110`, `src/taskloop/factory_commit.py:154-188`, `src/taskloop/factory_commit.py:333-376` — commit boundary and cause producers.
- `src/taskloop/verifier.py:53-94`, `src/taskloop/verifier.py:96-183` — applicability, custody, rerun and verdict boundary.
- `src/taskloop/attempt_types.py:227-297` — result vocabulary and stored field.
- `src/taskloop/attempt_result.py:53-78` — pending and terminal words.
- `src/taskloop/operations.py:513-534`, `src/taskloop/operations.py:599-606` — shared operation and formatted failures.
- `src/taskloop/attempt_entry.py:144-157`, `src/taskloop/attempt_entry.py:225-245` — formatting and automatic caller.
- `src/taskloop/repeat.py:42-53`, `src/taskloop/repeat.py:90-112` — repeat port and caller.
- `src/taskloop/composition.py:197-201` — operation construction.
- `src/taskloop/cli_step.py:256-272`, `src/taskloop/round.py:345-363` — command and round callers.
- `src/taskloop/attempt_status.py:133-154` — next-action consumer.
- `src/taskloop/attempt_store.py:310-350`, `src/taskloop/attempt_loads.py:90-118`, `src/taskloop/attempt_loads.py:235-249` — stored verdict names and readers.
- `src/taskloop/factory_schema.py:155-177` — storage vocabulary and references.
- `src/taskloop/dash_verify.py:13-58` — projection producer and all five displayed checks.
- `src/taskloop/dash_model.py:96-125` — page result fields.
- `src/taskloop/dash_task.py:180-269` — projection callers and attached attempt ordering.
- `src/taskloop/dash/static/ui.js:18-20` — label/identifier owner.
- `src/taskloop/dash/static/rail.js:24-76`, `src/taskloop/dash/static/rail.js:119-168` — title, grouping and markers.
- `src/taskloop/dash/static/drawer.js:6-28`, `src/taskloop/dash/static/drawer.js:311-361` — navigation/title consumers.
- `src/taskloop/dash/static/result.js:78-109` — result consumer.
- `src/taskloop/dash/static/words.js:27-40` — cause wording owner.
- `src/taskloop/step_guide.py:44-47`, `src/taskloop/step_guide.py:106-128`, `src/taskloop/step_guide.py:215-219` — completion versus checks guidance.
- `src/taskloop/step_refusal_guide.py:96-120` — refusal and waiting explanations.
- `src/taskloop/slot_state.py:20-61` — propagated slot causes.

## Contract
Intent: name completion of a valid commit/keep answer. Effect: documentation only; no runtime type/state/field changes. Result: the parent can rename each surface while preserving its meaning.

Enumerate `unsettled:unborn`, `branch`, `head_moved`, `dirty`, `redirected`, `worker_alive`, `superseded`, `staged`, `uncommitted`, `unsafe`, `ignored` and page-only `unsettled:rejected`. Give each an explicit target in the requested three families, preserving listings/explanations. Distinguish emitted, documented-only and synthetic causes. Include refused/unavailable results and pending verification; unknown evidence cannot mean success.

Inventory code/types, CLI/next-action words, storage/interchange, page labels/navigation and guidance. Scope one active-source search for `verify`, `verification`, `verified`, `verifier` and `unsettled`; cover every relevant occurrence or identical-use group with owner and target. Explicitly exclude configured checks, validation, identity verification and unrelated checks-process causes. Targeted reads may close omitted callers.

## Work packages
1. `docs/glossary.md`: define factory commit and reconcile conflicting wording. Closes acceptance 1.
2. New `naming-map.md`: map producers through callers, causes and exclusions; cross-check inventory coverage. Closes acceptance 2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; report actual gate outcomes.

## Acceptance behaviours
1. The glossary defines factory commit's purpose, owning attempt and completion condition, including unchanged results and stored verdicts.
2. The design note resolves every active factory verify/verification name and unsettled cause to a target, distinguishing file changes, refusals, waits and unrelated uses.
