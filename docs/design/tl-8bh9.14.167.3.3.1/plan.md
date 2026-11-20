# Header
Task: tl-8bh9.14.167.3.3.1
Base: 7e7ce78fd505cd79de366d0040e8a7cd7dea80d1
Depth: medium; two behaviours: live ages and quiet thresholds.
Decisions: settled. Dependencies: .167.3.2 landed.
Evidence budget: 12 model calls.
Size: 10 changed files, 2 behaviours, 65 implement model calls.

## Outcome and non-goals
Use live agent measurements on cards, drawer headers and rail rows between responses. Terminal and unavailable-duration presentation belong to sibling .167.3.3.2. Check timings, waiting ages, round freshness and historical gaps are outside scope.

## Settled decisions
- Use the existing duration projection on cards, attempt details and feed pages; no server measurement or schema change.
- Use `performance.now()` at receipt and on ticks; never anchor on a DOM redraw.
- Share measurement state across representations of one execution; order samples by `number`.
- Keep quiet presentation limited to running plan/implement agents, hidden below 120 seconds, amber from 120 seconds and red from 900 seconds.
- Feed messages and command display timestamps do not establish quiet age; `quiet_ms` does.
- Keep the existing calendar-time helpers for their other callers.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/duration.js` (new): `receiveDuration`, `elapsedDuration`, `quietDuration`; shared owner called by app/drawer receipts and UI/rail readers.
- `src/taskloop/dash/static/app.js`: `resyncBoard`, `start`, `fillCard`; receive projections, bind live nodes and extend interval ticking.
- `src/taskloop/dash/static/ui.js`: `tick`, `tickQuiet`, `quietSpan`; bind projection-backed elapsed/quiet nodes and retain quiet wording, visibility, dot and card border thresholds.
- `src/taskloop/dash/static/drawer.js`: `openDrawer`, `onTaskMoved`, `follow`, `pane`; receive detail/feed and same-signature card samples; bind header/rail without disrupting selection or scrolling.
- `src/taskloop/dash/static/rail.js`: `lasted`, `row`; bind live values to tickable nodes; preserve terminal/gap paths.
- `src/taskloop/dash/static/lines.js`: `touchQuiet`, `show`; refresh projection-backed quiet nodes, removing timestamp measurement; callers are `show` and drawer `follow`.
- `src/taskloop/dash_server.py`: `PAGES`; serve the new module.
- `tests/dash/owner-attention.test.js`: fake clocks and responses; card measurements and quiet borders.
- `tests/dash/rail.test.js`: `vocabulary`, drawer/follower fixtures and contract loop; migrate quiet fixtures, cover header/rail/feed.
- `src/taskloop/dash_duration.py`: consult `Duration`, `project`; existing producer of execution/sample identity and measurements.
- `src/taskloop/dash_board.py`: consult `card_of`, `duration_of`; agent card producer.
- `src/taskloop/dash_task.py`: consult `_agent`, `build_feed`; detail/feed producers, including empty pages.
- `src/taskloop/dash_model.py`: consult `Card`, `AttemptDetail`, `FeedPage`; nullable projection shape.
- `src/taskloop/dash/static/api.js`: consult `apiSource`; snapshot, detail, feed and stream transport boundaries.
- `tests/cli/test_dash_server.py`: consult static-file contract; existing enumeration verifies module registration.
- `tests/steps/test_dash_duration.py`: consult `projections` and projection assertions; authoritative payload fixtures.
- `docs/design/tl-8bh9.14.167.3.3.1/plan.md`: implementation artifact included in the Size estimate.

## Read list
- `src/taskloop/dash/static/app.js:139-184` — card timing and quiet DOM.
- `src/taskloop/dash/static/app.js:273-340` — snapshot, stream and tick integration.
- `src/taskloop/dash/static/ui.js:102-149` — calendar helpers, timer dispatch and thresholds.
- `src/taskloop/dash/static/drawer.js:25-29` — detail signature omits measurement updates.
- `src/taskloop/dash/static/drawer.js:46-120` — opening, detail receipt and feed follower.
- `src/taskloop/dash/static/drawer.js:316-368` — pane and movement-triggered detail receipt.
- `src/taskloop/dash/static/rail.js:3-17` — imports and elapsed calculation.
- `src/taskloop/dash/static/rail.js:119-139` — live rail row integration.
- `src/taskloop/dash/static/lines.js:47-54` — quiet update owner to replace.
- `src/taskloop/dash/static/lines.js:118-139` — incremental feed caller.
- `src/taskloop/dash/static/api.js:13-35` — receipt transport contracts.
- `src/taskloop/dash_duration.py:12-36` — projection fields and semantics.
- `src/taskloop/dash_model.py:29-47` — card projection.
- `src/taskloop/dash_model.py:147-186` — feed and attempt projection fields.
- `src/taskloop/dash_board.py:99-135` — card producer and agent-only projection.
- `src/taskloop/dash_task.py:79-117` — detail/feed producers.
- `src/taskloop/dash_server.py:24-27` — static module registration.
- `tests/cli/test_dash_server.py:144-147` — shipped-module contract.
- `tests/steps/test_dash_duration.py:20-40` — existing payload assertions.
- `tests/dash/owner-attention.test.js:1-74` — fake network, clocks and stream entry points.
- `tests/dash/owner-attention.html:7-14` — existing board fixture integration.
- `tests/dash/rail.test.js:1-25` — browser imports and attempt fixtures.
- `tests/dash/rail.test.js:357-372` — quiet boundary assertions to migrate.
- `tests/dash/rail.test.js:450-468` — browser contract registration and result reporting.
- `tests/dash/rail.html:7-11` — existing drawer fixture integration.

## Contract
Intent: receive nullable `Duration`. Effect: retain execution, sample number, elapsed/quiet bases and monotonic receipt time in page-local memory. Result: shared live readings without backend writes. Document shapes with JSDoc; no wire or stored fields change.

Intent: read active elapsed. Effect: add nonnegative monotonic time since receipt. Result: no regression for one execution; repeated/older samples cannot restart its clock. Reconcile newer samples with displayed progress; a different execution gets its own base. Honour `frozen` as an input guard; terminal formatting stays with the sibling.

Intent: read quiet age. Effect: advance `quiet_ms` monotonically across duplicate/stale samples. For newer samples compare command offsets (`elapsed_ms - quiet_ms`). Result: new command evidence can reset quiet age; wall jumps and empty pages cannot.

Intent: tick/redraw. Effect: update text, quiet visibility, colour and card border. Result: redraw never establishes receipt; valid live projections never use timestamp subtraction. Preserve nullable/non-agent presentation for the sibling without new fallback calculations. Feed events affect lines/scrolling, not age.

## Work packages
1. Add `duration.js`, register in `dash_server.py`, wire app snapshot/stream and drawer detail/feed receipts. Include same-signature cards and empty feed pages. Closes receipt/reconciliation in A1/A2.
2. Connect `ui.js`, `app.js`, `drawer.js`, `rail.js`, `lines.js` to shared readings and ticking. Closes visible presentation in A1/A2.
3. Extend both browser suites with separate fake wall/monotonic clocks and responses; run both HTML fixtures without live services for A1/A2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, retaining exit status.

## Acceptance behaviours
A1. With a live projection, cards, selected-attempt headers and rail rows gain only the monotonic tick delta while wall time jumps forward/backward; duplicate/older responses and redraws cause no regression or clock restart, and a new execution has its own base.
A2. Quiet age is hidden at 119,999 ms, amber at 120,000 ms and red at 900,000 ms on card and drawer; wall jumps, empty feed pages and stale samples do not change those crossings, while newer command evidence resets age and card severity through the projected measurement.
