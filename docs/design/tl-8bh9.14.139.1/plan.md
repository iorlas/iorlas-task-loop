# Header
Task: tl-8bh9.14.139.1. Base: 9ee126d3db36fb48c12ba8fa5d2e4792552a9511.
Depth: small; one waiting-display behaviour. Missing decisions/unlanded dependencies: none. Evidence budget: 6 model calls.
Size: 12 files including plan, 1 independent behaviour, 55 implement model calls.

## Outcome and non-goals
Unify waiting explanations and recorded starts across cards, drawer callouts and the Land row. Keep running agent activity ages and warnings. Exclude Land interactions, slot and outcome-label changes.

## Settled decisions
- Reuse existing status/admission explanations.
- Start evidence: check release, hold creation or abandoned attempt release; queued start is unknown.
- Tracker creation and old attempt starts cannot date the current wait.
- Preserve delivered slot projection and readable outcome labels.

## Open decisions
- None.

## Change map
- `src/taskloop/dash_model.py`: `Card` gains nullable `waiting_since`.
- `src/taskloop/dash_board.py`: `card_of`/`build_board`, new `_waiting_since`/`queued_card`: wait and activity projection.
- `src/taskloop/dash_task.py`: `build_task`, other `card_of` caller: share queued projection.
- `src/taskloop/dash/static/ui.js`: waiting helpers and `tick`; retain `quietSpan`/`tickQuiet`.
- `src/taskloop/dash/static/app.js`: `fillCard`/refresh caller clear warnings; `start` ticks waits.
- `src/taskloop/dash/static/drawer.js`: `render` waiting callout; `pane` running-only `quietSpan`.
- `src/taskloop/dash/static/rail.js`: `landRow`/`rail` share waiting note.
- `tests/steps/test_dash_read.py`: board/detail timestamps.
- `tests/cli/test_dash_words.py`: waiting wording.
- `tests/dash/owner-attention.test.js`: card/drawer waits and state changes.
- `tests/dash/rail.test.js`: Land waits and activity; retain outcome coverage.

## Read list
- `src/taskloop/dash_model.py:25-45`: Card contract.
- `src/taskloop/dash_board.py:54-155`: timestamps, card_of and build_board caller.
- `src/taskloop/dash_task.py:271-290`: build_task caller and queued fallback.
- `src/taskloop/task_status.py:59-156`: admission, status and explanation producer.
- `src/taskloop/check_status.py:45-76`: check release projection.
- `src/taskloop/land_status.py:55-75`: released checks prerequisite.
- `src/taskloop/attempt_reads.py:20-30`: release timestamp fact.
- `src/taskloop/dash/static/ui.js:96-128`: time rendering and activity helpers.
- `src/taskloop/dash/static/app.js:107-165`: card rendering and refresh caller.
- `src/taskloop/dash/static/app.js:277-300`: periodic tick integration.
- `src/taskloop/dash/static/drawer.js:172-210`: callout consumer.
- `src/taskloop/dash/static/drawer.js:248-280`: pane activity consumer.
- `src/taskloop/dash/static/rail.js:197-230`: landRow and rail caller.
- `tests/steps/test_dash_read.py:167-222`: board/detail fixtures.
- `tests/steps/test_dash_read.py:308-378`: slot and Land regressions.
- `tests/cli/test_dash_words.py:75-81`: wording contract.
- `tests/dash/owner-attention.test.js:115-141`: board/drawer observations.
- `tests/dash/rail.test.js:208-289`: labels and activity assertions.

## Contract
Intent: explain current waits. Effect: project optional ISO `Card.waiting_since`; render action and start or “Waiting since not recorded”. Result: board/detail agree without writes. `last_activity_at` is null outside running plan/implement agents; refresh clears stale warnings.

## Work packages
1. Update Python projection and read tests; closes A for recorded and unknown starts.
2. Update shared UI and all three consumers plus existing browser/wording tests; closes A across transitions. Run both browser fixtures without live services, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A. Waiting cards, drawer callouts and Land rows name the awaited action and recorded start or explicit unknown start; only running agents show activity age or quiet warnings, including after state changes.
