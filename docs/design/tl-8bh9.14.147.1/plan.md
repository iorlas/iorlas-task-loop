# Header
Task: tl-8bh9.14.147.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; three owning modules
Missing decision: none. Explicit unlanded dependency: none.
Evidence budget: 12 model calls.
Size: 9 files incl. tests/artifacts; 3 behaviours; ~60 implement calls.

## Outcome and non-goals
Extend existing agent feeds and check Result tails with followable check output identified by block/name. Log capture and task-wide checks numbering already exist. Exclude static assets, UI navigation, producer/schema changes, process actions and shelf changes.

## Settled decisions
- Use `/api/tasks/<task>/attempts/checks/<n>/feed` with `build_body` numbering.
- Follow only the latest block, matching Result; reset when it changes.
- Reuse `FeedPage` and `check` events; add optional block identity.
- Logs supply display text; typed store results supply outcomes.
- Keep agent cursors; use a separate URL-safe check cursor codec.
- Delegate behind `EvidenceFiles` to keep its source within the file cap.
- Run new `tests/dash` Python files explicitly; the standard gate excludes this directory.

## Open decisions
- None.

## Change map
- `src/taskloop/check_feed.py` (new): bounded check-log reader and pydantic page/cursor models; called only through new `EvidenceFiles` methods.
- `src/taskloop/evidence_files.py`: `EvidenceFiles` delegates check feed reads through key-derived `check_path`; preserve `check_tail`, `check_output`, `open_check_log`.
- `src/taskloop/dash_model.py`: `FeedEvent` adds optional `block`; clarify `FeedPage` covers checks as well as agents.
- `src/taskloop/dash_task.py`: `build_feed` resolves checks via `_chain`; consult `_checks`, `_checks_body`, `_check_line`, `build_body` for Result identity.
- `src/taskloop/dash_server.py`: `_feed` validates check cursors separately from agent `AFTER`, preserving `FEED`, `_task_api`, `respond` and `DashPorts.feed` wiring.
- `tests/dash/test_check_feed.py` (new): reader/projection cases through `EvidenceFiles`, `TaskPorts`, `build_feed`.
- `tests/dash/test_check_feed_endpoint.py` (new): exercise `respond` with typed `DashPorts` fakes, including serialized check events and invalid queries.
- `docs/design/tl-8bh9.14.147.1/plan.md`: implementation and validation contract.
- `docs/design/tl-8bh9.14.147.1/plan-metadata.json`: consulted paths and preparation commit.
- `src/taskloop/dash_composition.py` (consult): nested `feed` calls `build_feed`; retain wiring.
- `src/taskloop/checks.py` (consult): `CheckSink.log`, `BlockRunner._check`, `_started` produce logs; retain writes.
- `src/taskloop/check_store.py` (consult): `of_attempt`, `results`, `latest_results` supply identity/order/state.
- `src/taskloop/dash/static/api.js` (consult): `apiSource().feed` calls URL; retain cursor-safe transport.
- `src/taskloop/dash/static/lines.js` (consult): `fill` consumes check events; retain asset.
- `src/taskloop/activity_file.py` (consult): `tail`, `follow` supply agent semantics; retain decoder.
- `tests/steps/test_dash_read.py` (consult): `build_feed` callers, Result and numbering regressions.
- `tests/cli/test_dash_server.py` (consult): `Ports.feed` and endpoint regressions.
- `tests/steps/test_command_evidence.py` (consult): `activity_tail` regression caller.

## Read list
- `src/taskloop/evidence_files.py:24-101` — caps, root confinement and reader owner.
- `src/taskloop/evidence_files.py:154-173` — check paths and writer integration.
- `src/taskloop/evidence_files.py:259-289` — Result output readers and activity delegation.
- `src/taskloop/dash_task.py:51-115` — ports, agent projection and feed entry point.
- `src/taskloop/dash_task.py:154-217` — checks summary/body, chain numbering and Result identity.
- `src/taskloop/dash_task.py:236-280` — history and body lookup callers.
- `src/taskloop/dash_model.py:128-184` — event/page/detail contracts.
- `src/taskloop/dash_server.py:32-51` — feed callable boundary.
- `src/taskloop/dash_server.py:161-222` — JSON serialization, cursor query and route dispatch.
- `src/taskloop/dash_composition.py:55-75` — feed composition caller.
- `src/taskloop/check_store.py:67-121` — check/result identity and lifecycle fields.
- `src/taskloop/check_store.py:205-216` — latest block and position ordering.
- `src/taskloop/check_store.py:310-324` — public reads used by projection.
- `src/taskloop/checks.py:84-105` — log producer through evidence owner.
- `src/taskloop/checks.py:149-214` — log frame writes and merged output callback.
- `src/taskloop/activity_file.py:1-31` — existing display page semantics.
- `src/taskloop/activity_file.py:113-154` — tail/follow reset and bounded reads.
- `src/taskloop/dash/static/api.js:13-25` — existing HTTP feed consumer.
- `src/taskloop/dash/static/lines.js:65-104` — existing check-event presentation.
- `tests/steps/test_dash_read.py:1-64` — typed read fixtures and helpers to consult.
- `tests/steps/test_dash_read.py:303-334` — checks history and agent feed callers.
- `tests/steps/test_dash_read.py:472-522` — Result tails and restart numbering regressions.
- `tests/cli/test_dash_server.py:32-68` — server ports and fake feed caller.
- `tests/cli/test_dash_server.py:359-369` — current HTTP feed regressions.
- `tests/steps/test_command_evidence.py:1-46` — agent evidence caller compatibility.

## Contract
Intent: resolve a numbered checks attempt through `_chain`; unknown task/attempt returns not found. Read its current block's ordered `ResultRow` entries, using stored log identities.

Effect: `EvidenceFiles` resolves paths and invokes the reader without creating files or rows. Each request scans at most 256 KiB total and returns at most 20 events. Initial reads take latest output in check-position/byte order. Continuations retain per-file offsets and return unconsumed lines in that order, without dropping lines at the event limit. An oversized line emits a bounded fragment and advances. Hold a trailing partial line until completed or its check ends. Replace invalid UTF-8.

Result: pydantic reader models carry records (block, position, name, byte offset, text), cursor and availability/reset facts. The URL-safe cursor codec validates bounded attempt/block identity, per-log identity/offset and last emitted lifecycle state. Malformed cursors yield 400. Another attempt/block, replaced file or offset beyond EOF resets to a bounded tail with `replaced=true`. Missing/unreadable evidence sets `available=false`; a file appearing later can be followed from its start.

Projection: lines become `FeedEvent` values of type `check`, with block/name, stable block/position/offset id, text and stored check start time. Existing states and `passed` derive from typed conclusions and attempt lifecycle. Emit an identifiable summary on lifecycle change even without appended output; cursor state prevents duplicates. Result tails and agent numeric-pair cursors retain their behaviour.

## Work packages
1. `check_feed.py`, `evidence_files.py`, new reader tests: A1.
2. `dash_model.py`, `dash_task.py`, projection tests: A2.
3. `dash_server.py`, new endpoint tests: A3. Run `just install`, then `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40` for each new test file. Last, once each: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`.

## Acceptance behaviours
A1. Read-only tails/follows are bounded and duplicate-free, handle partial/oversized/invalid-UTF-8 lines, report unavailable evidence and reset on replacement, truncation or block change.
A2. Numbering selects correct logs across implement attempts/restarts; events identify Result checks and expose live/final output and typed lifecycle changes; Result and agent feeds remain valid.
A3. HTTP returns typed pages and accepts continuations; malformed queries yield 400, unknown attempts 404, store failures 503; agent queries and static files remain valid.
