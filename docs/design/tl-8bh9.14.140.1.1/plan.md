# Header
Task: tl-8bh9.14.140.1.1; base: ca861999263bd031d4f59007c60cdcf726a50fea
Depth: medium; three operation producers.
Owner decision: none; unlanded dependency: none.
Evidence budget: 12 model calls.
Size: ~18 changed files; 3 independent behaviours; ~50 implement calls.

## Outcome and non-goals
Add typed timing evidence at actual commit, push and checks-entry start boundaries. Execution-duration snapshots already exist; operation timing is missing. Retain retries separately and suppress cached results. Dashboard work, check execution duration and schema changes are excluded.

## Settled decisions
- Capture precedes the separate display part; no dependency blocks capture.
- Operation files belong under the existing attempt artifact directory, separate from control state and execution duration.
- Inject monotonic elapsed time and wall time for ordering.
- Only actual effect boundaries create records.
- Existing registered-start and semantic Git ports suffice; no shelf change.

## Open decisions
- None.

## Change map
- `src/taskloop/operation_evidence.py` (new): typed record, enums and isolated observer for all three producers.
- `src/taskloop/operation_file.py` (new): bounded reads and atomic snapshots behind `EvidenceFiles`.
- `src/taskloop/evidence_files.py`: operation reader/observer methods using `directory`.
- `src/taskloop/factory_commit.py`: `settle`, `_commit`, `_reviewed` observe actual stage/record calls.
- `src/taskloop/verifier.py`: `_settle` binds the attempt to its sole `settle` call.
- `src/taskloop/publish.py`: `BranchPublish._pushed` measures push; preserve `_read` caching and `_record` authority.
- `src/taskloop/launch.py`: `Launcher._start` measures checks-only registered start, after `_target` cache checks.
- `src/taskloop/composition.py`: inject artifacts/clocks in `open_verifier`, `open_publisher`, `open_checks_launcher`.
- `src/taskloop/attempt_entry.py`: direct `Verifier` construction and `_branch` publisher receive evidence support.
- `src/taskloop/cli_composition.py`: thread artifacts through `_starting`, `open_next`, `open_verify`, `open_publish`; inspection verifiers remain read-only. Trim this touched module to its file cap.
- `src/taskloop/cli_step.py`: `_verify`, `_publish` pass the artifact root.
- `tests/steps/test_operation_evidence.py` (new): persistence, validation, interruption and observation failures via `EvidenceFiles`.
- `tests/steps/test_factory_operation_timing.py` (new): producer integration with semantic Git/start fakes; avoid expanding oversized `test_verifier.py`.
- `tests/steps/test_commit_paths.py`: `settle` real-write versus adopted/keep coverage.
- `tests/steps/test_publish.py`: `publisher` injection and scripted push retry/cache coverage.
- `tests/steps/test_launch.py`: `FakeStart` failure/retry/cache coverage.
- `docs/design/tl-8bh9.14.140.1.1/plan.md`: scope and acceptance.
- `docs/design/tl-8bh9.14.140.1.1/plan-metadata.json`: preparation evidence.

## Read list
- `src/taskloop/factory_commit.py:92-154` — settle dispatch, saved-work record and stage/record boundaries.
- `src/taskloop/verifier.py:67-118` — injection and stored-verdict suppression.
- `src/taskloop/verifier.py:170-194` — sole commit producer caller and end-commit recording.
- `src/taskloop/publish.py:103-209` — cached publication, push and authoritative record.
- `src/taskloop/launch.py:137-268` — target caching, dispatch authorization and registered-start outcomes.
- `src/taskloop/evidence_files.py:78-145` — artifact boundary, directory identity and existing duration integration.
- `src/taskloop/duration_evidence.py:13-90` — validation and evidence-failure isolation already delivered.
- `src/taskloop/duration_file.py:16-105` — bounded reads, atomic publication and immutable seal pattern.
- `src/taskloop/composition.py:198-235` — verifier, publisher and launch composition roots.
- `src/taskloop/attempt_entry.py:222-241` — direct verification construction after capture.
- `src/taskloop/attempt_entry.py:303-316` — direct publication construction after lock release.
- `src/taskloop/cli_composition.py:107-125` — read-only inspection construction.
- `src/taskloop/cli_composition.py:142-194` — repeat/start and round callers of production factories.
- `src/taskloop/cli_composition.py:319-341` — manual verification/publication callers.
- `src/taskloop/cli_step.py:268-282` — CLI callers needing artifact-root propagation.
- `src/taskloop/operations.py:416-497` — checks cached-result, admission and relaunch routing, consulted without adding a second producer.
- `src/taskloop/check_admit.py:1-15` — admission boundary versus checks-entry start.
- `src/taskloop/check_entry.py:1-18` — checks execution begins after the measured launch boundary.
- `tests/steps/test_duration_evidence.py:1-72` — focused persistence and monotonic-clock test patterns.
- `tests/steps/test_commit_paths.py:1-62` — semantic slot and answer fixtures.
- `tests/steps/test_publish.py:1-95` — scripted semantic push fake and transaction guard.
- `tests/steps/test_launch.py:1-70` — registered-start fake and checks launcher integration.
- `tests/steps/test_verifier.py:1-50` — integration imports for verifier regression coverage.
- `tests/steps/test_check_operations.py:1-70` — shared checks-start consumer and semantic launcher contract.

## Contract
`OperationKind`: commit, publish, checks-start. `OperationState`: active, completed, failed, uncertain. A strict frozen pydantic record carries operation identity, kind, attempt identity, finite wall start timestamp, finite nonnegative elapsed seconds and state. Completion describes the measured effect, independently of subsequent database recording.

Intent: allocate a fresh identity and write active evidence immediately before each effect. Commit spans staging through recording and intervening safety checks; saved-work review spans its record. Publish spans push. Checks-start spans registered creation through its launch result, excluding the checks block. Every real retry gets another identity.

Effect: injected clocks and the artifact writer run outside write transactions. Isolated operation directories contain atomic active/final snapshots; final evidence is immutable. Reuse existing file primitives where ownership stays clear.

Result: distinguish successful, failed and uncertain effects without changing returned results or exception handling. Interrupted evidence remains incomplete; reopening never counts downtime. Reject invalid numbers/identity, oversized/corrupt records and conflicting seals. Allocation, clock and write failures disable observation alone; the effect still runs once. Missing evidence stays missing. Readers create nothing and never drive workflow state.

## Work packages
1. Add the two operation modules, `EvidenceFiles` integration and evidence tests: shared persistence/failure contract for A1-A3.
2. Wire `factory_commit`, `verifier`, `publish`, composition and entry/CLI callers; semantic Git tests close A1-A2.
3. Wire `Launcher`/`open_checks_launcher`; registered-start tests close A3. Use permitted focused pytest runs after installation as needed. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last; both pass.

## Acceptance behaviours
A1. Commits, including saved-work review, retain intervals; keep/adoption/stored-verdict paths emit none. Retries stay separate; evidence failures preserve safety checks and commit/verification outcomes.
A2. Real pushes, including failures and retries after recording failure, retain separate intervals; already-published results emit none. Observation failures preserve publication effects/results.
A3. Real checks-entry starts retain separate intervals with truthful completion/failure/uncertainty/interruption; running/dispatched cache hits emit none. Exclude checks execution; observation failures preserve registration, launch results and retries.
