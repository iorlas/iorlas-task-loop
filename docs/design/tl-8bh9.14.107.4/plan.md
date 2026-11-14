# Header
tl-8bh9.14.107.4; base 9cd27491744c1366b6c24e67c9aae68954f00af7.
Depth: small
Reason: one admission-evidence behaviour.
Decision missing: no; unlanded dependency: none stated.
Evidence budget: 6 model calls.
Size: 2 changed files; 1 independent behaviour; 45 implement model calls.

## Outcome and non-goals
Prove fresh-key admission after interrupted input creation and DB reopen. Exclude sweeping, claim recovery, session continuation and remote branches.

## Settled decisions
- Release unreferenced evidence by retaining bytes and permitting fresh-key admission.
- Rows and reservations own state; artifact paths confer no ownership.
- Rollback preserves prior reservation state.
- Immutable writes and key isolation are delivered; add reopen coverage. No schema change.

## Open decisions
- None.

## Change map
- `tests/steps/test_evidence_restart.py` (new): crash/reopen cases using fixtures below.
- `src/taskloop/evidence_files.py`: `put_input`, `_write`, `directory`; producer.
- `src/taskloop/admit.py`: `AttemptAdmission.admit`, `_claimed`, `_commit`; consult.
- `src/taskloop/admit_chain.py`: `ChainAdmission.admit_repeat`, `_takeover`, `NextAdmission.admit_next`, `_advance`; consult.
- `src/taskloop/admit_rows.py`: `reserve`, `insert_attempt`; consult.
- `src/taskloop/check_repeat/repair.py`: `put_input`, `store.admit`; producer/caller.
- `src/taskloop/check_repeat/store.py`: `CheckRepeatStore.admit`; consult commit.
- `src/taskloop/merge/resolve.py`: `Resolution.__call__`; existing-work caller.
- `src/taskloop/operations.py`: `ports.admission.admit`, `ports.advance.admit_next`; callers.
- `src/taskloop/repeat.py`: `_takeover`; repeat caller.
- `src/taskloop/composition.py`: `open_admission`, `open_chain`, `open_advance`; wiring.

## Read list
- `src/taskloop/evidence_files.py:66-108` — immutable storage and key isolation.
- `src/taskloop/evidence_files.py:273-275` — input producer.
- `src/taskloop/admit.py:152-178` — input before claim.
- `src/taskloop/admit.py:213-317` — claim and commit.
- `src/taskloop/admit_chain.py:102-170` — repeat transaction.
- `src/taskloop/admit_chain.py:239-337` — advance transaction.
- `src/taskloop/admit_rows.py:12-28` — shared row writes.
- `src/taskloop/check_repeat/repair.py:45-78` — repair admission.
- `src/taskloop/check_repeat/store.py:78-112` — repair commit.
- `src/taskloop/merge/resolve.py:32-78` — existing-work caller.
- `src/taskloop/operations.py:478-488` — initial and advance callers.
- `src/taskloop/repeat.py:156-166` — repeat caller.
- `src/taskloop/composition.py:213-255` — runtime construction.
- `tests/steps/test_admit.py:59-177` — input spy and admission helpers.
- `tests/steps/test_repeat.py:112-143` — repeat helper.
- `tests/steps/test_repeat.py:350-419` — callers/race coverage.
- `tests/steps/test_advance.py:21-50` — advance fixture.
- `tests/steps/test_check_repeat.py:45-90` — repair setup.
- `tests/steps/check_repeat_bench.py:27-41` — repair wiring.
- `tests/steps/test_restart.py:24-90` — intact-state restart pattern.

## Contract
No new types, fields or states. Intent: fresh `AttemptKey`. Effect: immutable `put_input` before admission commits. Result: absent rows leave inert bytes; retry selects another key. Committed `FileRef` and reservations remain authoritative. Interrupt before claim or chain/repair commit; close connections and rebuild ports. Normal compensation is not a crash. Merge inputs belong to existing work.

## Work packages
1. Add initial, repeat, advance and repair crash/reopen cases with committed-row controls. Compare rows and unrelated file bytes. Closes A.
2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A. Reopened admission with unreferenced input succeeds with a fresh key across all four paths, preserves evidence/user bytes and prior ownership, and retains committed-row references and reservations without duplicate admission.
