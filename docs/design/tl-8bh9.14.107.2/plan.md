# Header
Task: tl-8bh9.14.107.2; base: a45a755bdfc8d1d64fe1905cab974080327b269e
Depth: small; one captured-completion behaviour
Decisions missing: none. Dependencies unlanded: none.
Evidence budget: 6 model calls.
Size: 6 changed files; 1 independent behaviour; 45 implement model calls.

## Outcome and non-goals
Finish captured answer/session work before ordinary verification. Preserve the attempt and reservation. Exclude uncaptured execution, lost-entry release, claim recovery, orphan evidence and remote branches.

## Settled decisions
Reuse captured `Attempts.execute`, evidence readers and callback fences.
Respect holds and uncertain liveness.
No schema change or new shelf capability.

## Open decisions
- None.

## Change map
- `src/taskloop/attempt_status.py`: `next_action`, `_stopped` route stopped captured pending work to `verify`; preserve live/unknown precedence.
- `src/taskloop/recovery/complete_attempt.py` (new): captured-only completion using `Attempts.execute`, saved admission and custody.
- `src/taskloop/round.py`: `RoundPorts`, `_settle`, `_verified` complete before verification; retain retryable failures.
- `src/taskloop/composition.py`: wire captured completion into round ports.
- `tests/steps/test_restart.py`: reopen database and exercise round completion/retries.
- `tests/steps/test_continuation.py`: captured completion and preservation cases without execution.
- `src/taskloop/attempt.py`: consult `execute`, `_resume`, `_refresh`, `_answered` and capture producer.
- `src/taskloop/recovery/continue_attempt.py`: consult `_continue`, `_existing`, `_complete` consumers.
- `src/taskloop/drain/actions.py`: consult continuation consumer.
- `tests/steps/test_continuation_composition.py`: consult composition consumer.

## Read list
- `src/taskloop/attempt_status.py:135-155` — restart routing.
- `src/taskloop/attempt.py:84-144` — completion/session refresh.
- `src/taskloop/attempt.py:267-326` — capture/validation.
- `src/taskloop/attempt_result.py:1-60` — pending projection.
- `src/taskloop/round.py:105-160` — ports.
- `src/taskloop/round.py:225-297` — settlement.
- `src/taskloop/round.py:337-360` — verification/release.
- `src/taskloop/composition.py:100-150` — recovery wiring.
- `src/taskloop/recovery/continue_attempt.py:24-100` — custody/completion.
- `src/taskloop/recovery/store.py:88-105` — eligibility.
- `src/taskloop/drain/actions.py:1-80` — continuation consumer.
- `tests/steps/test_continuation_composition.py:1-80` — composition consumer.
- `tests/steps/test_continuation.py:1-105` — continuation setup.
- `tests/steps/test_restart.py:23-72` — reopen/round setup.

## Contract
Intent: under slot custody, reload current ownership and captured facts; refuse absent capture.
Effect: call trusted completion with saved admission/entry and callback fence; read saved answer and reconcile session. Never authorize a worker.
Result: reuse `AttemptResult`; verify only after answer/session completion. Storage, evidence or custody failure stays retryable. Conflict, changed ownership and hold preserve state. No stored fields or workflow words added.

## Work packages
1. Add captured-only completion and status/round/composition integration; closes A.
2. Cover A across reopen, repeated rounds, answer/session pending, transient failure, ownership change and hold. Run `just check` and `just test` once each, last.

## Acceptance behaviours
A. After restart, a stopped captured attempt finishes pending answer/session work and reaches verification with the same identity/reservation. Repeated rounds never launch an agent or abandon it. Transient failures retain work; holds, uncertain liveness and changed ownership prevent completion effects.
