# Header
Task: tl-8bh9.14.167.3.2; base: 94fba7111249a5d29911b6897b4ad2184317e251
Depth: medium; three behaviours
Decisions: none missing; dependency .167.3.1 landed.
Evidence budget: 12 model calls.
Size: 9 changed files incl. plan; 3 independent behaviours; 45 implement model calls.

## Outcome and non-goals
Expose saved execution elapsed time and command age consistently through board, history and feed. Delivered samples, readers, observers and seals supply measurements. Exclude browser timers/styling, new measurements, schema and lifecycle changes. Harness-reported action durations remain separate.

## Settled decisions
- One pure projection serves all execution-duration fields.
- `EvidenceFiles.duration` owns evidence reads; the recovery store owns execution selection.
- Saved samples define values after reopening; no server interpolation or cross-execution summation.
- Unmeasured checks, verification and delivery have unknown elapsed time.
- Keep dates and harness-reported action durations; remove wall-subtracted check durations.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_duration.py` (new): `Duration`, `project`, execution selection integrate `DurationSample`, recovery reader and `EvidenceFiles.duration`.
- `src/taskloop/dash_model.py`: `Card`, `AttemptDetail`, `FeedPage` gain nullable `Duration`; `CheckLine.duration_ms` becomes nullable for absent measurements.
- `src/taskloop/recovery/state_store.py`: add a narrow typed execution-identity read through the owning store; hide connection/SQL from dashboard projection code.
- `src/taskloop/dash_board.py`: `card_of` accepts the selected projection; `build_board` selects evidence for the displayed execution, including held/released cases; `queued_card` has no duration.
- `src/taskloop/dash_task.py`: `build_task`, `_agent`, `history`/`_history`, `build_feed` and `_page` share selection/projection; standalone feeds consult terminal state; `_took`, `_check_line`, `_checks`, `_checks_body` stop inventing check durations.
- `tests/steps/test_dash_duration.py` (new): projection and public read agreement/reopening/damage tests via `EvidenceFiles`, `BoardPorts`, `TaskPorts`.
- `tests/steps/test_dash_read.py`: adjust check-duration expectations and cover terminal incremental feeds without changing cursor semantics.
- `tests/cli/test_dash_server.py`: assert nullable structured duration survives HTTP/SSE serialization.
- Consult callers `dash_composition._ports` (board/task/body/feed), `dash_server.DashPorts`/serializers; producers `Attempts._call`, `NativeContinuation._run`, `CommandSink._sample`, `EvidenceFiles.observe_duration`; no producer edits.
- Consult `rail.js` and `lines.js` consumers; browser integration belongs to rendering task.

## Read list
- `src/taskloop/duration_evidence.py:12-82` — validated sample, states and observer boundaries.
- `src/taskloop/duration_file.py:17-49` — bounded reader, identity and seal preference.
- `src/taskloop/evidence_files.py:106-141` — generation-specific directory and duration ports.
- `src/taskloop/recovery/models.py:55-76` — durable execution identity.
- `src/taskloop/recovery/state_store.py:1-45` — owning reader and fencing boundaries.
- `src/taskloop/recovery/store.py:88-104` — existing typed snapshot integration.
- `src/taskloop/attempt.py:274-303` — initial observer lifetime and seal.
- `src/taskloop/recovery/native.py:64-89` — continuation observer identity and seal.
- `src/taskloop/command_sink.py:24-82` — command-offset updates and polling samples.
- `src/taskloop/dash_model.py:24-52` — card and board shapes.
- `src/taskloop/dash_model.py:78-85` — check-duration nullability.
- `src/taskloop/dash_model.py:125-196` — feed/page and attempt fields.
- `src/taskloop/dash_board.py:54-170` — selected execution, card callers and board assembly.
- `src/taskloop/dash_task.py:49-111` — live feed and agent detail projection.
- `src/taskloop/dash_task.py:145-175` — check duration and body projection.
- `src/taskloop/dash_task.py:188-290` — history, body and task callers.
- `src/taskloop/dash_composition.py:36-64` — HTTP read closures.
- `src/taskloop/dash_server.py:17-42` — typed HTTP port and serialization imports; locate serializers with a targeted search.
- `src/taskloop/dash/static/rail.js:10-17` — downstream attempt-duration consumer.
- `src/taskloop/dash/static/lines.js:6-18` — downstream wall-derived offsets, outside this task.
- `tests/steps/test_dash_read.py:1-95` — dashboard fixtures and equality checks.
- `tests/steps/test_dash_read.py:140-153` — check-backed board/detail integration.
- `tests/steps/test_duration_evidence.py:17-49` — existing reopening/seal coverage, reuse its public ports.
- `tests/steps/test_duration_evidence.py:70-82` — invalid-reader behaviour already delivered.
- `tests/cli/test_dash_server.py:1-100` — endpoint fixtures; locate serialization assertions before editing.

## Contract
Intent: read evidence for exactly the represented execution. Add a typed recovery-store method hiding its connection/SQL. No recovery intent selects the initial execution; a continuation selects only its own evidence, without initial fallback or summing generations/downtime.

Effect: read-only bounded loading. New immutable pydantic `Duration` carries `execution`, `number`, `elapsed_ms`, nullable `quiet_ms` and `frozen`. Convert finite nonnegative seconds once to integer milliseconds. Quiet age is elapsed minus command offset, or elapsed if no command occurred. No wall subtraction, extrapolation or server accumulation.

Result: `Card.duration`, `AttemptDetail.duration`, `FeedPage.duration` agree for the same execution/sample. `None` means unknown for absent, malformed, mismatched or invalid evidence. Sealed samples freeze before collection; terminal executions require a seal. Existing results determine lifecycle terminality; evidence never controls it. Terminal quiet age is null; terminal feeds mark running actions unfinished as history does. Keep timestamps, cursors, availability and reported action durations. Replace `_took` wall differences with null for unmeasured checks in body/feed. No execution-state writes.

## Work packages
1. Add projection/selector (`dash_duration.py`, `recovery/state_store.py`, `dash_model.py`, focused tests). Close A1-A3 for initial/continuation evidence.
2. Wire cards, history and standalone feeds (`dash_board.py`, `dash_task.py`); make check durations nullable. Close A1-A3 through public reads.
3. Add dashboard/HTTP regressions in the three mapped test files: wall jumps, reopened ports and no writes. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last; preserve exit status with pipefail.

## Acceptance behaviours
A1: For the same saved sample, board card, embedded task card, attempt detail and incremental feed expose equal elapsed/quiet values despite forward/backward wall jumps and reopened readers; continuation evidence cannot be confused with the initial execution.
A2: A sealed terminal execution keeps its elapsed value across later polls and restarts, exposes no advancing quiet age, and treats unfinished feed actions consistently; terminal state without a valid seal yields unknown.
A3: Missing, damaged, identity-mismatched or invalid evidence yields unknown across every read without wall fallback, mutation or failure of unrelated task data; unmeasured checks and verification never acquire fabricated durations.
