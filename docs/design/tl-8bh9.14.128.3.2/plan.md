# Header
Task: tl-8bh9.14.128.3.2; base: b2bf21d0db99b8830b31593d6ed937dfe6446d24
Depth: medium; shared recovery across lifecycle owners.
Decisions: settled; dependency .3.1 landed. Evidence: 12 calls.
Size: 20 files including tests/plan; 3 behaviours; 90 implement calls.

## Outcome and non-goals
Connect delivered authorization, native continuation, capture and allowance renewal to lifecycle consumers. Exclude schema changes, reconstruction, new harness capabilities and the separate killed-rounds publication verification task.

## Settled decisions
- Preserve attempt, session, reservation and original entry; intent records recovery ownership.
- Keep both registered-start permit boundaries.
- Status only observes; explicit holds stay held.
- Retain ordinary/checks launch.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/recover.py` — `Recovery`, `classify`: shared lifecycle observation and owner validation before/after worker registration.
- `src/taskloop/recovery/models.py` — existing enums/models: explained typed eligibility and owner observations.
- `src/taskloop/recovery/continue_attempt.py` — `Continuation`: consume preauthorization, propagate renewal and reload admission.
- `src/taskloop/launch.py` — `Launcher._target`, `_start`: authorize the recovery child's identity before its permit.
- `src/taskloop/attempt_entry.py` — `_registered`, `_step`, `_claimed`: recovery identity, continuation/capture retry and finalization.
- `src/taskloop/attempt_status.py` — `StatusPorts`, `_agent`, `next_action`: derive restart actions from shared observations.
- `src/taskloop/slot_release.py` — `SlotRelease._refusal`: recovery stop proof before release effects.
- `src/taskloop/tracker_client.py` — task inspection integration: adapt claim observations to recovery results.
- `src/taskloop/composition.py` — `open_continuation`, `open_launcher`, `open_releaser`: shared ports and bounded writer.
- `src/taskloop/cli_composition.py` — `open_reads`, `_starting`, `open_next`: wire status and round consumers.
- `src/taskloop/round.py` — existing-attempt relaunch: consume the shared action for the same attempt.
- `src/taskloop/repeat.py` — consult both launcher callers for fresh/existing attempt compatibility.
- `src/taskloop/check_repeat/repair.py` — consult repair's launcher caller for dispatch compatibility.
- `src/taskloop/cli_step.py` — consult `_show`, the CLI status caller.
- `src/taskloop/dash_task.py` — consult `build_task`, the `current_view` caller.
- `src/taskloop/attempt_store.py` — consult `register_entry`, the ordinary admitted-entry producer.
- `src/taskloop/recovery/store.py` — consult `snapshot`, `authorize`, the delivered atomic fence.
- `src/taskloop/recovery/native.py` — consult `NativeContinuation`, the saved execution producer.
- `tests/steps/test_launch.py` — recovery permit ordering, concurrent launch and uncertainty.
- `tests/steps/test_attempt_entry.py` — recovery identity, capture retry and finalization.
- `tests/steps/test_continuation_composition.py` — real wiring and renewed allowance.
- `tests/steps/test_slot_release.py` — owner/worker safety and retained evidence.
- `tests/steps/test_restart.py` — intact restart and round action without duplicate admission.
- `tests/steps/test_attempt_listing.py` — recoverable, blocked and held status views.
- `tests/steps/test_native_continuation.py` — consult existing preservation/permit assertions.
- `docs/design/tl-8bh9.14.128.3.2/plan.md` — new plan artifact; no new runtime module.

## Read list
- `src/taskloop/launch.py:134-246` — selection and registered permit.
- `src/taskloop/attempt_entry.py:153-316` — identity through finalization.
- `src/taskloop/attempt_status.py:56-243` — ports and action derivation.
- `src/taskloop/composition.py:82-210` — continuation/launcher/release wiring.
- `src/taskloop/slot_release.py:199-295` — release and stop proof.
- `src/taskloop/recovery/recover.py:29-145` — classification/authorization.
- `src/taskloop/recovery/models.py:12-109` — typed vocabulary.
- `src/taskloop/recovery/continue_attempt.py:20-100` — intent/capture handling.
- `src/taskloop/recovery/store.py:27-173` — atomic authorization/renewal.
- `src/taskloop/attempt_store.py:149-191` — ordinary entry registration.
- `src/taskloop/recovery/native.py:1-80` — saved native execution.
- `src/taskloop/tracker_client.py:20-40` — claim inspection adapter integration.
- `src/taskloop/cli_composition.py:105-180` — status/start/round wiring.
- `src/taskloop/round.py:226-281` — action selection and launch caller.
- `src/taskloop/repeat.py:170-196` — both launch callers.
- `src/taskloop/check_repeat/repair.py:130-155` — repair launch caller.
- `src/taskloop/cli_step.py:229-238` — CLI status consumer.
- `src/taskloop/dash_task.py:270-281` — dashboard status consumer.
- `tests/steps/test_launch.py:176-235` — replacement/uncertainty cases.
- `tests/steps/test_attempt_entry.py:491-523` — bounded completion retry.
- `tests/steps/test_continuation_composition.py:1-60` — custody/composition fixture.
- `tests/steps/test_slot_release.py:1-180` — release fixtures/effects.
- `tests/steps/test_restart.py:1-72` — reopened state and retained facts.
- `tests/steps/test_attempt_listing.py:22-100` — status fixtures/observations.
- `tests/steps/test_native_continuation.py:33-85` — session preservation.

## Contract
Intent: observe original entry, worker and recovery owner, including authorization before worker registration. Status classifies expired work without renewal. Extend existing enums/models with explained typed outcomes as needed.

Effect: under custody, authorize the registered child's boot-aware identity before its permit, with a finite allowance from launch minutes. Retain revision/reservation/claim/drain fences and ordinary entry registration. Uncertain permits retain their durable owner for reconciliation.

Result: entry revalidates ordinary identity or exact recovery ownership under custody. Continuation consumes its preauthorization without treating itself as a competing execution. Propagate renewal through expired reads; reload admission for native/retry timeouts. Same-generation retries cannot renew again.

Retry pending capture only through `Continuation.capture`; use trusted decoding/verification. No schema change.

Release checks recovery owner/worker under custody, excluding only the exact calling entry. Preserve existing save/park/unclaim effects. Map task inspection to claim outcomes inside the tracker adapter.

## Work packages
1. Shared contract: recover/models/continue_attempt and tracker adapter; acceptance 1–2.
2. Consumers: launch/entry/composition/CLI composition/status/round and corresponding tests; acceptance 1–2. Consult listed callers.
3. Preservation: slot release/tests and restart fixtures; acceptance 3. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both must pass.

## Acceptance behaviours
1. Reopening eligible stopped work yields one authorized entry resuming the same session/attempt with one bounded allowance and trusted completion. Concurrent launch, permit uncertainty and capture retry cannot duplicate execution or admission.
2. Status, launch and entry consistently retain live/unknown processes, lost/unknown claims, explicit holds, drain fences and changed ownership; refusals grant no permit or allowance renewal. Ordinary first launch and checks dispatch still work.
3. Release retains reservation, worktree changes and evidence while a recovery owner/worker is live or unknown. After completion and stop proof, settled and repeated release safely preserve session references, results and evidence.
