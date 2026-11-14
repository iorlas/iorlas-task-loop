# Header
Task: tl-8bh9.14.151.3
Base: ddd02a30f27d46341168b567777fcb23529b6860
Depth: small; one display behaviour.
Missing decision/unlanded dependency: none.
Evidence budget: 6 model calls.
Size: 4 changed files (tests/plan included), 1 behaviour, 30 implement model calls.

## Outcome and non-goals
Terminal failed agent attempts expose a stable end timestamp even before their slot is released. Keep genuinely unavailable times unknown. No schema, lifecycle, duration measurement or sibling dashboard fixes.

## Settled decisions
- Use an existing recorded timestamp; never substitute the dashboard read clock.
- Preserve release time; otherwise use captured diagnostics modification time, following the existing input-evidence timestamp pattern.
- Resolve captured evidence through its stored FileRef so execution-specific directories are respected.
- Keep elapsed measurements in the existing duration read model.

## Open decisions
- None.

## Change map
- `src/taskloop/evidence_files.py`: add `captured_at(FileRef)` beside `started_at`; guarded read of captured evidence modification time. Consult `capture`, `capture_refs`, `_capture_text` as producers.
- `src/taskloop/dash_task.py`: `_agent` fills terminal `AttemptDetail.ended_at` from release or captured evidence; consult its caller `_history` and public `build_task` path.
- `tests/steps/test_dash_read.py`: extend `saved_ask`/task-detail fixtures with deterministic captured timestamps and assertions for unreleased and released failures, running attempts and unavailable evidence.
- `docs/design/tl-8bh9.14.151.3/plan.md`: new implementation plan.

## Read list
- `src/taskloop/dash_task.py:103-117` — end-time projection to change.
- `src/taskloop/dash_task.py:231-249` — `_agent` caller.
- `src/taskloop/dash_task.py:272-288` — public task-detail integration.
- `src/taskloop/evidence_files.py:229-235` — existing display timestamp reader.
- `src/taskloop/evidence_files.py:331-345` — captured-file producers and diagnostics file.
- `src/taskloop/attempt_types.py:110-118` — FileRef input contract.
- `src/taskloop/attempt_types.py:280-323` — stored execution/result.
- `src/taskloop/attempt_reads.py:20-28` — existing release timestamp.
- `src/taskloop/attempt_result.py:53-83` — collected failures and success distinction.
- `src/taskloop/dash_model.py:169-186` — existing nullable end timestamp contract.
- `src/taskloop/dash_duration.py:30-44` — independent terminal duration projection.
- `src/taskloop/dash/static/rail.js:14-38` — timestamp consumers and history gaps.
- `src/taskloop/dash/static/drawer.js:324-341` — detail timing consumer.
- `tests/steps/test_dash_read.py:54-99` — saved failed execution and release fixture.
- `tests/steps/test_dash_read.py:325-338` — ended-attempt coverage.

## Contract
Intent: project terminal attempts before slot cleanup. Effect: read release time or stat the stored diagnostics reference through EvidenceFiles. Result: existing nullable ISO `AttemptDetail.ended_at`; running attempts remain null. Missing/unreadable evidence returns None. No writes, new states or stored fields. Terminal-duration rendering is already delivered; the gap is `_agent`'s release-only timestamp.

## Work packages
1. Update `evidence_files.py` and `dash_task.py`; add regression coverage in `test_dash_read.py`. Closes A1-A4. Run the focused dashboard read tests, then `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A1. A collected failed agent attempt with captured evidence and no slot release has the recorded capture end time, stable across dashboard reads.
A2. A released failed attempt retains its recorded release end time when capture and release differ.
A3. A running attempt has no end time even if evidence files exist.
A4. Missing or unreadable terminal evidence with no release leaves time unknown and task detail available.
