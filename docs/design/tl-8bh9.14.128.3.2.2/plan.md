# Header
Task: tl-8bh9.14.128.3.2.2
Base: ba8055746dc6e347d472d10becfbc1f8919522fe
Depth: medium; one behaviour across consumers.
Decisions: none missing; dependencies landed.
Evidence budget: 12 model calls.
Size: 16 changed files; 1 independent behaviour; 75 implement model calls.

## Outcome and non-goals
An intact restart continues eligible saved work through a surviving entry. Repeated scheduling converges on that execution. Exclude recovery-aware release preservation, schema changes, admission policy and native harness changes.

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
- `src/taskloop/attempt_status.py` — `StatusPorts/_agent/next_action`: map eligible recovery to start, live to wait, uncertainty to unknown.
- `src/taskloop/composition.py` — `open_launcher/open_continuation`: bind claims, observations and registration.
- `src/taskloop/cli_composition.py` — `open_reads/open_next/_starting`: share lifecycle ports across consumers.
- `src/taskloop/round.py` — `_settle/_resume`: launch recovery of the current attempt; extract settling.
- `src/taskloop/operations.py` — `start/_current/launched`: route existing recovery without admission; delegate extracted helpers.
- `src/taskloop/recovery/store.py` — `snapshot/compare`: support read-only observation; preserve write fences.
- `src/taskloop/recovery/lifecycle.py` (new) — mapping/owner registration integrated by Launcher, status and entry.
- `src/taskloop/start.py` (new) — start/current-selection helpers extracted from operations.start to meet caps.
- `src/taskloop/round_settle.py` (new) — settling extracted from round._run_round, with injected ports.
- `src/taskloop/repeat.py` — consult `StepRepeat.repeat/relaunch`, launcher callers.
- `src/taskloop/check_repeat/repair.py` — consult `CheckRepeat`, admission producer and launcher caller.
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
- `src/taskloop/attempt_status.py:135-245` — next action and agent status assembly.
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
- `src/taskloop/recovery/store.py:27-157` — fences.
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
Intent: Recovery observes attempt, claim, entry, worker and owner. Make snapshot/compare usable with open_reads; authorization revalidates in its write transaction.

Effect: registered start calls Recovery.authorize with the child's Identity and renewed deadline under custody before permitting entry execution. Entry validates its saved ownership/current key and calls Continuation(key, owner, intent=...) under already-held custody. Retain the original entry identity. Use existing worker-registration/capture callbacks; PENDING_CAPTURE retries only Continuation.capture.

Result: reuse Intent, Observations, Result, ReconciliationState and ContinuationResult/State, mapping explanations once into consumer outcomes. Live ownership prevents another start; uncertainty grants no execution. A lost registered worker requires fresh authorization; stale supplied Intent is refused. Completion feeds existing verification; captured work uses CapturedCompletion. Add no stored fields or schema version.

Extract consumer logic to meet caps without import cycles. SQL and claim details retain their owners.

## Work packages
1. Observation: recovery.store/lifecycle, attempt_status and both composition files; close A1 routing and A2 read-only/live/unknown checks.
2. Entry: launch, attempt_entry, composition, test_launch and test_attempt_entry; close A1 continuation and A2 registration/race checks.
3. Routing: operations/start, round/round_settle, test_restart and test_continuation_composition; close A1/A2 through repeated reopened rounds. Consult repeat/repair callers. Run focused tests, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. Reopened status, direct start and successive rounds converge on one recovery execution in the saved session with unchanged attempt/reservation; captured work completes before verification without another harness run.
A2. Resume stays single-execution across live/unknown processes, expired renewal, stale authorization, held/released work, claim loss, drain, uncertain start and capture retry; status changes no durable state and admitted/checks launches retain their behaviour.
