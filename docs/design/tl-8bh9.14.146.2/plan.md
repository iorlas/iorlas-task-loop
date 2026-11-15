# Header
tl-8bh9.14.146.2 @ 771f57ad2b82b9cb5e6e01e14966c82ad1705b7f
Depth: medium; three owning modules.
Owner decision missing: no. Unlanded dependency: no. Evidence ceiling: 12 model calls.
Size: 11 files with tests/artifacts, 2 independent behaviours, about 60 implement model calls.

## Outcome and non-goals
Expose delivery history before selecting Land; retain useful action and diff facts on selection. Preserve human guidance and board policy states. Exclude Accept/Reject, scheduling, delivery writes, schema changes and log reconstruction. Behaviours: typed history projection; visible waits/navigation.

## Settled decisions
- Use the shared land operation for selected summaries; project history from owning stores.
- Keep ready, tried and landed as event kinds, distinct from the card's policy/execution state.
- Emit tried only for a recorded candidate; a summary read is not a delivery try.
- Landed requires delivery and confirmed completion, with any slot released; integration alone remains tried.
- Retain all candidates under their checks attempts; abandoned chains remain history.
- Missing timestamps are unknown, never inferred from deadlines, display text or observation time.
- Replace Land command references with facts; preserve guidance and diff totals.
- Accept/Reject belongs to .157. No dependency is declared on that task.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_model.py`: add `LandEventKind`, `LandEvent`, `LandWait`, `TaskDetail.land_events`; remove `LandDetail` command fields.
- `src/taskloop/dash_land.py`: add read-only `build_events`; retain `build_land` facts, remove command construction.
- `src/taskloop/dash_task.py`: `build_task` returns projected events; use `_chain` for ordering/history.
- `src/taskloop/dash/static/rail.js`: replace `landRow` with events/waits; extend `rail`'s input.
- `src/taskloop/dash/static/drawer.js`: `render` passes events; `deliveryPane` removes command blocks; preserve `loadDelivery`/refresh fencing.
- `tests/dash/test_land_events.py` (new): semantic projector contracts at `build_events`/`TaskDetail`.
- `tests/dash/rail.test.js`: extend `mount`, `landSelection`, `landStaleReplies`, `waitingRows` and runner with events/waits/navigation.
- `tests/steps/test_dash_land.py`: update `read`/summary assertions; preserve read-only coverage.
- `tests/steps/test_dash_read.py`: exercise events from `build_task` without selecting delivery or reading tracker fields.
- `docs/design/tl-8bh9.14.146.2/plan.md` and `plan-metadata.json` (new): retain this bounded contract and cited inputs.
- Consult `dash_composition.delivery`/`task`, `dash_server.DashPorts`/`_json`: service callers/serialization; `drawer.render` and test `mount`: rail callers.
- Consult `LandStore.of_checks`/`for_task`, `ChecksRow`, `LandRow`, `land_state`/`land_next`, `LandPorts`, `LandSummary`: fact producers/completion rules.
- Consult `dash_board.card_of`, `ui.waitingNote`/`isWaiting`: policy/wait wording; `tests/dash/rail.html`: browser host.

## Read list
- `src/taskloop/dash_land.py:1-48` — summary producer and replacement command fields.
- `src/taskloop/dash_model.py:193-242` — task and delivery response integration.
- `src/taskloop/dash_task.py:204-237` — chain identities and checks ordering.
- `src/taskloop/dash_task.py:298-317` — task-detail producer.
- `src/taskloop/dash_composition.py:40-75` — task and delivery service callers.
- `src/taskloop/dash_server.py:170-176` — response encoding; inspect `_json_model` if nested-model encoding needs adjustment.
- `src/taskloop/land_store.py:77-120` — candidate outcomes and available timestamps.
- `src/taskloop/land_store.py:234-246` — owning candidate readers.
- `src/taskloop/check_store.py:73-100` — readiness, release and abandoned checks facts.
- `src/taskloop/land_status.py:37-96` — observed state and completion rules.
- `src/taskloop/land_check.py:53-74` — existing summary ports.
- `src/taskloop/land_summary.py:76-100` — typed summary facts.
- `src/taskloop/dash_board.py:100-129` — card status and wait provenance.
- `src/taskloop/dash/static/rail.js:209-249` — Land row and rail assembly.
- `src/taskloop/dash/static/drawer.js:230-286` — rail caller, summary loading and selected pane.
- `src/taskloop/dash/static/drawer.js:382-399` — refresh and selection retention.
- `src/taskloop/dash/static/ui.js:109-122` — waiting text and ticking timestamps.
- `tests/steps/test_dash_land.py:1-74` — semantic land fixture and read-only assertions.
- `tests/steps/test_dash_read.py:1-55` — task producer test imports and tracker fake.
- `tests/dash/rail.test.js:19-34` — event fixture integration in mount.
- `tests/dash/rail.test.js:267-285` — Land navigation and lazy summary contract.
- `tests/dash/rail.test.js:630-650` — browser runner and both themes.
- `tests/dash/rail.html:1-13` — static browser contract entry point.

## Contract
Intent: `TaskDetail.land_events` holds frozen pydantic models. `LandEventKind` is a stdlib enum READY/TRIED/LANDED with one JSON codec. Events carry stable checks/candidate identity, nullable UTC time, historical membership, explanation and optional typed `LandWait`. Reuse outcome types; new closed vocabularies use enums.

Effect: `build_events` reads typed rows/current observations, with no land action. Order by checks chain then candidate number within each checks attempt. READY requires passed, released checks; abandoned chains are history. TRIED represents each recorded candidate/outcome. LANDED requires delivery, close and slot release; use the latest required completion timestamp.

Result: show waits after readiness, between tries and during unfinished delivery/completion. A wait carries preceding-event identity, nullable start/end and awaited condition. Use recorded times only for their actual meaning. LandRow lacks try-start time: show unknown time/duration rather than substituting validation completion. Active validation is not waiting. Invalid/negative bounds produce unavailable timing. Completed waits remain; open waits tick from known bounds. Preserve unknown policy/process wording.

Encode nested models with the server codec. Feed events through task detail; lazy summary loading, errors and stale replies cannot erase them. Event selection opens Land without numbered agent attempts. No persistence changes or external effects.

## Work packages
1. Project history in `dash_model.py`, `dash_land.py`, `dash_task.py`; add projector/task tests. Closes A1–A3.
2. Wire `drawer.js`, render `rail.js` events/waits, update fixtures and summary tests. Closes A4–A6.
3. After install, run focused tests with the approved isolated pytest invocation and static `tests/dash/rail.html` contracts in both themes, without live services. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each. Planning runs no implementation gates.

## Acceptance behaviours
- A1: Passed released checks show readiness before any candidate exists; reading it causes no delivery action.
- A2: Failed, superseded, repeated and historical candidates retain distinct ordered tried events across checks chains, without inventing unrecorded tries.
- A3: Integration awaiting completion/release is not landed; confirmed completion is landed with known completion time or explicit unknown timing.
- A4: Every known wait remains visible with its awaited condition and available duration; missing bounds display unavailable timing, and active validation has no waiting clock.
- A5: Events appear before selecting Land and survive refresh, missing summary facts and stale replies; keyboard selection and existing attempt navigation still work.
- A6: The Land pane retains human guidance and diff facts, presents no command-reference blocks, and introduces no Accept/Reject controls.
