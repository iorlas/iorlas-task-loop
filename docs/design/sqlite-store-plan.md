# One SQLite execution store: the plan (tl-sqd3.26 STORE)

Owner decision (Denis, 2026-11-06): SQLite for all, as soon as possible. This note is the plan; each slice below is its own PR. The
design lives in `docs/architecture/zoom-out-review.md` (R1) and `docs/design/durable-factory*.md`; this note adds the inventory the
migration needs, the order, the kill test and the rollback.

## 1. What is already in `factory.db`

Schema v3 (`src/taskloop/contracts/factorydb.py`, WAL, `begin_immediate`, `cas_update` on the revisioned tables `run`, `ask`, `bead`;
vendored `sqlite_store` does the open, quarantine and `user_version` upgrades).

| table | state |
|---|---|
| `run` (manifest, state, heartbeat, facts), `attempt`, `step` (done memo), `check_pass`, `ask`, `ask_ledger`, `bead`, `kv`, `source` | in use (runrows, attemptrows, receiptrows, askrows, beadrows, the dashboard indexer) |
| `lease`, `wait`, `signal`, `effect`, `check_round` | schema only; nothing writes them except prune |

So the target is not a new schema: it is moving the remaining files into these tables (plus three small ones below) and giving every
writer the same revision rule the `run` table has.

## 2. Inventory of what is still a file

Paths are under `~/.config/task-loop/` unless they start with `.task/`. "RMW" is a get-then-put with `os.replace` and no lock or
revision, so the last writer wins (`JsonStore`/`Doc`, vendored `any_json_doc`). Contention: H hot (every step or beat), W warm, C cold.

| # | store | path | writer -> reader | today | |
|---|---|---|---|---|---|
| 1 | Checkpoint | `checkpoints/<bead>.json` | engine (`app/run/state.py` Checkpoints) -> engine resume, dashboard | RMW, one engine per bead assumed | H |
| 2 | Loop state | `loop/<repo>.<pid>.json`, `died-*` | loop (`app/loop/files.py`) every beat -> dashboard, tl | one file per pid, atomic | H |
| 3 | Loop command / rest | `loop/<repo>.command.json`, `-rest.json` | cli, dashboard -> loop | last writer wins; RMW | C/W |
| 4 | Parks | `parks/<bead>.json` | engine, loop (`contracts/parks.py`) -> loop pick, dashboard | RMW, unlocked | W |
| 5 | Net pause, reexec note | `pauses/<bead>.json`, `reexec/<bead>.json` | engine (`app/release/reexec.py`) -> next run | atomic | C |
| 6 | Owner request | `runs/<run>/owner-request.json` + `.lock` | dashboard/cli POST -> live engine | lock + atomic | W |
| 7 | Call state | `<bead>.call.json` | engine (`stores/call_state.py`) 3x per vendor call -> restart reattach | one writer, atomic | H |
| 8 | Follow-up outbox | `followups/<bead>.json` | engine -> engine, dashboard | RMW | C |
| 9 | Landed | `landed/<bead>.json` | land (once) -> lost, prune, loop | atomic | C |
| 10 | Slot tickets | `slots/<repo>/<seq>.json`, `seq` | any waiter (`stores/files.py` FileTickets) | `os.link`, lock-free; counter can race | H when contended |
| 11 | Engine lock | `<worktree>/.task/engine.lock` | engine start | json + flock `engine.take` (PR #40 moves it to `<cfg>/locks/`) | W |
| 12 | Worktree records | `worktrees/<repo>/<key>.json` | slots/engine -> prune | atomic | C |
| 13 | Check durations, per-round checks | `check-durations/<repo>.json`, `runs/<run>/engine-checks*.json` | engine | RMW | W |
| 14 | Shared flakes | `shared/<sha1>.json` | engine | RMW | C |
| 15 | Repos index, pin, bad versions, release result | `repos.json`, `pinned.json`, `bad-versions.json`, `releases/last.json` | every tl process / release | locked or atomic RMW | C |
| 16 | Storm | `storm/<sha1>.json` | adapters/storm.py -> loop | atomic | C |
| 17 | Snapshots | `snapshots/delegate.status.json`, `delegate.tried.json` | `tl lanes` chore -> dashboard | atomic | W |
| 18 | Dash/reflect state | `dash.json`, `reflect-*.json`, `dash.pid` | dashboard | atomic | W |
| 19 | ADRs | `decisions/<repo>/ADR-n.json`, `uses.jsonl` | owner verbs -> engine, dashboard | atomic + append | C |
| 20 | Run dir files | `runs/<run>/plan.json`, `handoff.json`, `pause.json`, `reexec.json`, `prepare.stamp` | engine -> engine, dashboard | `write_text`, not atomic | W |
| 21 | Host resources | `host.json` | owner verb -> engine, loop | atomic, static | C |

Hot ranking, worst first: checkpoint (1), loop state (2), call state (7), parks (4), slot tickets (10), `repos.json` (15).

### 2a. Durability class (amendment, Denis 2026-11-06)

Moving a fact into `factory.db` must not make the DB its only record when the fact outlives the machine. Every family has one class:

| class | meaning | on DB loss |
|---|---|---|
| **D** DB-only | operational, short-lived or recomputable | rebuilt or expired; nothing is owed |
| **R** record elsewhere | the DB row is a read cache; the record is in git or the task system | re-read from the record |
| **O** outbox | a disposable "about to do X" row, reconciled against the real world | reconciled against git, then dropped |

| family | class | record |
|---|---|---|
| rows 1-8, 10-18, 20, 21 (checkpoint, loop, parks, call state, tickets, locks, worktrees, checks, flakes, repos, storm, snapshots, dash, run-dir state, host) | D | none: the run or the loop recomputes them |
| 9 landed | O | **no `landed` table.** git and the receipts are the record of what landed; `effect` (`land:<bead>`) stays only as a "started merging X" outbox, reconciled against git on DB loss (merged on origin/main: done; else retry or stop) |
| 19 ADRs | R | `docs/adr/NNNN-title.md` in the repo; the DB keeps a read cache for the dashboard and `uses.jsonl` stays a log |
| `ask` (operational: stuck, timeout, budget) | D | none; they expire |
| `ask` (decision) + `ask_ledger` | R | the answer is a bead comment with `kind=decision`; the DB keeps only the open asks; `ask_ledger` is bead comments, not a table of record |
| plans | R / D | multi-PR or architectural: `docs/design/<ticket-id>/plan.md` (ticket id = the task system's id, as is); a single task: the bead body; per-run `plan.json`: DB (D) |

Consequences for the rest of this note: row 9 and row 19 in the table of section 3 read "see 2a"; the legacy `ask-ledger.jsonl` importer
(slice 9) imports into bead comments, not into the `ask_ledger` table; the `ask_ledger` table is no longer a source of record and is
dropped by the schema step that follows the importer.

### Stays a file, by design

- Logs and evidence: `engine/<run>.jsonl` and `.live/*`, `events.jsonl`, `traces.jsonl`, `loop/*.jsonl`, `usage-history.jsonl`,
  `profile-changes.jsonl`, land and suite logs. The design rule: a log is evidence, never authority. They keep `RotatingJsonl` and a log
  reader, rotated by age (CLAUDE.md).
- Worker answers, `runs/<run>/<node>-<n>.json`, `.raw.json`, `replan.md`, `brief.md`, artifacts, screenshots, `.task/` scratch, `slot-state/`.
- Kernel locks (`flock`, `any_lease`): the kernel drops them when a process dies; a DB row cannot. The `.holder` hint files go.
- `.task-loop.json` (in git at the base commit).
- Delegate's private state under `<cfg>/delegate/`: task-loop never reads it (`docs/dev/integrations.md`); delegate keeps its own `StateStore`.
- Legacy import-only files (`runs/<run>/manifest.json`, `done*.json`, `asks/*.json`, `ask-ledger.jsonl`, `results/**`) keep their importers until slice 9.

## 3. Target

Same file, `<cfg>/factory.db`; stdlib `sqlite3`, WAL, one writer connection per process and thread, `BEGIN IMMEDIATE` for writes, the
dashboard read-only (`mode=ro`). Every transition is one transaction: `expected_revision` check, the state change, and the effect rows
it implies.

| file store | table | note |
|---|---|---|
| 1 checkpoint, 8 follow-ups, 13 per-round checks, 20 run-dir state | `run` columns + `step`, `check_round`, new `checkpoint(bead PK, run, rev, body)` | the checkpoint is per bead across runs, so its own table, revisioned like `run` |
| 2 loop state, 11 engine lock, 12 worktree records (kv rows `worktree:<repo key>:<key>`: an ownership record is evidence, not a lease), 10 slot tickets | `lease` (kinds `loop`, `slot`, `run`) (slot tickets are `lease` rows `slot` named `<repo_key>/<seq>`, the counter a `kv` row: no `slot_ticket` table, no schema bump, so an older tl is not parked as behind) | `lease` already has host, pid, start_id (the pid-reuse fix of tl-br2.13), beat, until |
| 3 loop command, 6 owner request | `signal` | taken once (`taken`), written by the owner, read by the loop or engine |
| 4 parks, 5 pauses, reexec, 16 storm | `wait` (kind, wake_at, wake_on, facts, cleared) | the schema comment already says: park writes go through the loop-owned wait store |
| 7 call state | `effect` (key = bead+call key, state intent/returned/consumed, receipt) | this is exactly the outbox the review asks for |
| 9 landed | `effect` (`land:<bead>`), outbox only | class O (2a): git and receipts are the record; no `landed` table |
| 14, 15, 17, 18, 21 | `kv` (key, value JSON, stamp) | cold singleton documents: no schema of their own |
| 19 ADRs | `kv` read cache of `docs/adr/NNNN-title.md` | class R (2a): the file in git is the record, the verbs write it |
| decision asks, `ask_ledger` | `ask` (open asks only) | class R (2a): the answer is a bead comment `kind=decision` |

New tables beyond v3: `checkpoint` (schema v4, one `user_version` step, DDL and version in one transaction as
`sqlite_store.migrate` does). Nothing else changes shape.

## 4. Order

Smallest and most contended first, each slice its own PR, each readable both ways until it lands:

1. **Loop state + command (2, 3)** onto `lease`/`signal`. Hot, small, one writer plus the dashboard poll; kills the phantom-loop and rename dance (`LoopFiles.live()`).
2. **Parks, pauses, reexec (4, 5)** onto `wait`. Unlocked RMW today; the `wait` store is loop-owned, the engine submits through it.
3. **Checkpoint (1) + follow-ups (8)** onto `checkpoint`. The most contended RMW; revision makes the lost-update impossible. Largest slice: split into read path, then write path.
4. **Call state (7), landed (9)** onto `effect`; landed is the outbox only (2a), reconciled against git.
5. **Slot tickets + engine lock + worktree records (10, 11, 12)** onto `lease`/`slot_ticket`. Builds on tl-sqd3.6 (PR #40).
6. **Owner request (6), run-dir state (20), per-round checks (13)**.
7. **Cold singletons (14-18, 21)** onto `kv`, one PR for the family. **ADRs (19)** follow the ADR verbs writing `docs/adr`, then the `kv` row is a cache. **Decision asks** move with their answer to a bead comment before the `ask_ledger` table is dropped (tl-sqd3.26.10).
8. **Logs stay**: no slice; confirm the log reader and age rotation.
9. **Delete** the legacy importers, `parks.py`, `files.py` pointers, `Stores.loop_state`, the `.holder` hints.

### Per-slice rule (strangler)

1. Add the table access behind the existing store interface (`DocSet` / `JsonStore` protocol): the callers do not change.
2. Dual-read: the new store reads the DB, falls back to the file when the row is absent and imports it (the importers in `runrows.import_legacy` are the pattern). No dual-write: one writer per fact at every moment.
3. The slice lands; the file is written no more; the fallback stays one release.
4. The next release deletes the fallback, the file paths in `contracts/paths.py` and their tests.

## 5. The kill test (acceptance of the bead)

"Kill tests at every transition leave one current attempt and every pending effect." Per slice, a real-process test
(`tests/<slice>/real/`, SIGKILL) over a table-driven list of that slice's transitions:

- for each transition T: start the writer in a child, arm a hook that kills it (a) before the transaction commits and (b) right after;
  restart; assert exactly one current row for the fact (no half state, no second attempt), every `effect` row of T is either absent
  (a) or pending and replayable (b), and the replay is idempotent (running recovery twice changes nothing);
- a concurrent pair (two writers on one bead) ends with one revision winner and one `StaleRevision`, never a torn record.

The transition list per slice is generated from the table's state names, so adding a state without a kill case fails a rules test.

## 6. Rollback

- Per slice: the file fallback is still read for one release, so reverting the slice's PR returns to files with the data written
  meanwhile lost only for facts first written in the DB. Therefore the importer also has an **export** (`tl store export <slice>`),
  run before a revert, that writes the rows back as the old files. Tested in the slice.
- `factory.db` itself: a failed `user_version` step rolls back whole (one transaction). A DB the code cannot open is quarantined
  (`sqlite_store.quarantine`) and the run reports a visible error, never a silent file fallback ("only our database", CLAUDE.md).
- A release that finds a slice broken is rolled back by `tl rollback`/pin; the next release re-lands the slice.

## 6a. Compatibility across versions

The lesson (pix, 2026-11-06: 32 run rows with `pid_start` from a newer tl blocked every landing of an older one as "unreadable run
manifest", tl-x3m0). Three rules, one test shape:

- **(a) Stores are forward-readable.** Every row, manifest and `kv` read tolerates keys it does not know, from a newer writer; a write
  back keeps the keys this tl knows. A row that still does not validate raises an error that says "validation", names the row and the
  field, and is not an alias of a database fault.
- **(b) A database ahead of the code parks, it does not crash and does not fall back.** A `user_version` newer than the running tl's
  schema parks the loop (and refuses the engine and the verbs that write) with a typed reason, "factory.db is schema vN, this tl knows
  vM: update tl" (the vendored `sqlite_store` already raises that); it never reads the old files instead ("only our database").
- **(c) Each slice's tests carry an old-shape row and a new-shape row**: a row as the previous release wrote it (a field missing) and a
  row as a later one will (an extra key); both read, and the old one is completed on its next write.

## 7. Risks

- Hot writers (loop beat, checkpoint) on one WAL file: measured in slice 1 before the others (target: beat write < 5 ms p99 under 4 engines).
- Dashboard readers hold read transactions: always short, `mode=ro`, never across a poll interval.
- macOS and pix both have sqlite3 with WAL; the config dir is never on NFS.
- Process and thread leaks of connections: `shared_rw` caches one per thread; the conftest thread guard (PR #68) keeps tests honest.

## Decisions recorded

| date | decision | by |
|---|---|---|
| 2026-11-06 | One SQLite execution store for all authoritative state; logs and evidence stay files. | Denis |
| 2026-11-06 | One slice per PR, strangler: dual-read, never dual-write; old store readable until the slice lands. | plan |
| 2026-11-06 | Compatibility across versions: forward-readable stores, an ahead DB parks with a typed reason, every slice tests old and new row shapes. | lead |
| 2026-11-06 | Kernel locks stay kernel locks; delegate's private state stays out of this DB. | plan |
| 2026-11-06 | Durability classes (2a): ADRs are repo files (DB is a read cache); decision asks are answered as bead comments `kind=decision`, operational asks stay DB-only and expire; no `landed` table (git and receipts are the record, `effect` is a disposable outbox); multi-PR plans live in `docs/design/<ticket-id>/plan.md`, single-task plans in the bead body, per-run plan.json in the DB. | Denis |
