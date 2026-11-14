# Header
tl-8bh9.14.167; base 29d4433dfbef492ac63654b766357cb87ddc0dc3
Depth: medium; three behaviours.
No missing decision or unlanded dependency. Evidence budget: 12 model calls.
Size: 26 changed files including tests/plan; 3 independent behaviours; 80 implement model calls.

## Outcome and non-goals
Active execution and dashboard ages count runtime across clock changes. Show observations and genuine timeout explanations. Preserve admission, audit, claim and reconciliation ownership. No shelf change, power management or schema migration.

## Settled decisions
- Pinned any-agent 0.15.0 already enforces monotonic timeout, per the supplied owner decision.
- Convert the active entry's remaining epoch allowance once at execution entry; subtract monotonic preparation/runtime elapsed thereafter.
- Preserve epoch admission checks before dispatch and actual wall timestamps for audit.
- A jump never stops/holds/retries an agent. Report “Host slept or the clock changed”; detection cannot distinguish them.
- Genuine exhaustion retains run:timeout and durable owner notification; describe the allowance in words without requesting a CLI command.
- Same-boot evidence supports restart; incompatible evidence gives unknown duration.

## Open decisions
- None.

## Change map
- src/taskloop/attempt_clock.py (new): runtime deadline and typed observations; integrate with Attempts, registration and sink polling.
- src/taskloop/timing_file.py (new): validated timing snapshot owner; integrate through EvidenceFiles.directory.
- src/taskloop/attempt.py: execute/_start/_run/_call; retain the active allowance, charge preparation elapsed and share timing context.
- src/taskloop/composition.py: open_attempts/_run; inject both clocks and retain runner live forwarding.
- src/taskloop/session.py: registration_hook; use the active allowance at worker registration.
- src/taskloop/attempt_entry.py: _capture/_step/resumed; bound post-run retries by the active allowance.
- src/taskloop/command_sink.py: CommandSink.started/feed/poll/end; sample even without activity.
- src/taskloop/recovery/native.py: NativeContinuation sink producer; supply execution-scoped display timing, preserve recovery eligibility.
- src/taskloop/merge/resolve.py: Resolution sink producer; supply explicit display timing context.
- src/taskloop/dash_model.py: Card/AttemptDetail/FeedPage; numeric durations and typed observations.
- src/taskloop/dash_board.py: card_of/build_board; project validated running durations.
- src/taskloop/dash_task.py: build_task and attempt/feed producers; share the timing reader, including card_of's detail caller.
- src/taskloop/dash_composition.py: _ports; inject monotonic reads for board/task/feed.
- src/taskloop/dash/static/ui.js: tick/tickQuiet/quietSpan; numeric duration rendering and monotonic interpolation.
- src/taskloop/dash/static/app.js: card elapsed/quiet producers and refresh tick; consume durations and observations.
- src/taskloop/dash/static/drawer.js: attempt elapsed/quiet producers; consume the shared fields.
- src/taskloop/dash/static/lines.js: touchQuiet; use the feed sample instead of its last epoch timestamp.
- src/taskloop/hold_cause.py: cause; explain genuine runtime exhaustion.
- src/taskloop/hold_text.py: comment; retain the shared owner-notification wording path.
- tests/steps/test_attempt_clock.py and tests/steps/test_dash_clock.py (new): fake-clock execution, evidence and read-model contracts; use existing attempt/dashboard fixtures.
- tests/dash/clock.test.js (new): duration consumers through the existing dashboard test style.

## Read list
- src/taskloop/attempt.py:60-260 — execution ports, preparation, dispatch and budget consumers.
- src/taskloop/composition.py:88-125 — runner and attempt wiring.
- src/taskloop/attempt_entry.py:122-135 — capture bound; also _step/resumed at 199-232.
- src/taskloop/session.py:23-32 — registration deadline consumer.
- src/taskloop/prepare.py:317-332 — pre-dispatch admission gates.
- src/taskloop/environment.py:238-245 — setup admission gate; _command at 355-379 consumes its allowance.
- src/taskloop/merge/prepare.py:20-65 — preparation/merge-agent producers and admission policy.
- src/taskloop/attempt_store.py:178-203 — immutable admission fencing and registration effects.
- src/taskloop/command_sink.py:16-57 — all live timing integration points.
- src/taskloop/evidence_files.py:85-108 — artifact ownership/directories; started_at at 203-209 is the current wall source.
- src/taskloop/dash_board.py:97-127 — card projection; build_board at 155-172 calls it.
- src/taskloop/dash_task.py:95-110 — detail producer; build_task at 275-295 calls card_of; inspect feed producer when extending samples.
- src/taskloop/dash_model.py:21-53 — board contracts; inspect AttemptDetail/FeedPage declarations for matching fields.
- src/taskloop/dash_composition.py:37-64 — board/task/feed clock injection.
- src/taskloop/dash/static/ui.js:102-148 — epoch-based duration consumers.
- src/taskloop/dash/static/app.js:169-184 — card producers; refresh tick at 330-340.
- src/taskloop/dash/static/drawer.js:317-334 — detail duration consumers.
- src/taskloop/dash/static/lines.js:47-54 — live quiet reset caller.
- src/taskloop/hold_cause.py:133-150 — timeout explanation and owner wording.
- src/taskloop/hold_text.py:155-190 — shared explanation/comment rendering.
- src/taskloop/hold.py:206-220 — existing leased notification effect, consult only.
- src/taskloop/recovery/native.py:50-80 — continuation sink producer.
- src/taskloop/merge/resolve.py:56-74 — merge-agent sink producer.
- tests/steps/test_attempt.py:140-172 — execution fixture and remaining-allowance assertion.
- tests/steps/test_dash_read.py:248-276 — board/detail/feed fixture integration.

## Contract
Intent: convert the remaining admission allowance once to an entry-local monotonic deadline shared by registration, runner and capture/resume bounds. Charge preparation elapsed; retain pre-dispatch admission policy and immutable admission.deadline fencing. Keep wall audit time separate. Collection needs no allowance; another entry cannot recover control state from display evidence.

Effect: a pydantic snapshot carries execution/boot identity, paired clock samples, monotonic start/activity, terminal elapsed and observations. One enum/codec owns observation kinds. Compare clock deltas in both directions with a named jitter tolerance; record time and signed discrepancy. Sample on poll and end too. The owner atomically replaces bounded display evidence; write failure never affects execution.

Result: one reader derives nonnegative same-boot ages and frozen terminal elapsed. Invalid/missing/other-boot evidence gives unknown, never epoch-derived ages. Keep calendar timestamps. Clients interpolate numeric samples monotonically and refresh on resume/discontinuity. Observations remain visible alongside a genuine timeout. Existing hold/comment effects notify once.

## Work packages
1. Runtime files attempt_clock.py, attempt.py, composition.py, session.py, attempt_entry.py: fake-clock execution tests close A1, including registration and capture retries.
2. timing_file.py, command_sink.py, sink producers and hold rendering: evidence/reporting tests close A2, including idle/backward jumps and notification idempotence.
3. Dashboard Python/JavaScript files: projection and browser tests close A3, including reconnect and boot mismatch. Run just check 2>&1 | tail -60 and just test 2>&1 | tail -40 once each, last, preserving exit status.

## Acceptance behaviours
A1: A multi-hour wall jump cannot exhaust minutes of active runtime or create run:timeout; actual runtime exhaustion still times out.
A2: Idle/active jumps appear distinctly without holding execution; genuine timeout reaches the owner through durable notification.
A3: Card/detail elapsed and quiet ages survive jumps and dashboard restart; terminal duration freezes, invalid evidence gives unknown.
