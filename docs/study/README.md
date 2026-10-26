# Lifecycle measurement (tl-7y6.1.1)

`tl report lifecycle [--repo R] [--since T] [--until T] [--json]` prints one block per UTC week (Monday 00:00 to
Monday 00:00, half-open, clipped to the window). Source: `~/.config/task-loop/traces.jsonl` rows of the repo, their
engine logs, `asks/`, delegate `history.jsonl`, `route.py status --json`, and `git log` for reverts. A measure that
cannot be computed prints `unavailable (reason)`, never 0.

## Metric lines (the names are the contract)

| line | definition |
|---|---|
| `landed beads/day` | distinct beads with a landed run ending in the bucket / bucket days |
| `slot-min per landed bead` | slot-min (run time clipped to the bucket) / landed beads |
| `non-landing slot-min share` | slot-min of runs whose outcome is not landed / slot-min; `done` counts as non-landing |
| `avoidable asks/week` | asks whose kind is one the engine could have avoided (infra, budget, replan, denied, no acceptance) |
| `beads landed on run 1` | landed beads whose first run ever is the landing run; shares of landed and of touched |
| `runs per landed bead` | every run in the bucket / landed beads |
| `median dead time per started_because` | gap between a run's end and the next run's start, by that next run's reason |
| `fingerprint top-5 (beads/day)` | most common normalised failure causes, beads per fingerprint per day |
| `max consecutive same-fingerprint non-done runs per (lane,model)` | longest streak in delegate history |
| `slot-min in runs >180 min` | clipped slot-min of runs longer than 180 min |
| `verify-stage slot-min` | time inside verify nodes |
| `hung-step slot-min` | first vendor error or last event to kill, from `kill`/`vendor_error` records |
| `median release-gate minutes` | `gate` records that ran (cached gates excluded) |
| `uncached input tokens per landed bead` | input minus cached input over sessions / landed beads |
| `reverts per 100 landings` | landings reverted or fixed-forward within 7 d / eligible landings; landings with an unfinished 7 d follow-up are censored out |
| `quota % consumed per landed bead` | only with quota observations over the window; one current snapshot is never used |

`started_because` and `fingerprint` are written into every new trace row and into the `close` node. Rows from before
this engine have `kill`, `vendor_error`, `gate` and `cache` records missing, so those measures read `unavailable` for
old windows. Which 8 of these lines are the council's experiment metrics was not supplied with the bead.

## Baseline

`docs/study/baselines-2026-10-25.json` is written by `python3 tools/freeze_baseline.py` (read-only; needs this machine's
`~/.config/task-loop` and the lifesim checkout). It holds engine version, source sha, window, every metric over the whole
window as one bucket, the figures at the study snapshot, `corrections` (study figures more than 10% off), `unavailable`
(with reasons) and the cache-hit table for docs-only/design-only rounds after commit 5c05cccc.
