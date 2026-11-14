# Header
Task: tl-8bh9.14.128.3.2.1
Base: 6eb05ff38b6d7305a7c67df52b6f0ca4ea108eca
Depth: medium; three behaviours
Owner decision missing: no. Dependency unlanded: none stated.
Evidence budget: 12 model calls.
Size: 7 changed files, 3 independent behaviours, 55 implement model calls.

## Outcome and non-goals
Expose consistent observations, a claim reader and continuation using saved authorization. Authorization, reconciliation, registration, capture and allowance renewal already exist; their reusable boundary and consuming authorization without granting it again remain the gap. Lifecycle wiring and release preservation belong to the other split tasks. No schema or shelf change.

## Settled decisions
- Reuse Observations, Claim, ClaimState, Intent, Outcome and ContinuationResult.
- Observation accepts or acquires custody and fences external reads.
- Claim validation uses the bound tracker without lease renewal.
- Supplied intent requires revalidation and the current admission.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/recover.py` — add `Recovery.observe`; share fences with `authorize` and `_reconcile`.
- `src/taskloop/recovery/continue_attempt.py` — `Continuation.__call__`, `_continue`, `_existing`: consume optional exact intent.
- `src/taskloop/tracker_client.py` — add `tracker_recovery_claim`, an explicitly bound read-only callback.
- `tests/steps/test_recovery_contract.py` — new; use `Recovery`, `RecoveryStore`, recovery fixtures and `Continuation` for races/renewal.
- `tests/steps/test_continuation.py` — extend continuation callers for preauthorization and refusals.
- `tests/cli/test_recovery_claim.py` — new; test `tracker_recovery_claim` through the tracker-facts seam.
- `src/taskloop/recovery/models.py` — consult `Observations`, `Intent`, `Result`, `Claim`.
- `src/taskloop/recovery/store.py` — consult `snapshot`, `compare`, `authorize`, `execute`, `register` fences.
- `src/taskloop/recovery/observe.py` — consult producer `NativeProcesses`.
- `src/taskloop/recovery/native.py` — consult consumer `NativeContinuation.__call__`.
- `src/taskloop/composition.py` — consult constructor `open_continuation`; retain claim injection.
- `src/taskloop/tracker.py` — consult `task_facts`, `ACTOR`.
- `src/taskloop/task.py` — consult `TaskFacts`, `TaskInspectionError`.
- `src/taskloop/attempt_types.py` — consult `Admission`, `AttemptRecord`.
- `tests/steps/test_recovery.py` — consult constructor `recovery`, authorization/renewal callers.
- `tests/steps/test_recovery_store.py` — consult producers `database`, `observed`, `facts`, `OWNED`.
- `tests/steps/test_recovery_reconcile.py` — consult reconciliation callers.
- `tests/steps/test_recovery_snapshot.py` — consult capture/drift comparisons.
- `tests/steps/test_native_continuation.py` — consult `prepared`, `NativeRun`, direct native/continuation callers.
- `tests/steps/test_continuation_composition.py` — consult the external `open_continuation` caller.
- `tests/cli/test_tracker_facts.py` — consult tracker read fixtures.
- `docs/design/tl-8bh9.14.128.3.2.1/plan.md` — implementation contract.

## Read list
- `src/taskloop/recovery/recover.py:28-142` — matching, classification, observation and operation boundaries.
- `src/taskloop/recovery/models.py:41-110` — existing typed observations and results.
- `src/taskloop/recovery/store.py:27-155` — proof checks, comparison, registration and renewal effects.
- `src/taskloop/recovery/observe.py:9-19` — native observation producer.
- `src/taskloop/recovery/continue_attempt.py:20-100` — authorization, execution and completion paths.
- `src/taskloop/recovery/native.py:25-80` — current admission timeout and registration-before-permit.
- `src/taskloop/composition.py:82-102` — production construction and injected claim port.
- `src/taskloop/tracker_client.py:22-69` — explicit-root validation and task-facts read seam.
- `src/taskloop/tracker.py:134-148` — facts mapping and error boundary.
- `src/taskloop/task.py:20-74` — task binding, status and assignee fields.
- `src/taskloop/attempt_types.py:122-156` — admission deadline, reference and saved record.
- `tests/steps/test_recovery.py:22-99` — constructor, process fake and claim refusals.
- `tests/steps/test_recovery.py:239-297` — renewal and stale-callback regression coverage.
- `tests/steps/test_recovery_store.py:23-58` — seed, observation producer and preservation assertions.
- `tests/steps/test_recovery_reconcile.py:90-176` — races, capture and claim refusals.
- `tests/steps/test_recovery_snapshot.py:77-119` — capture precedence and comparison fences.
- `tests/steps/test_continuation.py:31-73` — reopened execution and duplicate-permit cases.
- `tests/steps/test_continuation.py:194-212` — injected claim and already-held custody caller.
- `tests/steps/test_native_continuation.py:29-79` — native fake, prepared attempt and continuation caller.
- `tests/steps/test_native_continuation.py:90-125` — direct native and continuation callers.
- `tests/steps/test_continuation_composition.py:23-60` — constructor caller and custody assertions.
- `tests/cli/test_tracker_facts.py:26-67` — fake task facts, absence and read failure.

## Contract
`Recovery.observe(key, *, custody=None, allow_expired=False) -> Observations | Result`: under custody, compare a snapshot, read identities/claim outside write transactions, then compare again. Return facts only for unchanged snapshots; preserve capture and refusal outcomes. Share this path with authorization/reconciliation. Expired observation grants no authority; only existing explicit renewal can extend allowance.

`tracker_recovery_claim(tracker_root: Path) -> Callable[[Admission], Claim]`: bind the root explicitly, since Admission lacks it. A nonclosed task assigned to the factory actor is OWNED; missing/closed/unassigned/reassigned is LOST; invalid binding or unreadable/malformed facts is UNKNOWN. Explain every result; perform no writes.

`Continuation.__call__(key, owner, *, custody=None, intent: Intent | None=None)`: retain ordinary continuation. With intent, reject mismatched key/owner or changed authority, reconcile under custody and execute using the current admission. LIVE returns, UNKNOWN refuses, CAPTURED completes. Authorized/intended execution proceeds after stop/claim proof; registered-but-gone requires fresh ordinary authorization. Never implicitly replace generation/token/deadline.

Intent: exact saved attempt/session authorization. Effect: durable execute intent, native registration/permit, capture. Result: existing explained continuation state. Repeated calls observe effects before launch. No new stored fields/states.

## Work packages
1. `recover.py`, new `test_recovery_contract.py`: shared observation, races and renewal observations; close A1.
2. `tracker_client.py`, new `test_recovery_claim.py`: bound claim callback; close A2.
3. `continue_attempt.py`, `test_continuation.py`, `test_recovery_contract.py`: exact authorization, renewed admission, stale callbacks and repeat execution; close A3. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, with pipeline failure reporting enabled.

## Acceptance behaviours
A1: Acquired/supplied custody yields one unchanged observation snapshot; races return explained capture/refusal results without authorization/deadline changes, including expired observation for renewal.
A2: Bound tracker reads explain owned/lost/unknown claims without tracker writes.
A3: Exact authorization resumes the same attempt/session with renewed allowance without reauthorizing; stale, lost-claim or uncertain cases grant no permit, live/captured repeats grant no duplicate, and old callbacks remain fenced.
