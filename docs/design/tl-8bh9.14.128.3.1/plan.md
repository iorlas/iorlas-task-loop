# Header
tl-8bh9.14.128.3.1; base 3ad928737db380afe2e0a7dc2787a1c753a48002
Depth: small
One recovery renewal behaviour. No missing owner decision; dependency delivered.
Evidence budget: 6 model calls. Size: 6 changed files, 1 independent behaviour, 45 implement calls.

## Outcome and non-goals
Recovery exists; renewal is missing. Exclude lifecycle wiring, duration policy, launch changes and publication verification.

## Settled decisions
- Caller supplies a finite absolute deadline to the existing operation.
- Existing attempt deadline remains authoritative; no schema change.
- Renewal occurs once per recovery generation; ordinary expiry remains enforced.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_store.py`: `recovery`, `_recovery_session`; renewal eligibility and fenced deadline write.
- `src/taskloop/recovery/store.py`: `snapshot`, `_compare`, `authorize`, `_authorize`; atomic renewal; consult `execute`, `register`.
- `src/taskloop/recovery/recover.py`: `Recovery.authorize`, `_observe`; request through custody/proof; retain `reconcile` expiry.
- `tests/steps/test_recovery_store.py`: `observed`, `race`, `facts`; renewal, contention, rollback.
- `tests/steps/test_recovery.py`: `recovery`; proof refusals and orchestration.
- `docs/design/tl-8bh9.14.128.3.1/plan.md`: implementation contract.
- `src/taskloop/recovery/state_store.py`: consult `save`, `fence`.
- `src/taskloop/attempt_types.py`: consult `Admission.deadline`.
- `src/taskloop/recovery/continue_attempt.py`: consult `_continue`, authorization caller; adoption deferred.
- `src/taskloop/recovery/native.py`: consult `NativeContinuation.__call__`, deadline consumer.
- `src/taskloop/recovery/registration.py`: consult `registration_hook`, registration caller.
- `src/taskloop/composition.py`: consult `open_continuation`, `open_recovery_registration`, producers.
- `tests/steps/test_recovery_snapshot.py`: consult snapshot caller.
- `tests/steps/test_recovery_registration.py`: consult authorization caller.
- `tests/steps/test_recovery_reconcile.py`: consult retained expiry behaviour.

## Read list
- `src/taskloop/attempt_store.py:70-130` — fences.
- `src/taskloop/recovery/store.py:50-138` — transactions.
- `src/taskloop/recovery/recover.py:73-142` — proof.
- `src/taskloop/recovery/state_store.py:11-44` — persistence.
- `src/taskloop/attempt_types.py:120-150` — deadline.
- `src/taskloop/recovery/continue_attempt.py:40-60` — caller.
- `src/taskloop/recovery/native.py:29-45` — consumer.
- `src/taskloop/recovery/registration.py:1-30` — caller.
- `src/taskloop/composition.py:82-102` — producers.
- `tests/steps/test_recovery_store.py:20-214` — database/races.
- `tests/steps/test_recovery.py:20-95` — proof fixtures.
- `tests/steps/test_recovery_snapshot.py:1-90` — caller.
- `tests/steps/test_recovery_registration.py:1-100` — callers.
- `tests/steps/test_recovery_reconcile.py:289-305` — expiry.

## Contract
Intent: optional deadline on `Recovery.authorize` and `RecoveryStore.authorize`; renewal-only observation admits expired work. Effect: after external stop/claim proof, one transaction compares snapshot, reservation, drain and ownership. `AttemptStore` writes deadline/revision; recovery saves matching intent. Deadline never shrinks; it must be finite and future under the writer lock. Result: existing `Result`/`Outcome` with explanations. Refusals and rollback leave no renewal; replay cannot extend again; callbacks remain fenced. No external action in SQL.

## Work packages
1. Stores/application: renewal contract, A1.
2. Both test files: A1. Last, once each: `just check 2>&1 | tail -60`; `just test 2>&1 | tail -40`.

## Acceptance behaviours
A1. Proof-backed renewal works after expiry; invalid/elapsed requests, missing proof, stale snapshots and failed commits preserve facts; competing connections elect one winner, replay cannot extend again, and reopen retains matching deadline/revision/intent with ordinary expiry enforced.
