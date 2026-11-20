# Header
Task: tl-8bh9.14.107.2; base: 13d49fb449a82309374e07847d26533fc1144883
Depth: small; one recovery behaviour.
Owner decision: none; unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 2 changed files; 1 independent behaviour; 20 implement model calls.

## Outcome and non-goals
Cover `open_completion` after database reopen. Existing tests cover answer/session completion, round retries and ownership fences with manually constructed completion. Retain runtime behaviour; exclude uncaptured execution and other reconciliation tasks.

## Settled decisions
Retain `CapturedCompletion`, status routing and completion before round verification.
Retain `Attempts.execute` as the captured-answer/session completion operation.
Use semantic process and harness fakes through existing ports; no shelf change is needed.

## Open decisions
- None.

## Change map
- `tests/steps/test_continuation_composition.py`: add a regression through `open_completion` after reopen, covering pending answer/session and repeated completion.
- `docs/design/tl-8bh9.14.107.2/plan.md`: bound remaining work and validation.
- `src/taskloop/composition.py`: consult `open_completion` and dependency producer `open_attempts`.
- `src/taskloop/cli_composition.py`: consult `open_round`, the constructor caller supplying `RoundPorts.completion`.
- `src/taskloop/round.py`: consult `RoundPorts.completion` and callback consumer `_verified`.
- `src/taskloop/recovery/complete_attempt.py`: consult `CapturedCompletion.__call__` and `_complete` fences.
- `src/taskloop/attempt.py`: consult `execute`, `_resume`, `_refresh`, the saved-evidence consumers.
- `src/taskloop/attempt_status.py`: consult `next_action` and `_stopped` routing.
- `tests/steps/test_restart.py`: consult reopened-round coverage and its manually constructed callback.
- `tests/steps/test_continuation.py`: reuse producer `captured_work`; consult preservation coverage.

## Read list
- `tests/steps/test_continuation_composition.py:1-60` — production-composition conventions; edit here.
- `src/taskloop/composition.py:106-120` — constructor and dependency producer.
- `src/taskloop/cli_composition.py:172-190` — production round wiring caller.
- `src/taskloop/round.py:123-130` — completion port.
- `src/taskloop/round.py:337-349` — callback consumer before verification.
- `src/taskloop/recovery/complete_attempt.py:13-49` — custody and captured-only completion.
- `src/taskloop/attempt.py:90-102` — saved execution precedes dispatch.
- `src/taskloop/attempt.py:117-145` — answer/session reconciliation.
- `src/taskloop/attempt_status.py:135-157` — restart routing.
- `tests/steps/test_restart.py:36-83` — reopen, retries and identity assertions.
- `tests/steps/test_continuation.py:37-75` — captured fixture and completion assertions.
- `tests/steps/test_continuation.py:78-149` — existing fence and retry coverage.

## Contract
Intent: reopen the intact database and construct completion through `open_completion`, using captured fixture evidence and its artifact paths.
Effect: fake the entry observation as stopped; decode the saved answer and reconcile its session under real slot custody. Fail the test on any harness execution.
Result: existing `AttemptResult` becomes pending verification; repeated completion preserves identity, reservation and completed session. Add no runtime names, fields or transitions.

## Work packages
1. Add the regression in `tests/steps/test_continuation_composition.py` for pending-answer and pending-session inputs; closes A.
2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both must pass.

## Acceptance behaviours
A. After reopen, production-composed completion finishes a captured pending answer or session and returns verification-ready work with the same attempt identity and reservation; repeated completion starts no agent and preserves the completed session.
