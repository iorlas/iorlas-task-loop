# Header
Task: tl-8bh9.14.167.3.1
Base: 203c7244352988d08a908a176567d166f78bf001
Depth: medium; 3 behaviours
Owner decision missing: no. Unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 10 changed files, 3 behaviours (A1–A3), ~45 implement model calls.

## Outcome and non-goals
Provide durable elapsed-time evidence for ordinary agent execution and native continuation. Save elapsed time and the latest command offset for later quiet-time projections; seal the final sample.
Exclude dashboard/browser changes, check durations, admission/preparation timing and merge-resolution timing.

## Settled decisions
Samples describe execution within an attempt; session lifetime and turn counts remain separate.
Monotonic runtime enforcement and clock-jump recording are delivered; reuse their injection and observation boundaries.
Dashboard readers still use wall timestamps; their replacement belongs to the next split task.
Use an owned display artifact, separate from factory.db and activity logs; no schema upgrade.
Bind ordinary evidence to AttemptKey and continuation evidence to its recovery generation/token directory.
Preserve saved values across restart without counting downtime or joining unrelated monotonic origins.

## Open decisions
- None.

## Change map
- `src/taskloop/duration_evidence.py` (new): sample model and observer for `Attempts._call`, `NativeContinuation._run` and `CommandSink`.
- `src/taskloop/duration_file.py` (new): bounded reader and atomic snapshot/seal writer behind `EvidenceFiles`.
- `src/taskloop/evidence_files.py`: duration facade using `directory(key, execution)`.
- `src/taskloop/command_sink.py`: optional duration observer; record command offsets independently of activity writes.
- `src/taskloop/attempt.py`: `Attempts._call` wires observations and seals in finally before cleanup.
- `src/taskloop/recovery/native.py`: `NativeContinuation._run` wires generation-bound evidence and final sealing.
- `tests/steps/test_duration_evidence.py` (new): persistence, validation, sealing and write-failure contracts.
- `tests/steps/test_attempt_runtime.py`: injected clocks, eventless completion and failure isolation.
- `tests/steps/test_native_continuation.py`: generation isolation and evidence failures.
- `docs/design/tl-8bh9.14.167.3.1/plan.md`: scope and acceptance.
- Consult `composition._run` and `merge.resolve.Resolution.__call__`: retain forwarding/defaults. Internal callers: `Attempts._run` → `_call`; `NativeContinuation.__call__` → `_run`.
- Consult `CommandSink` callers in `test_activity_file`, `test_last_command`, `test_check_status`, `test_dash_read`; `test_last_command` also constructs `WatchedHooks`, and `test_clock_jumps` calls the retained evidence writer.

## Read list
- `src/taskloop/attempt.py:257-300` — ordinary execution caller, hooks and finalization.
- `src/taskloop/attempt.py:159-210` — existing runtime clock and dispatch boundary.
- `src/taskloop/command_sink.py:1-63` — every observation boundary and activity-failure handling.
- `src/taskloop/evidence_files.py:68-116` — artifact ownership and recovery directory identity.
- `src/taskloop/evidence_files.py:255-321` — neighboring evidence APIs and capture separation.
- `src/taskloop/recovery/native.py:25-82` — continuation producer, registration and return paths.
- `src/taskloop/recovery/execution_models.py:37-44` — existing callback identity.
- `src/taskloop/composition.py:89-91` — live-sink forwarding to the harness.
- `src/taskloop/merge/resolve.py:21-75` — additional sink producer and separate merge identities.
- `src/taskloop/clock_jumps.py:35-54` — independent best-effort observer.
- `docs/shelf-digest.json:1-1` — supplied shelf lifecycle and monotonic-time facts.
- `tests/steps/test_attempt.py:65-132` — semantic execution fixtures and injected clocks.
- `tests/steps/test_attempt_runtime.py:144-216` — live boundaries, unavailable artifacts and eventless exceptions.
- `tests/steps/test_native_continuation.py:25-129` — continuation fake and captured-result contracts.
- `tests/steps/test_activity_file.py:17-36` — direct sink construction.
- `tests/steps/test_last_command.py:20-40` — command-sink fixture.
- `tests/steps/test_last_command.py:210-229` — hooks/runner forwarding contract.
- `tests/steps/test_check_status.py:80-100` — direct sink construction for checks status.
- `tests/steps/test_dash_read.py:250-337` — direct sink callers for dashboard activity.
- `tests/steps/test_clock_jumps.py:1-54` — existing clock-evidence writer contract.
- `src/taskloop/dash_board.py:96-110` — future elapsed/quiet consumer boundary.
- `src/taskloop/dash_task.py:97-111` — future attempt-detail consumer boundary.

## Contract
Intent: `DurationSample` is a frozen pydantic model: execution identity, finite nonnegative elapsed seconds, optional latest-command elapsed offset, ordered sample number and an active/sealed enum. Reject extra fields, wrong identity, nonfinite/negative values, decreasing samples and offsets beyond elapsed time. No command means an absent offset.
Effect: inject monotonic clock and writer into the observer. Establish its origin immediately before harness execution. Observe start/feed/poll/end and final return/exception; only command-start events update the command offset. Invalid clock observations invalidate evidence for that execution. Contain failures during construction, observation and finalization.
Effect: the file codec atomically replaces bounded complete active snapshots in the identity-derived directory. A seal cannot be replaced by later samples; identical sealing is idempotent and conflicting sealing fails. Read without creating files. Failed/interrupted writes leave a previous complete snapshot or unavailable evidence. Invalid evidence returns unavailable, never partial values.
Result: reopening artifacts preserves stored values without extrapolating downtime. An abrupt stop may leave an active sample; it cannot become a final duration merely because execution ended. Keep ordinary execution and each continuation distinct; aggregation is deferred.
Boundary: evidence changes no runtime allowance, worker registration, answer capture, task state or result. Duration and clock-jump observers fail independently. Preserve harness results and cleanup, including exceptions with no callbacks.

## Work packages
1. Add both duration modules, `EvidenceFiles` facade and new tests: close A1 and storage portions of A2/A3 through reopen, malformed-input and interrupted-write scenarios.
2. Wire `CommandSink`, `Attempts._call`, `NativeContinuation._run`; extend their two test files. Close A2/A3 through eventless exceptions and recovery-generation isolation.
3. Review listed callers. After the final edit, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each with pipeline failure detection. Validate A1–A3; no live tests.

## Acceptance behaviours
A1: Reopening artifacts after independent wall-clock jumps returns the persisted finite monotonic elapsed and command-offset samples; missing, oversized, malformed or identity-mismatched evidence returns unavailable without filesystem mutation.
A2: Success and exception boundaries seal the final sample even without activity callbacks; later observations and conflicting writes cannot change it, and a continuation uses separate evidence without extending an earlier seal or counting restart downtime.
A3: Invalid or regressing clock observations and read/write failures leave execution results, registration, timeouts, answer capture and cleanup unchanged; lost activity or clock-jump evidence does not prevent independent duration recording.
