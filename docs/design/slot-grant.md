# Slot grant: deterministic prevention of the 2026-11-03 stall (design only)

Verdicts: ✅ do, ❌ refuse. Cost = rough size. Incident: docs/incidents/2026-11-03-slot-queue-deadlock.md.

| Item | Verdict | Cost | Note |
|---|---|---|---|
| (a) Slot allocation as ONE atomic operation: `slot` table + `waiter` table ordered by `seq` in factory.db; `grant()` = one `BEGIN IMMEDIATE` that picks the lowest (prio, seq) LIVE waiter and assigns one free, set-up slot; leases carry owner pid + start_id + expiry; the same transaction reaps expired leases and drops dead waiters; a take cannot be written by anyone but grant | ✅ but LATER | M (about 150 lines + tests) | Natural first consumer of factory.db. Needs the `family` flip mechanism. Today's file-based take stays until then. |
| (a') Interim, file-based: the take refusal path (waiter first in line cannot use the slot) must drop or demote the ticket and the engine.take file may only be written inside the grant call by the first ticket; clear a take whose owner is a waiter | ✅ NOW | S | = tl-bxk.10.33.10; first find which hypothesis (3) is true |
| (b) Liveness invariant watchdog: a pure function over (slots, waiters, leases, now): `free slot AND live waiter AND no grant for > N s` = violation; `bead ready AND lane idle AND free slot > N min` = violation. A violation is logged as an incident row and auto-healed (re-run grant pass, drop stale lease). Runs in the loop tick and in `tl doctor` | ✅ NOW | S-M | Works on files today (read slots + tickets), on DB later. It is the alarm that was missing. |
| (c) Deterministic simulation / property test: random interleavings of waiters, crashes, setup failures, stale claims, with fake clock and fake processes; asserts "no free slot while a live waiter exists beyond one grant pass" and "a slot is never held by a non-running owner" | ✅ NOW (with (a')) | M | Fixed seeds in the logic suite plus a longer nightly seed sweep; catches the incident class, not just this case |
| (d) A setup failure is never retried while holding the slot | ✅ NOW | S | = tl-bxk.10.33.11 |
| Single global lock for all slot logic | ❌ | | serializes lanes; the atomic grant gives the same safety without it |

## Order decision (before or inside DB-08)
Neither. (a'), (b), (c), (d) first on files, as part of LOOPWALL, because they need no database and remove the live risk. The DB-backed `grant()` becomes its own family `slot` AFTER DB-03 and finish_run (tl-zej9.14), and the property test from (c) is its parity proof: the same random-interleaving suite runs against the file implementation and the DB implementation and must agree.

## Status of the file version (tl-bxk.10.33.12)
- (b) shipped: `domain/slot_liveness.py` (pure: slots, line, now -> violations), `app/slots/watchdog.py` (reads the facts, logs a `slot_stall` event once per episode, heals). It runs in every waiter's poll (`line.wait_slot`, so loops and `run-task --wait`), once a loop pass (`loop.py step`) and read-only in `tl doctor`.
- Heals: a free slot beside waiters that do not take it drops the tickets ahead of the caller (the first one when the caller is no waiter): a waiter needs no ticket to take. A slot an automatic taker holds with no engine lock for 15 min loses its lease. A slot set aside for 30 min, and a ready bead beside an idle lane and a free slot for 10 min, are only reported.
- Which 2026-11-03 hypothesis survives the current code: the 12 h set-aside is gone (a pending probe is retried on every take). Still possible, and now caught: a setup that never passes (aside_too_long), a live waiter hung with its ticket at the head (free_beside_waiter), a holder that died without releasing (orphan_held). Pid reuse behind a dead ticket is not realistic: the next reader of the line drops a dead ticket within seconds.
- (c) shipped: `tests/slots/test_slot_sim.py`, ten fixed seeds on the real SlotPool, ticket line and watchdog; the control test turns the heal off and the same seeds must break both invariants.
