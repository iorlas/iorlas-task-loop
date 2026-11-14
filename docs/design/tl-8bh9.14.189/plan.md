# Header
Task: tl-8bh9.14.189
Base: c746f0c33774f858dd2fda5e2e39d30c6c145ae1
Depth: medium; timing, sample, conditional reuse.
Owner decisions: settled. Unlanded deps: none. Evidence: 12 calls.
Size: <=18 changed files; 3 behaviours; <=90 model calls per implement attempt.

## Outcome and non-goals
Expose existing timestamps, collect the median, then apply its threshold. SetupStore persists both times; the median and reuse remain undelivered. Observe ordinary attempts; add no scheduler, closing service, schema or gate configuration.

## Settled decisions
- SetupStore.start/conclude retain timestamp ownership.
- Record cutoff, ten attempt IDs, timestamps, durations and median in measurement.md; the owning tracker actor records the number in this task.
- Select the next ten ordinary implement bootstrap attempts in repo/backlog admission order after cutoff, once per attempt. Incomplete/interrupted evidence remains visible; never replace slow samples silently.
- Median averages sorted positions five and six; exactly 30 seconds selects closure.
- Above 30 seconds, retain root .venv and run just install only with matching committed uv.lock bytes and configured setup digest.
- Selective cleanup uses clean(["/.venv"], ignored=True), never nested=True. Parking uses keep_ignored=True; owning cleanup removes other ignored leftovers.
- Retain detached-HEAD reset guards and gate rebuilds. Substitute only this repo's measured bootstrap configuration, not arbitrary setup commands.

## Open decisions
- None.

## Change map
- src/taskloop/setup_store.py — SetupStore: bounded timing and previous slot-setup reads.
- src/taskloop/environment.py — Preparation._setup/_reset/_concluded, reset_to: integrate reuse; extract policy to respect source cap.
- src/taskloop/setup_reuse.py — new: compare committed fingerprints; called by Preparation._setup/reset_to.
- src/taskloop/slot_env.py — RealEnvFiles: no-follow .venv directory observation.
- src/taskloop/prepare.py — detach_at/_take: retain environment during parking/rollback.
- src/taskloop/slot_park.py — park_slot: retain environment during release.
- docs/design/tl-8bh9.14.189/measure.py — new: report via factory_store.open_ro and SetupStore.
- docs/design/tl-8bh9.14.189/measurement.md — new: observed cutoff, sample, median and action.
- tests/steps/test_setup_store.py — timing reads: selection, deduplication, partial samples, fences.
- tests/steps/test_setup_measurement.py — new: measure.py median and threshold contracts.
- tests/steps/test_setup_reuse.py — new: policy invalidation using semantic fakes.
- tests/steps/test_environment.py — Preparation: timings and conditional setup.
- tests/steps/test_prepare.py — detach_at/_take: retention and branch protections.
- tests/steps/test_slot_release.py — SlotRelease._parked: retention across attempts.
- tests/steps/real/test_environment_real.py — hermetic anchored cleanup, symlinks and reset.
- src/taskloop/composition.py — _environment/open_attempts: consult wiring; extend file port if needed.
- src/taskloop/attempt.py — Attempts: consult ordinary Preparation.prepare caller.
- src/taskloop/validate.py — _environment: consult checks prepare_for caller.
- src/taskloop/merge/prepare.py — setup closure: consult source-merge prepare_for caller.
- src/taskloop/land_conflict/execute.py — setup closure: consult conflict prepare_for caller.
- src/taskloop/check_release.py — _reset/park_slot caller: preserve environment on enabled branch.
- src/taskloop/slot_release.py — _parked: consult ordinary park_slot caller.
- src/taskloop/wip.py — park: consult existing keep_ignored=True path.
- src/taskloop/factory_store.py — open_ro: consult compatible read-only opening.
- src/taskloop/factory_schema.py — setup_run/attempt/checks_attempt: consult ownership and ordering.
- src/taskloop/profile.py — ProfileFiles.blob/Profile.setup: consult fingerprint producers.

## Read list
- src/taskloop/setup_store.py:35-167 — rows, fencing and timestamp owner.
- src/taskloop/environment.py:94-201 — digest, reset and target contracts.
- src/taskloop/environment.py:293-397 — setup/reset/command/conclusion effects.
- src/taskloop/slot_env.py:78-120 — safe folder observation and removal port.
- src/taskloop/prepare.py:189-218 — branch take rollback.
- src/taskloop/prepare.py:274-295 — detached preparation park.
- src/taskloop/slot_park.py:16-55 — ordinary and saved release parking.
- src/taskloop/slot_release.py:328-350 — park caller and reservation conclusion.
- src/taskloop/check_release.py:299-337 — check release park and reset callers.
- src/taskloop/wip.py:205-210 — existing preserving park.
- src/taskloop/composition.py:77-83 — environment wiring.
- src/taskloop/composition.py:126-140 — setup store composition.
- src/taskloop/attempt.py:234-245 — ordinary preparation caller.
- src/taskloop/validate.py:139-155 — checks preparation caller.
- src/taskloop/merge/prepare.py:40-62 — source merge setup caller.
- src/taskloop/land_conflict/execute.py:83-100 — conflict setup caller.
- src/taskloop/profile.py:94-110 — committed regular-file read port.
- src/taskloop/factory_store.py:31-45 — read-only database opening.
- src/taskloop/factory_schema.py:109-211 — attempt scope/order and setup/check ownership.
- tests/steps/test_setup_store.py:22-95 — store contracts.
- tests/steps/test_environment.py:121-225 — setup, cleanup and relaunch.
- tests/steps/test_environment.py:506-555 — detached resets and checks setup.
- tests/steps/test_prepare.py:273-320 — branch rollback coverage.
- tests/steps/test_slot_release.py:1-120 — release fixture and owning operation.
- tests/steps/real/test_environment_real.py:44-86 — hermetic setup and filesystem assertions.

## Contract
Validated SetupSample values carry attempt ID, run, start, optional end, conclusion and digest. The report carries selected IDs, completed count and optional median. Fewer than ten complete valid durations, or negative/non-finite durations, yields no decision. SQL stays in SetupStore; reporting opens compatible state read-only.

Reuse intent uses factory.db's latest setup affecting that repo/slot, its commit/digest and committed lock bytes. Missing directory/file, failed/unfinished setup or changed fingerprints requires bootstrap. Include checks/merge owners; an older success cannot hide later failure. No file stores factory control state.

Under custody/fences, observe fingerprints, clean selectively, then run just install as a newly recorded setup. Existing conclusion/refusal/reconciliation records the result. Checks reset tracked files to their pinned commit and rebuild. Same-attempt reuse and repeats keep existing semantics.

## Work packages
1. setup_store.py, measure.py and timing tests: expose recorded times and establish cutoff. Closes A1 and partial-sample A2.
2. Observe ten later ordinary attempts; fill measurement.md and record the median through the tracker actor. Fewer than ten leaves the study pending for continuation, not complete. No live tests substitute for observations. Closes A2.
3. After measurement: <=30 seconds concludes the task with the number; above 30 implements setup_reuse.py, environment/parking and semantic/hermetic coverage. Do not ship reuse before measuring. Closes A3. Code-changing attempts end with just check 2>&1 | tail -60 and just test 2>&1 | tail -40, once each.

## Acceptance behaviours
A1. Actual implement setups retain start/end/conclusion; unfinished runs have no fabricated end and relaunch preserves prior records.
A2. Ten later bootstrap attempts reproduce the median recorded in the task; partial/invalid evidence produces no decision.
A3. Median <=30 seconds closes with the number; above 30 retains root .venv and runs just install on matching lock/config, otherwise bootstrap. Parking, other ignored cleanup, symlink boundaries, reset guards and non-editable gate rebuilds remain effective.
