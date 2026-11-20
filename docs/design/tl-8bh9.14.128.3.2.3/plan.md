# Header
Task: tl-8bh9.14.128.3.2.3; base: 94fba7111249a5d29911b6897b4ad2184317e251
Depth: medium; two behaviours
Decisions: none missing; predecessor landed. Evidence budget: 12 model calls.
Size: 10 changed files including tests and plan; 2 independent behaviours; 55 implement model calls.

## Outcome and non-goals
Release observes saved recovery identities after capture and preserves branch work and durable evidence through retries. Scheduling, continuation, renewal and admission are delivered. They and the database schema remain outside this change.

## Settled decisions
- Recovery ownership remains relevant to release after capture; execution eligibility is not a release proof.
- Check every saved recovery owner and worker identity, including its process group. A live caller does not exempt its recovery identity.
- Reuse existing process-observation ports and typed recovery records; introduce no process actions.
- Preserve the existing release record, reservation fence, claim-return retry and parking semantics.
- Extract existing parking and save construction to keep the changed release module within its source cap.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/store.py`: `RecoveryStore` adds a key-validated release-intent read independent of eligibility.
- `src/taskloop/release_proof.py`: add recovery proof over `Intent` and `SetupSeen`, with typed refusal reasons.
- `src/taskloop/slot_release.py`: `_release`, `_refusal`, `_parked`, `_record` check and fence recovery facts; `_pending` retains its fast path. Extract parking and `_saver`.
- `src/taskloop/slot_park.py` (new): moved `Saver`, `park_slot`, `_unreadable`, `_saved` and save construction serve both release parking consumers.
- `src/taskloop/composition.py`: `open_releaser` supplies the recovery read port using the existing database connection owner.
- `src/taskloop/attempt_entry.py`: direct `SlotRelease` construction supplies the same reader under existing custody.
- `src/taskloop/check_release.py`: parking import and `_parked` use the extracted operation.
- `tests/steps/test_slot_release.py`: `Ports.releaser` injects recovery reads; retain release contracts.
- `tests/steps/test_recovery_release.py` (new): existing release/registration fixtures test blocking, drift and preservation after reopen.
- `src/taskloop/operations.py`: consult `verify_task` and `release_task`, callers of `Release.release`.
- `src/taskloop/round.py`: consult `_reconcile` release/reconcile dispatch; deferred release must converge after recovery ends.
- `src/taskloop/cli_composition.py`: consult round construction, `open_verify`, `open_release`, producers using `open_releaser`.
- `src/taskloop/cli_step.py`: consult `_release`, the CLI caller of `release_task`.
- `src/taskloop/hold.py`: consult `_abandoned`, the hold caller of `release_task`.
- `src/taskloop/land_conflict/store.py`: consult `free`; preserve its reservation-removal integration.
- `docs/design/tl-8bh9.14.128.3.2.3/plan.md`: implementation scope and acceptance contract.

## Read list
- `src/taskloop/slot_release.py:110-158` — parking operations to move.
- `src/taskloop/slot_release.py:169-440` — release row, proof, custody, save construction and claim retry.
- `src/taskloop/release_proof.py:15-76` — existing refusal and process-proof interface.
- `src/taskloop/recovery/store.py:43-113` — connection owner and eligibility-limited snapshot.
- `src/taskloop/recovery/state_store.py:11-28` — validated intent read and replacement semantics.
- `src/taskloop/recovery/models.py:46-87` — stored identities and observation models.
- `src/taskloop/recovery/execution_models.py:11-40` — registered execution worker and callback identity.
- `src/taskloop/recovery/recover.py:155-178` — observation comparison and owner projection.
- `src/taskloop/attempt_store.py:93-113` — capture/release exclusions that the release read must avoid.
- `src/taskloop/setup_store.py:30-35` — existing process-group observation port.
- `src/taskloop/drain/models.py:42-65` — observation enum and identity conversion.
- `src/taskloop/composition.py:202-209` — managed release composition.
- `src/taskloop/attempt_entry.py:327-344` — release from the entry under custody.
- `src/taskloop/check_release.py:49-60` — extracted parking import integration.
- `src/taskloop/check_release.py:309-319` — second parking consumer.
- `src/taskloop/operations.py:513-565` — verification and explicit release callers.
- `src/taskloop/round.py:254-274` — collected and lost-entry release consumers.
- `src/taskloop/cli_composition.py:174-188` — round release producer.
- `src/taskloop/cli_composition.py:315-350` — CLI verify/release producers.
- `src/taskloop/cli_step.py:242-251` — CLI release dispatch.
- `src/taskloop/hold.py:181-190` — abandon dispatch from held work.
- `src/taskloop/land_conflict/store.py:12-23` — unaffected shared reservation-removal import.
- `tests/steps/test_slot_release.py:65-209` — semantic release ports, completed release and interruption fixtures.
- `tests/steps/test_slot_release.py:345-377` — claim retry and repeated abandon expectations.
- `tests/steps/test_recovery_registration.py:17-35` — durable recovery execution fixture producer.

## Contract
Intent: `RecoveryStore` exposes `AttemptKey -> Intent | None`, independent of capture, expiry, holds and release. Malformed or mismatched records raise the existing store failure; absence requires no recovery proof.

Effect: pure `recovery_stopped` checks the owner, saved worker and registered execution worker through group-aware `SetupSeen`, deduplicating identities. Convert once to `Seen`; live/unknown returns `NotReleased` with enum reasons and explanations. Recovery callers have no exemption.

Intent and effect: check recovery before collection/reconciliation. Under custody reread the intent, observe outside write transactions, then compare attempt and recovery facts before parking. Fence intent equality again in the release-record transaction through the recovery store API. Custody serializes recovery registration with release. Drift refuses; final fence failure retains the reservation and reports any completed park.

Result: stopped recovery permits normal release. Retain intent, execution, session, saved work and evidence. `_pending` retries only unfinished claim return without revisiting a reused slot or clearing scratch again. Initial release retains existing scratch cleanup after recording, dirty-slot refusal and authorized held-work saving.

## Work packages
1. Proof: `recovery/store.py`, `release_proof.py`, new recovery-release tests establish post-capture reads, live/unknown groups and malformed-record refusal. Closes A1.
2. Integration: `slot_release.py`, `composition.py`, `attempt_entry.py`, `check_release.py`, new `slot_park.py`, existing release test ports add custody checks and fences while retaining parking. Closes A1/A2.
3. Preservation: new tests assert branch tip, evidence bytes, session identity, reservation and claim effects across completed recovery, interruption, reopen and repeated release/abandon. Closes A2. Finish implementation with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
- A1: A live or unknown saved recovery owner, worker or group prevents initial settled release, abandon and lost-entry reconciliation, including after capture, without parking, freeing the reservation, clearing scratch or returning the claim; changed recovery facts also retain custody.
- A2: With recovery processes confirmed gone, completed release preserves branch work and durable attempt/session evidence; an interrupted release and repeated release after database reopen converge on one release record and claim return, without revisiting a reused slot or changing retained evidence.
