# Pilot 3: feedback A/B calibration, task v4 `parse_duration` (aa-hard1), default workflow, Codex gpt-6.1-sol

## Result in one line
Implement effort `low`: 4/4 passed on the first attempt, 0 failed_check repeats. NOT accepted. No weaker effort exists: `low` is the lowest effort gpt-6.1-sol offers, so I stopped after 4 runs (cap was 8).

## Setup
- Engine: `aa-engine` untouched at origin/main ecb6092be. Engine digest, workflow digest (default.toml), base commit 97c7b318 and task text are the same as pilot 2, so the results stay comparable.
- Setting mechanism: per-run machine config `[agents.implement] effort = "low"` in each run's `cfg.toml`. The workflow file is not touched, so the workflow digest is identical in both arms. `tl config show` printed `agents.implement.effort = low (file)` and `agents.plan.effort = high (default)`. The export shows `effort=low` and `ran_effort=low` for implement, and high for plan, in all 4 runs.
- Runner: `/tmp/aa/pilot3/run3.py`, copied from pilot 2's `run2.py`. Changes: the effort line in `cfg.toml`, and 2 block-randomized pairs (one a and one b, started together, order inside each pair random; group order `b01 a01`, then `a02 b02`). The other guards are unchanged: fresh clone, tracker, db and artifacts per run, land never run, rounds stopped by pid only, host load sampled at start and end.
- Valid efforts: `~/.codex/models_cache.json` lists low, medium, high, xhigh, max, ultra for gpt-6.1-sol. `minimal` is not offered, and the factory accepts any identifier without checking, so it would fail only inside Codex.

## Per-run rows (all in flight 2)
| run | outcome | implement attempts | failed_check repeats | uncached in | cached in | out | agent wall s (plan+impl) | elapsed s | load1 start/end |
|---|---|---|---|---|---|---|---|---|---|
| a01 | pass | 1 | 0 | 38944 | 154112 | 4146 | 110 (62+48) | 128 | 1.50/1.71 |
| b01 | pass | 1 | 0 | 26751 | 146560 | 4557 | 114 (60+54) | 128 | 1.50/1.71 |
| a02 | pass | 1 | 0 | 44886 | 148096 | 4083 | 108 (59+49) | 118 | 1.71/2.58 |
| b02 | pass | 1 | 0 | 29056 | 143488 | 4434 | 273 (222+51) | 285 | 1.71/1.79 |

- Compared with pilot 2 (effort medium), the implement step is cheaper: 48-54 s against roughly 80-100 s.
- The plan step dominates the wall time, and `b02` shows a 222 s plan outlier.
- 0 answer repairs, 0 plan holds, 0 infrastructure failures.
- Total input is about 173-193k tokens per run (pilot 2: 195-264k), output about 4.1-4.6k.

## Decision: accepted setting
None. The task text states every rule, and the model passes even at `low`. At 0/4 repeats, a one-sided 95% bound says the true repeat rate could still be up to about 53%. Four runs cannot distinguish a 0% rate from a 30% rate, but 0 repeats in 22 runs overall (18 earlier plus these 4) points to a rate that is low, not merely unmeasured.

## What a failing A/B setup needs (not run; would need a decision)
1. Lower the plan effort too. A thinner plan may leave rules out. This is an untested guess and is cheap to try (4 runs, about 0.8M input tokens).
2. A task whose acceptance hinges on a fact the agent must discover. A fact stated in the text is always satisfied. A task of this kind needs a new calibration.
3. A weaker model. This changes the model under test, so the owner decides.

## Cost to run 8 per arm (default vs attempt-budget, 8 block-randomized pairs, at effort low)
- 16 runs at about 183k input and 4.3k output per run: about 2.9M input tokens (about 0.5M of them uncached) and about 70k output tokens.
- Wall: about 2 to 4.5 minutes per pair, so about 20 to 40 minutes for 8 pairs run one after another.
- Extra cost only if repeats occur. A failed first attempt adds roughly another implement attempt (about 50-80k tokens). With no repeats the A/B would show nothing about feedback, so run it only after a setup that produces repeats.

## Decisions made
- Used the machine config (a per-run file) rather than the `--effort` flag, because the flag overrides plan and implement together, and rather than a copied workflow, which changes the digest.
- Stopped after set 1 instead of trying "minimal": the model does not offer it, and low is already the lowest, so no weaker effort setting exists.
- Pairs ran concurrently (in flight 2), as in pilot 2.
- Hidden check path left at `/tmp/aa/pilot2/hidden/accept.py` (it is in the base profile, so the base commit is identical).

## Improvements noticed
### A/A method
- Calibrate the failure rate with the stage, not the effort: implement effort barely moves the first-attempt pass rate when the text states every rule.
- Report uncached and cached input separately (done above). Plan wall time varies much more than implement wall time (60 s to 222 s), so compare plan and implement separately.
### Tooling
- The factory accepts any effort string (`identifier` validation only). Validating against the harness's offered levels at configuration time would fail fast, instead of failing inside Codex.
- `--effort` overrides plan and implement together. A per-step flag would avoid the per-run config file.
- The export needs a plan+implement total and a per-task token sum (summed by hand here).
### Storage
- Run trees: `/tmp/aa/pilot3/low_a/runs/*` (about 3 MB each); results JSON per run in `/tmp/aa/pilot3/low_a/results`. Nothing deleted. Nothing committed to the repo.
