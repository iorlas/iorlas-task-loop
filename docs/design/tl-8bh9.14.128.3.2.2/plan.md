# Header
Task: tl-8bh9.14.128.3.2.2
Base: f584d2e7cfe1d88574b198c39f6c480822ff3c93
Depth: medium; one behaviour across consumers.
Decisions: none missing; dependencies landed.
Evidence budget: 12 model calls.
Size: 17 files; 2 independent behaviours; 85 implement calls.

## Outcome and non-goals
Wire consumers to shared observation, authorization and preauthorized continuation. Exclude release preservation, schema changes, admission policy and native harness changes.

## Settled decisions
- Reuse Recovery.observe/authorize and Continuation with the durable Intent.
- Preserve AttemptKey, dispatch token, reservation and session; recovery ownership differs from original entry registration.
- Registered start commits recovery authorization before permitting the child to run.
- Bind tracker_recovery_claim to the stored tracker root.
- CapturedCompletion precedes verification; admitted/checks launches retain their registration paths.

## Open decisions
- None.

## Change map
- `src/taskloop/launch.py` — `Launcher.launch/_target/_start`: select recovery and register its owner.
- `src/taskloop/attempt_entry.py` — `_registered/enter/_claimed/_step/main`: validate owner, continue saved Intent under custody/renewal, then complete.
- `src/taskloop/attempt_status.py` — `StatusPorts/_agent`: map recovery through lifecycle; use extracted action selection.
- `src/taskloop/attempt_next.py` (new) — move `EntryState/Next/Stuck/next_action/_stopped` from attempt_status; integrate through its `_agent` caller to meet caps.
- `src/taskloop/composition.py` — `open_launcher/open_continuation`: bind claims, observations, registration and store lifetime.
- `src/taskloop/cli_composition.py` — `open_reads/open_next/_starting`: share lifecycle ports across consumers.
- `src/taskloop/round.py` — `_settle/_resume`: launch recovery of the current attempt; extract settling.
- `src/taskloop/operations.py` — `start/_current/launched`: route existing recovery without admission; delegate extracted helpers.
- `src/taskloop/recovery/store.py` — `snapshot/compare`: support read-only observation; preserve write fences.
- `src/taskloop/recovery/lifecycle.py` (new) — mapping/owner registration integrated by Launcher, status and entry.
- `src/taskloop/start.py` (new) — selection/admission helpers extracted from operations.start, with injected ports.
- `src/taskloop/round_settle.py` (new) — settlement/resume helpers extracted from round._run_round, preserving completion and release ordering.
- `src/taskloop/repeat.py` — consult `StepRepeat.repeat/relaunch`, launcher callers.
- `src/taskloop/check_repeat/repair.py` — consult `CheckRepeat._launch`, admission producer and launcher caller.
- `src/taskloop/tracker_client.py` — consult `tracker_recovery_claim/tracker_claims`, claim producers.
- `src/taskloop/recovery/recover.py` — consult `Recovery.observe/authorize/reconcile` fences.
- `src/taskloop/recovery/continue_attempt.py` — consult `Continuation.__call__/capture` execution boundaries.
- `src/taskloop/recovery/models.py` — consult `Intent/Observations/Result` contracts.
- `src/taskloop/recovery/continuation_models.py` — consult `State/ContinuationResult` outcomes.
- `src/taskloop/recovery/native.py` — consult `NativeContinuation` registration/capture producer.
- `src/taskloop/recovery/observe.py` — consult `NativeProcesses` observation producer.
- `src/taskloop/recovery/complete_attempt.py` — consult `CapturedCompletion` before verification.
- `src/taskloop/claim_lease.py` — consult `KeepAlive/keeping/renewal` claim lifetime.
- `tests/steps/test_launch.py` — registration, repeated/uncertain launches.
- `tests/steps/test_attempt_entry.py` — owner validation and continuation custody.
- `tests/steps/test_restart.py` — reopened consumer convergence and preserved identity.
- `tests/steps/test_continuation_composition.py` — production ports and read-only observation.
- `docs/design/tl-8bh9.14.128.3.2.2/plan.md` — implementation contract.

## Read list
- `src/taskloop/launch.py:71-252` — targets, outcomes and registered start.
- `src/taskloop/attempt_entry.py:153-341` — identity, custody, renewal and completion.
- `src/taskloop/attempt_status.py:40-245` — extracted vocabulary/action selection and agent status assembly.
- `src/taskloop/composition.py:65-134` — recovery, completion and attempt producers.
- `src/taskloop/composition.py:206-218` — both launcher constructors.
- `src/taskloop/cli_composition.py:108-190` — status and round composition.
- `src/taskloop/round.py:155-299` — round ordering and settlement callers.
- `src/taskloop/operations.py:325-523` — start/current selection and launch result consumer.
- `src/taskloop/repeat.py:157-203` — launch callers.
- `src/taskloop/check_repeat/repair.py:116-149` — repair caller.
- `src/taskloop/tracker_client.py:65-83` — claim adapter.
- `src/taskloop/tracker_client.py:186-225` — heartbeat producer.
- `src/taskloop/recovery/recover.py:73-166` — shared operations.
- `src/taskloop/recovery/store.py:100-157` — read connection change and committing fences.
- `src/taskloop/recovery/continue_attempt.py:20-115` — execution/capture.
- `src/taskloop/recovery/models.py:11-110` — typed observations.
- `src/taskloop/recovery/continuation_models.py:12-31` — outcomes.
- `src/taskloop/recovery/native.py:29-80` — callback ordering.
- `src/taskloop/recovery/observe.py:10-19` — liveness producer.
- `src/taskloop/recovery/complete_attempt.py:12-49` — completion.
- `src/taskloop/claim_lease.py:39-114` — renewal scope.
- `tests/steps/test_launch.py:1-125` — start fixtures.
- `tests/steps/test_attempt_entry.py:198-340` — custody fixtures.
- `tests/steps/test_restart.py:37-135` — reopened consumers.
- `tests/steps/test_continuation_composition.py:27-112` — production wiring.

## Contract
Intent: observe attempt, claim, entry, worker and owner through open_reads; authorization revalidates transactionally.

Effect: before permitting execution, authorize the child's Identity with a finite future deadline under custody. Entry validates owner/key and invokes Continuation(key, owner, intent=...) under custody and claim keep-alive. Keep original entry identity and native callbacks; PENDING_CAPTURE retries capture alone. Composition closes its stores.

Result: reuse Intent, Observations, Result, ReconciliationState and ContinuationResult/State with their explanations. Live/unknown ownership grants no execution. A lost worker needs fresh authorization; stale Intent is refused. CapturedCompletion precedes verification. Add no fields or schema version.

Extract 210+ lines from operations (604), 90+ from round (475), and action selection/vocabulary from attempt_status (407). Inject ports to avoid cycles; retain SQL and claim ownership.

## Work packages
1. Observation: recovery.store/lifecycle, new attempt_next, attempt_status and both composition files; close A1 routing and A2 read-only/live/unknown checks.
2. Entry: launch, attempt_entry, composition, test_launch and test_attempt_entry; close A1 continuation and A2 registration/race checks.
3. Routing: operations/start, round/round_settle, test_restart and test_continuation_composition; close A1/A2 through reopened rounds. Consult repeat/repair callers. Run focused tests, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. Reopened status, direct start and successive rounds converge on one recovery execution in the saved session with unchanged attempt/reservation; captured work completes before verification without another harness run.
A2. Repeated/concurrent scheduling never admits or executes duplicate work across live/unknown processes, expired allowance, stale authorization, held/released work, claim loss, drain and uncertain start; capture retry runs no harness, status writes nothing and admitted/checks launches retain their behaviour.
