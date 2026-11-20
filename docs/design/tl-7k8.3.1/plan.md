# Header
Task: tl-7k8.3.1; base: b8f6ebfc055ad2941677d02d6753edb404f19c2d
Depth: medium; two storage behaviours; schema remains 32.
Decisions settled; dependencies landed. Evidence budget: 12 calls.
Size: 14 files including tests/artifacts, 2 independent behaviours, about 60 implement calls.

## Outcome and non-goals
Persist replacement causes and validation, release, delivery and close timing. Distinguish unfinished phases from phases never entered. Dashboard presentation, scheduling, delivery policy and tracker synchronization are outside this slice.

## Settled decisions
- Amend schema 32 and its reviewed digest together; the version remains 32.
- Rename dependencies have landed; retain factory commit names.
- Retry cause describes replacement of a candidate, rather than repeated invocation of the same candidate's unfinished phase.
- Derive causes from candidate numbering, validation failure and supersession; keep detailed explanations on predecessors.
- Record starts at owning operation boundaries using injected clocks. Completion timestamps retain their existing meanings.

## Open decisions
- None.

## Change map
- `src/taskloop/land_timing.py` (new): typed phase and retry-cause enums, one codec per vocabulary and validated timing data; integrated by `land_store`, `land_check`, `check_release`, `land_push` and `land_close`.
- `src/taskloop/factory_schema.py`: `SCHEMA`, `LAND_ADMITTED`, `LAND_LOADED`; add candidate admission, retry cause and phase-start columns and constraints without changing version 32.
- `src/taskloop/land_store.py`: `LandRow`, `_row`, `insert`, phase-start write and completion writers; store admission time, derive cause transactionally from the latest predecessor and preserve first starts under existing fences.
- `src/taskloop/land_check.py`: `_settled`, `_reserved`, `_custody`; both admission producers supply time; start validation after custody/identity checks, before validation effects.
- `src/taskloop/check_release.py`: `ReleaseTarget`, `ChecksTarget`, `CandidateTarget`, `ChecksRelease._parked`; start candidate release after proof/custody, before reset/park; checks target has no land timing effect; retain `CandidateTarget.record_release` as completion writer.
- `src/taskloop/land_push.py`: `deliver`, `_step`, `_recorded`, `observed`, `withdraw`, `reconcile_delivery`; start actual delivery work before its effects; consult every delivery/supersession caller and preserve observation-only semantics.
- `src/taskloop/land_close.py`: `closed`, `_recorded`; persist close start before tracker invocation and retain recorded completion semantics.
- `src/taskloop/land.py`: consult `_made`, `_no_change`, `_pending`, `_delivered`, including supersession and resume routing.
- `src/taskloop/drain/reconcile.py`: consult `_land`, the additional `record_close` caller; observation may confirm completion without inventing an earlier start.
- `src/taskloop/land_data.py`, `src/taskloop/dash_land.py`: consult `candidate_data`, `_waits`, `_candidate`, `build_events`; preserve readers of expanded rows.
- `tests/steps/test_factory_schema.py`: `DDL_DIGESTS`, schema contract; replace only the reviewed version-32 digest and clarify the bundled-change comment.
- `tests/steps/test_land_store.py`: existing candidate fixtures, insert/read and fencing cases; extend for timing/cause persistence and invalid stored data.
- `tests/steps/test_land_timing.py` (new): focused operation tests using `land_bench.Bench` and existing semantic fakes; integrate through pytest discovery.
- `tests/steps/land_bench.py`: consult/extend `Bench` clock and tracker hooks.
- `docs/design/tl-7k8.3.1/plan.md`, `docs/design/tl-7k8.3.1/plan-metadata.json`: plan artifacts.

## Read list
- `src/taskloop/factory_schema.py:224-256` — candidate DDL; also consult `LAND_ADMITTED`/`LAND_LOADED` at 302-310.
- `src/taskloop/land_store.py:58-136` — admission and decoded row; consult `insert`, `record_release` at 183-225 and mutation fences at 255-332.
- `src/taskloop/land_check.py:82-149` — admission producers/release routing; validation effects at 181-229.
- `src/taskloop/check_release.py:86-99` — target protocol; concrete targets at 138-218 and proof/effect/record boundaries at 265-346.
- `src/taskloop/land_push.py:108-230` — delivery, supersession and reconciliation callers.
- `src/taskloop/land_close.py:39-91` — close effect and recording.
- `src/taskloop/land.py:210-303` — replacement and resume routing, including no-change supersession.
- `src/taskloop/drain/reconcile.py:41-61` — observed delivery/close adoption.
- `src/taskloop/dash_land.py:80-140` — current timestamp consumers and unknown event start.
- `src/taskloop/land_data.py:14-24` — current owning-row serialization.
- `tests/steps/test_factory_schema.py:13-32` — version digest contract.
- `tests/steps/test_land_store.py:24-120` — valid/invalid row fixtures; insert/read cases at 150-173 and 273-309.
- `tests/steps/land_bench.py:155-232` — injected clock, transaction racing and tracker hooks for new integration tests.

## Contract
Intent: admit N. Effect: admission stores `admitted_at` from `LandAdmitted.now` and `retry_cause` from predecessor N-1 of the same checks attempt. Result: N=1 has no cause; replacements encode `failed`, `moved`, `gone`, `withdrawn` or `abandoned` in an enum, supersession taking precedence over failure. Ineligible predecessors still refuse admission.

Intent: enter validation, release, delivery or close. Effect: a typed phase-start operation records the first observed start in `validation_started_at`, `release_started_at`, `delivery_started_at` or `close_started_at`, in a short transaction before the phase's effects. Result: retries preserve the original start; stale keys and ineligible states cannot alter it. Keep starts separate from reservation revisions used by release proofs so timing writes cannot invalidate their own proof.

Intent: finish a phase. Effect: retain `validated_at`, `released_at`, `delivered_at`, `closed_at`; admission supplies instantaneous validation/delivery bounds for `same_tree`/`no_change`. Result: skipped release has no timing; unfinished work has no completion. Nullable starts mean unobserved entry, including reconciliation; never invent historical starts. Codecs validate enum values and finite times; DDL rejects invalid causes and phase/state combinations. Clocks may jump: require no cross-phase wall-clock ordering.

Effects stay outside timing transactions; Git/tracker observations decide completion. The drain discards the old database. Expanded `LandRow` preserves existing readers.

## Work packages
1. Add `land_timing.py`, schema fields/codecs and store reads/writes; update the schema-32 pin and focused store assertions. Closes A1 and the persistence/fencing portion of A2.
2. Wire phase entry through `land_check.py`, `check_release.py`, `land_push.py` and `land_close.py`; inspect the listed orchestration and reconciliation callers. Close A2 without changing delivery or release policy.
3. Add `test_land_timing.py`, using existing bench hooks, and extend store tests for replacement causes and reopen/resume. Close A1–A2, then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, retaining both exit statuses.

## Acceptance behaviours
- A1: First admission has no retry cause; a replacement after failed validation or each eligible supersession preserves the exact typed cause through database reopen, without changing its predecessor or another checks attempt.
- A2: Distinct injected phase clocks persist actual starts and existing completions across validation, release, delivery and close; interrupted/resumed work preserves first starts and records only observed completions. Same-tree/no-change paths, skipped release, stale writers, concurrent completion and observation-only reconciliation retain truthful timing and existing outcomes.
