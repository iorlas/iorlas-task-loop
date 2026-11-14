# Header
tl-8bh9.14.107.4; base f99143708fba9163ea75f95a8facb62c2e8fe507. Depth: small; one evidence-reconciliation behaviour. No missing owner decision or stated unlanded dependency. Evidence budget: 6 model calls. Size: 2 changed files including this plan, 1 independent behaviour, 35 implement model calls.

## Outcome and non-goals
Existing immutable writes and database-owned reservations already permit release by retaining unreferenced evidence. The gap is crash/restart coverage. Exclude directory sweeping, claim recovery, session continuation and remote-branch recovery.

## Settled decisions
- Release unreferenced evidence by retaining its bytes and allowing reevaluation with a fresh key.
- A failed repeat or advance leaves the previous reservation authoritative.
- Artifact paths authorize neither deletion nor state reconstruction.
- Keep the schema and production contracts; close the observed gap with behaviour tests.

## Open decisions
- None.

## Change map
- `tests/steps/test_evidence_restart.py` (new): crash/reopen scenarios for `AttemptAdmission.admit`, `ChainAdmission.admit_repeat` and `admit_next`; use `test_admit.py` fixtures and `test_restart.py`'s restart pattern.
- `src/taskloop/admit.py`: consult `AttemptAdmission.admit`, `_claimed` and `_commit`, the initial input producer and row-commit boundary; no planned edit.
- `src/taskloop/admit_chain.py`: consult `ChainAdmission.admit_repeat`, `_takeover` and `admit_next`, both other `put_input` callers; no planned edit.
- `src/taskloop/evidence_files.py`: consult `EvidenceFiles.put_input`, `directory` and `_write`, the shared producer; no edit.

## Read list
- `src/taskloop/admit.py:152-178` — initial input before admission.
- `src/taskloop/admit.py:213-317` — claim intent and transactional reservation/attempt writes.
- `src/taskloop/admit_chain.py:102-170` — repeat input and fenced takeover.
- `src/taskloop/admit_chain.py:239-337` — next-step input and commit boundary.
- `src/taskloop/evidence_files.py:66-108` — file confinement, immutability and key-derived directory.
- `src/taskloop/evidence_files.py:273-275` — shared admitted-input producer.
- `src/taskloop/admit_rows.py:1-28` — reservation, attempt insertion and generation writes.
- `src/taskloop/attempt_types.py:107-134` — keys, references and admission contract.
- `tests/steps/test_admit.py:59-67` — file-effect interception pattern.
- `tests/steps/test_admit.py:134-177` — admission fixtures and evidence assertions.
- `tests/steps/test_restart.py:1-90` — fresh-runtime intact-database coverage.

## Contract
No new types, fields or states. Intent: admission selects a fresh `AttemptKey`. Effect: `put_input` precedes the row transaction. Result: without a committed row, retained bytes are inert and reevaluation uses another key; with a row, its `FileRef` and reservation remain authoritative. Release never deletes, renames or adopts evidence. Inject crashes outside ordinary exception compensation; reopen the same database with fresh operations.

## Work packages
1. Add the new test module: interrupt initial admission immediately after input creation and before claim, reopen, then admit successfully with a distinct key. Check the first input and unrelated sentinel files byte for byte. Closes A.
2. Extend that module to failed repeat and next-step transactions, and a committed-row control. Reopen before retrying; verify reservation ownership, input references and retained bytes. Closes A. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last.

## Acceptance behaviours
A. Across initial admission, repeat and step advance, restart after input creation without a committed new row permits reevaluation with a fresh key, preserves the prior reservation where present, and leaves both unreferenced evidence and unrelated data intact; a committed-row control retains its original evidence reference and reservation.
