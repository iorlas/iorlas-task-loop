# Growth and read performance

Task: `tl-8bh9.14.109`. Status: implemented; see [measurements and as-built decisions](measurements.md).
Prepared against `99655d38c09be07198ad0f5c0876d3d25a559a65` on 2026-11-14.

The owner approved synthetic measurements and read optimizations on 2026-11-13.
Implement sections 1–3 below. The retention and display decisions recorded below
are final; they do not need another question. This task authorizes no deletion.

The origin is the 16 read-only architecture censuses in session `local_16bd6c79`
(Haiku; key claims spot-checked), summarized in the repository's
[grilling record](../architecture-review/grilling-record.md) and
[findings catalog](../architecture-review/architecture-review-playbook.md).
These are findings to measure against the current code, not benchmark results.
The local tracker available during planning did not contain this task ID; the
supplied task description and owner decisions are the requirements here.

## Current implementation

- `AttemptReads.attempts()` in `src/taskloop/attempt_reads.py` selects and decodes
  all matching attempts, release and publication data. Optional filters use
  `(? IS NULL OR column=?)`. The unique index starts with
  `(adapter, backlog, task_id, seq)`; the optional predicates obstruct its use
  for a task-scoped lookup. Preserve the existing ordering and all four filter
  combinations, including task ID without backlog.
- `attempt_status.list_attempts()` reads that complete history and selects each
  task's highest `seq` in Python. The CLI, rounds and dashboard share this
  operation. Its existing status logic also reads checks, land and holds.
- `dash_board.build_board()` calls that operation, then reads all attempts again
  to supply rows and `tries()` counts. Those counts span restarts at plan: the
  stored repeat `number` alone cannot replace them. A displayed checks attempt
  can replace the selected implement attempt and has different numbering rules.
  `dash_server.Hub` polls only while subscribed and suppresses unchanged messages;
  this task concerns the work performed to build each board.
- `factory_schema.py` currently declares schema version 20 and 14 tables. The
  census's nine history tables are `attempt`, `execution`, `verification`,
  `slot_release`, `published_branch`, `setup_run`, `checks_attempt`,
  `check_result` and `land_candidate`. `task_hold` and the newer drain tables also
  exist; the census count is not a current total. There is no index starting with
  `attempt.repo_id`. `AttemptReads.slot_path()` is one concrete join to measure.
- `sqlite-store==0.1.0` is pinned to shelf commit
  `18d3164893f95dc82e391a7226652d286d9c4663`. Its read-only open performs no
  integrity scan. Its `Store` caches successful writable checks by process,
  resolved path, device and inode **per Store instance**, not across all Store
  instances. `composition.py` constructs separate ordinary and registration
  stores; command/round compositions construct further stores. Registration has
  a deliberately shorter busy timeout. A schema-version check on each store use
  is distinct from `PRAGMA quick_check`.
- `environment.Preparation` already empties the slot's environment, including
  uv cache/tools, at fresh setup. The old claim that these are never cleaned
  does not describe that current path.

## 1. Establish reproducible synthetic measurements

Create a small, opt-in native Python measurement driver and record its commands
and results under this folder, for example `measure.py` and `measurements.md`.
Use the installed successor package and current DDL, never the reference
implementation, an editable baseline or a `PYTHONPATH` substitute. Keep the
driver out of normal test collection and add no runtime benchmark command or
third-party dependency.

The driver must accept an explicit new synthetic output directory, refuse an
existing dataset rather than overwrite it, and retain what it creates. It must
never open a real factory database, slot, tracker, evidence tree or uv cache.
Use deterministic identities and valid relationships, enabled foreign keys,
and the same schema/settings as the application. Keep SQL in the owning store
boundary; use a small fixture store for synthetic construction and measurements
that need raw SQLite access. SQL and connections must not escape into dashboard
or status logic. Do not copy the old conftest or runners.

Measure at 1,000, 10,000 and 100,000 agent attempts, with proportional records in
the retained history tables. Vary history depth at a fixed task count separately
from task count at a fixed depth. Include several repositories and backlogs,
reused task IDs across backlogs, repeats, restarts, setup/check runs, landed tasks
and finished and unfinished holds. Keep evidence fixtures bounded by an explicit
file/byte budget recorded in the report; a database growth test does not require
creating evidence for every historical attempt. Use semantic Git, process and
tracker fakes so external service latency cannot dominate the read measurements.

For each dataset record row counts, database/WAL/index bytes, evidence files and
bytes, Python/SQLite versions, package pin, Git revision and host characteristics.
Separate dataset construction from timings. Record raw repeated samples and
median/p95, the sample count and warm-up policy for:

1. First writable open in a fresh process, repeat opens on the same `Store`,
   opens through distinct stores in that process, and read-only open. Distinguish
   process-cold from filesystem-cold; do not evict operating-system caches.
2. All-history, backlog-only, task-only and backlog-plus-task reads; current-task
   listing; a selected task's full history; and `slot_path()` by agent/check ID.
3. Full `list_attempts()` and board builds, including decoding and card creation,
   repeated board polls, SQL statement/row counts and peak Python memory.
   Report checks/land/hold reads separately if they dominate.

Capture `EXPLAIN QUERY PLAN` for the scoped filters, current-row selection and
repository join. Distinguish index traversal from wide row hydration and Python
allocation: retaining all cards means work can still grow with task count.
Measure the number and cost of integrity checks in representative command,
entry, checks-entry and multi-round composition lifetimes. Direct shell
invocations may provide fresh processes; factory source and tests must not add
subprocess, spawn, signal or wait escapes to arrange them.

Freeze this baseline before changing reads. Rerun the same inputs and sample
policy after each relevant change. Report absolute costs and ratios, including
small-dataset regressions. Use timings as evidence, not flaky CI thresholds;
use row/query counts and behavior assertions for deterministic regression tests.
If a resource bound prevents a dataset from running, record that limit and the
largest completed size, rather than presenting extrapolation as measurement.

## 2. Reduce history work in shared reads and the board

First replace nullable-OR predicates with parameterized equality predicates for
the filters actually supplied. Choose only fixed, application-owned SQL
fragments; never interpolate caller values. Reuse the existing decoding and
unique index, preserving empty results, backlog isolation, complete requested
history, release/publication fields, repeated-attempt flags and ordering.

Add a store-owned current-attempt read that selects each `(adapter, backlog,
task_id)` maximum `seq` before hydrating the wide attempt row. Compare grouped
maximum and indexed later-row exclusion on the baseline; select the simpler
measured choice. Do not introduce a second persistent owner of which attempt is
current. An index-only traversal of history may remain; the required improvement
is that listing no longer decodes every historical attempt or discards those
rows in Python.

Feed those rows through the existing status operation shared by CLI, rounds and
dashboard. Do not duplicate status, hold, checks or land decisions in the board.
Make the selected source rows and the needed try counts available to that same
board build through typed in-process data. The board must not invoke a second
all-history read. Counts can use narrow indexed SQL over the relevant task/step;
they must retain `tries()` semantics across plan restarts and the checks-view
substitution. Keep full history on the explicit task/detail/history paths.
Avoid assembling an entire task history merely to compute its current card.

Capture the selected rows/counts consistently within the store read boundary,
with a short read transaction where several SELECTs are necessary. End that
transaction before Git, tracker, process or evidence reads. Do not claim a
transactional snapshot of external facts. Handle store failures through the
existing typed failure result, including failure of board metadata reads.

Measure an index starting with `attempt(repo_id)` against `slot_path()` and other
actual repository-scoped reads. Add it if the measured query plan and timings
justify it; otherwise record why no index was added. Apply the same requirement
to any extra task/step counting index. Include index bytes, insertion cost and
startup integrity cost in the comparison. Do not add speculative indexes or
rebuild unrelated tables.

An added index is a schema change: follow the repository's version and drain
rules, with no silent migration or compatibility reader. Test new DDL only on
new synthetic databases and test refusal of a preserved old version. This task
must not drain, replace or discard the running factory database. Operational
rollout belongs to the separately authorized upgrade operation; no database
deletion is authorized here.

Keep the board's current refresh behavior, one card per attempted task and each
ready task without an attempt, and all landed and held cards. Preserve ordering,
column/status decisions, titles, times, slot custody, hold explanations and
checks/land information. Do not add pagination, a history cutoff, persistent board
cache, new scheduling policy or a materialized current-task table.

## 3. Remove redundant startup integrity work locally

Use section 1's measured composition lifetimes to identify redundant `Store`
construction for the same database in one process. Reuse the existing public
store/connection APIs across compatible operations within their owning process
lifetime. In particular, inspect per-round construction and nested land wiring;
do not construct a new store merely because another use case needs the same
writer. Keep per-thread ownership, transaction fencing, error eviction and
explicit closure after owned work has stopped.

Retain the automatic writable startup integrity check and file-identity
invalidation. Do not skip it, seed its private cache, copy shelf internals,
substitute a schema-version check, or add a TTL/file marker. Read-only dashboard
requests already avoid this scan; do not attribute their cost to `quick_check`.
Preserve registration's short busy bound and ordinary operations' existing
timeout. Never share a mutable timeout setting in a way that weakens either
contract. Some distinct connections/stores may remain necessary; explain and
measure them instead of bypassing safety to reach an arbitrary check count.

After local deduplication, repeat the startup measurements. If integrity checking
still materially dominates startup, document the measured residual and a narrow
proposed shelf change in this folder. A pinned shelf change or changed integrity
policy is outside this implementation authorization. Otherwise record that no
shelf proposal is needed. The report must distinguish essential checks from
avoidable repeats and state the remaining cost in numbers.

## Final owner decisions, 2026-11-13

| Item | Decision and completion evidence |
| --- | --- |
| Q1: growth measurements and reads | Approved now. Implement sections 1–3 and retain reproducible before/after measurements. |
| Q2: startup checks | Keep SQLite's automatic startup integrity check. Remove redundant repeats first. Propose a shelf change only if measured cost remains high; do not implement that policy change here. |
| Q3: attempt evidence | Retain all attempt evidence, including otherwise unreferenced files. No cleaner. A manual bounded purge design is only on a later owner request with owner approval. |
| Q4: history tables and holds | Keep the nine history tables and finished holds; growth is accepted. Also preserve the newer tables. Any purge needs its own design. |
| Q5: uv caches/tools | Keep the existing fresh-setup emptying rule. No additional cleanup, age/size policy or cache removal. Do not run fresh setup on real slots as part of this task. |
| Q6: board | Keep one card per task, including every landed and held task. No pagination until a measured problem supports a separate decision. Optimize the reads supplying those cards. |

No evidence, database row/table, finished hold, cache, worktree, branch, export or
user file is to be deleted by this work or its measurement driver. Existing
fresh-setup behavior is recorded, not newly executed or expanded here.

## Verification and completion

Use small focused pytest behavior/contract tests over real synthetic SQLite and
semantic ports. Cover the four filter shapes, same task IDs in distinct
backlogs, multiple repositories, empty history, latest `seq`, repeat chains,
restarts, abandoned attempts, check-driven repeats and checks/land substitution.
Exercise current listing through its CLI/round consumers and board construction;
assert complete landed/held visibility and unchanged task-detail history and try
addressing. Include unavailable reads and concurrent admission during selection.

Assert that a board build performs no all-history attempt hydration and does not
repeat the current-attempt selection. Check scoped index use structurally without
matching SQLite's entire display plan. For startup reuse, verify successful opens
still check automatically, reopen/replacement behavior remains safe, and distinct
registration/ordinary timeout contracts survive. Use public shelf APIs and
behavior observations rather than private-cache manipulation or mocks.

Keep source files/functions/tests within repository caps. Put new SQL in the
owning store modules; keep new boundary models pydantic v2 and new closed
vocabularies enums/classes. Do not turn this bounded task into a package-layout
rewrite or add new product vocabulary.

Read the justfile before implementation validation. Run `just check` and
`just test` (the required focused gates), plus only targeted affected contracts
not covered there. Run measurements after `just install`, using the frozen
installed environment with isolated Python. Do not run whole-suite/live tests
or launch agents, tracker actions or real factory work for a benchmark.

Completion requires a report in this folder mapping every finding above to its
measured fix or the recorded owner decision. Include baseline/final commands,
samples, query plans, costs and remaining limits; identify any optimization
rejected by measurement. Evidence and table growth, retained finished holds,
uv policy and complete board visibility are accepted decisions, not unimplemented
cleanup tasks. This plan alone is not implementation completion.

## As built, 2026-11-14

Sections 1–3 are implemented. Current attempts and whole-task step counts are
selected in one SQL snapshot and passed through the shared status operation to
the board. Scoped history predicates expose the existing task index. Grouped
maximum and a covering step-count index won the synthetic comparison; primary-key
slot joins removed the need for a repository index. The new index requires schema
21, with refusal of version 20 and no migration or running-database operation.

Ordinary and bounded registration writers remain separate and now survive across
rounds; nested land and start operations borrow the owning writers. Automatic
integrity checking and file-identity invalidation remain in shelf. The residual
measured startup cost motivates a shelf proposal only, recorded in the report.

Q2–Q6 remain exactly the final decisions above. Evidence, history, finished holds,
cache policy and every landed/held card are retained. Reproducible drivers, raw
samples, limitations, index/write/startup costs and validation are in
[measurements.md](measurements.md) and [samples/](samples/).
