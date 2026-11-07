# ASKAI: a worker call returns a typed result; the caller persists it with the done-memo (tl-e5t0.59)

Part of ARCHVERT (`stage-isolation.md` section 7, finding 6). Docs only; the slices below are code.

## Problem

`WorkerCall` (`app/run/worker_call.py`) writes engine fields from inside a call:

| write | where | what it is |
|---|---|---|
| `e.writer.seen` | `take_answer` | the brief and plan hashes the writer has seen |
| `e.planner_ref` | `end_call` | the planner's session ref |
| `e.last_flag` | `end_call` | `same_family` / `degraded` of the last call, read by look, verify and review |
| `e.lane_notes`, warn, comment | `end_call` | the same-family note |

`end_call` first calls `done_memo.keep` (a row in `factory.db`, table `step`), then `c.state.consumed()`. The fields above live in
`RunState`, which reaches disk only at the next `Checkpoints.save` (a row in the same `factory.db`, table `checkpoint`). A crash
between the memo and the next save leaves a consumed step whose session ref, fallback and planner ref are gone: the resumed run
reuses the answer and starts the next call with a stale thread.

## Decision

1. **`AskAi.ask(req) -> Asked`** (kernel port, `stage-isolation.md` (b)). `Asked` is a frozen value:
   `data`, `family`, and `updates: Updates`. The call never touches the engine.
2. **`Updates`** (frozen, one per call; contracts layer, no delegate import):
   - `session: SessionUpdate | None`: `seen` for the writer's brief and plan hashes; delegate owns the thread ref and context;
   - `flag: str`: `same_family` / `degraded` / `""`, reported by delegate; the engine never infers it from family names;
   - `note: str`: the lane note, or `""`.
3. **`settle(asked)`** is the caller's one function (kernel, next to `done_memo`): it applies `updates` to a `RunState` copy and writes
   the done-memo row and the checkpoint row **in one `factory.db` transaction**. `done_memo.keep` gets a variant that takes the open
   connection (`RunRows.transaction`, same `shared_rw` handle the checkpoint rows use). Then `c.state.consumed()`. Order is kept:
   memo and updates together, then consumed. A crash before the transaction re-asks nothing new (the call state still says
   `calling`); after it, recall finds both.
4. **Notes** (`warn`, `comment`, `lane_notes`) are effects, not state: `settle` returns them and the caller emits them after the
   transaction (an effect that is repeated after a crash is only a duplicate line; the dedupe on `lane_notes` stays).
5. **`last_flag` is not persisted.** It is a plain engine attribute today, not in the checkpoint; putting it there is an on-disk change that
   `Rec` refuses on a rollback. It stays in memory: `Updates.flag` is applied to the engine by the host, per call. It is not in `RunFacts` (frozen).
6. **`settle` amends only** the session (`writer.*`), `planner_ref` fields of the checkpoint state. It never
   writes `step`, `applied`, `ended` or any other field.
7. **Pause stays where it is** (the `retry_after` engine field) in slices 1-2. Moving it into the close intent is the
   last step of the close-intent work (stage-isolation.md section 7), not this bead's.

## What does not change

Request building, retries, stop handling (`LaneActs`) and what each stage sends. `host.ai` keeps its shape for the six call sites
(`plan`, `sendback`, `write`, `review`, `verify`, `look`) until slice 3.

## Slices (each behaviour-preserving, one PR)

1. **Value and transaction.** `Updates`/`Asked` in `contracts`, `done_memo.keep` on an open connection, `settle`. `take_answer` and `end_call` compute `Updates` and call `settle`; fields are still assigned from `Updates` by the host, so no caller changes. Crash test (below).
2. **Move the writes out.** `worker_call` returns `Asked`; the host's `ai` applies it. `grep -n "e\.\(writer\|planner_ref\|last_flag\|fallback_lane\|writer_fallback\)" worker_call.py` is empty.
3. **Callers take `Asked`.** Six call sites; `AskAi` as a port in the stages that use it. Waits for the stage hosts (ARCHVERT-HOSTS).

Order with B-LOOK: B-LOOK slice 1 lands before ASKAI slice 1 (shared `state.py` mapping); ASKAI slice 2 lands before B-LOOK slice 3 (`FakeLookPorts.ai`).

Not touched: `paths.py`, ids, run layout, `policy.TABLE`/`retry.PLAN` (B2b, held for Denis).

## Acceptance criteria

- No engine field is written by `worker_call` (a test greps the module for `self.e.<state field> =` and `e.<state field> =`).
- `Asked.updates` carries session, fallback, flag and note; each has a unit test from a `DelegateResult` (fallback only when delegate said it; read-only same-family override).
- A crash test: inject a failure after `settle`'s transaction and before `consumed()`; reopen the run; the done-memo is found **and** the checkpoint holds the same session ref, fallback and planner ref. A second test fails the transaction midway (after the memo row, before the checkpoint row): neither is visible.
- `settle` leaves `step`, `applied` and `ended` alone: `select_step` answers the same before and after (test).
- `carry_done_memo` (raw SQL on the same `step` table) still finds the memo `settle` wrote (test).
- A crash after `settle` and before `consumed()` resumes without asking the worker again (test).
- A checkpoint written before ASKAI (no `planner_ref`) still loads (test).
- `last_flag` is not a checkpoint field (a test of the checkpoint's wire keys).
- Ratchets: no new `Any`, `cast`, ignore; files under 400 SLOC; unit-layer tests only (`workdir` fixture for the sqlite file).

## Open

- Verified: `LoopRows` (checkpoint) and `RunRows` both open `factorydb.shared_rw(cfg.factory_db())`, so they share one per-thread connection and file. `begin_immediate` is not reentrant (a nested `BEGIN IMMEDIATE` errors), so `settle` opens one transaction and writes the checkpoint row on that connection: slice 1 adds `RowDoc.write_in(con, rec, expect_rev)`, the body of `write` without its own transaction, and `write` calls it.
- Pause into the close intent: after the close-intent step, a separate bead.
