# Header
Task: tl-8bh9.14.153.1.1
Base: cd64b25ec06d8255e15670a51b0aee06d3889bc9
Depth: medium; two behaviours.
Owner decisions: settled. Dependencies: none.
Evidence budget: 12 model calls.
Size: 7 changed files; 2 independent behaviours; 40 implement model calls.

## Outcome and non-goals
Replace the tail-only initial projection for ended agent attempts with a complete retained snapshot, in both task detail and the cursorless feed endpoint. Reuse the activity codec, logical-event collapse and dashboard projection. Keep incremental following compatible with existing consumers. Browser folding, scrolling, row-limit interactions, check feeds and retention policy are outside this backend change.

## Settled decisions
- The existing 8 MiB events retention cap is the completeness boundary; discarded or incomplete records cannot be recovered.
- Ended means the existing predicate: the result is collected or the attempt no longer holds its reservation. Success and failure use the same reader.
- A cursorless ended feed and its task-detail feed use the same complete reader; task detail retains its synthetic step event.
- Cursor-bearing requests retain existing bounded follow and stale-cursor reset semantics, including for ended attempts. Requesting a fresh snapshot exposes the complete retained history.
- Logical events keep first-occurrence order and the latest retained record per ID; resumed runs retain their producer-scoped IDs.
- Existing projection of unfinished commands/tools, availability and duration remains authoritative.

## Open decisions
- None.

## Change map
- `src/taskloop/activity_file.py`: add `complete`, reusing `_lines`, `_collapse`, `_cursor` and `ActivityPage`.
- `src/taskloop/evidence_files.py`: add `EvidenceFiles.activity_complete` at `events_path`, passing the retention bound.
- `src/taskloop/dash_task.py`: change `_agent`/`build_feed` initial selection; consult callers `_history`, `history`, `build_task` and projection `_page`/`feed_event`.
- `tests/steps/test_activity_file.py`: extend public `EvidenceFiles`/`CommandSink` coverage for completeness and limits.
- `tests/steps/test_dash_read.py`: extend `build_task`/`build_feed` coverage using `reads_of` and lifecycle fixtures.
- `src/taskloop/command_sink.py`: consult producers `CommandSink._record`/`end` and scoped IDs.
- `src/taskloop/dash_model.py`: consult unchanged `FeedEvent`, `FeedPage`, `AttemptDetail` fields.
- `src/taskloop/dash_composition.py`: consult callers `_ports.task`/`_ports.feed`; preserve wiring.
- `src/taskloop/dash_server.py`: consult callers `_feed`/`_json`; preserve validation and serialization.
- `src/taskloop/dash/static/drawer.js`: consult consumer `follow`; preserve cursor semantics.
- `src/taskloop/dash/static/lines.js`: consult consumers `lines`/`setNote`/`apply`; defer browser changes.
- `src/taskloop/dash/static/ui.js`: consult unchanged `FEED_LIMIT`.
- `tests/steps/conftest.py`: consult fixtures `registered`/`checking`.
- `tests/cli/test_dash_server.py`: consult existing feed endpoint assertions.
- `docs/design/tl-8bh9.14.153.1.1/plan.md`: new plan.
- `docs/design/tl-8bh9.14.153.1.1/plan-metadata.json`: new preparation manifest.

## Read list
- `src/taskloop/activity_file.py:14-56` — page shape, decoding, collapsing and byte reads.
- `src/taskloop/activity_file.py:113-154` — bounded tail and follow contracts to preserve.
- `src/taskloop/evidence_files.py:12-32` — reader integration and retention constants.
- `src/taskloop/evidence_files.py:42-64` — append truncation boundary.
- `src/taskloop/evidence_files.py:298-333` — event path, retained writer and reader methods.
- `src/taskloop/command_sink.py:24-73` — producer IDs, append records and completion.
- `src/taskloop/dash_task.py:59-104` — initial/follow endpoint selection and projection.
- `src/taskloop/dash_task.py:123-140` — embedded feed and existing ended predicate.
- `src/taskloop/dash_task.py:244-271` — history callers of `_agent`.
- `src/taskloop/dash_task.py:294-313` — task-detail caller of history.
- `src/taskloop/dash_model.py:128-188` — feed and attempt response fields.
- `src/taskloop/dash_composition.py:39-53` — task-detail composition caller.
- `src/taskloop/dash_composition.py:62-75` — feed composition caller and ports.
- `src/taskloop/dash_server.py:170-201` — serialization and feed cursor validation.
- `src/taskloop/dash/static/drawer.js:102-125` — running-only incremental consumer.
- `src/taskloop/dash/static/lines.js:23-45` — initial rendering and note owned by the interactions task.
- `src/taskloop/dash/static/lines.js:110-127` — incremental replacement and trimming.
- `src/taskloop/dash/static/ui.js:38-38` — browser feed limit.
- `tests/steps/test_activity_file.py:17-97` — sink helper and bounded reader assertions.
- `tests/steps/test_activity_file.py:116-155` — malformed records, retention and resumed IDs.
- `tests/steps/test_dash_read.py:32-79` — tracker/ports helpers and collected-result setup.
- `tests/steps/test_dash_read.py:310-332` — task-detail and incremental feed integration.
- `tests/steps/test_dash_read.py:380-395` — ended unfinished projection and follow compatibility.
- `tests/steps/conftest.py:106-142` — live and released attempt fixtures.
- `tests/cli/test_dash_server.py:359-367` — unchanged HTTP feed contract.

## Contract
Intent: `complete(path: Path, cap: int) -> ActivityPage` reads from byte zero; `EvidenceFiles.activity_complete(key: AttemptKey) -> ActivityPage` supplies the retention cap plus marker allowance. Reads create no artifacts or lifecycle changes.

Effect: open once, capture identity/size, read through that snapshot within the cap. Decode whole newline-terminated records, skipping malformed records and the marker; retain valid records larger than `READ_CAP`. Collapse across the full snapshot, including widely separated starts/completions. Do not loop over `follow`: it can skip oversized records.

Result: all logical events, cursor after the last whole line, `available=True`, `replaced=False`; unreadable/missing files return the existing unavailable result. `_page`/`feed_event` retain timestamp and unfinished projection.

Initial ended reads select `activity_complete`; running reads select `activity_tail(..., FEED_LINES)`. Cursor requests select `activity_after(..., FOLLOW_LINES)`. Preserve live `READ_CAP`, the 20-event initial tail and bounded follow pages. No schema or response-field changes.

## Work packages
1. `activity_file.py`, `evidence_files.py`, `test_activity_file.py`: implement complete reads; cover long histories/records, separated updates, resumed IDs and damaged/missing evidence. Closes A1's reader contract; protects A2's limits.
2. `dash_task.py`, `test_dash_read.py`: integrate both initial paths; cover collected/released attempts, unfinished projection, running-to-ended transition and cursor compatibility. Closes A1/A2; keep additions within file caps.
3. After `just install`, run each focused file with `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`. Last, run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each; verify exit results.

## Acceptance behaviours
A1: For an ended agent attempt, task detail and a cursorless feed request expose every decodable retained logical event in order, including records beyond the live window and long messages; duplicate IDs resolve to their latest retained record, and unfinished actions remain visibly unfinished. Missing or malformed evidence keeps its existing display-only treatment.
A2: A running attempt retains the 20-event initial tail and `READ_CAP` byte bounds; cursor requests preserve bounded deltas and replacement behaviour. Once the attempt ends, fresh initial reads expose its complete retained history without changing cursor, availability or duration fields.
