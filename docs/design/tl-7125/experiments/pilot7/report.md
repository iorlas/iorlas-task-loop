# Pilot 7: cost A/B of implement effort, `low` vs `medium` (default workflow both arms), 3 pairs

## Result in one line
6 of 6 runs passed on the first implement attempt, 0 failed-check repeats, 0 repairs, 0 holds, 0 infrastructure failures. Implement effort `low` was **about 5-20% cheaper in implement tokens and time on the code task, and indistinguishable from medium on the two docs tasks**; at n = 3 pairs that is inside the A/A noise. Both code diffs satisfy the task.

## Setup
- Same engine and base as pilot 6: `ab-engine6` at origin/main `ee47568084d2…` (engine digest `5d4e75d2cf7b…`), base commit `5c8c5ebae…` (+`land: manual`, `BEADS_DIR` for the checks; a copy in `/tmp/aa/pilot7/base-src`). **Default workflow in both arms (digest `2c1046c8…`, equal)**; effort set per run in the machine config `[agents.implement] effort`: arm a = `medium`, arm b = `low`; plan effort `high` in both (the export shows `ran_effort` medium/low for every implement row, `high` for plan). Codex 0.169.0, gpt-6.1-sol, `max_attempts` 3.
- Tasks of pilot 6 (texts in `/tmp/aa/pilot7/tasks/`): tl-p6b (docs, cleanup of experiment trees), tl-p6c (docs, how a hold appears in the export), tl-p6d (code, `plan_bytes` column). One pair per task, started together (2 in flight), order random inside the pair (tl-p6d: a,b; tl-p6b: a,b; tl-p6c: b,a); task order d, b, c. Fresh clone/origin/tracker/db/artifacts/slot per run, local bare origins only, nothing landed or pushed, nothing committed to the real repo. Caps 45 min (after the current check verdict) and 4M input tokens: not reached (longest 910 s, largest input 2.83M).
- Runner `/tmp/aa/pilot7/run8.py` (from pilot 6's; diffs rebuilt from the task branches in each run's repo).

## Per-run rows (uncached = input minus cached; time to green / task total from the export)
| run | effort | outcome | attempts | failed-check repeats | repairs | uncached in | cached in | out | plan wall s | impl wall s | time to green / task total s | elapsed s | files / lines changed (excl. plan files) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tl-p6b_a | medium | pass | 1 | 0 | 0 | 91106 | 475392 | 5695 | 118 | 55 | 386 / 505 | 517 | 1 / +33 -0 |
| tl-p6b_b | low | pass | 1 | 0 | 0 | 87354 | 454528 | 5688 | 123 | 52 | 482 / 607 | 611 | 1 / +27 -0 |
| tl-p6c_a | medium | pass | 1 | 0 | 0 | 79482 | 472192 | 4603 | 93 | 52 | 530 / 624 | 632 | 1 / +4 -0 |
| tl-p6c_b | low | pass | 1 | 0 | 0 | 92477 | 507776 | 4697 | 92 | 61 | 418 / 513 | 526 | 1 / +1 -1 |
| tl-p6d_a | medium | pass | 1 | 0 | 0 | 149730 | 2677888 | 19308 | 145 | 393 | 756 / 902 | 910 | 9 / +179 -14 |
| tl-p6d_b | low | pass | 1 | 0 | 0 | 128807 | 2375936 | 15577 | 133 | 316 | 660 / 795 | 805 | 9 / +151 -13 |
Host load (1 min) was 1.5-5.6 on 14 CPUs. Pilot 6's medium runs of the same tasks are extra reference points (not paired): tl-p6b 163 s agent wall, tl-p6c 146 s, tl-p6d 464 s (the `a` arm; here medium gave 173, 145 and 538 s): the medium runs repeat to within 0-16% on wall (p6d: 464 vs 538 s).

## Per-effort summary (mean of 3 tasks; low vs medium)
| measure | medium | low | low / medium by pair (p6b, p6c, p6d) |
|---|---|---|---|
| uncached input tokens | 106.8k | 102.9k | 0.96, 1.16, 0.86 |
| cached input tokens | 1.20M | 1.11M | 0.96, 1.08, 0.89 |
| output tokens | 9.9k | 8.7k | 1.00, 1.02, 0.81 |
| implement agent wall s | 166.7 | 143.0 | 0.95, 1.17, 0.80 |
| plan + implement agent wall s | 285 | 259 | 1.01, 1.06, 0.83 |
| time to green s | 557 | 520 | 1.25, 0.79, 0.87 |
Medium and low each ran their implement step with 5-7 model requests on the docs tasks and 30-31 on the code task (export `turns`), so effort did not change how many requests the agent made.

## Quality read of the code task (one reader, unblinded)
Both diffs touch the same 9 files (export, store, `attempt_loads`, CLI, tests, the protected public-surface snapshot and its fixture), add a `plan_bytes` column from the plan's committed content in Git, with NULL for no committed plan, and add no schema change; both passed the repo's `just check` and `just test` first time.
- medium (`tl-p6d_a`, +179/-14): finds the plan commit from the latest plan attempt's `end_commit`; adds 4 tests (no fall back past a plan that produced no commit, no leak across task scopes, an unreadable commit is a visible failure, the value on every row of the task).
- low (`tl-p6d_b`, +151/-13): requires the plan commit to be fenced (a stored factory-commit verdict `committed`), stricter provenance; adds 1 parametrized test (committed blob measured once per task; missing and unreadable content).
- Neither does anything extra; the medium diff has more test coverage (4 tests vs 1 parametrized), the low diff has the stricter evidence check. I cannot rate which is "better"; both satisfy the acceptance criteria as written. The docs tasks produced the same single-file change in both efforts (27-33 lines for tl-p6b, 1-4 lines for tl-p6c).

## What n = 3 pairs can and cannot show
- Cannot: an effect of a few percent either way. The A/A noise (wall sd 9-14%, input sd 4-13%) is as large as the largest effect seen (0.8-1.17), and the pair ratios point in both directions (p6c: low was 17% slower on implement, 16% more uncached input). Three tasks, one sample each, one provider window.
- Can: that `low` did not break a first attempt on these three tasks (6/6 pass, same checks), that it did not change the number of model requests, and that on the code task low was lower on every cost measure (tokens 4-20%, implement wall 20%), the one place with enough work for effort to matter; that direction is consistent with the expectation, but it is one pair.
- Cannot: quality differences beyond "satisfies the task" (single unblinded reader), or anything about failure rates: no run failed a check, so the effort's effect on the first-attempt failure rate is unmeasured (0 of 6 vs pilot 5's 4 of 4 before the cheap-checks prompt).

## Decisions made
- Used the per-run machine config (`[agents.implement] effort`) so both arms share the workflow digest; the new per-step flag from #864 would also have worked.
- Pilot 6's runs are reference points only; no pair mixes them.
- Rebuilt all diffs from the task branches (`git diff <base> task/<id>`), as the slot resets to the base after a pass.
- Stopped nothing early: no cap tripped, no run needed a stop; all rounds exited at their terminal state (no stray pilot 7 processes remain).

## Improvements noticed
### A/B method
- Effort cost differences per task are small next to the plan step, which is high effort in both arms and costs as much wall as the whole implement step on docs tasks (92-123 s plan vs 52-61 s implement); effort tests on implement only touch about a third of the wall of a small task.
- Report ratios per pair, never only means: three tasks of very different size make the mean dominated by the code task.
- A quality comparison of the two diffs needs a rubric fixed before the run (does it satisfy each acceptance line, tests added, files outside the task); this one was ad hoc.
### Tooling
- Per-run machine config is the only way to set one step's effort per run without a new workflow file; `--effort` per step now exists (#864) but the runner still writes cfg files: a runner that takes the flags would drop that code.
- `tl attempt export` has everything needed for this table but the changed-files and lines columns (L6): they come from `git diff` on the task branch.
- The export's `turns` (model requests, 30-31 for the code task) is a useful second cost axis and was not in the earlier tables.
### Storage
- Run trees under `/tmp/aa/pilot7/runs` (full clone, bare origin, venv, slot per run); durable: `results/*.json`, `diffs/*.patch`, this report. Nothing deleted.
