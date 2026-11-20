# Header
Task: tl-8bh9.14.128.2.2.2.1; base: 9719b1fc1ee1cde800fee37458c4b6ec2aeb7ea3.
Depth: medium; two behaviours. No missing decision; fencing part 1 landed. Evidence ceiling: 12 model calls. Size: 6 changed files including tests and plan, 2 behaviours, 40 implementation model calls.

## Outcome and non-goals
Add snapshot comparison and read-only reconciliation of saved recovery execution. Authorization, execution intent, atomic registration and callback fencing already exist. The gap is identifying live, stopped, uncertain or captured execution after interruption. Native continuation, launch/wait, composition and end-to-end crash execution belong to the chained task. No schema change.

## Settled decisions
- `Recovery.authorize` retains ownership authorization for stopped work.
- Reconciliation grants no registration permit or ownership transfer.
- Compare complete snapshots after observation; preserve eligibility/capture results.
- Registered execution matches its saved worker and registration revision.
- Reuse process ports; no additional shelf facts are needed.

## Open decisions
- None.

## Change map
- `src/taskloop/recovery/models.py`: add `ReconciliationState`, `Reconciliation`.
- `src/taskloop/recovery/store.py`: add `compare`; share its fence with `authorize`.
- `src/taskloop/recovery/recover.py`: add `Recovery.reconcile`; reuse `_observe` and custody.
- `tests/steps/test_recovery_snapshot.py` (new): `compare` contracts; integrate existing `database/observed/intended` helpers.
- `tests/steps/test_recovery_reconcile.py` (new): `reconcile` contracts; integrate `Recovery` ports and file databases.
- `docs/design/tl-8bh9.14.128.2.2.2.1/plan.md`: implementation contract.
- `src/taskloop/attempt_store.py`: consult `recovery/replace_worker`, snapshot producers.
- `src/taskloop/recovery/execution_models.py`: consult `Execution/Callback` invariants.
- `src/taskloop/recovery/state_store.py`: consult `intent/save/callback/fence` ownership.
- `src/taskloop/recovery/registration.py`: consult `registration_hook`, `register` caller.
- `src/taskloop/recovery/observe.py`: reuse `NativeProcesses.entry/process`.
- `src/taskloop/composition.py`: consult `open_recovery_registration`, store producer.
- `src/taskloop/evidence_files.py`: consult `EvidenceFiles`, intent/callback consumer.
- `src/taskloop/recovery/callbacks.py`: consult `Callbacks`, registered-identity consumer.
- `tests/steps/test_recovery.py`: preserve `authorize` callers.
- `tests/steps/test_recovery_store.py`: reuse `observed/database`, snapshot producers.
- `tests/steps/test_recovery_registration.py`: preserve `intended`, `execute/register` callers.
- `tests/steps/test_recovery_callbacks.py`: consult `registered`, callback producer.
- `tests/steps/test_recovery_evidence.py`: preserve `execute/register` callers.
- `tests/steps/test_recovery_observe.py`: preserve `NativeProcesses` callers.
- `tests/steps/test_schema_words.py`: preserve schema-refusal `snapshot` caller.

## Read list
- `src/taskloop/recovery/models.py:12-87` — outcomes and snapshot/observation models to extend.
- `src/taskloop/recovery/store.py:26-130` — authorization comparison, execution intent and registration fences.
- `src/taskloop/recovery/recover.py:16-60` — process ports, custody and observation sequence.
- `src/taskloop/attempt_store.py:69-114` — registration revision and eligibility/capture precedence.
- `src/taskloop/attempt_types.py:146-155` — attempt snapshot fields.
- `src/taskloop/recovery/execution_models.py:11-40` — execution phase invariants and callback identity.
- `src/taskloop/recovery/state_store.py:11-44` — durable identity loading, saving and callback fence.
- `src/taskloop/recovery/registration.py:13-19` — sole registered-start permit hook.
- `src/taskloop/recovery/observe.py:9-19` — native process observations reused by the application.
- `src/taskloop/composition.py:77-80` — bounded recovery store construction.
- `src/taskloop/evidence_files.py:110-122` — generation-specific launch roots.
- `src/taskloop/evidence_files.py:277-296` — intent/callback artifact consumers.
- `src/taskloop/recovery/callbacks.py:20-49` — callback identity consumers.
- `tests/steps/test_recovery_store.py:26-79` — file database, snapshots and preserved facts helpers.
- `tests/steps/test_recovery_store.py:164-195` — local fence mutation cases.
- `tests/steps/test_recovery.py:20-91` — semantic process and custody examples.
- `tests/steps/test_recovery.py:147-168` — capture and deadline races.
- `tests/steps/test_recovery_registration.py:27-92` — intent producer, registration and stale-generation callers.
- `tests/steps/test_recovery_callbacks.py:31-60` — registered callback production and replacement generations.
- `tests/steps/test_recovery_evidence.py:15-44` — immutable generation evidence contract.
- `tests/steps/test_recovery_observe.py:12-33` — PID reuse, boot and group uncertainty cases.
- `tests/steps/test_schema_words.py:66-75` — incompatible schema snapshot caller.

## Contract
`RecoveryStore.compare(expected: Snapshot, clock) -> Snapshot | Result` rereads eligibility, drain and intent in a short transaction. Equality returns the snapshot; drift returns explained CHANGED; eligibility results retain their meaning, including CAPTURED. Share comparison inside authorization's committing transaction without nesting transactions.

`ReconciliationState`: LIVE, GONE, UNKNOWN, CAPTURED. Validated frozen `Reconciliation` carries key, state, explanation and compared snapshot, absent only for CAPTURED. Existing `Result` carries eligibility, identity, storage, claim or custody refusals.

`Recovery.reconcile(expected: Intent, *, custody=...) -> Reconciliation | Result` reads under custody, validates authorization, observes outside write transactions, compares again, then classifies. Expected intent may precede registration: allow forward execution progress only with unchanged authorization fields. INTENDED matches original worker/revision; REGISTERED matches saved execution worker/revision, exactly authorization revision plus one. Drift yields CHANGED.

LIVE identifies an exact registered worker observed alive. GONE requires confirmed entry and worker absence; ambiguity yields UNKNOWN. Preserve owner observations and refuse lost/unknown claims. Ownership replacement requires existing authorization. Unregistered intent provides no adopted worker or launch permit.

Intent: identify durable execution. Effect: observe processes/claim and revalidate state. Result: explained classification/refusal. Capture during observation yields CAPTURED. No spawn, signal, wait, collection, allowance renewal, ownership transfer or stored-field changes.

## Work packages
1. `recovery/store.py`, new `test_recovery_snapshot.py`: compare snapshots, retaining atomic authorization. Closes A1.
2. `recovery/models.py`, `recovery/recover.py`, new `test_recovery_reconcile.py`: typed reconciliation, reopen and race cases. Closes A2.
3. Run focused and existing recovery contracts via isolated pytest. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last; inspect command exit statuses.

## Acceptance behaviours
A1. Exact snapshots compare successfully; changed attempt, intent, registration, drain, session, claim eligibility, hold, release, successor or deadline cannot validate stale observations, and capture wins without changing existing authorization atomicity.
A2. After database reopen, reconciliation distinguishes exact live registration, confirmed gone processes, unknown identity/group observations and captured execution; registration advancement is accepted only with matching durable identity/revision, racing changes refuse, custody/claim failures are explained, and every path preserves execution, ownership, allowance and artifacts without launching work.
