# Header
Task: tl-8bh9.14.128.3; base: 06d1561b5b2b93364a1e051594457f16ff8309ae.
Depth: medium; recovery integration, retention, renewal.
No missing owner decision or explicitly unlanded dependency.
Evidence: 12 calls. Size: 20 changed files, 3 independent behaviours, 85 implement calls.

## Outcome and non-goals
Recovery already supplies native continuation, authorization, callback fencing, capture retry and separate artifact paths. Connect registered-entry launch, completion and deadline renewal while preserving work and evidence. Observe surviving execution. Ordinary retries remain fresh sessions. No schema change, harness upgrade, state reconstruction or live experiment.

## Settled decisions
- Reuse `Recovery` for authorization and `Continuation` for execution.
- Preserve the original entry as stop-proof evidence; replacement execution owns recovery through `Intent.owner`.
- Use the existing registered-start port and dispatch action boundary; agent execution stays outside the round process.
- Observe tracker ownership read-only; heartbeat renewal is not ownership observation.
- Renew an expired eligible execution once per new recovery generation, from current validated minutes. Adoption and polling do not extend it.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/lifecycle.py` (new): coordinate `Launcher`/`attempt_entry.enter` with `Continuation`.
- `src/taskloop/recovery/status.py` (new): extract recovery projection from `attempt_status._agent` to fit its cap.
- `src/taskloop/launch.py`: `_target`/`_authorized`/`_start` route registered recovery; preserve checks.
- `src/taskloop/attempt_entry.py`: `arguments`/`_registered`/`enter`/`_step`/`_claimed`/`main` consume recovery; extract coordination to lifecycle.
- `src/taskloop/attempt_status.py`: `_agent`/`_stopped` project recovery into existing start/wait/unknown actions.
- `src/taskloop/attempt_store.py`: `recovery`/`_recovery_session` observe expiry; fence deadline writes.
- `src/taskloop/recovery/models.py`: validate allowance and recovery-entry inputs.
- `src/taskloop/recovery/recover.py`: `authorize`/`reconcile` require stop/claim proof before renewal.
- `src/taskloop/recovery/store.py`: fence renewal/authorization; expose saved-owner reads.
- `src/taskloop/composition.py`: `open_continuation`/`open_launcher`/`open_checks_launcher` wire ports.
- `src/taskloop/cli_composition.py`: `_starting`/`open_reads` share launch/status ports.
- `src/taskloop/slot_release.py`: `release` validate recovery-owner authority.
- `tests/steps/test_launch.py`: routing/adoption/ambiguous registration cases.
- `tests/steps/test_attempt_entry.py`: identity/claim/capture/completion cases.
- `tests/steps/test_recovery_store.py`: atomic renewal/expiry cases.
- `tests/steps/test_continuation.py`: renewal/callback fencing cases.
- `tests/steps/test_continuation_composition.py`: claim/custody/registration wiring cases.
- `tests/steps/test_restart.py`: killed-rounds completion case.
- `tests/steps/test_recovery_lifecycle.py` (new): retention/release cases via `Launcher`, `enter`, `SlotRelease`.
- `docs/design/tl-8bh9.14.128.3/plan.md`: bounded implementation contract.

## Read list
- `src/taskloop/round.py:226-286` — `_settle`/`_resume` launch callers and current-attempt fences.
- `src/taskloop/launch.py:65-252` — registration producer, dispatch action, ambiguous starts.
- `src/taskloop/attempt_entry.py:153-341` — identity, claim and completion consumers.
- `src/taskloop/attempt_status.py:130-252` — agent/check next-action projection.
- `src/taskloop/attempt_store.py:73-174` — eligibility, worker and entry writes.
- `src/taskloop/attempt_reads.py:257-334` — tracker root, releases and current-row producers.
- `src/taskloop/recovery/models.py:1-110` — snapshots, intents and outcomes.
- `src/taskloop/recovery/recover.py:60-142` — custody and world observations.
- `src/taskloop/recovery/store.py:28-138` — authorization/registration transactions.
- `src/taskloop/recovery/continue_attempt.py:23-100` — adoption, capture and completion.
- `src/taskloop/recovery/native.py:25-80` — native deadline and callback consumers.
- `src/taskloop/attempt.py:83-151` — captured completion versus fresh preparation.
- `src/taskloop/composition.py:55-104` — bounded writer and continuation producer.
- `src/taskloop/composition.py:195-211` — agent/check launcher producers.
- `src/taskloop/cli_composition.py:108-150` — shared read/start composition.
- `src/taskloop/tracker_client.py:162-204` — claim adapter; retain backend details here.
- `src/taskloop/slot_release.py:199-285` — caller authority and stop proof.
- `src/taskloop/evidence_files.py:100-123` — retained roots/logs.
- `src/taskloop/evidence_files.py:275-306` — continuation artifact preparation.
- `tests/steps/test_launch.py:1-180` — start/observe semantic fixtures.
- `tests/steps/test_attempt_entry.py:77-224` — entry fixture and verification.
- `tests/steps/test_recovery_store.py:1-180` — recovery eligibility fixtures.
- `tests/steps/test_continuation.py:1-180` — crash/lost-acknowledgement cases.
- `tests/steps/test_continuation_composition.py:1-60` — production wiring assertions.
- `tests/steps/test_restart.py:1-72` — intact-database restart fixture.

## Contract
Intent: validate attempt key, minutes, recovery generation and owner. Under custody recheck reservation, holds, drain, session, claim and process identities. Observe recovery owner and original entry/worker; live/uncertain execution forbids another launch. Incomplete registration remains unresolved.

Effect: record dispatch action, then spawn outside the transaction. Bounded registration authorizes the observable child before its permit. Reconcile ambiguous starts against its identity and intent. Keep `admission.entry`; validate `Intent.owner` before calling `Continuation` under held custody. Ordinary dispatch retains its identity check.

Renewal: expired snapshots grant no authority. After absence/claim proof, atomically compare facts, update attempt deadline/revision and save matching recovery authorization. Use finite now plus current minutes once per new generation. Ineligible, held, released, superseded, captured, draining or live/uncertain work gains no allowance. Re-fence callbacks. Captured work can finish after expiry without renewal.

Result: consume `ContinuationResult`; retry pending capture only through `capture`. Use trusted decoding, verification and owner-fenced release with original stop proof. Publish outside custody. Retain evidence using existing intent-specific roots. Status never mutates authorization or reads logs for control.

## Work packages
1. Extend attempt/recovery stores and `Recovery`; test fenced expiry and renewal. Closes A3.
2. Connect launch, lifecycle, entry, release, composition and status; preserve round `_settle`/`_resume` and check-launch interfaces. Closes A1.
3. Extend restart/composition tests and add lifecycle coverage through semantic ports. Reopen after interrupted rounds and ambiguous launch/capture; complete verification, release and publication. Closes A2 and integrates A1/A3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. Round/CLI launch and entry consumption converge on one continuation: live/unknown execution is observed, stopped eligible work resumes once, captured work completes without another agent invocation, and ownership/hold refusals remain effective.
A2. Following simulated killed rounds and intact-database reopen, session S completes with the same attempt and retained work/evidence through verification, settled release and publication; another restart duplicates neither execution nor delivery.
A3. Expired stopped eligible execution receives a finite allowance from current minutes before execution; polls, stale callbacks, competing callers, holds and live/unknown execution cannot renew it or bypass the bound.
