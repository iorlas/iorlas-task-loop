# Pilot 9: feedback A/B with an engineered failed check. 11 of 12 runs reached a repeat; the attempt-budget sentence did not change what the agent did

## Result in one line
Calibration (6 default runs): 6/6 failed the engineered `convention` check at implement attempt 1 and 6/6 passed after one repeat, so the design was accepted without adjustment. A/B (6 pairs): **11 of 12 runs reached a repeat** (denominator; 1 default run held at plan before any implement). Of those, 10 passed on the first repeat (default 4 of 5, attempt-budget 6 of 6) and 1 needed a second repeat (default `tl-p6d_a`). The budget sentence `Implement attempt N. The failed-check repeat cap is 3, including the initial attempt.` was in the stored attempt-2 input of **all 6 attempt-budget runs and 0 default runs**. Outcome after the repeat: no difference that n = 5 vs 6 can resolve. **Verdict: feedback works as a mechanism (agent fixes the convention from the check output alone); the attempt-budget sentence showed no measurable effect and no harm.**

## Setup
- Engine: new worktree `ab-engine9` at origin/main `562e84d4fc881f45ecb7dd239957e64896cb06c5` (#870); engine source digest `eff68ff03d7a` (sha256 over `src/**/*.py`). Workflow digests: default `2c1046c8…`, attempt-budget `f6c4d010…`; `diff` shows they differ only by the added `use = "attempt_budget"` feedback section. `max_attempts` 3. Codex 0.169.0, gpt-6.1-sol, plan high, implement medium.
- Base repo: that commit + one local commit (`4c46ef56`): `land: manual`, checks wrapped in `env BEADS_DIR=<empty external tracker>`, `docs/changelog.md` (an empty `## Unreleased` section), and a third **required** check `convention` (`python3 /tmp/aa/pilot9/convention_check.py`). `MISE_TRUSTED_CONFIG_PATHS` set. Same base in both arms.
- **Engineered failure.** `convention_check.py` (outside the repo, so not in the agent's checkout) does two things in order: (1) an environment gate: write a stamp file into `~/.cache/pilot9-stamps`, which is read-only inside the Codex sandbox; (2) a convention: the diff from `merge-base(HEAD, origin/main)` must add a line starting `- ` to `docs/changelog.md`. Failure message: "convention: every change must add one changelog line. Add a line starting with '- ' under the '## Unreleased' heading of docs/changelog.md, then commit it with the change." The task texts never mention a changelog.
- **Verified before running** (`codex sandbox`, workspace-write, no network): in the sandbox the check fails on the stamp (exit 2, "Read-only file system"), so the agent can never see the convention message by running it; outside the sandbox it passes the gate and fails on the missing changelog line (exit 1). Confirmed in the factory: attempt 1 `check-1-convention.log` shows exit 1 with the message; attempt 2 shows "convention ok: 1 changelog line(s)".
- Runner `/tmp/aa/pilot9/run9.py` (from pilot 6): fresh clone/origin/tracker/db/artifacts/slot per run, local bare origins only, nothing landed or pushed, 2 in flight, caps 45 min / 4M input tokens per run (never reached; longest run 1195 s, largest input 3.0M including cache), 3-consecutive-infra stop (not triggered). Block-randomized pairs and order: `order.txt`.
- **The host rebooted mid-pilot** (about 20:06; `/tmp/aa` was wiped). The first calibration started 19:35 and was lost with no result. Everything was rebuilt from scratch (same design) and rerun from 20:57; those first calibration runs are not counted anywhere. The `ab-engine9` worktree survived.
- Host load (1 min) at run start 2.9 to 8.8 on 14 CPUs; other Codex processes at start 0 to 10 (two other experiment sessions share the host); all pairs 2 in flight. The feedback comparison is not timing-sensitive; timings below are for the record only.

## Tasks
| id | kind | note |
|---|---|---|
| tl-p6b | docs: cleanup of experiment trees (`docs/factory-machine.md`) | pilot 6 text, unchanged |
| tl-p6c | docs: hold in the export (`docs/cli.md`) | pilot 6 text |
| tl-p6d | code: `plan_bytes` export column | pilot 6 text; no protected-file hold this time |
| tl-p9a | docs: token columns of the export (`docs/cli.md`) | new, small, no protected files |
| tl-p9b | docs: `--workflow` selection (`docs/cli.md`) | new |
| tl-p9c | docs: restart behaviour (`docs/factory-machine.md`) | new |
Texts in `/tmp/aa/pilot9/tasks/`. The ledger had no further small open rows clear of protected files, so three tasks are new docs tasks written for this pilot.

## Calibration (default arm, 1 run per task)
| run | outcome | implement attempts | failed checks per attempt |
|---|---|---|---|
| tl-p6b_a | pass | 2 | convention; none |
| tl-p6c_a | pass | 2 | convention; none |
| tl-p6d_a | pass | 2 | convention; none |
| tl-p9a_a | pass | 2 | convention; none |
| tl-p9b_a | pass | 2 | convention; none |
| tl-p9c_a | pass | 2 | convention; none |
Acceptance window (first attempt fails in most runs, repeat passes in at least one): met 6/6 and 6/6. Results: `calib-results/*.json`.

## A/B: per-run rows (uncached = input minus cached; whole run = plan + implement attempts)
| run | arm | outcome | implement attempts | failed checks per attempt | budget sentence in stored input | uncached in | cached in | out | elapsed s | time to green / task total s | files / lines (excl. plan files) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tl-p6d_b | attempt-budget | pass | 2 | convention; none | yes | 172275 | 2648576 | 19075 | 1006 | 826 / 993 | 9 / +177 -13 |
| tl-p6d_a | default | pass | **3** | check+test+convention; convention; none | no | 213503 | 2681984 | 20548 | 1195 | 1068 / 1190 | 8 / +193 -26 |
| tl-p9b_b | attempt-budget | pass | 2 | convention; none | yes | 178846 | 993792 | 7954 | 824 | 657 / 810 | 2 / +10 -0 |
| tl-p9b_a | default | pass | 2 | convention; none | no | 135934 | 880640 | 7467 | 1129 | 974 / 1124 | 2 / +9 -0 |
| tl-p6c_b | attempt-budget | pass | 2 | convention; none | yes | 123857 | 796928 | 6023 | 623 | 490 / 613 | 2 / +6 -0 |
| tl-p6c_a | default | pass | 2 | convention; none | no | 155577 | 818688 | 6434 | 867 | 737 / 860 | 2 / +3 -1 |
| tl-p6b_a | default | pass | 2 | convention; none | no | 131763 | 707584 | 7615 | 811 | 674 / 796 | 2 / +37 -0 |
| tl-p6b_b | attempt-budget | pass | 2 | convention; none | yes | 99699 | 844928 | 6117 | 630 | 527 / 623 | 2 / +23 -0 |
| tl-p9c_a | default | pass | 2 | convention; none | no | 122025 | 960640 | 6542 | 936 | 817 / 928 | 2 / +9 -0 |
| tl-p9c_b | attempt-budget | pass | 2 | convention; none | yes | 92452 | 1150976 | 8126 | 1156 | 1001 / 1143 | 2 / +9 -0 |
| tl-p9a_a | default | **held at plan** (no implement) | 0 | none | no | 43055 | 343296 | 3937 | 119 | none | 0 |
| tl-p9a_b | attempt-budget | pass | 2 | convention; none | yes | 123589 | 785664 | 5960 | 652 | 547 / 645 | 2 / +7 -0 |
(Every pass "files" count includes the one `docs/changelog.md` line, +1 to +2 lines.) Pair order was randomized per pair; see `order.txt`.

## The question: what happened after the repeat
Denominator: **11 runs reached a repeat** (5 default, 6 attempt-budget; `tl-p9a_a` held at plan, 119 s, before any implement attempt: the planner answered with a plan-step hold whose text reads like a finished plan; it is a result, not replaced).
| | default (n = 5) | attempt-budget (n = 6) |
|---|---|---|
| passed on the first repeat | 4 | 6 |
| second repeat needed | 1 (`tl-p6d_a`, see below) | 0 |
| held after the repeat | 0 | 0 |
| budget sentence in the stored repeat input | 0 of 5 | 6 of 6 |
First-repeat attempt (implement attempt 2) means: uncached input 43.2k default vs 36.2k attempt-budget; output 983 vs 1051 tokens; agent wall 58 s vs 69 s; time to green 854 s vs 675 s; whole-run elapsed 988 s vs 815 s. These sit inside the known A/A noise (wall sd 9-14%, input sd 4-13%) and the arms differ in load at the time; read them as no difference. In every run the repeat was a single docs-file edit; the agent added a changelog line and nothing else, in both arms, so directness is equal.

## The one default run that needed two repeats (tl-p6d_a)
Attempt 1 failed three checks (`check` and `test` for a natural reason: a refusal-coverage test on the new code, and `convention`). The failed-check input of attempt 2 shows **only the first failed check** (`check`, with its output); the `convention` result is not in the feedback at all (it appears only as a command in the check list). The agent fixed the test failure, did not add a changelog line, and failed `convention` again; attempt 3 added it. So this repeat was caused by the engine's feedback showing one failed check at a time, not by the arm: the budget sentence would not have changed it. Not seen in the other 10 runs because they failed only `convention`.

## What agents did with the check inside the sandbox
In the runs I read (p6d_a attempts 1 and 2), the agent's final answer states `python3 /tmp/aa/pilot9/convention_check.py exited 2 because its review stamp directory is read-only` and that the full gates are factory-owned: agents do run the profile's extra check, see the environment failure, and correctly treat it as not theirs. The convention was never learned from the sandbox output, as designed.

## Conclusion (small n)
- The engineered failure is honest and works: all 17 runs that implemented failed it at attempt 1 (the 18th run held at plan) and 16 of 17 fixed it from the failure message in one repeat; the feedback text carries the whole fix.
- The attempt-budget sentence rendered in all 6 arm-b repeats and none in arm a, and the repeat outcomes are the same (default 4/5 first-repeat passes, budget 6/6; the one miss is explained above and unrelated to the arm). **At n = 5 vs 6 nothing separates the arms; the sentence neither helped nor hurt.** It cannot be judged better or worse from this; keeping it or dropping it should be decided on other grounds (it adds a section and a code path).
- Cost per run: 0.6-1.2M cached-heavy input and 6-8k output for docs tasks, 3.0M and 19-21k for the code task; the repeat itself costs about 35-45k uncached input and about 1k output tokens, roughly 60 s of agent wall.

## Decisions made
- Failure source: required `convention` check outside the repo, environment-gated by a read-only directory (verified in `codex sandbox`), message states the whole rule; chose the changelog rule because it applies to every task and needs no change to the repo's other gates.
- Used the three pilot 6 task texts and wrote three new docs tasks (no further screened rows exist in the ledger).
- Moved the calibration trees to `runs-calib/` so A/B result files and trees are separate.
- Counted `tl-p9a_a` (plan hold) as a result and did not replace or rerun it; counted the pre-reboot lost calibration as not-runs.
- Fixed the runner after calibration run 1 to check the budget sentence in `input.txt` only (the first draft also matched transcripts); the A/B used the fixed runner.
- Did not touch other sessions' files; nothing committed to the real repo; no pids killed (all runs ended on their own).

## Improvements noticed
### Engine
- **The failed-check input shows only the first failed check.** When two required checks fail, the agent sees one and the other reappears as a second failed-check repeat (tl-p6d_a: one wasted attempt, ~46k uncached input). Show every failed check (names at least) in the feedback.
- `tl attempt export` already carries `failed_checks` per row; a row with `failed_checks: [check, test, convention]` next to feedback that names one check is the evidence.
### A/B method
- A feedback A/B works only with an engineered failure the agent cannot reproduce: the check's environment gate is the part that keeps it honest; verify it in `codex sandbox` first (done).
- The denominator (runs that reached a repeat) was 11 of 12: report it before outcomes (L60 holds).
- To see an effect of the sentence one would need a failure that is not fixed by one edit; with a trivially fixable failure both arms end at one repeat. A harder engineered failure (a fix needing two attempts) is the only way to exercise the cap.
### Tooling
- A host reboot wiped `/tmp/aa`: keep the runner, tasks, scripts and a copy of the base repo outside `/tmp` (a copy is in `~/.cache/pilot9-src`). Durable evidence of this pilot: `results/*.json`, `calib-results/*.json`, `diffs/*.patch`, this report.
- The planner's plan-step hold in `tl-p9a_a` (hold text describes a finished plan) is worth a look: a plan answered as held without a stated cause. Not investigated.
### Storage
- Trees left in `/tmp/aa/pilot9/runs` and `runs-calib`; worktree `ab-engine9` (a git worktree of this repo) to be removed when done; the directory `~/.cache/pilot9-stamps` and `~/.cache/pilot9-src` are mine to delete. Nothing deleted.
