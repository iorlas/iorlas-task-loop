# LOOPBUDGET: a cap on the loop's wall minutes per window (tl-oi1)

Status: proposal, 2026-11-06. Nothing here is built. This is the simplified bead (owner sweep 2026-10-28): one cap, summed wall minutes of bead runs, one config int, a stop with one reason line. Call counting is dropped (no quota reader; delegate lanes report their own limits). The open-asks list is not built: the Decisions view and `tl ask list` already show them.

## Problem

A night cannot run away only if something bounds it. Today the bounds are per bead (`budget_min`, `budget_min_by_label`) and per resource (`min_free_gb`, `min_ram_mb`). Nothing bounds the sum: a loop with four slots and repeatedly retried beads spends as long as the beads keep coming. The owner cannot say "at most 8 hours of runs tonight".

## What exists

- `LoopWait` with a typed reason and a `wake` text: `low_disk` stops claims below `loop.min_free_gb` and says why (app/loop/waits.py). A budget stop is the same shape.
- `LoopConfig` (contracts/config.py): constants of the loop, re-read at every tick.
- Run rows in factory.db with `started`, `ended`, `state` per run, and `RunTrace.started/ended`; the scorecard already sums `minutes` per bead (app/report/card.py).
- The dashboard shows a loop wait on its card and lists open asks (Decisions); the strip shows the scorecard window.

## Design

1. **The number.** `loop.window_budget_min` (float, default 0 = off): the most wall minutes of bead runs the loop starts claims for inside one window.
2. **The sum.** Wall minutes of every run of this repo that began inside the window, `ended - started` for a finished run and `now - started` for a live one. Waits for a shared resource do not count (the same exclusion `budget_min` makes). Retried runs count: retries are what the cap is for. One pure function, `domain/loop/window.py: spent(rows, since, now) -> float`, table-tested on a fake clock.
3. **The window.** A rolling `loop.window_hours` (default 12) back from now. Rolling needs no notion of "night", no clock-zone rule and no reset moment to get wrong; the cost is that the cap frees minutes gradually, not all at once at dawn.
4. **The stop.** Before a claim, `Taker` asks `spent >= window_budget_min`. If so no new bead is claimed; the loop writes one line, `budget: <spent> of <cap> min in the last <h> h; next claim when <t>`, once per change, and returns `LoopWait(reason="budget", wake=<time the oldest counted run leaves the window>)`. A claimed or running bead is never stopped by this (the per-bead budget does that). The loop stays up, so a raised cap or an old run leaving the window resumes it with no restart.
5. **Dashboard.** The wait chip already renders any `LoopWait`; add the `budget` reason text and the spent/cap numbers to the strip line (`Score` gains `budget_spent_min` and `budget_min`, filled by the same `spent` function so `tl report` and the strip cannot disagree). No new view.
6. **Config.** One new key. A new `.task-loop.json` key ships one release after the code that reads it (the pre-push judge refuses an unknown field), so the code reads it with its default off and the profile change goes in the next release.

## Slices (one PR each, tests first)

1. `domain/loop/window.py` + table tests (live run, finished run, run straddling the window start, waits excluded, empty). No behaviour change.
2. `LoopConfig.window_budget_min/window_hours` + the `Taker` check + `LoopWait("budget")` + fake-clock loop test (cap hit, claim held, oldest run ages out, claim taken).
3. Strip and `tl report` numbers; one test per state (off, under, at the cap).

## Decisions for the owner

- **Rolling window or a calendar night?** Recommend rolling 12 h: no clock-zone rule, nothing resets on a timer. A calendar night ("22:00 to 07:00") is exact for "tonight" but needs a zone and a reset rule.
- **Default cap.** Recommend off (0) in code and the owner sets it per repo; with 4 slots a night of 8 h is up to 32 h of summed run minutes, so say which unit the owner thinks in (summed run minutes, as here, or wall hours of the loop). Recommend summed run minutes: it is what a run row records.
- **Does a retry count?** Recommend yes: repeated failure is the failure mode the cap exists for, and not counting it would let the cap miss exactly that.
- **Stop or ask?** Recommend a quiet wait with one log line, no owner ask: an ask at 03:00 helps nobody, and the wait clears itself. The owner sees it on the strip in the morning.
- **Interaction with QUOTA (docs/design/quota.md).** They are separate caps (minutes here, subscription burn there) and can stack. Recommend building this one first: it needs no lane data.
