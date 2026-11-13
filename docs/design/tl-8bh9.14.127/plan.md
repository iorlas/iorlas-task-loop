# Version check on restart

Task: `tl-8bh9.14.127`. Status: proposed; implementation waits for the owner's yes.

Restart with an incompatible `factory.db` fails before scheduling or changing state, with
a message explaining the mismatch and the drain/discard procedure. Restart with a
compatible, intact database continues its unfinished work through existing liveness
reconciliation. Writing this plan does not authorize implementation or database discard.

## Authority and current evidence

The owner's delivery strategy was relayed by architecture-review session
`local_16bd6c79` on 2026-11-13. See
[Appendices Q and R](../architecture-review/architecture-review-playbook.md#appendix-q---owner-rulings-round-30-2026-11-13),
[the foundation boundary](../tl-8bh9.8.7/plan.md), and [the glossary](../../glossary.md).
Appendix R requires restarts at drained boundaries and lists version checking, draining,
and session resume as separate gaps. Session resume belongs to `tl-8bh9.3.4`.

Source inspected for this plan:

- `factory_schema.py` owns `SCHEMA` (currently v16), with no migration steps, and
  compares `PRAGMA user_version` with the running code's version. Its `refusal` reads
  the stored version for diagnostics. The older-version message advises moving the
  database aside and adopting slots, without a drain prerequisite. Newer versions use
  the dependency's error text; unreadable version metadata also falls back to that text.
- `cli_composition._open_ro` supplies that explanation;
  `operations.require_database` returns `Failed` with `refused:schema`.
  `open_rounds` checks the database before acquiring the rounds lock or installing
  handlers. Other step openers and adoption of an existing database use the same guard.
  Dashboard state reads share `open_reads`.
- `attempt_reads.StoreConnection` checks the version on every use, including writes.
  `composition` and the entries use `Store(SCHEMA)` or the owning library's schema-aware
  reader. Preserve these protections against an old process writing another schema.
- `round.run_round` already observes existing attempts and process identity. Its tests
  cover running entries, admitted attempts that can relaunch, and uncertain/dead entries.
  They do not establish restart behavior by closing and reopening the database.
- `tests/cli/test_open_rounds.py` covers an absent database and reopening the rounds
  context; `tests/steps/test_operations.py` covers adoption refusing another schema.
  Neither proves the full mismatch message or preservation of unfinished state on restart.
- No drain command is registered. `tl version` reports package metadata, currently
  declared as `0` in `pyproject.toml`; it is not a persisted compatibility contract.

The inspected restart path already refuses schema mismatches. No automatic database
deletion was found there. This task makes the safety instruction explicit and proves
both refusal and continuation, rather than presuming an existing destructive reset.
The task ID was unavailable through local `bd show` during planning; the supplied task
description is the requirements source. No tracker state was changed.

## Proposed compatibility rule

Use the existing schema version as the runtime's persisted-state compatibility version:
the running code accepts a database exactly when its recorded version equals
`SCHEMA.version`. An incompatible change to layout **or interpretation of stored
execution state** increments that version, even when DDL alone need not change.
Compatible source/package changes keep the version and resume normally. Package version,
Git revision, timestamps and log contents do not decide compatibility.

This uses one existing owner and one recorded value. This task adds no metadata table,
second runtime counter, migration, compatibility reader or startup rewrite. It needs no
schema bump merely to improve the refusal. The runtime's contract stays fixed for the
life of the process. Recheck the current schema number before implementation rather
than hard-coding v16 in messages or tests.

| Database at startup | Result | State effects |
|---|---|---|
| Recorded version equals the running code's | Continue through existing reconciliation | Existing attempt, reservation and session references remain authoritative |
| Older recorded version | Refuse with stored/expected versions and drain/discard explanation | No factory state or external action changes |
| Newer recorded version, including a downgrade | Same refusal; explain that matching code can reopen the intact database | No factory state or external action changes |
| Version zero or missing/unreadable metadata in an existing file | Refuse with the available diagnosis; never infer an empty usable factory | Preserve the file; no replacement or stamping |
| Database absent | Keep existing missing-database behavior; only explicit slot adoption initializes it | Restart creates no database |
| Temporary database access failure | Keep existing unavailable/database handling | Never convert access failure into initialization or discard |

## Refusal and recovery instruction

Own the explanation in `factory_schema.py`, retaining the current typed refusal path
and nonzero CLI result. Include the resolved database path, recorded version when
readable, and the version expected by the running code. Human output and existing JSON
`detail` carry the same explanation. Do not return only an opaque SQLite/library error
for a known mismatch, or treat a schema refusal as a transient retry.

The message states these facts in words:

> Restart refused: factory.db uses schema version X; this runtime expects Y. The
> database has been preserved. Resume with matching code to keep unfinished work. For
> an incompatible upgrade, first stop admitting work and let running attempts and
> their entry processes finish under the matching runtime. After confirming they have
> stopped, the owner deliberately discards the old factory database before initializing
> the new runtime. Discard loses local execution progress and session references.

Use actual values and path in place of the example. For unknown metadata, say what
could not be established instead of inventing a recorded version. Explain that draining
belongs before an upgrade: the newly started incompatible runtime cannot safely perform
it. No drain command exists, so advertise none. Remove command-based recovery advice
from this refusal; it explains the situation and the owner's decision in words.

No refusal deletes, renames, truncates, migrates, stamps or replaces the database, its
SQLite sidecars, evidence, worktrees or tracker data. Stopping the rounds process alone
does not prove that its entries or agents have stopped. Database discard remains an
explicit owning operation outside this task; restart never performs it.

## Bounded implementation

1. After owner approval, extend the existing version diagnosis and `refusal` in
   `factory_schema.py`. Keep schema SQL and connection handling in their existing
   owner; reuse the shelf store. Avoid a new generic startup/version service.
2. Verify that the existing shared guard propagates the full explanation before any
   scheduling action. Change `cli_composition` or CLI rendering only if focused tests
   show a missing propagation path. Preserve per-use write checks and the startup
   ordering. Keep missing-file and temporary-access failures distinct from mismatch.
3. Add focused restart contracts, preferably in
   `tests/cli/test_factory_restart.py` and `tests/steps/test_restart.py`, reusing existing
   fixtures and semantic process/tracker/Git fakes. Change existing tests only where
   their assertions encode the old recovery text. No subprocess or live agent tests.

The drain command, pinned previous-release runner, self-upgrade scheduling, process
termination, database cleanup, session conversation continuation and broader engine
reconciliation changes remain separate tasks. Compatible restart here preserves session
references and existing behavior; it does not implement deferred harness session resume.

## Verification and acceptance

- Parameterize older/newer/zero versions through the real startup guard and CLI
  presentation, covering human and JSON diagnostics. Verify the path, both known
  versions, nonzero exit and drain-before-discard instruction. Keep a populated
  database fixture and prove its version and application rows remain unchanged after
  repeated refusals. Include invalid/unreadable and absent paths without initialization.
- At `open_rounds`, prove an incompatible database installs no handlers and reaches no
  round, tracker mutation, Git change or process launch. Prove adoption also refuses an
  existing incompatible file. Use recording ports, not parsing logs for control.
- Close all fixture store connections, reopen the same compatible on-disk database
  with fresh store/round objects, and observe its unfinished attempt and reservation.
  A matching surviving entry is observed without another launch or admission. A
  safely relaunchable admitted attempt continues with the same identity and reservation
  under the existing rules. Unknown liveness remains unknown. Preserve stored session
  references and completed-step progress; create no fresh first-step attempt or claim.
- After implementation, read the then-current justfile, run `just check` and
  `just test` (its declared focused successor gates), and run any new focused test file
  not selected by that recipe after `just install`, using
  `uv run --frozen --no-sync python -I -m pytest`. No whole-suite/live tests or baseline
  imports. Retain source/test size caps and add no dependency or typing escape.

Completion requires an unchanged incompatible database plus an actionable refusal, and
observable continuation from the same compatible database after reopening. Plan review
and implementation approval precede source changes. This planning step changes only
this file and runs no runtime gates.
