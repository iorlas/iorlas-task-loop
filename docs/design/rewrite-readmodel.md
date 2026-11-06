# REWRITE-READMODEL: the engine publishes the facts, the dashboard renders them (tl-7i9k.36)

Design note only; no code moves with it. Acceptance of the bead (from `docs/architecture/review-rewrite-opus.md` REWRITE-06): `stuck_of` and the `ready_count` fallback are deleted; the dashboard and `tl status` show the same stuck and ready values on one fixture world. Ledger rows folded in: M-111 (read verbs reconcile), M-146 (dash wire types in contracts), M-147 (Ports/`quiet`), M-177 (dashboard cycle), M-189, M-200, M-242. Measured on origin/main, 2026-11-06.

## What is re-derived today

| decision | where the dashboard decides it | where the engine already decides it |
|---|---|---|
| stuck episode is open | `taskloop_dash/views/runfacts.py:143` `stuck_of`: walks the log and ends the episode by its own rule (silent: any record but Beat/Stuck; same_red: a later round green or red another way) | `domain/stuck.py` `StuckWatch` writes the `Stuck` record by the same rule; nothing writes the end |
| ready beads | `views/needs.py:48` `ready_count`: with a live loop, its published `queue`; without one, a second rule (`is_work`, open, no assignee, no wait label, `blockers`, `has_ask`, not `blocked`) | the loop's queue (`skip is None`); bd's own `ready` |
| passes, phases, floor, tone | `views/passes.py` 217, `phases.py` 102, `floor.py` 109, `queue.py` 31, `cost.py` 83, `runfacts.py` 277 | `PassEnd` in the log for passes; slot state in factory.db |
| the JS | `static/js` 2,958 lines in all; the re-deriving part (`data.js` 111, `views/floor.js` 172, drawer/phone sorting) is a fraction | none |

`taskloop_dash/views` is 2,198 lines in 23 files; about 800 of them derive (the estimate of the architecture note held: 600-800). The rest only shape rows.

Constraint that decides the shape: `.importlinter` contract `dash-imports-contracts-only` forbids `taskloop.domain`, `app`, `stores` for `taskloop_dash`. So a rule both sides share must live in `contracts/` as a pure function, exactly as `contracts.reconcile.loop_absent` does today (`views/needs.py` already imports it). The architecture note proposed relaxing the contract to allow `taskloop.domain.projection`; this note does not (owner decision 1).

## What moves

1. **Stuck: the engine writes the end.** Add a `StuckEnd` log record (episode id = the `Stuck` record's `sig`/`id`), written by `app/run/stuck.py` when `StuckWatch` closes an episode (it already tracks `silent_said`/`red_said`). The dashboard's answer becomes "the newest `Stuck` with no later `StuckEnd`": one comparison, no rule. Delete `stuck_of`'s episode logic. Old logs have no `StuckEnd`: the reader treats a log with no `StuckEnd` rows and a finished run as not stuck, and a live run falls back to the old rule for one release (logged when the two disagree), then the fallback goes with the 7-day log window.
2. **Ready: one number, published.** Delete the fallback branch of `ready_count`. With a live loop the number is its `queue` (unchanged). With no live loop the page has two honest answers: "unknown, loop absent" or bd's own ready set. Recommend bd's: the index already reads the repo's beads, and `bd ready` is the only definition of ready the owner knows; the dashboard takes `ready` as a field of the bead row the index loads (the index cache is rebuildable, so no durability rule is touched), not a rule of its own. To verify at the cut: that the index loader can fetch `ready` in the call it already makes.
3. **Wire types leave `contracts/dash*.py`.** `dash.py` 547, `dashenums.py` 68, `dashruns.py` 45, `dashcost.py` 39, `dashhealth.py` 35, `snapshots.py` 146, `slottable.py` 123 = about 1,000 lines, 23 src importers and 23 test importers (about 35 test files). Move the page-only types (cards, rows, `Pass`, `LaneCard`) to `taskloop_dash/wire/`; keep in `contracts/` only what the engine and the page both read (`WRITES`, the log records, `loop_absent`-style rules). Mechanical, wide, no behaviour.
4. **Read verbs do not reconcile (M-111).** Callers of `runlife.reconcile` in read paths: `cli/wait.py` (2), `app/report/card.py`, `app/run/requests.py`; the loop already reconciles each pass (`app/loop/loop.py:168`). Reconcile writes (a LOST run gets its end). Make the loop the only caller; read verbs read the state as it is and mark a run "lost (not yet reconciled)" from the same pure `runlife` check. `tl wait` is the sharp one: a waiter must not sit on a dead run for a pass interval; it keeps a pure liveness check and treats "dead and unreconciled" as CRASHED without writing.
5. **Dash Ports (M-147) and the package cycle (M-177).** `quiet` catches `SystemExit` and returns a default; make it return `Unavailable` and let the page show the missing source. Break the `views` <-> `readers`/`index` cycle by moving the shared row types down into `wire/` (they are the cycle). Small, rides with step 3.
6. **Blind-spot ratchet (M-242).** A test that lists the dashboard fields rendered without a fixture asserting them; a rise fails. Lands last.

Not in scope: M-189 (the dashboard as a client of a `tl dash-feed` process) and M-200 (one lane view model, part of LANEPURGE's rename). Both are bigger than a cut here; M-189 changes where the dashboard runs, which is Denis's call.

## Cut order (each a PR green on `just test`)

1. **StuckEnd**: the record, the writer in `app/run/stuck.py`, the reader with the one-release fallback and a disagreement line. First slice, the smallest. Test: one fixture log, `tl status` and the page give the same stuck.
2. **Ready**: delete the `ready_count` fallback; `ready` from bd on the bead row. Test: the same fixture world, loop up and loop down.
3. **Read verbs stop reconciling**: `wait`, `card`, `requests`; the loop keeps its call. Test: the crash matrix (`tests/run/test_crash_matrix.py`) still lands every row.
4. **Wire types out of contracts** (wide, mechanical, one PR, run when the queue is empty: it touches 23 + 23 files).
5. **`quiet`/Ports and the cycle**, then the blind-spot ratchet.
6. **Passes/phases/floor** only if owner decision 2 says so.

Total: 6 PRs; code moved or deleted about 800 py (the derivation), 1,000 py relocated; net deletion about 300 py.

## Owner decisions, with a recommendation

1. **Share through `contracts/` pure functions, or let `taskloop_dash` import `taskloop.domain.projection`?** Recommend contracts: the contract stays as it is, the dashboard stays a reader, and there are only two rules (stuck, ready) to share.
2. **Pass rows: add a `Pass` record to the engine log (the architecture note) or keep deriving passes from `PassEnd` + phase order?** Recommend keeping, and deferring: passes work today, the risk is to owner trust (the page is how Denis sees the factory), and nothing in the bead's acceptance needs it.
3. **Ready with no live loop: bd's `ready` or "unknown"?** Recommend bd's `ready` (step 2 above).
4. **Fallback for one release, with a logged disagreement, or a hard cut?** Recommend the one release for stuck only: old logs carry no `StuckEnd`, and a hard cut would show finished-looking runs as stuck.
5. **Does `tl wait` keep a pure unreconciled-liveness check?** Recommend yes; the alternative makes waiters latency-bound by the loop's pass.
