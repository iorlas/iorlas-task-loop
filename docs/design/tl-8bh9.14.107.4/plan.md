# Header
tl-8bh9.14.107.4; base 1793cc8b08c882ee83229efa62bb435ee84d8274. Depth: small; one admission-evidence behaviour. No missing decision or stated unlanded dependency. Evidence budget: 6 model calls. Size: 2 changed files, 1 independent behaviour, 45 implement model calls.

## Outcome and non-goals
Cover restart after input writes before admission commits. Immutable writes and fresh keys permit reevaluation with unreferenced bytes retained. Exclude sweeping, claim recovery, session continuation and remote-branch recovery.

## Settled decisions
- Release unreferenced evidence by retaining bytes and permitting fresh-key admission.
- Rows and reservations own state; artifact paths confer no ownership.
- Rollback preserves prior reservation state.
- Keep production contracts and schema; test existing guarantees.

## Open decisions
- None.

## Change map
- `tests/steps/test_evidence_restart.py` (new): crash/reopen cases using admission fixtures.
- `src/taskloop/evidence_files.py`: consult `put_input`, `_write`, `directory`; immutable producer.
- `src/taskloop/admit.py`: consult `AttemptAdmission.admit`, `_claimed`, `_commit`; initial producer.
- `src/taskloop/admit_chain.py`: consult `ChainAdmission.admit_repeat`, `_takeover`, `NextAdmission.admit_next`, `_advance`; chain producers.
- `src/taskloop/check_repeat/repair.py`: consult `put_input` and `store.admit` caller; repair producer.
- `src/taskloop/merge/resolve.py`: consult `Resolution.__call__`; input caller with existing merge work.
- `src/taskloop/operations.py`: consult `ports.admission.admit`, `ports.advance.admit_next` callers.
- `src/taskloop/repeat.py`: consult `_takeover`, the `admit_repeat` caller.
- `src/taskloop/composition.py`: consult `open_admission`, `open_chain`, `open_advance` wiring.

## Read list
- `src/taskloop/evidence_files.py:66-108` — immutable storage and key isolation.
- `src/taskloop/evidence_files.py:273-275` — input producer.
- `src/taskloop/admit.py:152-178` — input before claim.
- `src/taskloop/admit.py:213-317` — claim and commit.
- `src/taskloop/admit_chain.py:102-170` — repeat transaction.
- `src/taskloop/admit_chain.py:239-337` — advance transaction.
- `src/taskloop/admit_rows.py:12-28` — shared row writes.
- `src/taskloop/check_repeat/repair.py:45-78` — repair admission.
- `src/taskloop/merge/resolve.py:32-78` — existing-work caller.
- `src/taskloop/operations.py:478-488` — initial and advance callers.
- `src/taskloop/repeat.py:156-166` — repeat caller.
- `src/taskloop/composition.py:213-255` — runtime construction.
- `tests/steps/test_admit.py:59-177` — input spy and admission helpers.
- `tests/steps/test_repeat.py:112-179` — repeat helpers.
- `tests/steps/test_advance.py:21-50` — advance fixture.
- `tests/steps/test_check_repeat.py:1-90` — repair setup.
- `tests/steps/test_restart.py:24-90` — intact-state restart pattern.

## Contract
No new types, fields or states. Intent: fresh `AttemptKey`. Effect: immutable `put_input` before the row transaction. Result: absent rows leave inert bytes; retry selects another key. Committed `FileRef` and reservations remain authoritative. Interrupt after input creation before claim, and at chain/repair commit boundaries; retain files, close connections and reconstruct ports before retry. Avoid ordinary compensation as a crash simulation. Merge inputs belong to existing work, outside fresh admission.

## Work packages
1. Add initial, repeat, advance and check-repair interruption cases plus committed-row controls in the new test module. Compare prior rows, evidence and unrelated sentinels across restart. Closes A.
2. Run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
A. Intact-state restart after input creation without a new committed row permits fresh-key reevaluation across admission paths, preserves prior ownership and evidence/user bytes, and keeps committed-row references and reservations authoritative.
