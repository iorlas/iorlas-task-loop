# Header
Task: tl-8bh9.14.153.1
Base: 220beb55af526f716b1d5e0d3f2e6e700e126801
Depth: medium; three behaviours
Missing decisions: none. Unlanded dependencies: none.
Evidence: 12 model calls.
Size: 11 changed files (tests/artifacts included), 3 independent behaviours, 80 implement model calls.

## Outcome and non-goals
Complete finished history while preserving live retention and deliberate scrolling. Row rendering and scroll preservation already exist; both initial backend producers still return only 20 actions within a 256 KiB window. Browser changes alone cannot recover omitted events.
Exclude expandable commands, path presentation and URL navigation. Only lines.js and ui.js may change among static files. Retain the event-storage cap.

## Settled decisions
- Supplied discussion has no numbered decisions.
- Existing attempt state selects full history or live retention.
- Extend the evidence reader and producer; preserve drawer interfaces.
- Fold at about eight displayed lines, including wrapping; allow expansion and collapse.
- Jump belongs inside Lines and resumes ordinary following at the bottom.
- Use existing classes or local styles; no stylesheet or HTML-shell edits.

## Open decisions
- None.

## Change map
- `src/taskloop/activity_file.py`: new `read_all(path, cap)` returns `ActivityPage`; decode complete records and use `_collapse` globally.
- `src/taskloop/evidence_files.py`: new `EvidenceFiles.activity_all(key)` delegates with `EVENTS_CAP`.
- `src/taskloop/dash_task.py`: `_agent`/`build_feed` select full ended initial reads; preserve `_page` projection and `_history` caller.
- `src/taskloop/dash/static/ui.js`: `FEED_LIMIT` documents live-only retention; keep 20.
- `src/taskloop/dash/static/lines.js`: `lines`, `setNote`, `fill`, `apply`, `show`, `atBottom`; conditional trimming, folding and jump control.
- `tests/steps/test_activity_file.py`: `EvidenceFiles`/`CommandSink` fixtures cover complete reads and paired records.
- `tests/steps/test_dash_read.py`: `build_task`/`build_feed` fixtures cover live and ended histories.
- `tests/dash/lines.test.js` (new): public Lines exports and drawer/API entry points; browser contracts with fake data.
- `tests/dash/lines.html` (new): fixture integrates new test module and compiled CSS, following rail.html.
- `docs/design/tl-8bh9.14.153.1/plan.md`: implementation contract.
- `docs/design/tl-8bh9.14.153.1/plan-metadata.json`: preparation evidence.
- Consult `src/taskloop/command_sink.py`: `CommandSink.feed`/`_record` produce paired action records.
- Consult `src/taskloop/dash/static/drawer.js`: `follow`, `render`, `pane`, `onTaskMoved` call Lines and refresh detail/scrolling; no edits.
- Consult `src/taskloop/dash/static/api.js`: `apiSource.detail`/`feed` supply drawer data.
- Consult `src/taskloop/dash_composition.py`: `feed` calls `build_feed`.
- Consult `src/taskloop/dash_server.py`: `_feed` routes requests.
- Consult `src/taskloop/dash_model.py`: preserve `FeedPage`/`AttemptDetail` wire fields.
- Consult `tests/dash/rail.test.js`: `vocabulary` calls `lines`/`setNote`.

## Read list
- `src/taskloop/activity_file.py:14-56` — page shape, decoding and replacement order.
- `src/taskloop/activity_file.py:113-154` — existing live tail, cursor and byte-window semantics.
- `src/taskloop/evidence_files.py:12-31` — imports and the stored activity cap.
- `src/taskloop/evidence_files.py:307-321` — owning event writer and activity read ports.
- `src/taskloop/command_sink.py:37-65` — activity producer and failure boundary.
- `src/taskloop/dash_task.py:58-119` — feed producers and terminal classification.
- `src/taskloop/dash_task.py:233-251` — caller assembling agent history.
- `src/taskloop/dash_model.py:147-181` — existing response contracts.
- `src/taskloop/dash_composition.py:62-66` — feed composition caller.
- `src/taskloop/dash_server.py:177-195` — feed route integration.
- `src/taskloop/dash/static/ui.js:38-46` — live limit and DOM creation.
- `src/taskloop/dash/static/lines.js:21-45` — initial DOM and feed status.
- `src/taskloop/dash/static/lines.js:57-140` — row content, replacement and scroll maintenance.
- `src/taskloop/dash/static/drawer.js:97-128` — polling and Lines callers.
- `src/taskloop/dash/static/drawer.js:178-239` — rebuild and scroll restoration.
- `src/taskloop/dash/static/drawer.js:308-361` — pane integration and tab selection.
- `src/taskloop/dash/static/api.js:13-24` — detail and feed producer interface.
- `tests/steps/test_activity_file.py:15-38` — writer fixtures and logical-action assertions.
- `tests/steps/test_activity_file.py:88-97` — bounded live-read regression.
- `tests/steps/test_dash_read.py:310-332` — task-detail/feed integration fixture.
- `tests/steps/test_dash_read.py:380-394` — terminal unfinished-command/cursor behaviour.
- `tests/dash/rail.test.js:370-380` — existing Lines caller assertions.
- `tests/dash/rail.test.js:579-597` — browser test completion convention.
- `tests/dash/rail.html:1-13` — integration points for new fixture.
- `tests/dash/duration.test.js:1-25` — existing isolated JavaScript test convention.

## Contract
Intent: request ended initial history. Effect: `activity_all` reads one snapshot through `read_all`, bounded by `EVENTS_CAP`, with no event-count or live byte-window cutoff. Result: `ActivityPage` in first-occurrence order, globally replaced by action id, cursor after the final complete record. Preserve invalid/incomplete-record and unavailable-file handling; `_page` still marks unfinished commands.
Intent: follow live activity. Effect: preserve bounded tail/cursor reads and replace by id before trimming. Result: at most 20 live rows after updates, preserving pause/duration and scroll compensation.
Intent: open or refresh ended Lines. Effect: render complete producer history with truthful status text. Result: unchanged wire fields, schema and endpoints. Verify the existing drawer state-change refresh; do not add a fetch owner.
Intent: inspect long text. Effect: constrain to about eight rendered lines with an accessible toggle. Result: original text expands and collapses; short text stays plain. Measure after attachment and on resizing, including wrapped single paragraphs.
Intent: jump. Effect: a control inside Lines scrolls `#tail` to its end. Result: arrivals follow there; scrolling up preserves position. Preserve `#tail`, `#lines`, `#feednote` and attempt keys. Component observers/listeners must not accumulate after replacement.

## Work packages
1. A1: activity_file.py, evidence_files.py, dash_task.py and their two Python test files. Cover more than 20 actions and READ_CAP bytes, paired records across that boundary, and live-to-ended refresh.
2. A2/A3: lines.js, ui.js and new lines.test.js/lines.html. Cover wrapping, expansion, scrolling, arrivals, empty feeds and switching in both themes; reuse compiled styling.
3. Run focused Python and local browser contracts with synthetic data. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Nine implementation/test files plus two artifacts total eleven.

## Acceptance behaviours
- A1: A finished succeeded or failed attempt exposes every retained valid logical event in order, including history beyond 20 events and the live byte window; paired actions appear once with final state. Live following remains capped and finishing refreshes the complete history.
- A2: Messages exceeding about eight displayed lines initially fold; keyboard or pointer activation reveals every original character and can collapse again. Short messages remain readable without a redundant control, including at narrow widths.
- A3: Jump to latest reaches the newest row for both live and finished feeds; subsequent live arrivals follow from the bottom, while scrolling upward preserves the person's place until they return or activate the control.
