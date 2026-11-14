# Header
tl-8bh9.14.167.3; base 48bb8b6a19e941e360bc62ae2894300aa6eb4322
Depth: medium; resilient ages, terminal freeze, invalid evidence
Owner decisions: none. Dependencies: landed. Evidence budget: 12 calls.
Size: 22 changed files incl. tests/plan; 3 behaviours; 65 implement calls.

## Outcome and non-goals
Share duration projection across cards and selected attempts. Persist monotonic evidence across dashboard restarts. Runtime accounting, jump recording and timeout notification are delivered. No scheduler, tracker or schema changes. Waiting ages, feed offsets and tool durations are outside scope.

## Settled decisions
- Start elapsed at observed execution start; start quiet at latest recorded activity, or execution start before activity.
- Compare live samples only within a confirmed boot; preserve ages across dashboard restart.
- Persist final differences across reboot; never substitute release time or file mtime.
- Missing evidence means unknown; IO failure affects display only.
- Keep quiet thresholds at two and fifteen minutes; idle polls never reset quiet age.

## Open decisions
- None.

## Change map
- `src/taskloop/duration_evidence.py` (new): validated evidence/projection integrated through `EvidenceFiles` and sinks.
- `src/taskloop/evidence_files.py`: bounded atomic duration snapshot IO in the attempt directory.
- `src/taskloop/command_sink.py`: `started/_record/end` capture start, accepted activity and completion; `poll` preserves activity.
- `src/taskloop/attempt.py`: `Attempts._call` supplies monotonic clock and confirmed boot; distinguishes exceptional exit.
- `src/taskloop/recovery/native.py`: `_run` separates execution identities and retains only comparable earlier samples.
- `src/taskloop/checks.py`: `CheckSink.start/registered/conclude` captures each check's comparable start/end evidence.
- `src/taskloop/validate.py`: `CheckSink` caller wires duration inputs and checks-attempt completion.
- `src/taskloop/dash_model.py`: `Card/AttemptDetail/FeedPage` carry nullable ages and advancing flag.
- `src/taskloop/dash_board.py`: `card_of/build_board` project evidence instead of wall subtraction.
- `src/taskloop/dash_task.py`: `_agent/_checks/build_feed/build_task` share projection for current and historical attempts.
- `src/taskloop/dash_composition.py`: `_ports` wires monotonic reads with `StatusPorts.boot` for board/detail/feed/body constructors.
- `src/taskloop/dash/static/ui.js`: numeric age rendering advances with `performance.now()`; unknown has no severity colour.
- `src/taskloop/dash/static/app.js`: card elapsed/quiet rendering and tick selection consume projections.
- `src/taskloop/dash/static/drawer.js`: `pane` and feed callback replace timing together.
- `src/taskloop/dash/static/lines.js`: `touchQuiet` uses projection, never replayed timestamps.
- `src/taskloop/dash/static/rail.js`: `lasted` renders projected elapsed, including frozen terminal values.
- `tests/steps/test_duration_evidence.py` (new): fake clocks and persistence through `EvidenceFiles`.
- `tests/steps/test_dash_read.py`: card/detail/feed agreement and checks/history fixtures.
- `tests/steps/test_command_evidence.py`: accepted activity, idle polls, completion and failed writes.
- `tests/steps/test_attempt_runtime.py`: duration production preserves execution outcomes.
- `tests/dash/rail.test.js`: browser clocks, thresholds, freeze and unknown rendering.
- `docs/design/tl-8bh9.14.167.3/plan.md`: scope and acceptance.

## Read list
- `src/taskloop/evidence_files.py:205-211` — existing mtime start fallback.
- `src/taskloop/evidence_files.py:255-294` — evidence/activity IO integration.
- `src/taskloop/command_sink.py:23-63` — producer hooks and accepted records.
- `src/taskloop/attempt.py:258-298` — clock inputs and exceptional exits.
- `src/taskloop/recovery/native.py:49-80` — continuation producer/identity.
- `src/taskloop/merge/resolve.py:56-74` — other sink producer; preserve distinct launch keys and optional evidence.
- `src/taskloop/checks.py:82-105` — checks producer and process registration.
- `src/taskloop/validate.py:145-180` — discovered `CheckSink` caller and completion boundary.
- `src/taskloop/attempt_status.py:50-62` — existing boot port.
- `src/taskloop/dash_model.py:27-62` — card payload.
- `src/taskloop/dash_model.py:144-182` — feed/attempt payloads.
- `src/taskloop/dash_board.py:97-170` — card construction and board caller.
- `src/taskloop/dash_task.py:49-110` — agent/feed projection.
- `src/taskloop/dash_task.py:145-170` — checks projection.
- `src/taskloop/dash_task.py:270-295` — detail's card caller.
- `src/taskloop/dash_composition.py:37-64` — dashboard port constructors.
- `src/taskloop/dash/static/ui.js:88-149` — formatters and tick helpers.
- `src/taskloop/dash/static/app.js:170-184` — card consumers; consult tick selector before editing.
- `src/taskloop/dash/static/drawer.js:90-118` — feed callback; consult `pane` before editing.
- `src/taskloop/dash/static/lines.js:47-54` — quiet updates.
- `src/taskloop/dash/static/rail.js:12-17` — `lasted`, also consumed by drawer.
- `tests/steps/test_dash_read.py:1-60` — semantic ports and fixtures.
- `tests/steps/test_command_evidence.py:1-100` — existing sink tests/fixtures.
- `tests/steps/test_attempt_runtime.py:1-110` — clock injection fixtures.
- `tests/dash/rail.test.js:357-372` — quiet thresholds.

## Contract
Intent: a pydantic v2 model binds attempt key, execution generation, boot, finite nonnegative monotonic start/activity samples and optional final elapsed/quiet differences. Checks also bind block/position.

Effect: `EvidenceFiles` owns bounded atomic snapshots. Preserve start; accepted activity advances activity; completion seals differences. Continuations preserve comparable starts without overwriting another execution or reopening terminal evidence. Write loss cannot change execution outcome.

Result: card/detail/feed share nullable `elapsed_ms`, `quiet_ms` and an advancing flag from authoritative state. Live values require boot agreement and ordered samples; terminal values require sealed differences. Unsealed terminal evidence is unknown. Checks require comparable first start/final completion across actual results. Verification has no timing evidence.

Invalid evidence yields null, without wall/log fallback. Feed replay cannot reset quiet. Browser receipt anchors ages to `performance.now()`; new projections replace anchors. Terminal values never tick. Unknown has no quiet severity. Calendar timestamps remain labels.

## Work packages
1. Add evidence model/IO and producer integration in `duration_evidence.py`, `evidence_files.py`, `command_sink.py`, `attempt.py`, `recovery/native.py`, `checks.py`, `validate.py`; test persistence, sealing, invalid data and failures. Closes A1-A3 at the evidence boundary.
2. Wire `dash_model.py`, `dash_board.py`, `dash_task.py`, `dash_composition.py`; prove card/detail/feed, checks and history agreement in `test_dash_read.py`. Closes A1-A3 at the API boundary.
3. Update the five mapped browser modules and `rail.test.js`; verify clock jumps, refresh, unknown and freeze. Closes A1-A3 visibly. Finish implementation with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last; no live tests.

## Acceptance behaviours
A1. Forward/backward host or browser wall jumps leave ages unchanged for unchanged monotonic progress; monotonic progress advances elapsed/quiet, activity resets only quiet, polls do not, and same-boot dashboard/browser restart restores matching card/detail ages.
A2. Success, failure and timeout seal durations once; later polling, reload, wall jumps and reboot retain terminal values. Abrupt loss without final evidence shows unknown.
A3. Missing/corrupt, wrong-identity, unmatched-boot live, unordered, negative, nonfinite or future evidence shows unknown consistently; replay, capped logs and IO failure cannot fabricate ages, reset quiet or alter execution outcomes.
