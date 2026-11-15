# Header
Task: tl-8bh9.14.159.2.1
Base: 2b8754b78a9fdd0bc551e59c21bd95220ff50087
Depth: medium; shared dispatch and manual command.
Decisions: settled. Dependency .201: landed.
Evidence budget: 12 model calls.
Size: 45 changed files incl. tests/artifacts; 2 behaviours; 45 implement calls.

## Outcome and non-goals
Expose `FactoryCommit.commit` and `tl step commit` through existing entry, repeat and round integrations. A covers shared dispatch; B covers command routing. Keep `factory_commit.py` as the Git boundary. Typed-result families, stored vocabulary, action/status/log/lock words and dashboard terminology belong to later parts.

## Settled decisions
- Apply the operation/command rows of `.159.1/naming-map.md`; the owner answer dated 2026-11-15 authorizes the `.201` Read-list exception.
- Rename `verifier.py` to `commit.py`, `Verifier` to `FactoryCommit`, `VerifyHold` to `CommitHold`, and its `verify/_verify/_verified` methods to `commit/_commit/_committed`.
- Rename `operations.Verify.verify` to `Commit.commit`; `verify_task/verify_failure/VERIFY_KINDS` to `commit_task/commit_failure/COMMIT_KINDS`.
- Rename operation parameters/fields `verifier` to `factory_commit`, `Settle.verify` to `Settle.commit`, `open_verifier` to `open_factory_commit`, `open_verify` to `open_commit`, and the round's `_verified` to `_committed`.
- Rename the CLI parser variable and handler to `commit/_commit`, and its command/dispatch spelling to `commit`. Keep unrelated ordinary uses of verify and verified.

## Open decisions
- None.

## Change map
- `src/taskloop/verifier.py` → `src/taskloop/commit.py` (new path): `FactoryCommit`, `CommitHold`, renamed methods; integrate entry and composition.
- `src/taskloop/operations.py`: `Commit.commit`, `commit_task/commit_failure/COMMIT_KINDS`; preserve ordered effects.
- `src/taskloop/repeat.py`: `Settle.commit`, `StepRepeat.factory_commit`, `_leftovers/_index`; rename port calls.
- `src/taskloop/round.py`: `RoundPorts.factory_commit`, `_committed`; invoke `commit_task`.
- `src/taskloop/composition.py`: `open_factory_commit`; construct the renamed operation.
- `src/taskloop/cli_composition.py`: `open_commit/open_start/open_next/open_reads`; wire constructors and ports.
- `src/taskloop/cli_step.py`: parser, `_commit`, `OPERATIONS`; replace command, help and dispatch.
- `src/taskloop/attempt_entry.py`: `_step`; invoke `FactoryCommit.commit` under entry custody.
- `tests/steps/test_operations.py`: `FakeVerifier`, verdict/order cases; update signature and assertions.
- `tests/steps/test_repeat.py`: `Verifies`, `repeater`, late fake; update signatures and keyword callers.
- `tests/steps/test_repeat_dispatch.py`: takeover fake; rename operation method.
- `tests/steps/test_round.py`: `Recorded`, port fixture; update signatures and call recording.
- `tests/steps/test_check_operations.py`: fake's Git `commit` field becomes `sha`, including accesses, to allow its callable `commit` method.
- `tests/steps/test_recovery_entry.py`: patched operation function; rename target and signature.
- `tests/cli/test_step_cli.py`: routing/output cases; accept `commit`, reject old spelling.

Omitted files change solely by the selected one-to-one rows: imports, configuration paths and identical comments/local references. Follow these rows across callers; exclude other map rows.

## Read list
- `docs/glossary.md:145-171` — factory commit boundary and retained verdict meaning.
- `docs/design/tl-8bh9.14.159.1/naming-map.md:14-64` — selected operation and command rows, boundaries.
- `src/taskloop/plan_step.py:77-105` — committed rename exception.
- `src/taskloop/verifier.py:40-197` — current operation and custody/error paths; destination is new.
- `src/taskloop/operations.py:58-93` — protocol and failure mapping.
- `src/taskloop/operations.py:513-532` — result, release and publication ordering.
- `src/taskloop/repeat.py:44-131` — repeat port, gate and feedback.
- `src/taskloop/round.py:111-125` — injected operation port.
- `src/taskloop/round.py:245-256` — existing dispatch action.
- `src/taskloop/round.py:347-359` — completion and operation dispatch.
- `src/taskloop/composition.py:199-209` — writer, custody and timing composition.
- `src/taskloop/cli_composition.py:110-196` — status, repeat and round constructors.
- `src/taskloop/cli_composition.py:320-334` — guarded manual composition.
- `src/taskloop/cli_step.py:80-88` — parser registration and options.
- `src/taskloop/cli_step.py:268-270` — handler; also consult `OPERATIONS` at 327.
- `src/taskloop/attempt_entry.py:218-248` — entry integration and collection ordering.
- `src/taskloop/attempt_types.py:1-80` — retained result type imports; no edit.
- `tests/steps/test_operations.py:145-160` — operation fake; verdict/order assertions at 404-423 and 426-457.
- `tests/steps/test_repeat.py:130-158` — fake and injection helper; late fake at 506-515.
- `tests/steps/test_repeat_dispatch.py:439-450` — takeover during operation.
- `tests/steps/test_round.py:128-170` — recorded operation port; dispatch assertions at 297-335.
- `tests/steps/test_check_operations.py:235-260` — fake field/method collision and effect ports.
- `tests/steps/test_recovery_entry.py:80-105` — patched operation under entry custody.
- `tests/cli/test_step_cli.py:290-307` — command output contract; routing matrix at 749-760.

The rename exception covers remaining callers and import-contract configuration; targeted searches locate their sites.

## Contract
Intent: invoke `Commit.commit(AttemptKey)` or repeat's `Settle.commit(AttemptKey)`. Effect: use existing store, custody, observation, Git and timing ports. Result: existing `VerifyResult` and stored verdict; no new state or field.

`commit_task(reader, factory_commit, releaser, publisher, backlog, task_id)` returns existing `VerifiedTask | Failed`. Release follows a terminal verdict; publication follows success; failures retain separate explanations. Stored verdicts require no Git access. Unknown evidence and superseded ownership prevent writes. Preserve repeat eligibility, collection and timing.

The command uses `open_commit` with existing arguments/formats; the old spelling is a parser error. Imports use `taskloop.commit` without aliases. The Git boundary's `Committed(sha)` remains distinct.

## Work packages
1. Rename operation/protocol/helpers and composition; update entry/repeat/round and signature-bearing fakes, including the field collision. Apply selected-row importer changes. Files: the Change map's source and step tests. Closes A.
2. Replace CLI parser/handler/dispatch, extend CLI rejection coverage, and update mechanical references/import contracts. Files: CLI source/tests and selected-row callers. Closes B–C.
3. After `just install`, run focused operation/CLI/entry/repeat/round cases with `uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`. Run C; then run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each, last. Preserve command exit status. Validates A–C.

## Acceptance behaviours
A. Entry, repeat, round and manual dispatch reach `FactoryCommit.commit` through their owning ports; stored-result reuse, custody fencing, staged-path refusal, repeat eligibility and release/publication ordering retain their existing outcomes and timing.
B. `tl step commit` routes the existing flags and output formats through `open_commit` and `commit_task`; the old subcommand is rejected without effects.
C. `rg -nw -e 'Verifier|VerifyHold|Verify|verify_task|verify_failure|VERIFY_KINDS|verifier|open_verifier|open_verify|taskloop[.]verifier|verifier[.]py|step verify' src/taskloop tests/steps tests/cli tests/rules .importlinter` returns no matches for the selected map rows; the old module path is absent. Construct removed-command negative input from pieces so it does not preserve an obsolete command string.
