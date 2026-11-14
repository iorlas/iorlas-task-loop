# Header
Task: tl-8bh9.14.139.3. Base: eb074c8f977bbff8093124ce2379a792cae46fbe.
Depth: small; one dashboard slot behaviour. No missing decision or unlanded dependency. Evidence budget: 6 model calls.
Size: 3 files including plan; 1 behaviour; 20 implement model calls.

## Outcome and non-goals
Supply the current slot to existing card footers and slot lanes. Exclude waiting wording, outcome labels and Land drawer interactions.

## Settled decisions
Use the operation's slot assignment and release facts, rather than the preceding agent attempt's reservation.
Keep slot selection in `card_of`, shared by board and task detail.
Reuse `Card.slot` and the existing browser rendering; introduce no storage or API fields.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_board.py`: change `card_of` slot selection; `build_board` consumes it.
- `tests/steps/test_dash_read.py`: extend `board_of` coverage for A1.
- `src/taskloop/attempt_status.py`: consult `AttemptView` and `_swapped` checks projection.
- `src/taskloop/check_status.py`: consult `ChecksView` and `checks_release` for checks lifecycle facts.
- `src/taskloop/check_store.py`: consult `ChecksRow` assignment.
- `src/taskloop/land_status.py`: consult `LandView` for the current candidate.
- `src/taskloop/land_store.py`: consult `LandRow.slot` and `holds_slot` for landing custody.
- `src/taskloop/dash_model.py`: consult nullable `Card.slot`.
- `src/taskloop/dash_task.py`: `build_task` calls `card_of` for detail.
- `src/taskloop/dash_composition.py`: `_ports.board` calls `build_board`; `_ports.task` calls `build_task`.
- `src/taskloop/dash/static/app.js`: consult `laneOf` and `fillCard` slot consumers.
- `tests/steps/conftest.py`: consult `registered`, `checking` and `landing` fixture setup.
- `docs/design/tl-8bh9.14.139.3/plan.md`: retain this implementation contract.

## Read list
- `src/taskloop/dash_board.py:97-148` — projection and board caller.
- `src/taskloop/dash_model.py:25-49` — card and board fields.
- `src/taskloop/attempt_status.py:67-99` — composed view fields.
- `src/taskloop/attempt_status.py:184-212` — checks producer and release swap.
- `src/taskloop/check_status.py:25-64` — checks view and release interpretation.
- `src/taskloop/check_store.py:58-100` — checks assignment models.
- `src/taskloop/land_status.py:44-74` — candidate view producer.
- `src/taskloop/land_store.py:77-140` — candidate assignment and custody properties.
- `src/taskloop/dash_task.py:276-289` — detail caller.
- `src/taskloop/dash_composition.py:36-48` — application callers.
- `src/taskloop/dash/static/app.js:74-75` — lane selection.
- `src/taskloop/dash/static/app.js:112-135` — card slot footer.
- `tests/steps/test_dash_read.py:54-61` — board helper.
- `tests/steps/test_dash_read.py:167-179` — existing slot assertions.
- `tests/steps/test_dash_read.py:307-340` — landing state coverage.
- `tests/steps/conftest.py:102-155` — operation fixtures.

## Contract
Intent: project the current assignment. Effect: read checks and candidate custody from `AttemptView`, without IO or writes. Result: `Card.slot` is the held slot or null. Landing custody takes precedence over historical checks assignment; slotless candidates cannot inherit released checks slots. Preserve the agent-slot rule for other cards.

## Work packages
1. Update `dash_board.py` and `test_dash_read.py` for A1: distinct checks/landing slots, release, slotless candidates and board/detail agreement; confirm existing browser consumers receive the value.
2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last; both must pass.

## Acceptance behaviours
A1. Checking and landing cards show their current assigned slot in the footer or matching slot lane; released or slotless operations show no stale slot, and board and task detail agree.
