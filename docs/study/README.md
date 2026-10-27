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

## Experiments (tl-7y6.1.2)

`tl experiments [list|check] [--repo R] [--since T] [--until T] [--json]` reads one typed sidecar per bead from
`<repo>/.task-loop/experiments/<bead-id>.json` (council 49 §5: <= 8 open, one metric each, typed, revert pre-written,
overdue is visible). The repo is resolved with `tl.repo_root` (list, check and verdict alike), so the command finds
the same sidecars from any subdirectory of the repository — a subdirectory run never silently reads an empty set.
Fields:

- `hypothesis` (non-empty string) — what the change claims
- `metric` — one KPI id, from the registry below; an unknown id is rejected with the list of valid ids
- `baseline` (number) — the value the current metric is compared against
- `check_when` — either `{"date": "YYYY-MM-DD"}` (due that UTC day, overdue the day after) or
  `{"runs": N, "since": "YYYY-MM-DD"}` with N >= 1 (due once N runs of the bead started on/after the anchor day,
  overdue once a further run started with still no verdict)
- `keep_if`, `revert` (non-empty strings) — the keep condition and the pre-written revert
- `labels` (list of strings) — a `bet` label is rejected: a bet is not an experiment
- `created` (optional `YYYY-MM-DD`)
- `verdict` — `null` while open, else `{"kind": "keep"|"revert"|"extend", "date": "YYYY-MM-DD"}`; any verdict closes
  the experiment record. The typed-comment grammar (`@verdict keep|revert|extend`) arrives with s1-intake-parser;
  until then `tl experiments verdict ID keep|revert|extend [--date D]` writes the sidecar field, and a closed record
  is never re-verdicted (`extend` means a new sidecar).

The current metric is `tl report lifecycle`'s value over `--since`/`--until` (default: the last 7 days) as one
window; a measure that report cannot compute prints `unavailable`, never 0. An overdue open experiment is flagged
`NO VERDICT`, never silent. Experiments are counted independently of bead closure: only a verdict closes one, and
`tl experiments check` exits 1 when more than 8 are open (or a sidecar is rejected); `tl experiments` alone exits 0.

The KPI ids (each printed in brackets at the end of its `tl report lifecycle` line; `landed beads/day` etc. below are
the labels, the bracketed id is what a sidecar's `metric` takes):

- `landed_beads_per_day` — landed beads/day
- `slot_min_per_landed` — slot-min per landed bead
- `non_landing_slot_min_share` — non-landing slot-min share
- `avoidable_asks_per_week` — avoidable asks/week
- `landed_run1_share` — beads landed on run 1 (share of landed)
- `runs_per_landed` — runs per landed bead
- `slot_min_over_180` — slot-min in runs >180 min
- `verify_stage_slot_min` — verify-stage slot-min
- `hung_step_slot_min` — hung-step slot-min
- `median_release_gate_minutes` — median release-gate minutes
- `uncached_input_tokens_per_landed_bead` — uncached input tokens per landed bead
- `reverts_per_100_landings` — reverts per 100 landings
- `quota_percent_per_landed_bead` — quota % consumed per landed bead

The registry (`lifecycle.KPIS`) only names existing week-row JSON keys; it never calculates, so an experiment's
current value is exactly the number the lifecycle report printed for the same window.

### Loading experiments from beads (one-off importer)

`python3 dev/migrate_experiments.py --snapshot beads.json [--mappings overrides.json] [--repo R] [--json]`
(tl-7y6.1.2 stage 2) reads an explicit worktree-local bead snapshot — `bd list --json --all -n 0` output saved to a
file, or `{"beads": [...]}` — and never queries the tracker. `--repo` is resolved as given (no git): a one-off
writer writes exactly where it is told. Only a bead's `## Experiment` description block is extracted (the exact
heading, a trailing colon allowed; `## Experiments` or prose mentions are not blocks), as typed `field: value` lines:

    ## Experiment
    hypothesis: smaller slices raise the beads landed per day
    metric: landed beads/day
    baseline: 0.14
    check_when: date 2026-11-02
    keep_if: landed beads/day stays >= 0.2 for a whole week
    revert: git revert the slice commits and re-freeze the baseline

`metric` may be the registry id or its label (normalized through `lifecycle.KPIS`); `check_when` is `DATE`,
`date DATE` or `N runs since DATE` (an indented continuation line extends the value above it). A baseline or trigger
the block cannot express faithfully — prose ("about a third"), ranges ("3-5 runs"), "after the asks settle", "next
release" — is never guessed, and asks or releases are never reinterpreted as runs: the typed value goes in the
mappings file, `{"<bead-id>": {"metric": ..., "baseline": ..., "check_when": {...}, "created": ...}}` (only those
four fields; the text comes from the block, never from a mapping).

The import is all-or-nothing: every record is validated by the shared stage-1 contract before anything is written,
so bet labels, duplicate or path-escaping bead ids, unknown metric names, invalid records, a conflicting different
open sidecar, or a resulting open count above 8 (existing open sidecars included, verdict-closed ones not) reject
the whole import and leave the repo untouched — exit 1 for refused bead content, 2 for a malformed snapshot or
mappings file. Existing verdicts are never overwritten (a closed sidecar stands, `kept` in the report) and an
identical rerun writes nothing (`unchanged`). Provenance lives in the report (stdout, or `--json`: bead id, title,
status, the block's text, the snapshot path) — the sidecar's own schema carries only the stage-1 fields above, and
the sidecar is named after its bead.

The eight experiments of this stage are **not** loaded yet: the worktree holds no complete source snapshot (an
all-status arch-study-1025 listing found six `Experiment` blocks, some on closed beads, with ranges and
asks/releases-based triggers needing explicit mappings). `tests/fixtures/experiments/migration-beads.json` is
deliberately synthetic — eight invented beads proving the importer; loading the real eight waits on that snapshot
and its mappings, then `tl experiments` reports them against their baselines.

## Baseline

`docs/study/baselines-2026-10-25.json` is written by `python3 tools/freeze_baseline.py` (read-only; needs this machine's
`~/.config/task-loop` and the lifesim checkout). It holds engine version, source sha, window, every metric over the whole
window as one bucket, the figures at the study snapshot, `corrections` (study figures more than 10% off), `unavailable`
(with reasons) and the cache-hit table for docs-only/design-only rounds after commit 5c05cccc.
