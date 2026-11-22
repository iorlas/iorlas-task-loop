# Workflow experiments: results and what they taught us

Status: archive of experiments run 2026-11-21 and 2026-11-22 (epic tl-7125, declarative workflows). One folder per
experiment with its report, the per-run result files and the task or check material. Raw run trees, transcripts and
agent patches stay outside Git (`/tmp/aa`, `~/.codex/sessions`); the reports quote what they showed. The running list of
improvements these experiments produced is [../improvement-ledger.md](../improvement-ledger.md) (rows L1 to L67).

All runs used Codex `gpt-6.1-sol` (CLI 0.169.0), plan effort `high`, implement effort `medium` unless a report says
otherwise, the default workflow, `land: manual`, and never landed. Arms are fresh clones with their own tracker,
`factory.db`, artifacts and slot. Samples are small: read every number as exploratory.

## Index

| experiment | what it asked | runs | result in one line |
|---|---|---|---|
| [pair1](pair1/report.md) | Does an A/A pair run end to end on a frozen engine? | 2 (1 a, 1 b), task "Add slugify" | Both passed; they differed by ~20% in input tokens and wall time, which one pair cannot interpret. Task too easy. |
| [pilot1](pilot1/report.md) | A/A noise on a harder task (`parse_duration`) | 20 (10 per arm) | 18 held `needs_owner`, 2 passed: the plan contradicted rules only the hidden acceptance check knew. Measured nothing about noise. |
| [pilot2](pilot2/report.md) | Calibrate a task that sometimes fails, then A/A noise baseline | 8 calibration + 10 (5 per arm) | Calibration never found failures (6 pass, 2 plan holds). The 10-run A/A passed 10/10: input tokens 221k (sd 8.6k) vs 232k (sd 31k), agent wall 144.7 s (sd 13) vs 158.8 s (sd 22). |
| [pilot3](pilot3/report.md) | Does lower implement effort make first attempts fail? | 4 | `low` is the lowest effort offered; 4/4 passed first try, 0 repeats. |
| [pilot4](pilot4/report.md) | Does a repo-convention trap make first attempts fail? | 8 (two trap variants) | 8/8 passed first try: the agent reads every document the repo points at. |
| [pilot5](pilot5/report.md) | Feedback A/B (default vs attempt-budget) on real repo tasks | 2 valid-but-capped, plus invalid setup pairs | No verdict (run cap too short for 5-6 minute checks). First real failed checks: lint/format/type slips the agent could not run in its sandbox (4 of 4). |
| [pilot6](pilot6/report.md) | Same A/B after the cheap-checks prompt (#863) | 6 valid (3 pairs) | 0 of 6 failed a check at attempt 1; the attempt-budget text was never rendered, so the A/B says nothing about it. |
| [pilot7](pilot7/report.md) | Cost A/B: implement effort `low` vs `medium` on real tasks | 6 (3 pairs: two docs tasks, one code task) | 6/6 passed first try at both efforts, 0 repeats. `low` was 4-20% cheaper on the code task and indistinguishable on the docs tasks: inside the A/A noise at n = 3 pairs. Effort did not change the number of model requests. |

Earlier arms (old engine, schema v34) are kept outside Git as history; the current build cannot read them.

## What we learned

1. **Noise baseline.** At 5 runs per arm on one small task, agent wall time has a standard deviation of 9 to 14% of the
   mean and input tokens 4 to 13%. A 5 to 10% difference between arms is not distinguishable from noise; seeing a 10%
   wall difference needs well over 10 runs per arm (pilot2, ledger L34).
2. **Confounders to control.** Arm confounded with concurrency by chance; prompt-cache warmth (cached input ratio
   0.74 to 0.94 on an identical prefix); time of day; plan length varies run to run; the planner's size gate (`Depth:
   large`, above three behaviours) holds some tasks before any implementation. Block-randomize pairs, report uncached
   input separately, count holds as results (L35 to L38).
3. **The agent sees the check.** The check command is in the profile and the prompt, so agents run it before
   finishing and fix failures inside their own attempt. A "hidden" check is hidden from the files, not from the agent;
   it leaked case names in pilot1. Never compare runs across different profiles (L22, L39).
4. **No contamination found.** In eight transcripts agents stayed in their checkout, loaded only the checkout's
   `AGENTS.md`, no skills, plugins, memories, network or other runs (L40).
5. **Failed-check repeats come from the environment, not model weakness.** Synthetic tasks produced 1 repeat in 30
   runs. Real tasks failed lint/format/type at attempt 1 in 4 of 4 runs because the agent's sandbox could not run the
   repo gate (no bd database, read-only gate cache) and the old prompt told it to run `just check`. The cheap-checks
   prompt (#863) fixed that: 0 of 6 failed at attempt 1 afterwards (L51, L53, L58).
6. **The attempt-budget variant is untested.** It renders only in the feedback after a repeat; with repeats now rare it
   was never shown (L59). Parked until a failure the agent cannot fix before answering can be engineered, or real
   repeats accumulate.
7. **A fresh slot is not a ready slot.** `mise` trust, a bd database and a branch upstream (the secret scan reads all
   history without one) were blockers in a synthetic setup; in a real slot the first two do not occur and the third is
   covered by the `.gitleaks.toml` allowlist (#866; shelf proposal `shelf-branch-upstream.md`) (L52).
8. **Cost per run on real tasks.** Docs tasks about 0.5 to 0.6M input tokens (mostly cached) and 8 to 12 minutes;
   a code task 1.8 to 2.2M input and 14 to 17k output; one check cycle 5 to 6 minutes with two runs in flight
   (L50, L56).
9. **Same instruction, opposite behaviour.** Two runs of one task diverged on whether an agent may edit the protected
   public-surface snapshot; the variant text was not involved (L63).

## Method standard for the next experiment

- Freeze engine, base commit, task text, workflow digests and efforts; record them in the report header.
- Block-randomized pairs (one a, one b, random order inside the pair); at most two in flight; record in-flight count
  and host load per run.
- Screen every task before the first run: it must not need an edit to a protected file (public-surface snapshot, DDL
  hash, import contracts, repeated-string census, shelf pins, workflows).
- Calibrate with one run, then one pair, before any four-run calibration; agree the acceptance window and the token
  cap up front. Size the wall cap from a measured check cycle and stop at a step boundary after the check verdict.
- Report repeats as the denominator for any feedback comparison; report uncached and cached input separately;
  compare plan and implement separately (plan wall varies 60 to 222 s).
- Use `tl attempt export` (columns include `failed_checks`, `repair_count`, `rework_count`, `hold_text`,
  `task_total_seconds`, `ran_model`, `harness_version`); keep per-run results JSON, not run trees.

## Reproduce

`pilot5/run6.py` and `pilot6/run7.py` are the runners used (fresh clone, local bare origin, tracker, `factory.db`,
rounds stopped by confirmed pid). They assume `/tmp/aa` paths and an engine worktree; read the report's Setup section
first. Task texts are under `tasks/`; hidden check sources (pilot1, pilot2, pilot4) under `hidden/`.

## Next

No experiment is queued. The effort cost A/B (pilot7) is inconclusive at n = 3 pairs; seeing a 10% difference needs well
over 10 pairs of screened code tasks, which only pays off if the goal is a cheaper default effort.
