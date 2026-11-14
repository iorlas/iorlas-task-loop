# Header
Task: tl-8bh9.14.107.5
Base: fd1be071c69c3e6eaf063d3e19ed8091a1049f3a
Depth: small
Reason: one branch reconciliation behaviour.
Owner decision: none. Unlanded dependency: none.
Evidence: 6 model calls.
Size: 2 changed files; 1 independent behaviour; 35 implement model calls.

## Outcome and non-goals
Cover admission from owned remote work without an attempt row after reopening intact state, preserving branches through reevaluation. No branch sweeper, remote deletion, schema change or historical-attempt reconstruction.

## Settled decisions
Resume through normal admission and preparation, without manufacturing historical attempts.
Existing local-first, otherwise remote-tracking source selection remains authoritative.
Exercise an owned push and its retained remote-tracking ref.
Existing tests cover remote tips with an attempt; the gap is no-row admission across database reopen.
Evidence reconciliation is delivered at the base; retain its coverage.

## Open decisions
- None.

## Change map
- `tests/steps/test_prepare.py` — add restart coverage using `pushed`, `leave`, `execute` and admission fixtures.
- `src/taskloop/admit.py` — consult `AttemptAdmission`, `branched`, `free_slots`: no-row admission and source-selection caller.
- `src/taskloop/prepare.py` — consult `refreshed_sources`, `branch_refusal`, `_take` and its preparation caller; retain existing semantics.
- `tests/steps/test_prepare_main.py` — consult existing `branch_refusal` caller tests; preserve their contracts.
- `tests/steps/test_restart.py` — consult database close/reopen coverage without importing its test.
- `docs/design/tl-8bh9.14.107.5/plan.md` — new plan at the task's integration path.

## Read list
- `tests/steps/test_prepare.py:53-116` — remote producer and execution helpers.
- `tests/steps/test_prepare.py:139-220` — existing remote-source and refusal contracts.
- `tests/steps/test_prepare.py:330-389` — initial admission setup and unrelated-history refusal coverage.
- `src/taskloop/admit.py:145-225` — admission orchestration, no-row check and claim authorization.
- `src/taskloop/admit.py:350-385` — free slots and the sole external caller of refreshed source selection.
- `src/taskloop/prepare.py:107-171` — source observation and refresh producer.
- `src/taskloop/prepare.py:189-245` — branch take and preparation caller.
- `tests/steps/test_prepare_main.py:17-97` — other source-selection callers.
- `tests/steps/test_restart.py:28-72` — close every connection and reopen the same database.

## Contract
No new runtime types, fields or states. Intent: eligible task without attempt/reservation, owned published branch and retained remote-tracking tip. Effect: reopen the database and construct fresh admission/execution objects. Result: one ordinary attempt/reservation selects the retained source and preserves its commits. Refusal leaks no claim or reservation. Compare unrelated local and remote refs before and after; release never deletes branches.

## Work packages
1. In `tests/steps/test_prepare.py`, create owned committed/pushed work without rows, remove its fixture-local branch and reopen a file-backed database. Cover success and refusal for A.
2. In that file, compare unrelated refs and reevaluate for A. If coverage exposes a runtime defect, revise this test-focused scope. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each.

## Acceptance behaviours
A. After an intact restart, owned remote task work without an attempt row resumes from its retained commits exactly once, or remains safely available after refusal without leaked ownership; unrelated branches retain their names and tips across both initial reconciliation and reevaluation.
