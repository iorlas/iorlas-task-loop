# Header
Task: tl-8bh9.14.107.1
Base: 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: medium; registration and crash reconciliation.
Decisions settled; no stated unlanded dependencies.
Evidence budget: 12 model calls.
Size: 11 changed files; 2 behaviours; 65 model calls/implement attempt.

## Outcome and non-goals
Reconcile uncaptured lost-entry work through safe abandonment and release, retaining the durable registration gates. A live orphan remains reserved until its registered identity and group are gone. Captured-session completion and recovery of claims, evidence or branches without rows belong to the other split tasks. No schema or shelf change.

## Settled decisions
- The supplied guarantee places gate creation, identity observation and committed registration before permission and execution. Callback failure or entry death during registration forbids execution.
- After a permit, an orphan is reconciled by its durable worker identity; parent-death killing is not required.
- Entry/worker registration before execution is already delivered by Launcher._start and session.registration_hook with their store callbacks.
- Select existing abandonment and claim-return reconciliation for uncaptured stopped work.
- A missing worker proves no permitted target only for a dispatching attempt with a recorded entry independently confirmed gone. Absence alone, a self-release exemption or an unknown observation is insufficient.
- Captured execution takes precedence over abandonment. Existing holds remain held.

## Open decisions
- None.

## Change map
- `src/taskloop/release_proof.py`: `stop_proof` accepts the bounded no-worker dispatch case only after external entry-death proof; retain `worker_stopped`'s conservative standalone contract.
- `src/taskloop/slot_release.py`: `SlotRelease` adds fenced reconciliation using existing abandonment effects; exclude captured executions and holds.
- `src/taskloop/operations.py`: `Release` exposes reconciliation through existing result handling.
- `src/taskloop/attempt_status.py`: `_stopped`, `_released` route lost entries and pending claim returns toward release.
- `src/taskloop/round.py`: `_settle` reconciles agent attempts requiring release using the snapshot key.
- `src/taskloop/step_guide.py`: replace the entry_lost database-discard instruction with the reconciliation decision in words.
- `tests/steps/test_launch.py`: restart between entry registration and permission.
- `tests/steps/test_slot_release.py`: absent/registered worker safety, reopen and refusal preservation.
- `tests/steps/test_lost_entry.py` (new): status-to-round crash scenarios using existing round/dispatch fixtures.
- `tests/steps/test_dispatch_slot.py`: worker durability before target effects; callback failure.
- `docs/design/tl-8bh9.14.107.1/plan.md`: this implementation contract.
- Consult callers/producers: `Attempts._dispatch/_call`, `registration_hook`, `AttemptStore.dispatch/register/register_entry`, `Launcher._target/_start`, `attempt_entry._step`, `open_launcher/open_checks_launcher`, `operations._start/relaunch_checks`, `round._resume`.
- Consult shared consumers `Repeat`, `ChecksRelease`, `Verifier` and `slot_release` proof re-exports; preserve their contracts.

## Read list
- `src/taskloop/launch.py:134-273` — entry registration gate, phase refusal and start result boundaries.
- `src/taskloop/attempt_store.py:133-203` — entry, dispatch and worker identity writes.
- `src/taskloop/session.py:15-32` — callback deadline/refusal boundary.
- `src/taskloop/attempt.py:152-193` — prepared dispatch producer and frozen base.
- `src/taskloop/attempt.py:246-265` — harness registration and exception handling.
- `src/taskloop/attempt_entry.py:198-218` — entry execution, capture and verification caller.
- `src/taskloop/release_proof.py:35-70` — entry, worker and setup stop proofs.
- `src/taskloop/slot_release.py:216-284` — release admission, claim return and stop fences.
- `src/taskloop/operations.py:84-145` — release ports and their integration into operation ports.
- `src/taskloop/operations.py:342-398` — start caller, released-attempt and hold handling.
- `src/taskloop/attempt_status.py:135-162` — next-action classification.
- `src/taskloop/attempt_status.py:261-273` — abandonment and pending claim-return classification.
- `src/taskloop/round.py:225-280` — settling and relaunch callers; new test integration point.
- `src/taskloop/step_guide.py:84-94` — obsolete discard guidance.
- `src/taskloop/composition.py:198-209` — agent/check launcher composition callers.
- `src/taskloop/repeat.py:140-165` — standalone worker proof caller; keep conservative semantics.
- `src/taskloop/check_release.py:245-265` — checks and candidate release entry points.
- `src/taskloop/verifier.py:1-80` — proof/release imports and verification integration.
- `src/taskloop/recovery/continue_attempt.py:40-73` — distinguish saved-session continuation from this release path.
- `src/taskloop/recovery/store.py:87-138` — captured/held eligibility and existing recovery fences.
- `tests/steps/test_launch.py:131-232` — registered-start semantic scenarios.
- `tests/steps/test_dispatch_slot.py:42-114` — dispatch fixtures and base/deadline expectations.
- `tests/steps/test_slot_release.py:1-38` — semantic release fixtures and owning API dependencies.
- `tests/steps/test_recovery_reconcile.py:1-72` — existing stopped/live execution reconciliation coverage.

## Contract
Intent: reconcile the current uncaptured AttemptKey under custody, fenced by revision, phase, reservation generation and identities. A typed SlotRelease method returns existing ReleaseResult; new finite reasons use an enum. No new stored fields or phases.

Effect: independently confirm recorded entry death. Dispatching without a worker then proves no target received permission; registered work additionally requires its worker/group gone. Unknown/live identities, setup activity, holds, captured execution and changed ownership forbid abandonment. Keep standalone worker_stopped conservative for Repeat.

Result: revalidate attempt, reservation, capture absence and hold before existing abandonment effects. Retain Git/claim outbox reconciliation: adopt completed parking or pending claim return after restart. Preserve evidence and dirty/diverted slots; report specific refusals. Status reads perform no effects.

## Work packages
1. `release_proof.py`, `slot_release.py`, `test_slot_release.py`: add the bounded proof and fenced reconciliation operation; close A2 for both absent and registered workers without weakening other consumers.
2. `operations.py`, `attempt_status.py`, `round.py`, `step_guide.py`, new `test_lost_entry.py`: connect automatic settlement to the owning release operation and preserve partial claim-return recovery; close A2 through an intact-database reopen and a subsequent round.
3. `test_launch.py`, `test_dispatch_slot.py`: preserve and verify the existing permission boundaries and crash windows; close A1. Finish the implement attempt with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last. No live harness runs.

## Acceptance behaviours
A1: Entry and worker identities are committed before their respective targets execute; crashes or callback failure before permission leave no unregistered running target, and restart safely handles the retained registration.
A2: Reopening an intact database after dispatch or worker registration makes an uncaptured lost-entry attempt reach safe release and reconciled claim return once its processes are proven stopped, without entry_lost or database discard. Repetition is idempotent; live/unknown identities, changed ownership, holds, captured results and unsafe slots preserve their work and reservations with a specific explanation.
