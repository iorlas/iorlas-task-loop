# Header
Task: tl-8bh9.14.159.2.1
Base: 6ae80fbdf660bdf4bcdd80c5546fae15aaadb470
Depth: medium; dispatch and manual command.
Decisions: settled; .201 landed.
Evidence budget: 12 model calls.
Size: 45 changed files incl. tests/artifacts; 2 behaviours; 45 implement calls.

## Outcome and non-goals
The naming contract and Read-list exception are delivered; runtime names remain. Rename dispatch and command surfaces. Keep `factory_commit.py` as the Git boundary; result families, stored/action/log/lock vocabulary and dashboard terms belong to other parts.

## Settled decisions
- Apply `.159.1/naming-map.md` operation/command rows with the owner's 2026-11-15 exception delivered by .201.
- Selected rows: `verifier.py` → `commit.py`; `Verifier/VerifyHold` → `FactoryCommit/CommitHold`; its `verify/_verify/_verified` → `commit/_commit/_committed`.
- Selected rows: `operations.Verify.verify` → `Commit.commit`; `verify_task/verify_failure/VERIFY_KINDS` → `commit_task/commit_failure/COMMIT_KINDS`.
- Selected rows: operation `verifier` parameters/fields → `factory_commit`; `Settle.verify` → `Settle.commit`; `open_verifier/open_verify` → `open_factory_commit/open_commit`; round `_verified` → `_committed`.
- Selected rows: CLI `_verify` and parser variable → `_commit` and `commit`; command and dispatch `step verify` → `step commit`. Importers and identical local references follow these rows.
- Exclude result rows, including cause-dependent `VerifyUnavailable/Unsettled`; preserve unrelated wording and serialized words.

## Open decisions
- None.

## Change map
- `src/taskloop/verifier.py` → `src/taskloop/commit.py` (new path): `FactoryCommit/CommitHold`; integrates entry/composition.
- `src/taskloop/operations.py`: `Commit.commit`, `commit_task/commit_failure/COMMIT_KINDS`; rename dispatch.
- `src/taskloop/repeat.py`: `Settle.commit`, `StepRepeat.factory_commit`, `_leftovers/_index`; rename port calls.
- `src/taskloop/round.py`: `RoundPorts.factory_commit`, `_committed`; invoke `commit_task`.
- `src/taskloop/composition.py`: `open_factory_commit`; rename constructor.
- `src/taskloop/cli_composition.py`: `open_commit/open_reads/_starting/open_next`; wire constructors and ports.
- `src/taskloop/cli_step.py`: parser, `_commit`, `OPERATIONS`; change command/help/dispatch.
- `src/taskloop/attempt_entry.py`: `_step`; invoke `FactoryCommit.commit` under entry custody.
- `tests/steps/test_operations.py`: `FakeVerifier`; rename callable port.
- `tests/steps/test_repeat.py`: `Verifies`, `repeater`, late fake; update signatures and keyword callers.
- `tests/steps/test_repeat_dispatch.py`: `Racing`; rename callable port during takeover.
- `tests/steps/test_round.py`: `Recorded/Bench`; rename port and assertions.
- `tests/steps/test_check_operations.py`: `Recorded`; rename Git fact field `commit` to `sha` and its accesses before adding callable `commit`.
- `tests/steps/test_recovery_entry.py`: patched callable; rename target/signature.
- `tests/steps/test_verifier.py`: helper `verifier`; rename helper and annotation.
- `tests/steps/test_slot_lock.py`: helper `verifier`; rename signature/callers.
- `tests/steps/killed_rounds_bench.py`: `install_hooks`; rename wrapper/patch, retain effect labels.
- `tests/steps/test_restart.py`: `complete_round`; rename bound method/patch, retain action words.
- `tests/cli/test_step_cli.py`: command routing/output cases; accept `commit` and reject removed spelling.

The exception covers remaining callers: imports, import-contract/ratchet paths, help invocations and public-surface command fixtures. Their changes follow selected rows only; retain result payloads. No map edits.

## Read list
- `docs/glossary.md:145-171` — factory commit boundary and verdict meaning.
- `docs/design/tl-8bh9.14.159.1/naming-map.md:14-64` — selected rows and operation ordering.
- `src/taskloop/plan_step.py:77-105` — rename exception.
- `src/taskloop/verifier.py:40-197` — operation, custody and error paths; destination is new.
- `src/taskloop/operations.py:513-532` — orchestration; also 58-93 for protocol and 599-606 for failure mapping.
- `src/taskloop/repeat.py:44-131` — port, signature and repeat gates.
- `src/taskloop/round.py:347-361` — dispatch; also 113-124 for typed ports and 250-255 for caller.
- `src/taskloop/composition.py:204-210` — shared writer, custody and timing.
- `src/taskloop/cli_composition.py:115-196` — read/repeat/round composition; also 320-334 for manual composition.
- `src/taskloop/cli_step.py:80-88` — command parser; also 268-270 for handler and 318-332 for dispatch.
- `src/taskloop/attempt_entry.py:218-248` — entry custody and collection ordering.
- `src/taskloop/attempt_types.py:1-65` — shared port identities and repeat vocabulary; no edit.
- `tests/steps/test_operations.py:145-160` — fake signature; existing verdict/order assertions at 404-457.
- `tests/steps/test_repeat.py:130-158` — fake and helper signatures; late fake at 506-515.
- `tests/steps/test_repeat_dispatch.py:439-450` — takeover port.
- `tests/steps/test_round.py:128-170` — typed fake and recording; dispatch assertions at 297-335.
- `tests/steps/test_check_operations.py:235-260` — field/method collision.
- `tests/steps/test_recovery_entry.py:80-105` — patched operation under custody.
- `tests/steps/test_verifier.py:135-145` — helper signature and constructor.
- `tests/steps/test_slot_lock.py:80-85` — helper signature and constructor.
- `tests/steps/killed_rounds_bench.py:146-165` — typed hook and patch target.
- `tests/steps/test_restart.py:123-149` — restart ordering hook.
- `tests/cli/test_step_cli.py:297-307` — output contract; routing matrix at 749-760.

Selected rows cover omitted files; C is their no-match scan.

## Contract
Intent: `Commit.commit(AttemptKey)` or `Settle.commit(AttemptKey)`. Effect: existing store, custody, observation, Git and timing ports. Result: unchanged `VerifyResult`; no state/field changes.

`commit_task(reader, factory_commit, releaser, publisher, backlog, task_id)` retains `VerifiedTask | Failed`: terminal verdict, settled release, then publication on success, with separate failure explanations. Reuse avoids Git; unknown evidence/superseded ownership prevent writes.

CLI arguments/formats stay intact through `open_commit`; removed spelling fails before effects. Imports use `taskloop.commit`, without aliases or old methods. Git `Committed(sha)` remains distinct from verdict types.

## Work packages
1. Rename operation/protocol/helpers, wiring, hooks and contract paths in the Change map's source/step tests; fix the field collision. Closes A and operation names in C.
2. Rename CLI parser/handler/dispatch and command callers, including help/public-surface fixtures; extend rejection coverage in CLI tests. Closes B-C.
3. After `just install`, run focused operation, CLI, entry, repeat, round and restart cases via `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`. Check C; run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last, preserving exit status. Validates A-C.

## Acceptance behaviours
A. Entry, repeat, round and manual dispatch reach `FactoryCommit.commit` through owning ports; reuse, custody fencing, staged-path refusal, repeat eligibility, release/publication ordering and timing retain existing outcomes.
B. `tl step commit` preserves flags and output formats through `open_commit` and `commit_task`; the removed subcommand fails parsing without effects.
C. `rg -nw -e 'Verifier|VerifyHold|verify_task|verify_failure|VERIFY_KINDS|verifier|open_verifier|open_verify|_verified|taskloop[.]verifier|verifier[.]py|step verify|class Verify|: Verify|^[[:space:]]+Verify,|"step", "verify"' src/taskloop tests/steps tests/cli tests/rules .importlinter` returns no matches; the old module path and operation methods are absent. Build negative command input from pieces so it does not retain an obsolete command string.
