# Header
Task: tl-8bh9.14.167.3.3.2
Base: 9d97ec42e5b4d1fd1c2f424f062c49ba89396138
Depth: medium; terminal and unknown rendering.
Decisions: settled; part 1 landed.
Evidence budget: 12 model calls.
Size: 9 changed files, 2 independent behaviours, 55 implement model calls.

## Outcome and non-goals
Cards, drawer headers and rail rows show measured agent elapsed time or explicit neutral unknown wording.
Exclude waiting labels, approximate gaps, checks timing, verification placeholders, command durations and scheduling. No server, storage or schema changes.

## Settled decisions
- `Duration` supplies execution identity, sample number, elapsed milliseconds, nullable quiet milliseconds and `frozen`; `null` means unavailable.
- Retain `receiveDuration`'s monotonic live anchors, exact final frozen values and rejection of later receipts for frozen executions; retain quiet thresholds.
- Agent elapsed values never fall back to started/ended timestamps. Timestamp labels may still describe when an event happened.
- Use “Unknown duration” and “Last activity unknown” with neutral styling. Zero remains a known duration; an unavailable quiet value carries no warning dot or card severity.
- Successful null responses mean unavailable evidence, including after known values. Retain failed-request handling.
- Frozen elapsed evidence is usable even without start/end timestamps. Frozen samples have no active quiet indicator.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/ui.js`: `elapsedSpan`, `quietSpan`, `tick`, `tickQuiet` handle null inputs and clear severity; retain `fmtDur`/`since` for other domains.
- `src/taskloop/dash/static/rail.js`: `lasted`, `row` use agent projections or unknown; consult `gapBetween`/`gapWords`.
- `src/taskloop/dash/static/app.js`: `fillCard` handles null/frozen evidence without agent timestamp fallback; retain snapshot/stream receipt integration.
- `src/taskloop/dash/static/drawer.js`: `openDrawer`, `follow`, `pane`, `onTaskMoved` propagate availability and redraw changed timing nodes.
- `src/taskloop/dash/static/lines.js`: `touchQuiet` clears unavailable quiet presentation; preserve command formatting.
- `tests/dash/duration.test.js`: extend terminal and unknown helper contracts.
- `tests/dash/rail.test.js`: extend `liveDurations` and rail/header assertions; revise null-feed expectations.
- `tests/dash/owner-attention.test.js`: extend `liveDurations` for null/frozen receipts and resyncs.
- `src/taskloop/dash/static/duration.js`: consult `receiveDuration`, `elapsedDuration`, `quietDuration`; retain measurement rules.
- `src/taskloop/dash_duration.py`: consult `Duration`, `project`, `read` producers.
- `src/taskloop/dash_board.py`: consult `duration_of` producer.
- `src/taskloop/dash_task.py`: consult `_agent`, `build_feed` producers.
- `src/taskloop/dash_model.py`: consult `Card`, `AttemptDetail`, `FeedPage` boundaries.
- `src/taskloop/dash/static/result.js`: consult independent check-duration formatting.
- `tests/cli/test_dash_server.py`: consult HTTP/stream projection contracts.
- `docs/design/tl-8bh9.14.167.3.3.2/plan.md`: new implementation plan.

## Read list
- `src/taskloop/dash/static/duration.js:1-40` — receipt ordering, final values and nullable reads.
- `src/taskloop/dash/static/ui.js:89-107` — shared formatting and timestamp labels.
- `src/taskloop/dash/static/ui.js:125-164` — elapsed and quiet presentation.
- `src/taskloop/dash/static/rail.js:13-39` — elapsed fallback and separate gap calculations.
- `src/taskloop/dash/static/rail.js:118-137` — row duration caller.
- `src/taskloop/dash/static/app.js:140-186` — card timing and quiet indicators.
- `src/taskloop/dash/static/app.js:280-346` — snapshot, stream and tick integration.
- `src/taskloop/dash/static/drawer.js:57-122` — detail and feed receipt boundaries.
- `src/taskloop/dash/static/drawer.js:325-345` — selected attempt header.
- `src/taskloop/dash/static/drawer.js:361-390` — same-signature updates and detail refresh.
- `src/taskloop/dash/static/lines.js:44-104` — quiet caller and independent command formatting.
- `src/taskloop/dash/static/result.js:60-70` — independent check-duration caller.
- `src/taskloop/dash_duration.py:12-44` — projection shape, terminal availability and freezing.
- `src/taskloop/dash_board.py:132-135` — agent-only card projection producer.
- `src/taskloop/dash_task.py:79-117` — feed and attempt projection producers.
- `src/taskloop/dash_model.py:29-47` — nullable card duration.
- `src/taskloop/dash_model.py:147-186` — nullable feed and attempt duration.
- `tests/dash/duration.test.js:1-87` — Node contracts and DOM doubles.
- `tests/dash/rail.test.js:90-104` — existing missing-duration assertions.
- `tests/dash/rail.test.js:394-408` — agent/check quiet distinction.
- `tests/dash/rail.test.js:458-524` — drawer receipts and fixture registration.
- `tests/dash/owner-attention.test.js:1-40` — board fixture, clocks and receipts.
- `tests/dash/owner-attention.test.js:190-224` — board duration assertions.
- `tests/cli/test_dash_server.py:220-235` — HTTP and stream projection contract.

## Contract
Intent: show the current agent measurement or its absence.
Effect: helpers accept `Duration|null` with JSDoc. Null yields static unknown text without a cached execution binding; unknown quiet clears warning classes, dots and `data-quiet-level`. Frozen samples suppress active quiet indicators.
Result: live values advance through the existing owner; frozen elapsed equals `elapsed_ms`, even below prior extrapolation. Ticks and repeated receipts leave it fixed. Reloads use server evidence without browser persistence.

Intent: apply successful detail, board and feed responses consistently.
Effect: keep availability on task/attempt objects; remove null-preserving `??` fallback. Rebuild timing nodes when availability, execution or freezing changes, including same-signature updates. Preserve selection, disclosure, tab and scroll; update only matching attempts.
Result: null cannot reuse cached measurements. Valid evidence restores rendering through existing receipt rules. No new wire fields, states, stored fields or external effects.

## Work packages
1. Terminal presentation: `rail.js`, `drawer.js`, `app.js`, shared helpers and three test files; closes A1. Cover smaller final values, success/failure, absent timestamps, ticks, reordered receipts, redraw and fresh-page reload.
2. Unknown presentation: `ui.js`, `app.js`, `drawer.js`, `lines.js`, `rail.js` and three test files; closes A2. Cover initial null, known/null transitions and severity clearing via board resync/stream, detail and feed. Run existing offline HTML fixtures and `node --test tests/dash/duration.test.js`. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A1. A terminal agent attempt with final evidence shows the exact measured elapsed duration consistently across cards where timing applies, drawer header and rail, regardless of wall-clock changes, browser ticks, redraws or refreshes, and has no active quiet warning.
A2. An unavailable agent duration displays explicit unknown wording without timestamp substitution or cached values; unavailable quiet time has neutral wording and no severity, including after a warning, while valid evidence restores normal timing and threshold behaviour.
