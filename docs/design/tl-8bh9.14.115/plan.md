# Shelf reuse and repeated helpers

Status: **proposed**. Task: tl-8bh9.14.115. Prepared 2026-11-13 against task-loop
`2e785034` and a read-only shelf checkout at `76f31d6cd9f1061b24dd437848d03c24c7bdbeb6`.
This plan authorizes no implementation or release. Obtain the owner's yes before implementing it;
use the owning shelf release workflow and its publication authority before publishing packages.

## Evidence and scope

Origin: the 16 read-only architecture-review censuses, session `local_16bd6c79`, Haiku,
2026-11-13, with key claims spot-checked. The session scratchpad's `grilling-record.md`
is the original reference. The repository retains a [review record](../architecture-review/grilling-record.md)
and [playbook](../architecture-review/architecture-review-playbook.md), including finding J.
The reported counts (79 argparse hits; four UTC stamps, three JSON hashes, four ticker loops)
are historical search results, not a requirement to replace that many current sites.

Read the [foundation plan](../tl-8bh9.8.7/plan.md), [glossary](../../glossary.md) and
`justfile` before implementation. Retain the independently installed successor, explicit IO/time
ports, process identity checks, store ownership and existing application operations.
Do not import baseline code or bring back old packages, runners or test bootstraps.

Current source checks establish these boundaries:

- UTC machine stamps recur in `dash_model.iso`, `dash_board` and `round_log.stamped`.
  Human UTC formatting recurs in `show_render`, `hold_guide`, `hold_text` and `hold_cause`.
- `environment.setup_digest` and `checks.argv_digest` hash compact JSON arrays.
  `EvidenceFiles.directory` hashes a JSON array using default separators, including spaces.
  Its hash selects retained artifact directories; it is not interchangeable with the compact form.
  Other SHA-256 uses hash raw evidence or profile bytes and must keep doing so.
- `rounds._pause`, `KeepAlive.run` and `DashServer._poll` have different scheduling and stop
  contracts. `attempt_entry` also has bounded retry waits governed by attempt deadlines.
- Activity files have capped writes, bounded reads, replacement-aware cursors and a specific
  corruption/truncation policy. `rounds.log` is a text grammar, not JSON Lines.
- Machine paths deliberately ignore ambient XDG/plugin settings. Factory SQLite is synchronous
  and already uses released `sqlite-store`; execution already uses `stream-proc`/`any-agent`.

Local `bd show tl-8bh9.14.115 --json` found no matching task. Use the supplied task requirements
for this plan; do not recreate, claim or close a different task to compensate. Resolve tracker
availability through its owning operation when implementation is assigned.

## Package decisions

These are the proposed keep/adopt decisions for owner approval, with explicit consumer scope.
Versions below describe the inspected shelf checkout, not a claim that new releases exist.

| Package | Decision | Application and reason |
|---|---|---|
| `timefmt` 0.3.0 | Adopt after its UTC extension is released. | Move repeated pure UTC rendering into this existing formatting owner. Preserve both machine and human output exactly. Existing browser `fmtDur` remains JavaScript: the Python library cannot directly replace it, and moving live ages to the server would change the dashboard contract. Keep raw numeric duration fields and the current CLI seconds wording. |
| `app-dirs` 0.1.0 | Keep explicit machine paths. | Its default follows XDG, while `machine_config` intentionally uses the supplied home only. Calling it with `env={}` can preserve config/state locations but replaces trivial path expressions and still leaves slots under `.local/share`. That adds a dependency without removing a meaningful mechanism. Preserve flags > file > default, `--config`, and all existing locations. |
| `verb-cli` 0.1.0 | Adopt its released help-tree test helper; keep the current runtime parser in this task. | Use `verb_cli.testing.assert_help_tree` as a dev dependency. Expose parser construction without running composition, and fill missing descriptions/positional help. Current flags include positional arguments, special destinations and one-way booleans; `to_argparse` generates paired booleans and cannot replace them unchanged. Full typed command discovery/output migration and the review's accepted `any-cli` rename belong to the CLI redesign, after its shelf release. Do not introduce a temporary second runtime CLI framework or a rename alias here. |
| `jsonl-log` 0.4.0 | Keep the owning evidence implementation. | `read_from` limits returned entries, not bytes scanned, and does not supply the current inode/replacement contract. Its rotation/retention can delete evidence, and its append semantics differ from `CappedLog`. Adopting it now would require substantial extra machinery. Keep `activity_file`, `CommandSink`, capped evidence and the text round log; enable no rotation or expiry. |
| `any-proc` 0.3.0 | Keep `stream-proc` and `any-agent`. | Its JSON-result one-shot runner and restarting supervisor do not replace identity-registered execution, reconciliation or owned group observation. Automatic respawning would conflict with once-only dispatch. Add no process wrapper, supervisor, direct subprocess use or signal path. |
| `sqlite-resource` 0.1.0 | Keep `sqlite-store`. | It manages async `aiosqlite` connections. The current per-thread synchronous store, schema checks, transactions and read-only opens have an existing shelf owner. An async conversion adds a dependency and enlarges tests without addressing this task. |
| `due-schedule` 0.1.0 | Keep existing interval/deadline policy. | It answers interval/cron due-ness from wall datetimes and last-run history. Rounds use a monotonic delay after work, early wake on released reservations and graceful stop; no cron requirement exists. Do not add croniter, durable schedule state or a second scheduler. |

The repository's later review decisions still apply: scheduler policy stays local and generic CLI
mechanics eventually move to the renamed CLI library. This task's explicit promotion request covers
only reusable waiting mechanics, not the scheduler, reconciliation, backoff policy or workflow state.

## Promoted helper contracts

Build and release each promotion in an assigned shelf worktree before task-loop imports it. The
owner's approval must cover the proposed package/API placement below before names enter code;
these are library identifiers, not additions to the factory glossary. If placement is changed,
record the accepted choice here before implementation rather than inventing a second owner.

### UTC formatting in timefmt

Extend `timefmt` with pure epoch-seconds formatters for `YYYY-MM-DDTHH:MM:SSZ` and
`YYYY-MM-DD HH:MM:SS UTC`. Both receive the timestamp; neither reads the clock, environment
or local timezone. Retain existing whole-second conversion and existing failure behavior for
unsupported timestamps. Nullability and optional deadline parentheses remain caller policy.

Adopt the released functions in the seven modules listed above. `round_reader` continues to
validate the existing log grammar; formatting reuse does not introduce a new parser or format.
Keep the existing `dash_model.iso` boundary only where its nullable contract is useful.
Do not broaden this into permissive time parsing or change leases, stored epochs or duration units.

### Canonical JSON and SHA-256

Proposed shelf placement: a small stdlib-only `json-digest` package. Alternatives are a local
helper (fails the requested released promotion) and extending `any-json-doc` (a file-store owner
with unrelated atomic-IO dependencies). Prefer the narrow package for deterministic serialization;
the owner must accept its name before it enters code.

Provide canonical JSON bytes and their lowercase SHA-256 hex digest over a typed recursive JSON
value. Define the encoding once: UTF-8, sorted string object keys, compact separators, ASCII escaping,
no trailing newline, ordered arrays and finite numbers only. This is the package's documented
Python JSON encoding contract, not a claim of RFC 8785 conformance. Unsupported values fail;
do not coerce arbitrary objects, stringify keys or round-trip models just to call this helper.

Replace the compact array hashing in `environment.setup_digest` and `checks.argv_digest` using
their existing input normalization. Their inputs are strings and arrays, so sorting keys and
rejecting non-finite numbers do not change any existing bytes or hashes. Keep domain-named
functions where they state what is hashed; remove duplicate serialization/hash implementation.

Keep `EvidenceFiles.directory`'s existing single encoding and hash unchanged. It deliberately uses
different bytes, so the third reported site is a documented keep decision. Do not relocate evidence,
introduce a format discriminator or add a fallback reader. Raw artifact/profile digests remain raw.
The promotion is complete when released and consumed at the two genuinely matching sites, rather
than by forcing the historical count to three.

### Stop-aware waiting in any-clock

Extend the existing `any-clock` time-mechanism package with a small pure synchronous wait iterator
or equivalent callback primitive. It accepts an explicit monotonic clock, a wait operation, a stop
predicate and a positive interval, with an optional monotonic deadline. It owns no thread, signal,
process, database, task selection, retry budget or persisted state.

Document and test delayed first work, delay measured after work (no catch-up burst), bounded final
wait, and stop checks before waiting and before yielding work. An event wait must be able to wake
early on stop; predicate-only adapters retain the current bounded polling responsiveness. A deadline
prevents work at/after expiry. Callback exceptions remain visible to the owning caller.

Adopt it in `KeepAlive.run`, `DashServer._poll` and the pacing part of `rounds._pause` only after
proving their timing contracts. Keep lease loss/fault checks, reservation baselines/early wake,
unreadable-slot behavior and regular-round scheduling in their current owning modules. Keep thread
start/join and interrupt handling local. Do not turn the library into an alternative scheduler.

Reassess `attempt_entry` retry waits explicitly but retain them: their attempt wall deadline,
bounded retry count and capture/resume decisions are not periodic stop-aware work. Do not alter
those semantics merely to find a fourth consumer. Existing review guidance for a local scheduler
and this generic mechanism promotion can therefore both hold.

## Delivery sequence

1. Obtain the owner's yes on these decisions, including the proposed `json-digest` name. Recheck
   current source and existing shelf releases before work; record drift or an already released
   equivalent rather than creating duplicate helpers. Use the task tracker for bounded implementation
   work and release dependencies; this document is the design, not a second task-state store.
2. In owning shelf worktrees, implement the three small mechanisms with public-contract pytest tests,
   documentation and Python 3.15 verification. Use shelf's declared focused gates and release procedure.
   Release each changed/new package; record actual version, immutable tag, commit and test evidence.
   No guessed version/tag, unpublished source path or task-loop vendored copy counts as release.
3. In the assigned task-loop worktree, pin the released versions in `pyproject.toml` and `uv.lock`.
   Adopt UTC formatting and matching JSON hashes first, then wait mechanics. Add the existing CLI
   help helper as a pinned development dependency and expose parser construction for its single
   tree-wide public contract. Preserve command spellings, flags, defaults, exits and stream routing.
4. Remove only the implementations actually replaced. Recheck every keep decision and record its
   result alongside release evidence here. No database/schema migration, state recovery, evidence
   retention, CLI redesign or process lifecycle redesign is part of this delivery.

Shelf source and release operations occur only under the shelf owner's authority; a task-loop
implementation may wait for those releases. This planning attempt writes only this plan and does
not create shelf branches, packages, tracker tasks, source changes or publications.

## Verification and completion

Use public behavior tests with semantic clocks/events and existing owning fakes, not real sleeps,
mock libraries, subprocesses or a test per private helper. Shelf tests cover UTC across timezone/day
boundaries, JSON known-byte/digest vectors including Unicode and array order, rejected unsupported
values, and waits stopped before first work, during wait, after work and at the deadline.

Task-loop verification must prove:

- Existing machine paths stay independent of XDG/plugin variables and current precedence holds.
- Machine stamps and human timestamps retain exact text, null handling and log-reader acceptance.
- Setup/check hashes retain known expected values, and a fixed existing attempt key resolves to its
  original evidence directory. No migration, new reader, evidence deletion or duplication is needed.
- Lease renewal still stops on loss/fault, dashboard polling stops promptly, and rounds retain
  regular delay, reservation-based wake and unreadable-baseline behavior. Already-stopped callers
  do no extra work. Entry retry budgets and deadlines are unchanged.
- The entire implemented CLI help tree explains itself and current CLI contract tests retain flags,
  errors, defaults, request forwarding, exit codes and JSON stream behavior. Entry import isolation
  still excludes the command surface and its dev-only help helper.
- Kept process/store/log/scheduling mechanisms retain their existing focused contracts; no adoption
  is justified solely by a smaller import count or a historical search count.

Read `justfile`, then run `just install`. Run affected pytest files through
`uv run --frozen --no-sync python -I -m pytest`, selecting configuration/CLI, evidence, setup/check,
claim-lease, rounds, round-reader and dashboard behavior tests for the changed import closures.
Run installed CLI help via `uv run --frozen --no-sync python -I -m taskloop ...`.
Finish with `just check` and `just test`, the declared focused successor gates. Do not run historical
whole-suite/live tests. Preserve the 400/80/800 caps and introduce no `Any`, casts or ignore escapes.
Report exact environmental failures without weakening gates or declaring them passed.

Completion requires owner-approved keep/adopt decisions for all seven packages, all three helper
promotions released with immutable provenance, task-loop consuming the matching released helpers,
obsolete matching implementations removed, and focused gates with recorded results. An unimplemented
plan, shelf source without a release, or a dependency pin without consumer changes is not completion.
For this documentation-only planning attempt, validate the diff and path restriction; no runtime
checks or release actions are needed.
