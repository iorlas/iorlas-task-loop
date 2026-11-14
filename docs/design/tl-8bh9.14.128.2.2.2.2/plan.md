# Header
Task: tl-8bh9.14.128.2.2.2.2; base: 4315cef17d82.
Depth: medium; 3 behaviours. Decisions: none missing; dependencies: none explicitly unlanded. Evidence budget: 12 model calls. Size: 1 changed file, 3 behaviours verified, 15 implement model calls.

## Outcome and non-goals
Validate the existing callable continuation, production composition and crash-safety contracts at the current revision. These implementations and their focused tests exist; the remaining gap is confirmation through the required gates. No runtime changes are currently needed. Exclude scheduler integration, new CLI commands, schema changes, admission, setup, publication and changes to shelf.

## Settled decisions
- Reuse `Continuation`, `NativeContinuation`, `ContinuationResult` and `open_continuation`; do not recreate delivered modules or duplicate their tests.
- Reuse the existing reconciliation snapshot and adoption boundaries supplied by `Recovery` and `RecoveryStore`.
- A live registered worker is adopted by returning its identity; uncertain liveness refuses execution.
- A stopped registered worker requires confirmed owner absence before a successor generation can execute.
- Custody spans reconciliation, durable intent, native execution and capture; nested recovery receives already-held custody.
- Registration acknowledgement precedes the execution permit and identity-bound callbacks. Lost acknowledgement requires reconciliation.
- Keep the existing saved session, admission settings, deadline, watched output, stop hooks and harness cleanup.

## Open decisions
- None.

## Change map
- `docs/design/tl-8bh9.14.128.2.2.2.2/plan.md`: replace obsolete creation instructions with bounded acceptance verification; sole planned file change.
- `src/taskloop/recovery/continue_attempt.py`: consult `Continuation.__call__`, `_existing`, `capture`, `_complete`; callable coordination and capture consumers already exist.
- `src/taskloop/recovery/native.py`: consult `NativeContinuation.__call__`, `_run`; native execution and registration/callback producer already exist; called by `Continuation` and both native/operation test modules.
- `src/taskloop/recovery/continuation_models.py`: consult `State`, `ContinuationResult`, `refused`; used by callable coordination and all three continuation test modules.
- `src/taskloop/composition.py`: consult `open_continuation`, `open_recovery_registration`, `open_attempts`, `_run`; production constructor is called by the composition test, with no other callers found.
- `src/taskloop/recovery/recover.py`: consult `Recovery.authorize`, `reconcile`, `matches`; reconciliation and authorization consumed by `Continuation`.
- `src/taskloop/recovery/store.py`: consult `RecoveryStore.execute`, `register`, `compare`, `authorize`; intent and registration producers consumed by continuation/native execution.
- `src/taskloop/recovery/callbacks.py`: consult `Callbacks.returned`, `capture`, `PendingExecution`; producer in native execution, consumers in callable capture, result models and operation tests.
- `tests/steps/test_continuation.py`: consult callable consumers and reopened-database crash matrix, capture retry, stale callbacks and custody assertions; retain existing coverage.
- `tests/steps/test_native_continuation.py`: consult `NativeRun`, `prepared` producers shared with operation/composition tests and native registration/admission assertions; retain existing coverage.
- `tests/steps/test_continuation_composition.py`: consult `test_real_composition_retains_custody_through_native_execution`; retain production wiring and bounded-registration coverage.

## Read list
- `src/taskloop/recovery/continue_attempt.py:20-100` — callable, adoption, capture-only retry and completion.
- `src/taskloop/recovery/native.py:25-80` — saved-session execution, registration hook, callbacks and cleanup.
- `src/taskloop/recovery/continuation_models.py:12-31` — existing explained result vocabulary.
- `src/taskloop/composition.py:59-126` — registration writer, execution port and callable production construction.
- `src/taskloop/recovery/recover.py:28-130` — exact identity comparison and revalidated authorization/reconciliation.
- `src/taskloop/recovery/store.py:50-138` — durable intent, registration transaction and generation ownership.
- `src/taskloop/recovery/callbacks.py:14-49` — pending result producer and exact-identity capture consumer.
- `tests/steps/test_continuation.py:31-137` — crash observations, local fences, owner proof and stale capture.
- `tests/steps/test_continuation.py:141-212` — captured restart, capture-only retry and already-held custody.
- `tests/steps/test_native_continuation.py:32-129` — shared execution producer, native resume and permit refusal.
- `tests/steps/test_continuation_composition.py:23-60` — production caller, distinct writers and custody lifetime.

## Contract
No new types, fields, stored states or effects are proposed. Preserve `ContinuationResult` with explained `State` outcomes and its optional intent, refusal, completion and `PendingExecution`.

Intent: `Continuation` takes the saved attempt key, owner identity and optional already-held custody. Reconcile existing registrations before authorization. Live workers return their saved identity; unknown observations or changed local/claim facts refuse. Confirmed stopped work obtains a revalidated authorization and durable execution intent before the external execution call.

Effect: `NativeContinuation` reads the saved input, builds a resume launch with the saved session and original admission settings, and limits execution to the remaining deadline. The started hook commits exact owner/generation/worker registration before permitting execution. Session and returned-result callbacks use that accepted identity. Custody stays held; cleanup runs after the native call, including refusal.

Result: capture uses the registration-bound pending result. Storage loss returns pending capture for an execution-free retry. Durable captured facts complete through trusted decoding without another agent invocation. Database reopen consults saved intent and current observations. A confirmed stopped worker may be replaced in a new generation; duplicate permitted execution within one generation remains forbidden. A stale generation cannot overwrite its successor.

## Work packages
1. Verify the existing callable and native contracts against `continue_attempt.py`, `native.py`, `callbacks.py`, `recover.py`, `store.py`, `continuation_models.py` and the operation/native test modules. Close A1 without adding duplicate implementation or coverage.
2. Verify `composition.py` and `test_continuation_composition.py` connect the same operations, bounded registration writer and continuous custody. Close A2; no additional scheduler caller is required.
3. Verify the existing crash matrix and capture/decoding restart assertions in `test_continuation.py` distinguish launch requests from execution permits and successor generations. Close A3. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each; both must pass. No source or test edits are planned; any failure must be assessed against A1-A3 before making a bounded correction.

## Acceptance behaviours
A1. Callable continuation adopts a live registered identity, resumes only revalidated stopped work, and refuses unknown observations, lost claims or changed fences without permitting execution; stale callbacks cannot capture over a successor.
A2. Production composition resumes the saved session with the admitted settings and remaining deadline, holds custody across execution and capture, commits bounded registration before callbacks, and performs harness cleanup on success and refusal.
A3. Reopening after intent, registration or lost acknowledgement never duplicates permitted execution within a generation; confirmed absence permits only an authorized successor, while capture retry and captured decoding restart invoke no agent.
