# Depth

Small: one dashboard vocabulary-consistency behaviour owned by the dashboard presentation module. No owner decision is missing and no dependency is explicitly unlanded. Evidence-gathering ceiling: 6 model calls. The supplied code map is context, not a list of files to change. The reference to .150 does not establish an unlanded dependency; its rail is present at source commit `58bea2a81143889b616d8873b112a8eaaa46eb1c`.

## Size

Estimated changed files: 16, including this plan, the glossary, up to eleven dashboard presentation files and three existing test files. Some audited files may need only a documented display-word explanation rather than an edit. No new runtime modules or test framework are needed.

Independent behaviours: 1. Every dashboard-owned label uses the existing glossary vocabulary or has an explicit explanation in the glossary for its display wording. Acceptance: the board, drawer, rail, results, activity lines, task view and logs consistently use attempt, Check, Hold and Success/Failure; the waiting column and activity-age label describe their actual facts; wording contracts cover these surfaces, including tooltips and accessibility text. Existing navigation, selection, disclosures, timing and raw-code explanations continue to work. These are surfaces of one vocabulary contract, not separate workflow changes.

Estimated model calls for one implement attempt: 55, including focused verification and the two final gates. This stays below 60 files, 3 independent behaviours and 100 calls.

## Evidence and intended wording

There is no existing plan at this path and the inspected branch history has no unfinished task result. The worktree was clean before planning.

`ui.js` owns column and attempt-state labels, but attempt wording also appears directly in `rail.js`, `drawer.js`, `result.js` and `lines.js`. The rail already includes .150's repeated-attempt labels, verification titles, collapsed-history tooltip and repeat references. `taskview.js` additionally has a “Try again” control. JavaScript `try` statements and unmodified external content are not dashboard labels.

The supplied glossary defines attempt as one concrete execution of an operation and step as one bounded operation; neither an attempt nor a check command is an additional step. Apply those distinctions throughout the presentation:

- Replace numbered “try” labels with “attempt”, including step position, repeat references, verification headings, tooltips and accessible names. Change the tracker-read action to “Reload task” and the feed's “Trying again” sentence to ordinary reconnecting wording, so neither suggests a factory attempt.
- Show the step/column as “Check”, and its help as a check attempt running the profile's checks. Plural “checks” remains appropriate for a collection of individual configured check commands; explain that distinction in the glossary. Update `words.js` strings only where they incorrectly name the step, retaining readable explanations and family-specific tails.
- Show the column as “Hold” and attempt outcome badges as “Success” and “Failure”. Ordinary explanatory sentences may use grammatical inflections, with their relationship to the glossary stated explicitly. Individual command and verification marks must either use those outcome words consistently or have their passed/failed wording explained in the glossary.
- Replace the waiting column's “Ready” label with “Waiting” and correct its help and elapsed-time suffix. `dash_board.column_of` also puts queued and abandoned tasks there, so the current claim that every card is approved and awaiting admission is inaccurate. Explain Waiting as a display grouping of tasks with no current work, not a new readiness state; retain each card's existing queued/abandoned explanation.
- Replace “Quiet” with “Last activity … ago”, preserving the existing measured timestamp, thresholds, colours and updates. Explain that this is elapsed time since recorded activity, not a conclusion about an agent's health or a scheduling state.

Audit the rest of the page's headings, controls, badges, help text, tooltips and accessible names. Add a compact dashboard-wording section to the existing glossary explaining deliberate plain-English presentation words (for example Board, Result, Prompt, Lines, Theme, Details and history grouping labels) in terms of existing concepts. Do not add glossary terms for ordinary English or create new factory vocabulary. Resolve ambiguous existing labels by using the existing term or documenting precisely what the displayed word denotes. External task titles, tracker prose, check names, raw output, code identifiers and raw-code hover text keep their owning source; the glossary must explain these boundaries instead of attempting to enumerate external content.

This is a presentation change. Keep the existing wire identifiers (`waiting`, `checks`, `held`, `succeeded`, `failed`), attempt numbers, selection keys and stored facts. Their display mapping can differ explicitly from their serialization; no backend rename, schema change, compatibility layer or scheduler change is needed. Reuse the existing shared label mappings rather than introducing a second vocabulary owner.

## Implementation

1. Build a bounded inventory of dashboard-owned labels from the read list. Compare domain labels with the supplied definitions and the existing glossary definitions already located by the targeted lookup. Record deliberate display differences in the glossary, without inventing new domain terms.
2. Update shared labels and the callers that compose labels directly. Include the existing .150 rail and all hidden, folded, hover and accessibility text. Keep check-collection prose distinct from the singular Check step and preserve the raw-code fallback in `say`/`wordNode`.
3. Update existing wording contracts and browser fixture assertions affected by these strings. Extend focused contracts to cover labels that were previously missed, particularly waiting, activity age, numbered attempts and the tracker reload action. Keep the inventory/test data local to the existing test files; no new files are planned beyond this plan.
4. Verify the vocabulary contract and existing UI behaviour, then run the required gates once each, last.

## Read list

- `docs/glossary.md:1-37` — glossary usage rules and work/execution definitions; existing file where dashboard display explanations belong.
- `src/taskloop/dash/static/words.js:1-69` — owning typed-code wording table, family explanations and raw-code hover behaviour.
- `src/taskloop/dash/static/ui.js:5-38` — shared column, step, outcome and land labels used by board, drawer and rail.
- `src/taskloop/dash/static/ui.js:93-126` — step position and activity-age wording, thresholds and update helpers.
- `src/taskloop/dash/static/app.js:76-190` — board callers, card position, elapsed suffixes, hold count and activity display.
- `src/taskloop/dash/static/app.js:196-299` — remaining board controls, stream-status labels and timer integration to audit.
- `src/taskloop/dash/static/drawer.js:136-278` — task position, tabs, status, repeat references and selected-attempt titles.
- `src/taskloop/dash/static/rail.js:18-145` — verification titles, accessible names, attempt labels and repeat references.
- `src/taskloop/dash/static/rail.js:150-229` — history summaries, disclosure tooltip, remaining step labels and land row.
- `src/taskloop/dash/static/result.js:56-137` — individual check outcomes, verification attempt number and result sections.
- `src/taskloop/dash/static/taskview.js:16-71` — tracker failure action, task section headings and property labels.
- `src/taskloop/dash/static/lines.js:1-105` — event-kind words, reconnect sentence, command/check outcomes and attempt-start label.
- `src/taskloop/dash/static/logs.js:3-82` — log filter labels, page heading and distinction between owned labels and raw log content.
- `src/taskloop/dash/static/usage.js:1-22` — usage labels and explanations for the whole-page wording inventory.
- `src/taskloop/dash/static/index.html:13-29` — static navigation, layout, theme and accessibility labels.
- `src/taskloop/dash_model.py:10-40` — producer's serialized column/state codes and card facts; consult without changing the protocol.
- `src/taskloop/dash_board.py:18-38` — actual membership of the waiting column and distinction from admission readiness.
- `src/taskloop/dash_board.py:99-119` — producer of the recorded activity timestamp and hold explanation.
- `src/taskloop/dash_task.py:90-173` — agent/check state producers and result-body shape consumed by presentation mappings.
- `src/taskloop/dash_verify.py:1-58` — verification check vocabulary imported by existing wording contracts.
- `tests/cli/test_dash_words.py:1-52` — wording-table coverage, family-tail assertions and focused regression integration point.
- `tests/dash/rail.test.js:1-262` — existing offline DOM fixture and rail selection/disclosure/wording contracts to preserve and extend.
- `tests/dash/owner-attention.test.js:1-258` — board/drawer fixture and owner-attention contracts affected by shared label changes.
- `tests/cli/test_dash_server.py:128-160` — static-page integration contracts; avoid adding assets or changing the page whitelist.

Use additional targeted searches only to locate omitted glossary definitions or missed label callers and changed source; do not expand into historical implementations or unrelated design plans. All listed files already exist except this new plan, whose integration point is the task's established design directory.

## Verification and completion

Keep or extend `test_dash_words.py` contracts for the existing typed-code table and family-tail behaviour. Assert the vocabulary contract across its actual presentation surfaces, without banning JavaScript syntax, collection plurals, protocol keys or user-provided text. Add representative DOM assertions to the existing rail and owner-attention fixtures for attempt numbering, Check/Hold and Success/Failure labels, Waiting membership wording and activity-age text. Retain their selection, repeat navigation and disclosure assertions; wording edits must not alter their behaviour.

After installation, the allowed focused Python command is `uv run --frozen --no-sync python -I -m pytest -q tests/cli/test_dash_words.py --tb=short | tail -40`. Browser fixture checks, if run, use only local fixture data and the existing harness; no live factory, tracker, agent or remote service. Do not introduce a browser dependency merely to run this wording change. State clearly whether those fixture checks ran; they do not replace the required gates.

Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Completion requires both gates to pass and the whole-page inventory to account for every dashboard-owned label through an existing glossary term or an explicit display-word explanation. Planning does not run implementation gates.
