# REWRITE-READMODEL: the engine publishes the facts, the dashboard renders them (tl-7i9k.36)

Design and implementation note; read verbs now use pure liveness checks. Acceptance of the bead (from `docs/architecture/review-rewrite-opus.md` REWRITE-06): `stuck_of` and the `ready_count` fallback are deleted; the dashboard and `tl status` show the same stuck and ready values on one fixture world. Ledger rows folded in: M-111 (read verbs reconcile), M-146 (dash wire types in contracts), M-147 (Ports/`quiet`), M-177 (dashboard cycle), M-189, M-200, M-242. Measured on origin/main, 2026-11-06.

## What is re-derived today

| decision | where the dashboard decides it | where the engine already decides it |
|---|---|---|
| stuck episode is open | `tldash/views/runfacts.py:143` `stuck_of`: walks the log and ends the episode by its own rule (silent: any record but Beat/Stuck; same_red: a later round green or red another way) | `domain/stuck.py` `StuckWatch` writes the `Stuck` record by the same rule; nothing writes the end |
| ready beads | `views/needs.py:48` `ready_count`: with a live loop, its published `queue`; without one, a second rule (`is_work`, open, no assignee, no wait label, `blockers`, `has_ask`, not `blocked`) | the loop's queue (`skip is None`); bd's own `ready` |
| passes, phases, slots, tone | `views/passes.py` 217, `phases.py` 102, `slots.py` 109, `queue.py` 31, `cost.py` 83, `runfacts.py` 277 | `PassEnd` in the log for passes; slot state in factory.db |
| the JS | `static/js` 2,958 lines in all; the re-deriving part (`data.js` 111, `views/slots.js` 172, drawer/phone sorting) is a fraction | none |

`tldash/views` is 2,198 lines in 23 files; about 800 of them derive (the estimate of the architecture note held: 600-800). The rest only shape rows.

Constraint that decides the shape: `.importlinter` contract `dash-imports-contracts-only` forbids `taskloop.domain`, `app`, `stores` for `tldash`. So a rule both sides share must live in `contracts/` as a pure function, exactly as `contracts.reconcile.loop_absent` does today (`views/needs.py` already imports it). The architecture note proposed relaxing the contract to allow `taskloop.domain.projection`; this note does not (owner decision 1).

## What moves

1. **Stuck: the engine writes the end.** Add a `StuckEnd` log record (episode id = the `Stuck` record's `sig`/`id`), written by `app/run/stuck.py` when `StuckWatch` closes an episode (it already tracks `silent_said`/`red_said`). The dashboard's answer becomes "the newest `Stuck` with no later `StuckEnd`": one comparison, no rule. Delete `stuck_of`'s episode logic. Hard cut: delete the old stuck rule with no one-release fallback, including for old logs.
2. **Ready: one number, published.** Delete the fallback branch of `ready_count`. The ready number comes from bd's `ready`, including when no loop is live: the index already reads the repo's beads, and `bd ready` is the only definition of ready the owner knows; the dashboard takes `ready` as a field of the bead row the index loads (the index cache is rebuildable, so no durability rule is touched), not a rule of its own. To verify at the cut: that the index loader can fetch `ready` in the call it already makes.
3. **Wire types leave `contracts/dash*.py`.** `dash.py` 547, `dashenums.py` 68, `dashruns.py` 45, `dashcost.py` 39, `dashhealth.py` 35, `snapshots.py` 146, `slottable.py` 123 = about 1,000 lines, 23 src importers and 23 test importers (about 35 test files). Move the page-only types (cards, rows, `Pass`, `AccountCard`) to `tldash/wire/`; keep in `contracts/` only what the engine and the page both read (`WRITES`, the log records, `loop_absent`-style rules). Mechanical, wide, no behaviour.
4. **Read verbs do not reconcile (M-111).** The read-path callers were `app/asks/owner_verbs.py` (`live`, `repo_runs`, `verdict`, the latter two used by `cli/wait.py`) and `app/report/card.py` (`crashes`). The loop previously reconciled once before its `while True`, not each pass; it now reconciles at the start of every pass, exactly once. Reconcile writes (a LOST run gets its end). The loop is the only src caller apart from `app/wire/doctor.py`, which stays; read verbs read the state as it is and mark a run "lost (not yet reconciled)" from the same pure `runlife` check. `tl wait` is the sharp one: a waiter must not sit on a dead run for a pass interval; it keeps a pure liveness check and treats "dead and unreconciled" as CRASHED without writing.
5. **Dash Ports (M-147) and the package cycle (M-177).** `quiet` catches `SystemExit` and returns a default; make it return `Unavailable` and let the page show the missing source. Break the `views` <-> `readers`/`index` cycle by moving the shared row types down into `wire/` (they are the cycle). Small, rides with step 3.
6. **Blind-spot ratchet (M-242).** A test that lists the dashboard fields rendered without a fixture asserting them; a rise fails. Lands last.

Not in scope: M-189 (the dashboard as a client of a `tl dash-feed` process) and M-200 (one account view model, part of LANEPURGE's rename). Both are bigger than a cut here; M-189 changes where the dashboard runs, which is Denis's call.

## Cut order (each a PR green on `just test`)

1. **StuckEnd**: the record, the writer in `app/run/stuck.py`, the reader with a hard cut and no fallback. First slice, the smallest. Test: one fixture log, `tl status` and the page give the same stuck.
2. **Ready**: delete the `ready_count` fallback; `ready` from bd on the bead row. Test: the same fixture world, loop up and loop down.
3. **Read verbs stop reconciling**: `wait`, `card`, `app/asks/owner_verbs.py`; the loop reconciles every pass. Test: the crash matrix (`tests/run/test_crash_matrix.py`) still lands every row.
4. **Wire types out of contracts** (wide, mechanical, one PR, run when the queue is empty: it touches 23 + 23 files).
5. **`quiet`/Ports and the cycle**, then the blind-spot ratchet.
6. **Passes/phases/slots**: keep deriving passes; no new pass record in this cut.

Total: 6 PRs; code moved or deleted about 800 py (the derivation), 1,000 py relocated; net deletion about 300 py.

## Decisions recorded 2026-11-07

1. Share rules through contracts pure functions; keep the dashboard import boundary.
2. Keep deriving passes from `PassEnd` and phase order.
3. Ready comes from bd's `ready`, including when the loop is absent.
4. HARD CUT for stuck: no one-release fallback.
5. `tl wait` keeps a pure unreconciled-liveness check: dead stale live manifests return CRASHED without writing; SUSPECT still counts as live.
