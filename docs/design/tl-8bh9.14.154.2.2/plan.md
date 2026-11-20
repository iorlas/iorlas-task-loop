# Header
Task: tl-8bh9.14.154.2.2
Base: 80d7fd0f7d9e519854a36088f6e2529149c5ddfe
Depth: small; one dashboard markup behaviour
Decision: none missing. Dependency: .154.2.1 landed.
Evidence budget: 6 model calls.
Size: 6 files, 1 independent behaviour, 30 model calls per implement attempt.

## Outcome and non-goals
Expose meaning beside cues in attempt rows, verification controls, history and event kinds. Columns, badges, quiet age and check outcomes already have words. Reduced motion is delivered; responsive layout and amber styling are out of scope.

## Settled decisions
- Use visible words, beyond hover titles and accessible names.
- Reuse STATE labels, verdict explanations and WORD event labels; retain selection and update behaviour.
- Reuse existing layout utilities.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/rail.js`: row, verificationButtons, summary — show state and verdict words alongside dots/marks, including folded history; consult verdict, STATE and the drawer renderContent caller.
- `src/taskloop/dash/static/lines.js`: line — show WORD beside KIND; cover initial and incremental rendering and the drawer pane caller.
- `tests/dash/test_accessibility_markup.py`: contracts — cover visible label wiring and existing labelled indicators.
- `tests/dash/rail.test.js`: rail/lines fixtures — assert rendered adjacent words for states, verdicts, history and event kinds, including replacements; update assertions affected by longer button text.

## Read list
- `src/taskloop/dash/static/rail.js:1-180` — state dots, verdict controls and folded summaries.
- `src/taskloop/dash/static/rail.js:181-245` — history groups and rail entry point.
- `src/taskloop/dash/static/lines.js:1-140` — event mappings, initial rendering and replacement path.
- `src/taskloop/dash/static/ui.js:6-84` — shared labels, dots and callouts.
- `src/taskloop/dash/static/ui.js:110-138` — quiet indicators already paired with age text.
- `src/taskloop/dash/static/app.js:110-185` — labelled column/card producers.
- `src/taskloop/dash/static/drawer.js:230-245` — rail integration.
- `src/taskloop/dash/static/drawer.js:330-365` — state badges and lines integration.
- `src/taskloop/dash/static/result.js:55-70` — labelled check results.
- `src/taskloop/dash/static/words.js:1-69` — existing verdict explanations.
- `src/taskloop/dash/static/index.html:12-41` — static controls and dynamic mounts.
- `tests/dash/test_accessibility_markup.py:1-155` — existing static contract helpers.
- `tests/dash/rail.test.js:1-597` — DOM fixtures and affected renderer assertions.
- `tests/dash/rail.html:1-13` — browser test integration.

## Contract
Intent: expose existing presentation meaning as visible text. Effect: renderer DOM changes only; no API, stored fields or execution states change. Result: STATE.label accompanies attempt dots; verdict.label accompanies verification marks; history summaries include words for each result; WORD accompanies each KIND glyph. Keep failure reasons, accessible names and click targets consistent. Initial and incremental event rendering use the same labelled row. Existing quiet-age, check and column text remains sufficient without interpreting colour or emoji.

## Work packages
1. Update rail.js and lines.js to close A1 across normal, failed, pending, folded and incremental views. Keep words readable with existing wrapping utilities.
2. Extend both test files for A1: assert visible adjacent words, including DOM replacements. Run focused Python contracts and the synthetic browser fixture where available. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A1: Every dashboard colour or emoji indicator has adjacent visible words conveying its meaning, including attempt states, verification outcomes, folded history and all event kinds after insertion or replacement.
