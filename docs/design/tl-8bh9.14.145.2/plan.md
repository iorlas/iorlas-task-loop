# Header
tl-8bh9.14.145.2 | base 5734adbb04e688b2dee882ce1997e0b655f56aff
Depth: medium
Reason: 2 behaviours, 3 owning modules. No missing owner decision or known unlanded dependency.
Evidence budget: 12 model calls. Size: 13 changed files, 2 independent behaviours, about 60 implement calls.

## Outcome and non-goals
Show recorded event causes in the task rail and its single selected detail panel. Reuse attempt ordering, folded history, factory commit links, operation rows and land events. Keep the existing attempt output tabs and delivery reads. Storage, scheduling, land actions, new URL forms and new timing collection are outside this change.

## Settled decisions
- Use stored TaskEvent snapshots, including cleared holds, rather than current card text.
- Project LandRow retry causes and recorded times alongside existing land events.
- Preserve existing repeat/restart and factory commit navigation.
- Attempt notices select their causal attempt; land notices select an event locally within the existing land route.
- Share one panel shell; extract presentation from drawer.js to meet its file cap.

## Open decisions
- None.

## Change map
- src/taskloop/dash_model.py — AttemptDetail, LandEvent: validated event context and candidate retry/timing fields.
- src/taskloop/dash_task_event.py — new; build_task calls its projection of HoldStore snapshots onto causal chain entries.
- src/taskloop/dash_task.py — build_task, _history: bulk-read and attach historical holds.
- src/taskloop/dash_land.py — _candidate, build_events: expose retry_cause and recorded candidate times; retain existing ordering and waits.
- src/taskloop/dash/static/rail.js — rail, row, landEvent: readable cause notices and event-specific selection through the existing select callback.
- src/taskloop/dash/static/event-detail.js — new; drawer.pane and deliveryPane integrate its shared shell and context renderer.
- src/taskloop/dash/static/drawer.js — select, pane, deliveryPane, renderContent, onTaskMoved: event selection, shared presentation and refresh retention.
- tests/dash/test_task_events.py — new projection/serialization contracts using build_task and owning hold fixtures.
- tests/dash/test_land_events.py — candidate retry cause and timestamp projection contracts.
- tests/dash/task-events.test.js — new fixture browser contracts integrated into rail.test.js; exercise rail and drawer together.
- tests/dash/rail.test.js — import and run the new suite without growing beyond its file cap.
- docs/design/tl-8bh9.14.145.2/plan.md — implementation contract.
- docs/design/tl-8bh9.14.145.2/plan-metadata.json — preparation commit and consulted paths.
- Consult callers/producers: dash_composition.task/body → build_task/build_body; drawer.renderContent → rail; app → drawer entry points; hold_event.event → TaskEvent; hold.hold → HoldStore.of_attempts; dash_task → dash_land.build_events; dash_server._json → serialization.

## Read list
- src/taskloop/dash_task.py:151-170 — attempt projection and repeat identity.
- src/taskloop/dash_task.py:229-361 — chain owners, history, body lookup and task assembly.
- src/taskloop/dash_model.py:170-224 — attempt and task payload integration.
- src/taskloop/dash_model.py:247-280 — land event payload integration.
- src/taskloop/hold_store.py:60-100 — persisted event snapshot and time.
- src/taskloop/hold_store.py:124-141 — bulk hold reader, including cleared holds.
- src/taskloop/hold_event.py:37-119 — cause producer and captured context.
- src/taskloop/task_event.py:24-56 — causal owner invariants.
- src/taskloop/task_event_cause.py:166-298 — structured causes and optional context.
- src/taskloop/land_store.py:81-120 — candidate identity, retry cause and phase times.
- src/taskloop/land_timing.py:10-28 — existing phase and retry enums.
- src/taskloop/dash_land.py:74-141 — event/wait projection and caller.
- src/taskloop/dash/static/rail.js:99-157 — cause links and attempt row integration.
- src/taskloop/dash/static/rail.js:186-307 — operation/history and land row integration.
- src/taskloop/dash/static/drawer.js:24-85 — selection and drawer loading.
- src/taskloop/dash/static/drawer.js:174-401 — common panel integration and refresh preservation.
- src/taskloop/dash/static/navigation.js:43-62 — existing selection and URL ownership.
- src/taskloop/dash/static/app.js:4-5 — drawer entry-point caller.
- src/taskloop/dash_composition.py:47-60 — task and body callers.
- src/taskloop/dash_server.py:170-177 — nested model serialization.
- tests/dash/rail.test.js:208-285 — attempt/tab and cause navigation fixtures.
- tests/dash/rail.test.js:769-793 — new browser suite integration.
- tests/dash/operation-rail.test.js:10-62 — operation ordering and folded-history regression contracts.
- tests/dash/test_land_events.py:18-69 — candidate reader fixtures and event assertions.
- tests/steps/test_dash_read.py:1-88 — owning store and evidence fixture patterns; add tests in the new file.

## Contract
Intent: expose recorded causes. Effect: build_task bulk-loads holds for chain agent ids and maps TaskEvent.cause_id to its agent/checks projection number. Result: context attaches to the causal entry, including historical holds; checks context belongs to checks output.

Add frozen pydantic TaskEventDetail containing TaskEvent and held_at, optional on AttemptDetail. Reuse existing cause/ reason enums and structured explanation, failed checks, paths, stop information and refs. Missing snapshots remain absent and display reason not recorded where expected. No schema change.

Extend LandEvent with optional RetryCause and admission/phase timestamps from LandRow. Ready events have no candidate facts. Retain recorded times despite wall-clock disagreement; unknown durations remain unknown.

Effect: rail selection passes step/number and optional land event id to drawer.select. Result: the panel shows selected context above existing body/feed content. Keep event id local; validate it after refresh, defaulting to the latest surviving event if missing. Attempt selection clears it. Separately loaded delivery diff/actions must be labelled as current delivery when showing historical context.

Render stored explanation and populated structured context through DOM text nodes with readable labels; omit absent optional fields. Reads and clicks cause no tracker, Git or process writes.

## Work packages
1. Project context in dash_model.py, new dash_task_event.py, dash_task.py and dash_land.py; add test_task_events.py and extend test_land_events.py. Closes A1.
2. Integrate rail.js, drawer.js and new event-detail.js; add task-events.test.js through rail.test.js. Closes A2, including text escaping and keyboard activation.
3. Run fixture browser contracts through the rail harness. After installation run `uv run --frozen --no-sync python -I -m pytest -q tests/dash/test_task_events.py tests/dash/test_land_events.py --tb=short | tail -40`. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each and last.

## Acceptance behaviours
- A1: Every recorded hold cause appears against its deciding agent/checks row, including cleared and abandoned history; candidate retry causes and recorded phase times survive projection unchanged; missing facts remain unknown and reads cause no execution changes.
- A2: Selecting an event shows its full recorded context in the single detail panel; distinct historical land candidates stay distinguishable across redraws, and attempt URLs, tabs, factory commit links, folded history, operation rows, live check navigation and stale-response protection continue to work.
