# Header
Task: tl-8bh9.14.128.2.2.2; base: 9ee126d3db36fb48c12ba8fa5d2e4792552a9511.
Depth: medium; three behaviours. Decisions settled; no explicitly unlanded dependency; part 1 present. Evidence: 12 model calls total.
Size: 8 files including tests/plan, 3 behaviours, 65 implement calls.

## Outcome and non-goals
Connect saved-session launch to existing registration, fenced callbacks and completion; reconcile uncertain launches first. Part 1 already delivers durable registration, callback fencing and generation-specific evidence. Exclude round selection, replacement entry activation, owner commands, deadline renewal and preparation.

## Settled decisions
- Preserve attempt, session, input, base, settings and deadline.
- Reconcile before authorization; adoption retains identity without inventing a process handle.
- Reuse schema 27 and existing stored shapes; any incompatible change requires a version bump and drain/discard upgrade.
- Reuse process, launch, run and stop adapters.
- Composition accepts explicit claim/custody ports.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/continue_session.py` — new `Continuation.continue_session` and typed result; integrates authorization, registration, callbacks, launch and completion.
- `src/taskloop/recovery/store.py` — reconciliation snapshot/compare boundary independent of fresh authorization eligibility.
- `src/taskloop/composition.py` — new `open_continuation` using `open_attempts`, `open_recovery_registration`, `_run`, native observations and explicit claim/custody.
- `tests/steps/test_recovery_continuation.py` — new operation contracts.
- `tests/steps/test_recovery_adoption.py` — new crash/reopen execution-count contracts.
- `tests/steps/test_recovery_composition.py` — new callable wiring contract.
- `tests/steps/test_recovery_store.py` — reconciliation read/compare contracts.
- `docs/design/tl-8bh9.14.128.2.2.2/plan.md` — implementation plan.
- Consult callers/producers: `attempt.py` (`execute`, `_launch`, `_call`, `capture`), `attempt_entry.py` (`_step`, `resumed`), `merge/resolve.py` (launch), `session.py` and `recovery/registration.py` (`registration_hook`), `recovery/callbacks.py` (`Callbacks`).
- Consult helper consumers: `test_recovery.py`, `test_recovery_registration.py`, `test_recovery_callbacks.py`, `test_recovery_evidence.py`.

## Read list
- `src/taskloop/recovery/models.py:11-87` — outcomes, intent and observation producers.
- `src/taskloop/recovery/execution_models.py:11-40` — execution phase and callback identity.
- `src/taskloop/recovery/recover.py:22-60` — authorization and custody integration.
- `src/taskloop/recovery/store.py:25-130` — eligibility, intent, registration and ownership comparison.
- `src/taskloop/recovery/state_store.py:11-44` — sole recovery SQL owner and callback validation.
- `src/taskloop/recovery/registration.py:13-19` — committed registration permit callback.
- `src/taskloop/recovery/callbacks.py:14-49` — bound session/result and pending capture consumer.
- `src/taskloop/recovery/observe.py:9-19` — native identity/group observation adapter.
- `src/taskloop/attempt.py:82-140`, `src/taskloop/attempt.py:217-311` — completion, launch, hooks and capture.
- `src/taskloop/attempt_store.py:65-128` — worker replacement, eligibility and fencing.
- `src/taskloop/attempt_loads.py:217-239` — captured execution and its trusted callback association.
- `src/taskloop/composition.py:52-113` — bounded registration writer, run adapter and attempts factory.
- `src/taskloop/agents/launch.py:86-129` — explicit native resume and preserved launch policy.
- `src/taskloop/evidence_files.py:100-114`, `src/taskloop/evidence_files.py:273-296` — generation destinations and capture.
- `src/taskloop/session.py:23-90` — ordinary registration and shared session reconciliation.
- `src/taskloop/agents/stop.py:54-85` — stop intent/report hooks for supervised execution.
- `src/taskloop/drain/actions.py:30-75` — durable external action scope and uncertain results.
- `src/taskloop/merge/resolve.py:50-76` — other launch producer, consult only.
- `src/taskloop/attempt_entry.py:196-228` — ordinary execution/capture caller, consult only.
- `tests/steps/test_recovery_store.py:1-85` — database fixtures and world observations.
- `tests/steps/test_recovery_registration.py:26-149` — intended execution and lost acknowledgement contracts.
- `tests/steps/test_recovery_callbacks.py:25-67` — existing bound callback/capture integration.
- `tests/steps/test_recovery_evidence.py:16-45` — existing generation destination assertions.
- `tests/steps/test_recovery.py:1-75` — authorization caller and custody/process fakes.
- `src/taskloop/factory_schema.py:46-52` — current compatibility version.

## Contract
`Continuation.continue_session(key, owner)` returns an explained typed in-process result with existing outcome/intent, optional attempt completion or bound pending capture. No new stored fields.
Intent: hold custody, read capture/registration, observe exact identities and claim outside transactions, then compare the snapshot before transitions. Reconciliation can inspect expired/draining work without granting execution. Captured work uses existing completion without authorization or launch.
Effect: persist intent, then build with `resume=intent.session` and generation-specific destinations. Started commits registration through the bounded writer, constructs `Callbacks` from that committed worker, then returns the permit; uncertainty/refusal permits nothing. Retain stop/report and command hooks. Use the drain action scope; leave uncertain effects observable.
Result: capture/retry with the same callback identity. Reread after exceptions/lost acknowledgements. Alive worker/group is retained; unknown blocks. A new generation requires previous owner and whole worker group absence, fresh authorization and intent. Unregistered intent cannot have permitted execution; fence stale registration before replacement. Never replay a registered generation, infer absence from files/locks or stop during reconciliation.

## Work packages
1. `recovery/store.py`, `test_recovery_store.py`, new adoption suite: snapshot/compare, registered revisions and captured-first completion; acceptance 3.
2. New `continue_session.py` and operation suite: authorization, resume, registration-bound hooks and pending capture; acceptance 1.
3. `composition.py` and new composition suite: callable wiring; acceptance 2. Finish crash contracts and ordinary-path regressions.
Use temporary SQLite and semantic fakes counting execution only after started returns. Crash before/after intent, before registration commit, after commit before acknowledgement, after permit and after capture. Reopen with alive/gone/unknown, reused identity and surviving group observations. Include competing callers, ownership changes, drain/deadline/claim refusal and capture unavailability.
Run focused isolated pytest checks. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipeline failure detection. No implementation gates during planning.

## Acceptance behaviours
1. Continuation resumes the saved session under original policy/deadline, executes only after registration, and completes or retains bound capture without preparation or fresh-session fallback.
2. The composed callable reaches launch/run/registration/process ports with stop/drain boundaries; ordinary execution and merge launches retain their behaviour.
3. Reopen retains live workers, blocks unknown groups, completes captured work without launch and requires absence proofs for replacement; crash execution counts prove no duplicate execution.
