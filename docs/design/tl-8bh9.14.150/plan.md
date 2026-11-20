# Compact Steps rail

Status: implemented; real-browser validation blocked by the execution sandbox. Task: `tl-8bh9.14.150`.

The owner's 2026-11-13 review calls for one visible row per step try, verification
marks on that row, compact restart/repeat information, and folded past runs. This
task supersedes the separate verification and routine factory-work rows in
`dashboard-ux-review-1113.md` and the corresponding earlier dashboard design.
It is a rendering change using the existing data, without a schema change.
Related work: `.145` (stored causes), `.146`, `.140`; this slice does not implement
their event recording or depend on a cause being available.

## Current code and boundaries

Inspected at `260d9183`. There was no plan at this path and no commit with a
`Task-Loop-Wip:` trailer in the available branch history. The supplied task is the
requirements source; `bd show tl-8bh9.14.150` found no record in this environment.

- `dash_task._chain` orders an agent attempt, its verification, then its checks.
  Verification has its own task-wide number; it is not the agent's try number.
  `AttemptDetail` already carries `after`, `repeat_of`, `led_by`, `past`, times,
  state and summary. The current history marks abandoned chains as past.
- `rail.js` currently renders all these entries as rows, inserts gaps from five
  seconds, adds repeat/restart rows and always prints `try 1`. `landRow` also
  prints an idle line while waiting for land.
- `dash_board._repeat` supplies a circular restart explanation and tests restart
  before repeat, so a repeated plan can be presented as a restart.
- `dash_task._agent` supplies the literal placeholder `restarted at plan` for a
  restart reason. It is not evidence of a stored cause.
- `drawer.js` imports `lasted`, `verifyTitle`, `causeLink` and `rail`. Selecting
  `(verification, n)` already opens Result, even from Lines or Prompt.
- `words.js` owns display translations and raw-code hover text. Existing Python
  tests check its table and the backend's verification reasons.

Keep history entries, endpoint addresses, try numbering, Result details, stored
state and scheduling behavior intact. Do not introduce events, a run model,
database writes, dependencies, log parsing or inferred restart causes. `Run 1`
is the owner's requested display label for grouped existing history only.

## Rendering behavior

1. Project the ordered history into step rows and attached verification entries.
   Attach a verification to the immediately preceding agent attempt according to
   the existing ordering contract, retaining its own `(step, n)` for selection.
   Do not attach it to checks or match it by the verification number. A step row
   keeps its duration and status. Omit `try N` when `N == 1`; show it from 2 on.

2. Replace each verification row with a small, separately focusable check/cross
   button on its agent row. Success (`verified` or `reused`) shows a check;
   failure shows a cross and one short `Not committed: <why>` line. Both the
   mark and failure line select that verification's Result, including its failed
   check, listing and rule. Keep the step's main button selecting the step itself;
   do not nest buttons. Give marks accessible names, hover explanations and a
   selected indication when their Result is open. Pending verification is neutral
   and inspectable, never a success mark. Missing verification has no invented
   verdict; a terminal verification without a recorded outcome says that the
   outcome was not recorded. Other step failures keep a readable summary and
   their existing result access. Avoid two `Not committed:` prefixes.

3. Keep ordinary factory-work gaps as hover information on the following row.
   A gap of at least 120 seconds may have one short factory-work row; below that
   threshold it has none. Calculate gaps between non-verification entries with
   recorded start/end times. Missing, invalid or negative intervals produce no
   duration. Explain that these are approximate elapsed gaps, not measurements
   of individual commit/publish operations. Never count a restart/repeat gap as
   factory work.

4. Remove idle rows, including the extra idle line under Land. Fold a recorded
   wait before a restart into its compact row, e.g. `waited 8m 21s`. A repeat's
   elapsed gap can remain in its tag's hover explanation without a separate row.
   Keep Land's existing state and waiting explanation; do not invent a cause for
   elapsed time or change land policy.

5. A restart row reads `Restarted at plan · 20:38`, adding the date only when the
   timestamp is not today in the browser's local calendar. Use a short local
   formatter rather than changing the shared `startedAt` behavior incidentally.
   With no timestamp, omit the time. The reason is `Reason not recorded` until a
   real cause is available. Normalize the existing restart placeholder explicitly
   in presentation; do not treat it as a stored cause or infer one from prompts,
   commits or logs. Preserve a genuine supplied explanation. The restart row
   selects the new plan attempt and exposes its reason on click as well as hover.

6. A repeat is a `Repeat` tag on the new try, with its readable reason and the
   previous try available on hover/in the selected attempt detail. It adds no
   separate rail row or extra cause-link row. Preserve the existing `led_by`
   navigation in the detail pane and access to the failed verification mark.
   Check-driven implementation repeats still lead back to their failed Checks
   result through the existing step rows; do not invent a verification link.

7. Split past history at existing `restart_at_plan` boundaries, using `past` to
   decide which groups are folded. A repeat never starts another group. Show
   each past group as one disclosure summary, e.g.
   `Run 1 · Plan ✓ · Implement ✓`. Derive each step's latest status from its
   actual result/verification; do not mark an unverified answer as committed or
   hide earlier failures behind a later success (retain a compact failure hint).
   Expanding reveals all its tries, verification marks and reasons. Open the group
   containing the selected step or verification. Keep the current group open and
   do not reset a person's expanded group on ordinary drawer redraws; store only
   ephemeral disclosure state with the drawer if needed. A waiting task whose
   history is entirely past still gets no invented pending steps.

## Implementation scope

Implement the projection and compact rows in `src/taskloop/dash/static/rail.js`.
Keep functions bounded and avoid a general event abstraction. Preserve the public
helpers imported by `drawer.js`, updating their wording where needed. Make only
the small `drawer.js` integration needed for disclosure state, truthful restart
detail wording and readable repeat reasons. Update stale comments in `ui.js` if
they describe verification as a separate rail row.

Update `src/taskloop/dash/static/words.js` with words for raw `verification` and
`unsafe` causes and other existing repeat reasons used in this presentation.
Use the same table for tag hover/detail text, preserve raw codes as hover text,
and retain the unknown-code fallback. Do not translate arbitrary explanation
prose or add a second vocabulary owner.

In `src/taskloop/dash_board.py::_repeat`, classify actual repeats before the
restart case, consistent with the history's `previous_attempt_id`/try data.
Use `Reason not recorded` for an unstored restart cause, preserving recorded
repeat reasons. No change to `dash_model`, history payloads or cause writers is
needed. In particular, handle the current history placeholder in presentation.

Extend `tests/cli/test_dash_words.py` and focused dashboard read tests in
`tests/steps/test_dash_read.py`. If new Tailwind classes are needed, run `just css`
and include the generated `dash.css`; reuse existing classes where practical.
Keep source/test size limits and add no subprocess-based JavaScript test runner.

## Verification and acceptance

- Extend the words tests for raw causes, unsettled reasons and rejection wording;
  retain coverage that every named backend verification reason has words.
- Extend dashboard read coverage for an unstored restart explanation and a plan
  repeat classified as repeat. Retain the verification endpoint/listing and
  task-wide try-number tests: rendering must not require deleting API entries.
- Exercise the real ES modules with deterministic history fixtures in a browser:
  a healthy finished task has four primary rows (Plan, Implement, Checks, Land);
  the reviewed restart/repeat shape fits about eight visible lines with past
  history folded and routine gaps hidden. The screenshot is not present in the
  repository; use equivalent explicit input covering the described rows, and
  compare to the original if available during implementation.
- Check successful, reused, failed, pending and absent verifications; unsafe and
  rejected-path/rule failures; check-driven and plan repeats; multiple past runs;
  waiting with all history past; gap boundaries at 119/120 seconds; missing times;
  and restart dates today versus an earlier local date. Confirm every failure is
  reachable after expanding history, mark clicks open Result from every tab,
  keyboard activation works, and selection/disclosures survive a redraw. Inspect
  both themes and ensure short summaries expose their full reasons on click.
- Read the justfile, then run `just check` and `just test` for the implementation.
  The current test recipe targets `tests/cli`, `tests/steps`, `tests/rules` through
  the installed successor package. Do not run additional whole-suite/live tests
  or use an editable baseline/PYTHONPATH. Record actual results and any environment
  failure without claiming a pass.

This planning step changes only this document; it does not claim implementation
or gate completion.


## As built

The rail now projects agent verifications onto separately focusable Result buttons,
keeps one row per step try, folds past history at restart boundaries, and remembers
open disclosures with the drawer. Repeats are inline tags; restarts carry local time
and any recorded wait. Factory gaps shorter than two minutes are hover information;
no elapsed gap is attributed to an individual commit/publish action. The old restart
placeholder becomes `Reason not recorded` in presentation and in the board fallback.
Plan repeats are classified before restarts. All existing history and Result endpoints
remain intact. Compact step labels omit the extra emoji to make room for repeat tags
and marks in the existing rail width. Agent summaries already covered by an attached
verification are suppressed, keeping one failure explanation line. The stylesheet was rebuilt with pinned Tailwind
4.1.11 (the unversioned shim was unavailable, so its installed bin was added to PATH).

Extended `tests/cli/test_dash_words.py` and `tests/steps/test_dash_read.py` cover cause
words, rejection wording, an unstored restart reason and correct Plan repeat classification.
New `tests/dash/rail.test.js`, loaded by `tests/dash/rail.html`, exercises the real ES modules:
healthy four-row history; verification states and failure navigation; 119/120-second gaps;
missing/invalid timing; local restart dates; plan, implementation and check-driven repeats;
multiple past histories, earlier failure hints, selection and disclosure redraws; and
verification Result navigation from Lines, Prompt and Result, retaining listing/rule detail.
For a browser run, serve the repository statically and open the HTML, or use Chromium
with `--headless --allow-file-access-from-files --virtual-time-budget=5000 --dump-dom`
on its file URL; the root `data-result` and `#results` report success/failure.

Validation in this slot: `just check` passed (lint, types, nine import contracts),
`just test` passed (3,351 passed, 13 skipped), and the focused dashboard tests passed.
`node --check` passed for the changed rail/drawer modules and browser test module.
A temporary semantic DOM harness under `$TMPDIR` executed all seven JavaScript contract
groups successfully, including drawer interactions. This is not browser/layout evidence.
The cached Playwright Chromium executable could not load `libglib-2.0.so.0`; the system
Chromium failed on sandbox-denied socket operations, including with crash reporting
disabled. Consequently actual browser layout, keyboard activation, screenshots and visual
review of both themes remain unverified here. No screenshot was available in the repository.
