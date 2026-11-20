# Header
Task: tl-8bh9.14.151.2
Base: ddd02a30f27d46341168b567777fcb23529b6860
Depth: small; one dashboard wording behaviour.
Owner decision: none. Unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 6 files including plan; 1 behaviour; 20 implement model calls.

## Outcome and non-goals
Numbering and prior-attempt links already exist. The gap is that the projection copies the earlier outcome into the reason and renderers hardcode “Repeat”. Show “Re-run after restart” in rail and detail. Exclude sibling dashboard fixes, execution and schema changes.

## Settled decisions
- Identify re-runs within the same implement owner using existing checks ordering.
- Keep AttemptDetail fields; render the checks repeat relationship as a re-run after restart.
- Use a restart explanation independent of earlier outcomes.
- Leave agent repeat and restart-at-plan wording intact.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_task.py`: `_checks` and sole caller `_history` replace outcome-derived reasons and scope prior links by owner; consult `_chain`, `history`, `build_task`.
- `src/taskloop/dash/static/rail.js`: `row` renders the checks re-run label and tooltip; consult `changeReason`, also used by `restart` and drawer `began`.
- `src/taskloop/dash/static/drawer.js`: `began` and its selected-detail caller render checks restart wording with the prior-attempt reference.
- `tests/steps/test_dash_read.py`: revise the second-checks projection coverage and cover earlier passed/failed outcomes and a new implement owner.
- `tests/dash/rail.test.js`: extend `restartsAndRepeats` and drawer coverage for checks and agent wording.
- `docs/design/tl-8bh9.14.151.2/plan.md`: new plan, integrated with projection and renderers above.

## Read list
- `src/taskloop/dash_task.py:157-169` — checks outcome and relationship projection.
- `src/taskloop/dash_task.py:190-244` — producer, sole caller and ownership/order.
- `src/taskloop/dash_task.py:272-291` — task-detail integration.
- `src/taskloop/check_store.py:57-96` — checks admission and stored owner/number.
- `src/taskloop/check_store.py:310-314` — ordered checks producer per implement attempt.
- `src/taskloop/dash_model.py:169-186` — existing relationship fields.
- `src/taskloop/dash/static/rail.js:29-33` — reason formatting shared with drawer.
- `src/taskloop/dash/static/rail.js:119-137` — label and tooltip consumer.
- `src/taskloop/dash/static/drawer.js:311-350` — relationship detail and its caller.
- `tests/steps/test_dash_read.py:14-60` — fixtures.
- `tests/steps/test_dash_read.py:449-461` — existing checks relationship assertion.
- `tests/dash/rail.test.js:1-30` — fixtures.
- `tests/dash/rail.test.js:107-140` — repeat/restart assertions.
- `tests/dash/rail.test.js:180-205` — drawer assertions.

## Contract
Intent: explain subsequent checks for the same implement owner. Effect: project a restart explanation and render it in rail, tooltip and detail. Result: “Re-run after restart” with the prior checks attempt identifiable. No new stored fields or vocabulary values. State and summary retain the current outcome. First checks under another implement owner have no restart relationship.

## Work packages
1. Update projection and Python dashboard tests, closing A1.
2. Update rail/detail presentation and browser fixture assertions, closing A1. Run the focused Python dashboard file using the permitted isolated pytest command and the browser fixture with local fake data. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each; no live factory tests.

## Acceptance behaviours
A1. Restarted checks read as “Re-run after restart” in rail, tooltip and detail regardless of the previous checks outcome; numbering and prior-attempt references remain correct, fresh checks for another implement owner are not labelled restarted, and agent repeats retain their wording.
