# Header
tl-8bh9.14.128.3.1; base 8579cff88e02944e2457f9764d6a82a29fbf5ac9
Depth: small
One recovery renewal behaviour. No missing owner decision; dependency delivered.
Evidence budget: 6 model calls. Size: 6 changed files, 1 independent behaviour, 45 implement calls.

## Outcome and non-goals
Renewal/tests exist; verify the current base and repair only A1 failures. Exclude lifecycle wiring, duration policy, launch changes and publication verification.

## Settled decisions
- Caller supplies a finite absolute deadline.
- Attempt deadline remains authoritative; no schema change.
- Renew once per recovery generation; retain expiry.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_store.py`: `renew`, `recovery`, `_recovery_session`; verify existing deadline/revision fences.
- `src/taskloop/recovery/store.py`: `snapshot`, `_compare`, `authorize`, `_authorize`; verify renewal; consult `execute`, `register`.
- `src/taskloop/recovery/recover.py`: `Recovery.authorize`, `_observe`, `reconcile`; verify proof and expiry.
- `tests/steps/test_recovery_store.py`: `race`, `facts`; verify renewal/rollback.
- `tests/steps/test_recovery.py`: `recovery`; verify proof.
- `docs/design/tl-8bh9.14.128.3.1/plan.md`: scope.
- `src/taskloop/recovery/state_store.py`: consult `save`, `fence`.
- `src/taskloop/recovery/continue_attempt.py`: consult `_continue`, caller.
- `src/taskloop/recovery/native.py`: consult `NativeContinuation.__call__`, deadline consumer.
- `src/taskloop/recovery/registration.py`: consult `registration_hook`, registration caller.
- `src/taskloop/composition.py`: consult `open_continuation`, `open_recovery_registration` producers.
- `tests/steps/test_recovery_snapshot.py`: snapshot caller.
- `tests/steps/test_recovery_registration.py`: `intended`, authorization caller.
- `tests/steps/test_recovery_reconcile.py`: expiry caller.
- `tests/steps/test_recovery_callbacks.py`: `registered`, callback caller.
- `tests/steps/test_recovery_evidence.py`: evidence caller.

## Read list
- `src/taskloop/attempt_store.py:80-145` — fences.
- `src/taskloop/recovery/store.py:27-169` — proof/transactions.
- `src/taskloop/recovery/recover.py:73-142` — proof.
- `src/taskloop/recovery/state_store.py:11-44` — persistence.
- `src/taskloop/recovery/continue_attempt.py:40-60` — caller.
- `src/taskloop/recovery/native.py:29-45` — consumer.
- `src/taskloop/recovery/registration.py:1-30` — caller.
- `src/taskloop/composition.py:82-102` — producers.
- `tests/steps/test_recovery_store.py:85-104` — race fixture.
- `tests/steps/test_recovery_store.py:128-307` — fences, expiry, rollback.
- `tests/steps/test_recovery.py:65-124` — proof refusals.
- `tests/steps/test_recovery.py:239-297` — renewal/callbacks.
- `tests/steps/test_recovery_snapshot.py:1-90` — caller.
- `tests/steps/test_recovery_registration.py:1-100` — callers.
- `tests/steps/test_recovery_reconcile.py:289-305` — expiry.
- `tests/steps/test_recovery_callbacks.py:31-36` — registration helper.
- `tests/steps/test_recovery_evidence.py:15-34` — evidence caller.

## Contract
Intent: retain optional `deadline` on both `authorize` methods. Effect: custody/stop/claim proof precedes one transaction comparing snapshot, reservation, hold, drain and ownership; `renew` writes deadline/revision with matching `Intent`. Deadline never shrinks and must be finite/future under the lock. Result: existing `Result`/`Outcome`; no schema change or external action in SQL.

## Work packages
1. Verify A1; repair demonstrated failures only in the five source/test files.
2. Verify A1 on the current base. Last, once each: `just check 2>&1 | tail -60`; `just test 2>&1 | tail -40`.

## Acceptance behaviours
A1. Renewal after expiry requires proof; invalid/elapsed requests, missing proof, stale snapshots and failed commits preserve facts; contention elects one winner; replay cannot extend again; reopen retains deadline/revision/intent; stale callbacks and ordinary expiry stay fenced.
