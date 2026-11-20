# Header
Task: tl-8bh9.14.151.1
Base: ddd02a30f27d46341168b567777fcb23529b6860
Depth: small; one display behaviour.
Missing decision: none. Unlanded dependency: none explicit.
Evidence budget: 6 model calls.
Size: 2 files incl. plan; 1 behaviour; 15 implement model calls.

## Outcome and non-goals
Close regression gaps for Quiet eligibility and warning cleanup. The renderer already gates cards on running plan/implement agents and nonfrozen duration, clearing severity on rebuild. Preserve it unless stronger cases expose a defect. Exclude the parent's other fixes, scheduler changes and schema changes.

## Settled decisions
- Use the existing task status, column and duration fields to determine eligibility.
- Preserve STEPS membership: land remains a step for position and rail rendering.
- Extend the matching browser contract fixture rather than introduce a test harness.

## Open decisions
- None.

## Change map
- `tests/dash/owner-attention.test.js`: `waitingStates`, `liveDurations`, layout loop; extend duration/state and transition coverage.
- `src/taskloop/dash/static/app.js`: `fillCard`, `newCard`, `renderBoard`; consult eligibility and reset; edit only if cases fail.
- `src/taskloop/dash/static/ui.js`: `runningAgent`, `quietSpan`, `tickQuiet`, `tick`; consult eligibility and severity.
- `src/taskloop/dash_board.py`: `card_of`; consult producer of card status, column and duration.
- `src/taskloop/dash_model.py`: `Card`; consult input fields.
- `src/taskloop/dash/static/drawer.js`: consult running-attempt `quietSpan` caller.
- `src/taskloop/dash/static/lines.js`: consult `quietSpan` caller.
- `tests/dash/duration.test.js`: consult `quietSpan` threshold/frozen contracts.
- `tests/dash/owner-attention.html`: existing fixture entry.
- `docs/design/tl-8bh9.14.151.1/plan.md`: new bounded plan.

## Read list
- `src/taskloop/dash/static/app.js:145-210` — card lifecycle and render caller.
- `src/taskloop/dash/static/ui.js:97-110` — position and eligibility.
- `src/taskloop/dash/static/ui.js:128-177` — severity producer and duration nodes.
- `src/taskloop/dash_board.py:99-133` — card input producer.
- `src/taskloop/dash_model.py:28-48` — card fields.
- `src/taskloop/dash/static/drawer.js:335-347` — separate Quiet caller.
- `src/taskloop/dash/static/lines.js:40-56` — separate Quiet caller.
- `tests/dash/duration.test.js:40-87` — threshold and frozen contracts.
- `tests/dash/owner-attention.test.js:7-32` — fixture data and clock.
- `tests/dash/owner-attention.test.js:63-83` — event and snapshot helpers.
- `tests/dash/owner-attention.test.js:151-255` — existing negative cases and live duration coverage.
- `tests/dash/owner-attention.test.js:468-480` — both layout execution points.
- `tests/dash/owner-attention.html:1-16` — browser fixture entry.

## Contract
Intent: render existing Card inputs. Effect: create Quiet only for running plan/implement agents with nonfrozen duration; rebuild clears severity. Result: ineligible cards have no Quiet node or warning despite old live duration evidence. No new typed names, stored fields or external effects.

## Work packages
1. Extend `tests/dash/owner-attention.test.js` for A1: seed land/held cards with old nonfrozen warning samples; transition a warned article independently into each excluded state. Exercise snapshot, stream, tick and redraw paths. Retain live/frozen controls. If needed, correct `fillCard` or `runningAgent`; reassess Size before expanding scope.
2. Run the isolated browser fixture and existing duration contracts. Then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; record gate exit status with pipeline failure propagation.

## Acceptance behaviours
A1: Quiet and its warning border appear only for eligible live agent cards; land, held and other ineligible cards stay clear despite stale duration evidence, transitions, timer ticks and redraws in both layouts.
