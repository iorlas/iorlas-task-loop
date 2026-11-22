# Pilot 6: feedback A/B on real tasks, current origin/main: no failed-check repeat occurred, so feedback was never exercised

## Result in one line
6 valid runs (3 pairs): 5 passed on the first implement attempt, 1 held at attempt 1; **0 failed-check repeats, 0 repairs, 0 infrastructure failures**. The attempt-budget text renders only in feedback after a repeat, so no run ever saw it: the two workflows were byte-equivalent in every run. **This A/B cannot say anything about the attempt-budget variant.** What it does show: with the cheap-checks prompt (#863) lint failures went from 4/4 runs (pilot 5) to 0/6.

## Setup
- Engine: new worktree `ab-engine6` at origin/main `ee47568084d20de164d20f19d840f8df03aa59f3` (#867); engine digest `5d4e75d2cf7b…`. Workflow digests: default `2c1046c8…`, attempt-budget `f6c4d010…`; `diff` shows they differ only by the added `use = "attempt_budget"` feedback section. `max_attempts` 3. Codex 0.169.0, gpt-6.1-sol, plan high, implement medium.
- Base repo: that commit + one local commit (`5c8c5eba`): `land: manual` and checks wrapped as `env BEADS_DIR=<empty external tracker> just check|test` (needed, the repo's gate needs a bd database; `MISE_TRUSTED_CONFIG_PATHS` for slots). No sandbox note in the task texts and no gitleaks allowlist (already in the repo).
- Runner `/tmp/aa/pilot6/run7.py` (from pilot 5): fresh clone/origin/tracker/db/artifacts/slot per run, 2 in flight, caps 45 min (stop only after the current check verdict) and 4M input tokens per run, nothing landed or pushed, no retries. Files left over from another session's earlier smoke run (`runs/tl-p5c_a`, `results/tl-p5c_a.json`) are not mine and not counted: it passed after one failed check (802 s).

## Tasks
| id | ledger | kind | note |
|---|---|---|---|
| tl-p6a | L8 | `tl drain` saves the export when finished | **screened out** before running: it changes the drain result, which is in the public-surface snapshot (a protected file). Its pair failed at build with a missing task file (2 infrastructure starts, 0 tokens) |
| tl-p6b | L27 | docs: cleanup of experiment trees (`docs/factory-machine.md`) | |
| tl-p6c | L29 | docs: how a hold appears in the export (`docs/cli.md`) | |
| tl-p6d | L38 | code: `plan_bytes` export column, no schema change | |
Only 2 further screened tasks could be found in the open ledger rows (no other open row is both small and clear of protected files); I ran what there was. 4 pairs were planned, 3 ran. Texts in `/tmp/aa/pilot6/tasks/`.

## Per-run rows (uncached = input minus cached; time to green and task total from the export)
| run | arm | outcome | attempts | failed-check repeats (checks failed) | repairs | uncached in | cached in | out | agent wall s (plan+impl) | time to green / task total s | elapsed s | files / lines changed (excluding plan files) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tl-p6b_a | default | pass | 1 | 0 | 0 | 86157 | 406656 | 5801 | 163 (109+54) | 578 / 688 | 700 | 1 / +27 -0 |
| tl-p6b_b | attempt-budget | pass | 1 | 0 | 0 | 86559 | 488064 | 4646 | 146 (88+59) | 390 / 480 | 486 | 1 / +26 -0 |
| tl-p6c_a | default | pass | 1 | 0 | 0 | 94190 | 515456 | 4577 | 146 (100+45) | 381 / 483 | 498 | 1 / +4 -0 |
| tl-p6c_b | attempt-budget | pass | 1 | 0 | 0 | 82881 | 526080 | 5033 | 150 (91+59) | 491 / 583 | 592 | 1 / +5 -0 |
| tl-p6d_a | default | pass | 1 | 0 | 0 | 133483 | 1687552 | 17122 | 464 (181+282) | 413 / 596 | 611 | 8 / +181 -12 |
| tl-p6d_b | attempt-budget | **held** (`failed:needs_owner` at implement 1) | 1 | 0 | 0 | 134139 | 2035840 | 14466 | 411 (130+280) | none | 422 | 0 (no commit) |
Load average (1 min) at start/end 1.6-3.1 / 1.8-5.6 on 14 CPUs; all pairs ran 2 in flight. No cap was hit: longest run 700 s, largest input 2.17M.

## tl-p6d: one arm passed, one held. Was it the workflow?
- Both agents planned the same way (plan 3.9 KB, one behaviour) and implemented with the same input: the two implement-attempt-1 inputs differ only in commit ids and the plan summary text (diff checked). The attempt-budget section is rendered only in the feedback after a repeat; the held run had no repeat, so the variant text was not in its prompt at any point.
- Default agent edited `tests/rules/public_surfaces.json` (and a fixture) and passed; the attempt-budget agent answered `needs_owner`: "Owner review is required to update tests/rules/public_surfaces.json; AGENTS.md forbids editing what judges this work." So the same AGENTS.md instruction on protected files produced opposite behaviour in two runs: plain run-to-run variance; one pair cannot show anything more, and the workflow cannot have caused it.

## Did the cheap-checks prompt reduce first-attempt failures?
Yes on this sample: pilot 5 (before #863): the check `lint` (and once `test`) failed at attempt 1 in 4 of 4 runs (two tasks). Pilot 6: 0 of 6 runs failed any check at attempt 1 (checks passed on first run in all 5 finished runs, 1 held before checks). Caveat: the tasks differ (two are docs-only), so the drop is not a clean comparison; the code task (tl-p6d_a) also passed first time, where pilot 5's code tasks all failed lint. Agents' answers list `just format/lint/typecheck/rules` runs and focused pytest, as the new prompt asks.

## What happened after repeats
Nothing: no run had a repeat. The question "does the attempt-budget sentence change what happens after a failed check" is **unanswered** (n = 0).

## Conclusion (small n)
- The A/B as designed cannot work with this prompt: the repeats it needs are now rare on real tasks too (0/6, with 4/4 before). To exercise feedback a task must fail checks the agent cannot or does not run (a check run only after the commit, a different environment, or a task that forces a lint/type miss).
- Cost-wise: runs were cheap (docs 0.5-0.6M input and 4-6k output each; the code task 1.8-2.2M input, 14-17k output) and fast (8-12 minutes). Wall and tokens of the docs pairs differ by up to 40% between arms (tl-p6b 700 vs 486 s, tl-p6c 498 vs 592 s) with identical prompts: A/A noise (wall sd 9-14%) already explains it, and here it is larger, a sign of the contention of two runs sharing the host's check capacity.
- Both docs tasks changed one file with +4..+27 lines in both arms (directness equal); tl-p6d_a changed 8 files (the export code, its tests, the protected snapshot and its fixture).

## Decisions made
- Applied the supervisor's rulings as they came: screened tl-p6a out before it ran; kept tl-p6d as a valid pair (the supervisor's correction); no extra pairs; per-run caps 45 min / 4M tokens never reached.
- Treated the two build failures of the screened-out pair as not-runs (no engine start, no tokens), so they do not count toward the 3-consecutive-infrastructure-failures stop.
- Rebuilt all diffs from the task branches in the run's repo (`git diff <base> task/<id>`), because the slot is reset to the base after a pass and the saved patches were empty. Patches: `/tmp/aa/pilot6/diffs/<run>.patch` (tl-p6d_b has none: nothing committed).
- Did not touch the other session's leftover files.

## Improvements noticed
### A/B method
- Prompt-level guards (cheap checks) remove the natural source of repeats; a feedback A/B needs an engineered failure the agent cannot fix before answering (L48). Screen the task for protected files before the run (done for tl-p6a).
- One arm of a pair can hold on an agent decision unrelated to the variant (tl-p6d): count holds, but log whether the variant's text had been rendered at all (it renders only after a repeat); a pair with no repeat tells nothing about the variant.
- Repeats are the denominator: report the number of runs that reached a repeat before any pass-rate comparison.
### Tooling
- The saved per-run diff is empty after a pass because the slot returns to the base; the runner must read the task branch from the run's repo (`task/<id>`), or `tl attempt export` should carry changed files and lines (L6).
- The export columns added in #865 (`failed_checks`, `repair_count`, `time_to_green_seconds`, `task_total_seconds`, `hold_text`) were all present and sufficient; `time_to_green` here is ~100 s below `task_total`, which is the plan phase.
- A missing task file should fail before a pair starts; the runner counted it as an infrastructure start.
### Storage
- Run trees (full clone, bare origin, venv, slot per run) are large; durable evidence: `results/*.json`, `diffs/*.patch`, this report. Nothing deleted: `/tmp/aa/pilot6/runs`, `/tmp/aa/pilot5/runs`, the `ab-engine6` worktree (a git worktree of this repo, to be removed when done).
- Ledger material: (1) the same AGENTS.md rule on protected files gave opposite behaviour in two runs (tl-p6d); (2) the cheap-checks prompt cut first-attempt check failures from 4/4 to 0/6.
