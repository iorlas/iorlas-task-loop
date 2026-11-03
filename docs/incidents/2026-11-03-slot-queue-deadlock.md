# Incident 2026-11-03: slot capacity lost to a 12 h set-aside on the Mac (lifesim), about 2 h, 7 lanes

Source: measured on the Mac by the local session and relayed; NOT reproduced on this box. Beads: tl-bxk.10.33.10 (SLOTQUEUE), tl-bxk.10.33.11 (SLOTSETUPFAIL).

## Timeline (Mac local time as reported)
- 05:42 `tl slot reset s2 for lifesim-d5f.34` failed: `did not give a clean tree: setup exited 1`. The real cause was `tools/check_agent_guides.py` (docs/agents/unity.md 25131 bytes over the 24756 cap, grown by the writer's WIP). The engine reported it as "waiting for infrastructure ... will be retried" and retried.
- 05:56 loop pid 25425 wrote `.slots/s2/.task/engine.take` while itself waiting ("no free slot for this loop: 2 ahead in line for 60 min").
- Tickets 000424 and 000425 (pids 75904, 73860; `~/.config/task-loop/slots/lifesim-5615f08c`) were ahead of it and could not take s2. Slot s2 was free and set up. 7 lanes queued for about 2 h; one lane worked; load was low.
- 07:30 cleared only by a full factory restart.

## Causes (from the report and a first code read; the first three are hypotheses until reproduced)
1. Setup failure caused by the bead's own tree is mapped to an infra retry that keeps the slot: `app/loop/take.py:58` turns every `SlotFail` except `bead_pinned` and `busy` into `pre_engine` (the "waiting for infrastructure" wait).
2. Slot grant is two steps (ticket in the line, then take under `hold_path` on `RepoDirs.engine_take`, `paths.py:281`), not one atomic grant.
3. Revised after the saved evidence (tickets 000424-000426, line.lock, engine.take record; the slots dir and the take files were removed by hand before this was preserved): `.slots/s2/.task/engine.take` is the record file of the short `hold_path` mutex that guards a take (`app/slots/engine_lock.py:66,117`, `adapters/locks.py:59`), written with the last holder's pid and time (25425 at 05:56:28). It is not a take of the slot: it is probably a stale record of a brief hold, so "a waiting loop holds a take" is NOT supported and bead .10 must be re-read in that light. `line.py` says only the first live ticket may take, and tickets 424/425 were first. The better-supported hypotheses, in order: (a) slot s2's slot bead stayed held or broken after the failed setup of d5f.34 at 05:42 (cause 1), so `Slot.free_reason` refused it for every waiter regardless of order; (b) tickets 424/425 belonged to live loops that could not take for another reason (area/profile, refusal that keeps the ticket); (c) pid reuse kept a dead ticket live (`pid_start` is null in all tickets, so reuse cannot be told apart). To decide: the s2 slot bead state at 05:50-07:30 (bd show of the slot bead / its comments), and the lines in loop-25425.log, loop-73860.log, loop-75904.log, loop-64620.log around 05:42-06:00 on the Mac.
4. Nothing detected it: idle lanes + a free slot + a non-empty line for 2 h raised no alarm.

## Cost
About 2 h x 6 lanes of factory time (a quarter of a night's lanes).

## Prevention
See docs/design/slot-grant.md (bead tl-bxk.10.33.12).

## ROOT CAUSE (confirmed from the Mac loop log, 2026-11-03, relayed)
Not a queue inversion. `loop-25425.log`: 05:43:01 d5f.34 setup failed on s2; 05:43:07 "waiting for infrastructure, retried"; 05:56:47 second failure; 05:57:02 "SLOT s2 SET ASIDE for 12 h: 2 runs failed within 1.5 min each (lifesim-d5f.34 ...)"; 05:59:13 "no free slot ... 2 ahead in line". The slot bead (s2) stayed in_progress and the set-aside survived a factory restart (a 07:34 restart did not free it). With 2 slots, 1 set aside and 1 busy, the two tickets ahead waited on s1 only. The `engine.take` pid was a stale mutex record; hypotheses (b) and (c) are dropped.
Fixes: bead tl-bxk.10.33.11 (own-tree failure fails the bead, not infra) and the new SLOTASIDE-LIFECYCLE bead (set aside the bead not the slot; aside auto-clears on a passing probe; shown as degraded capacity; restart reports it); tl-bxk.10.33.10 is refuted; the watchdog in tl-bxk.10.33.12 counts an aside older than N minutes as a violation.
