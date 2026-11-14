# Header
Task: tl-8bh9.14.128.2.2.2.2; base: f99143708fba9163ea75f95a8facb62c2e8fe507.
Depth: medium; continuation, composition, crash safety. No missing decision or unlanded dependency. Evidence budget: 12 model calls. Size: 8 changed files, 3 behaviours, 50 implementation model calls.

## Outcome and non-goals
Expose callable saved-session continuation and existing-execution adoption through production composition. Preserve fencing across retry and restart. Exclude scheduler policy, CLI commands, schema changes, admission, setup, verification, release and publication.

## Settled decisions
- Reuse `Recovery.authorize/reconcile`, `RecoveryStore.execute/register`, `AgentLaunch.build(resume=...)` and `Callbacks`; these boundaries already exist.
- Adopt a live worker by returning its saved identity without launch or output attachment.
- Unknown liveness blocks execution; takeover requires confirmed absence and authorization.
- Keep slot custody across reconciliation, intent creation, native execution and capture; pass an already-held context to nested recovery operations.
- Reconcile lost registration acknowledgements before any further launch.
- Inject claim observations into composition; add no tracker mutation.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/continue_attempt.py` (new): `Continuation` coordinates existing `Recovery`, `RecoveryStore`, native execution and capture under custody.
- `src/taskloop/recovery/native.py` (new): `NativeContinuation` builds the saved-session launch and connects recovery registration, `Callbacks`, watched output and stop hooks to the existing execution port.
- `src/taskloop/recovery/continuation_models.py` (new): typed callable results with enum outcomes, explanations, saved identity and retryable pending capture.
- `src/taskloop/composition.py`: add `open_continuation`; reuse `_registration`, `open_recovery_registration`, `open_attempts` and `_run`, wiring `NativeProcesses`, custody, clock, IDs and injected claim observations.
- `tests/steps/test_continuation.py` (new): exercise the callable operation and reopened-database crash boundaries using the existing recovery fixtures.
- `tests/steps/test_native_continuation.py` (new): exercise native resume and registration/session/capture hooks through a semantic execution fake.
- `tests/steps/test_continuation_composition.py` (new): prove production ports are connected, including bounded registration and already-held custody.
- `docs/design/tl-8bh9.14.128.2.2.2.2/plan.md`: implementation scope and acceptance contract.

## Read list
- `src/taskloop/recovery/recover.py:28-140` — authorization, exact identity comparison and read-only reconciliation.
- `src/taskloop/recovery/store.py:26-138` — intent producer, registration transaction and ownership fencing.
- `src/taskloop/recovery/models.py:12-110` — explained outcomes, claims, intent and reconciliation results.
- `src/taskloop/recovery/execution_models.py:11-40` — existing execution phases and callback identity.
- `src/taskloop/recovery/registration.py:13-19` — registration hook and permit refusal.
- `src/taskloop/recovery/callbacks.py:14-49` — pending result producer and identity-bound capture consumer.
- `src/taskloop/recovery/state_store.py:31-44` — callback construction and durable fence; consult only.
- `src/taskloop/recovery/observe.py:9-19` — native entry/worker/group observations.
- `src/taskloop/agents/launch.py:86-129` — saved-session launch producer and launch failures.
- `src/taskloop/attempt.py:58-127` — execution dependency, capture, collection and stored-result completion.
- `src/taskloop/attempt.py:218-311` — launch, watched hooks, cleanup and callback-aware capture/answer consumers.
- `src/taskloop/composition.py:54-109` — bounded registration, native execution and attempts composition.
- `src/taskloop/slot_lock.py:39-73` — nonreentrant custody acquisition and release.
- `tests/steps/test_recovery.py:20-56` — process fake, recovery factory and nested custody contract.
- `tests/steps/test_recovery_registration.py:24-126` — intended execution producer, competing workers and lost registration acknowledgement.
- `tests/steps/test_recovery_callbacks.py:114-137` — pending capture and reopen fixture pattern.
- `tests/steps/test_recovery_reconcile.py:45-122` — existing reconciliation consumers and live/gone/unknown coverage.
- `tests/steps/test_agent_launch.py:151-205` — native resume across harnesses and fresh-session distinction.

## Contract
`Continuation` accepts an attempt key, current owner identity and optional already-held custody. Its ports are the existing recovery operation, recovery store, attempts application and a native execution callable. New result models use pydantic v2 and a closed enum; carry an explanation, the relevant saved intent/worker and, when capture is unavailable, its identity-bound pending result. Do not add stored fields or execution phases.

Intent: under custody, collect captured work or revalidate the snapshot, processes and claim. Return live identities; refuse unknown, changed, held, draining, expired or lost-claim states. Authorize confirmed stopped work and persist `execute` before external effects; takeover requires owner-stop proof.

Effect: read the saved input and existing admission settings, prepare answer artifacts and call `AgentLaunch.build` with the saved session. Continue in the existing slot without redispatching or rerunning setup. Compute remaining time from the admission deadline. Use the established execution port and cleanup ownership. The started hook commits recovery registration before returning; construct callback identity from that accepted registration before session output can be consumed. Preserve watched evidence and stop handling from the ordinary execution path.

Result: session reports and returned outcomes go through `Callbacks`; no unbound capture. Storage failure retains `PendingExecution` for capture-only retry. Captured facts finish decoding through the existing trusted completion path, without invoking an agent. Reopening the database consults durable intent/registration and current process observations; it does not recover control state from evidence files. Repeated intent writes are not proof that the external effect did not occur.

## Work packages
1. Add callable coordination and result models in `continue_attempt.py` and `continuation_models.py`, with operation tests in `test_continuation.py`. Close A1, including live adoption, unknown refusal, ownership changes and already-held custody.
2. Add `native.py`, wire `composition.open_continuation`, and cover native hooks plus production composition in the two new test files. Close A2; use the existing launch and registration adapters rather than introducing shelf APIs.
3. Extend `test_continuation.py` with crashes before/after intent, after registration commit/before acknowledgement, before capture and before decoding. Reopen the database with live/gone/unknown observations; count permits separately from launch requests. Close A3. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each; both must pass.

## Acceptance behaviours
A1. The callable resumes only revalidated stopped work, returns the saved identity for a live registered execution, and refuses uncertain or fenced-out work without a permitted target execution.
A2. Production composition resumes the saved session with the original settings and deadline; registration precedes execution, callbacks retain its exact generation/owner/worker identity, and custody and cleanup are correctly shared.
A3. Crash, lost acknowledgement, capture retry and database reopen never permit duplicate execution of the same recovery generation; captured work completes without an agent, and old-generation callbacks cannot overwrite its successor.
