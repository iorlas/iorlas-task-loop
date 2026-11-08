# QUOTA: quota-aware admission and a per-bead token budget (tl-7i9k.16, R9-19)

Status: proposal, 2026-11-06. Nothing here is built. Ideas: M-402 (admission), M-403 (token budget); M-275 (reserve verb) and M-276 (accounts across two machines) are out of this note.

## Problem

The weekly window of a subscription account runs out before it resets (a measured burn of 1.2 points an hour) and the loop keeps claiming beads: the calls then end `busy` or `no_account` (35% of calls in one week, 55 `busy` refusals on 11-01) and every refusal costs a retry round. `engine.budget_usd` caps nothing on a subscription: delegate's dollar cost is 0 or unknown (tl-7y6.4.12 now stores `null` for unknown). The only per-bead bound is time.

## What exists

- `StatusSnapshot.accounts[].windows[]` (`used_pct`, `resets_at`), `five`, `week`, `out`, `out_until` (contracts/delegate_status.py): the reading, refreshed by `tl accounts` / `tl usage`.
- `CallEnd.tokens` (in, cached, out, cache_write) per call and `Engine.stats["tokens_*"]` per run; `fresh = in - cached + out` (dash `runfacts.fresh`).
- A typed wait already parks a bead without failing it (`pause_reasons.Reason`, owner asks, `profile_ahead` as the latest example).

## Design

1. **Samples.** The loop's chore (each pass, no model call) reads the snapshot and appends `(t, account, window, used_pct, resets_at)` to a `quota:samples` kv row, kept 48 h. One writer: the loop (a rules entry in test_state_writers).
2. **Risk, pure.** `domain/accounts/quota.py`: `risk(samples, now) -> QuotaRisk(account, window, projected_pct, resets_at, level)`. Burn = slope of `used_pct` over the last 6 h (at least 3 samples, else `unknown`, which never holds). `projected = used + burn * hours_to_reset`. Level `risk` when `projected >= loop.quota_hold_pct` (default 100); `out` when delegate says the account is out. Pure and table-tested; a reset (used_pct drops) starts a new series.
3. **Hold.** `Taker` asks the risk before a claim. A bead whose write family is the account at risk is not claimed; the loop says `quota: <account> projects <p>% at reset <time>` once per change and sleeps to the earlier of `resets_at` and the next pass. Beads of another family keep running (the second writer family, per the synthesis). A claimed bead is never stopped by this. New typed wait `quota` in the dashboard account card; no bead fails and no ask is filed.
4. **Token budget.** `engine.budget_fresh_tokens` (default 2_000_000; 0 = off) charged from `CallEnd` fresh tokens across all runs of the bead (the trace rows already sum per bead). Checked at a step boundary beside the existing `budget_min`: over it, the run parks with the owner ask `budget` (raise it with `tl override`, or split the bead). Replaces `budget_usd` as the default bound; `budget_usd` stays for API-priced accounts.
5. **Config.** Two new keys (`loop.quota_hold_pct`, `engine.budget_fresh_tokens`). A new `.task-loop.json` key ships one release after the code that reads it, so the code reads both with defaults and no profile change goes with the code.

## Slices (one PR each, tests first)

1. Samples + `domain/accounts/quota.py` + table tests (no behaviour change).
2. Hold in `Taker` + the `quota` wait + fake-clock loop test (window runs out, claim held, reset, claim taken).
3. Token budget charge + `budget` park + test with the sample `CallEnd` rows.
4. Dashboard: risk on the account card (reads the kv row through the locator).

## Decisions for the owner

- Default `quota_hold_pct` 100 holds only when the week will run out; 90 keeps a reserve for the owner's own sessions on the same subscription. Which?
- Default budget 2M fresh tokens: no landed-bead data is in this repo; take it from `tl report` before slice 3 (the median landed bead and its 95th percentile).
- Hold scope: the account's family only (above), or every claim. Family only keeps the second family warm; every claim protects a shared subscription.
- Measuring: the success test is `busy`/`no_account` calls per week before and after; the dashboard's account-card history is enough, no new monitoring.
