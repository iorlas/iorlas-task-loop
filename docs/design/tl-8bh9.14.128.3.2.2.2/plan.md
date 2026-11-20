# Header
Task: tl-8bh9.14.128.3.2.2.2; base: f548d5ee858797fb472983bffd3d47b6d0a88bd5
Depth: medium; three behaviours.
Owner decision: none missing; predecessor landed. Evidence budget: 12 calls.
Size: 9 changed files including tests/plan, 3 behaviours, ~55 implement calls.

## Outcome and non-goals
Wire launch and entry to existing recovery authorization, native continuation and capture retry. Launcher currently rejects dispatched work; entry recognizes only the original entry. Shared observations/status gating and continuation composition are delivered. Scheduler convergence, new admission policy and schema changes are outside scope.

## Settled decisions
- Use the landed shared observations.
- The child registered by the launcher is the recovery owner; retain the attempt's original entry identity.
- Reuse Recovery.authorize, Continuation, Continuation.capture and tracker_recovery_claim.
- Launch minutes use existing atomic deadline renewal.
- Commit authority before child permission; reconcile uncertain starts.
- Keep the existing admitted-attempt and checks launch paths and their result contract.
- No new stored fields, schema version or glossary vocabulary is required.

## Open decisions
- None.

## Change map
- src/taskloop/launch.py — Launcher.launch/_target/_start: inject recovery dispatch for dispatched agents; share registered-start mechanics and LaunchResult handling.
- src/taskloop/recovery/launch.py (new) — connect Launcher to Recovery.authorize; child-owner registration before permit, explained refusal and uncertain-start reconciliation.
- src/taskloop/attempt_entry.py — _registered/_step/_claimed/main: recognize recovery owner; delegate continuation inside custody/lease lifetime.
- src/taskloop/recovery/entry.py (new) — connect enter to Continuation and Continuation.capture; validate owner, retry PendingExecution, return typed completion.
- src/taskloop/composition.py — open_launcher/open_continuation: inject recovery dispatch and bound claim reader using existing registration/observation ports.
- tests/steps/test_recovery_launch.py (new) — Launcher authorization, permit ordering, refusal and uncertain launch.
- tests/steps/test_recovery_entry.py (new) — enter owner/session identity, custody/lease and capture retry effects.
- tests/steps/test_continuation_composition.py — production recovery entry wiring.
- docs/design/tl-8bh9.14.128.3.2.2.2/plan.md — plan.
- src/taskloop/cli_composition.py — _starting caller of open_launcher: consult existing StartPorts assembly.
- src/taskloop/operations.py — start/relaunch_checks callers: consult launch outcome mapping and preserve checks behavior.
- src/taskloop/round.py — existing-attempt launch caller: consult LaunchResult integration; scheduler changes remain deferred.
- src/taskloop/repeat.py — launcher producer/consumer: consult repeated-step launch integration.
- src/taskloop/check_repeat/repair.py — CheckRepeat launcher consumer: consult repaired implement-step dispatch.

## Read list
- src/taskloop/launch.py:71-265 — ports, results, target selection and registered start.
- src/taskloop/attempt_entry.py:122-175 — capture retry and identity admission.
- src/taskloop/attempt_entry.py:176-371 — held execution, claim renewal, completion and production entry.
- src/taskloop/composition.py:83-104 — bounded recovery registration and native continuation wiring.
- src/taskloop/composition.py:206-218 — agent/check launch composition.
- src/taskloop/recovery/recover.py:29-178 — authority comparison, reconciliation and held-custody authorization.
- src/taskloop/recovery/store.py:27-164 — authorization fences, execution/worker registration and deadline extension.
- src/taskloop/recovery/state_store.py:11-44 — durable intent codec and callback fence.
- src/taskloop/recovery/models.py:12-103 — typed observations, owner identity and authorization.
- src/taskloop/recovery/continuation_models.py:12-31 — continuation states and pending result.
- src/taskloop/recovery/continue_attempt.py:20-115 — continuation, reconciliation and capture-only entry points.
- src/taskloop/recovery/native.py:25-80 — saved-session launch and worker-bound callbacks.
- src/taskloop/recovery/callbacks.py:14-49 — PendingExecution producer and capture identity checks.
- src/taskloop/attempt.py:91-116 — original execution versus trusted completion/capture.
- src/taskloop/attempt_store.py:82-188 — eligibility, renewal and original entry registration.
- src/taskloop/claim_lease.py:39-117 — initial renewal and keep-alive lifetime.
- src/taskloop/tracker_client.py:65-83 — claim observation bound to tracker root.
- src/taskloop/cli_composition.py:142-153 — launcher producer and StartPorts consumers.
- src/taskloop/operations.py:350-375 — direct-start launch outcome mapping.
- src/taskloop/round.py:282-297 — existing-attempt launch consumer.
- src/taskloop/repeat.py:180-203 — repeated/new and existing attempt launch callers.
- src/taskloop/check_repeat/repair.py:130-150 — repair launch caller.
- tests/steps/test_launch.py:51-159 — registered-start fake and launch fixtures.
- tests/steps/test_attempt_entry.py:166-194 — enter fixture integration and result assertions.
- tests/steps/test_continuation_composition.py:26-117 — production custody and completion fixtures.

## Contract
Launch intent: exact dispatched AttemptKey and allowance enter an injected recovery dispatch port; registered start supplies the child's boot-aware Identity. Effect: Recovery.authorize observes entry, worker/group, prior owner and bound claim under custody, compares the snapshot and commits Intent before child permission. Start runs outside write transactions. Result: existing Outcome/LaunchResult with nonempty explanation; stale/live/unknown/held/drained/unclaimed work grants no permit. Uncertain committed starts retain observable owner authority.

Entry intent: original entry identity or exact current Intent.owner. Effect: under the slot lock revalidate key, generation/token, revision and session; bind claim reads to the stored tracker root, renew first and retain KeepAlive through completion. Result: Continuation receives saved Intent and owner with already-held custody; entry_* remains intact. NativeContinuation registers its worker before callbacks and resumes Intent.session.

Capture intent: the exact PendingExecution from PENDING_CAPTURE. Effect: retry only Continuation.capture until acceptance, conflict or deadline. Result: trusted completion finishes capture/validation before verification; no retry issues another harness call. Return completion to ordinary entry handling; release/publication retain their existing authorization boundaries. Reuse Intent, ContinuationResult and State; add no stored field or new outcome vocabulary.

## Work packages
1. Launch authorization — launch.py, recovery/launch.py, composition.py and recovery launch tests; closes A1.
2. Recovery entry — attempt_entry.py, recovery/entry.py and recovery entry tests; closes A2.
3. Capture integration — recovery/entry.py and continuation composition tests; closes A3. Run just check and just test once each, last, using the required tail commands.

## Acceptance behaviours
A1. A stopped eligible dispatched attempt launches only after durable authorization names the actual child; stale, live, unknown, held, drained or unclaimed work permits no child execution, and an uncertain committed start is reconciled without a second live owner.
A2. Entry accepts the exact saved recovery owner and continues the same attempt/reservation/session while holding custody and renewing its bound claim; a mismatched owner or changed authority runs no harness.
A3. Busy capture storage retries the identical pending execution without another harness invocation; accepted capture completes before verification, while conflict or deadline stops retry.

