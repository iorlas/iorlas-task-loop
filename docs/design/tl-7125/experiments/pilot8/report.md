# Pilot 8: cost A/B of implement effort, `low` vs `medium` (default workflow both arms), 10 pairs of code tasks

## Result in one line
20 of 20 runs passed on the first implement attempt: 0 failed-check repeats, 0 repairs, 0 holds, no cap tripped. **Implement effort `low` vs `medium` showed no difference in implement wall time (paired geometric mean 1.00, 95% CI 0.92-1.09) and none in total input tokens (0.98, 0.85-1.11); `low` wrote about 13% fewer output tokens in the implement step (0.87, 0.79-0.97, 7 of 10 pairs lower) and its diffs were about the same size (0.89 lines; 7 of 10 smaller).** The one narrow-interval difference (implement output) is one of about ten comparisons and is small in absolute terms (2.6k vs 2.2k tokens). Quality read (one unblinded reader): every diff satisfies its task; medium added a few more tests.

## Setup
- Engine: new worktree `ab-engine8` at origin/main `562e84d4fc88…`; engine digest `5d4e75d2cf7b` and workflow digest `2c1046c8` (default workflow, same in all 20 runs), Codex 0.169.0, model `gpt-6.1-sol` (export `ran_model` and `harness_version` identical on every row). Base repo = that commit + one neutral local commit `d47c2b91…` (`land: manual`; `BEADS_DIR` for the checks; `MISE_TRUSTED_CONFIG_PATHS` kept). The base commit hash differs from earlier pilots' only because that commit was rebuilt (see Decisions).
- Arms: a = `medium`, b = `low` for the implement step, set per run in the machine config `[agents.implement] effort`; plan effort `high` in both (export `ran_effort` confirms medium/low on implement and high on plan for every run). `max_attempts` 3.
- Tasks: 10 distinct small code tasks, one pair each, texts in `tasks/` (`tl-p8a`..`tl-p8j`), found by a scout subagent from open ledger rows and a source read, each checked as undone on the base and as needing no protected file (no api module, schema, snapshot, import contract, ratchet, shelf pin or workflow). None of the 20 diffs touched a protected file (verified from the diffs). Same task id in both arms. Fresh clone, local bare origin, tracker, `factory.db`, artifacts and slot per run; nothing landed, nothing pushed to GitHub, nothing committed to the real repo.
- Design: block-randomized pairs, both arms of a pair started together (always 2 in flight), order randomized inside the pair; pair order a, e, f, d, i, b, h, j, c, g (`order.txt`; within-pair order is the arm order listed there). Caps 45 min after the current check verdict and 4M input tokens per run: not reached (longest run 911 s; largest input 1.22M). Runner `run8.py` (pilot 7's, plus the other-Codex count and in-flight count).
- Confounders recorded per run (last column): other running Codex processes at start (not ours: 0 in 6 pairs, 1 in two pairs, 2 in two pairs), in flight 2 always, load1 1.6-5.7 on 14 CPUs. The count is shared by both arms of a pair (both started within seconds), so it does not bias the paired ratios, but other sessions share the Codex subscription and host, and check cycles (time to green) vary 150-700 s with that load.

## Per-run rows (uncached = input minus cached, all steps; wall/turns from the export; files and lines from `git diff <base> task/<id>` without the plan files)
| run | effort | outcome | att. | repeats | repairs | uncached in | cached in | out | plan wall s | impl wall s | turns | time to green / task total s | elapsed s | files / lines (excl. plan files) | other codex / in flight / load1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tl-p8a_a | medium | pass | 1 | 0 | 0 | 107221 | 704256 | 6703 | 106 | 96 | 9 | 790 / 897 | 911 | 3 / 39 | 2 / 2 / 1.57 |
| tl-p8a_b | low | pass | 1 | 0 | 0 | 108620 | 762496 | 6827 | 108 | 92 | 10 | 242 / 351 | 363 | 3 / 36 | 2 / 2 / 1.57 |
| tl-p8b_a | medium | pass | 1 | 0 | 0 | 93393 | 961664 | 6683 | 104 | 97 | 13 | 302 / 408 | 417 | 2 / 43 | 1 / 2 / 5.74 |
| tl-p8b_b | low | pass | 1 | 0 | 0 | 52623 | 840320 | 6025 | 106 | 80 | 9 | 607 / 715 | 725 | 2 / 49 | 1 / 2 / 5.74 |
| tl-p8c_a | medium | pass | 1 | 0 | 0 | 94121 | 761856 | 6846 | 100 | 90 | 10 | 253 / 356 | 369 | 3 / 64 | 0 / 2 / 3.62 |
| tl-p8c_b | low | pass | 1 | 0 | 0 | 95170 | 1014400 | 8278 | 133 | 101 | 14 | 266 / 400 | 411 | 3 / 60 | 0 / 2 / 3.62 |
| tl-p8d_a | medium | pass | 1 | 0 | 0 | 86120 | 734720 | 5818 | 109 | 94 | 9 | 284 / 396 | 403 | 2 / 41 | 2 / 2 / 4.05 |
| tl-p8d_b | low | pass | 1 | 0 | 0 | 99678 | 642816 | 6292 | 134 | 109 | 7 | 471 / 606 | 614 | 2 / 41 | 2 / 2 / 4.05 |
| tl-p8e_a | medium | pass | 1 | 0 | 0 | 108613 | 907264 | 6829 | 128 | 122 | 13 | 605 / 733 | 740 | 2 / 13 | 1 / 2 / 4.37 |
| tl-p8e_b | low | pass | 1 | 0 | 0 | 92935 | 802560 | 5864 | 109 | 114 | 11 | 490 / 599 | 614 | 2 / 10 | 1 / 2 / 4.37 |
| tl-p8f_a | medium | pass | 1 | 0 | 0 | 82476 | 490112 | 4332 | 74 | 58 | 6 | 254 / 330 | 339 | 2 / 35 | 0 / 2 / 4.75 |
| tl-p8f_b | low | pass | 1 | 0 | 0 | 82353 | 587136 | 5711 | 107 | 64 | 7 | 422 / 531 | 540 | 2 / 36 | 0 / 2 / 4.75 |
| tl-p8g_a | medium | pass | 1 | 0 | 0 | 90828 | 702976 | 7766 | 114 | 100 | 9 | 324 / 439 | 445 | 3 / 73 | 0 / 2 / 2.53 |
| tl-p8g_b | low | pass | 1 | 0 | 0 | 89372 | 840704 | 6409 | 95 | 101 | 12 | 295 / 392 | 402 | 3 / 70 | 0 / 2 / 2.53 |
| tl-p8h_a | medium | pass | 1 | 0 | 0 | 105336 | 839808 | 5855 | 92 | 92 | 12 | 502 / 597 | 607 | 2 / 33 | 0 / 2 / 3.56 |
| tl-p8h_b | low | pass | 1 | 0 | 0 | 103254 | 586624 | 5859 | 91 | 91 | 8 | 290 / 384 | 397 | 2 / 31 | 0 / 2 / 3.56 |
| tl-p8i_a | medium | pass | 1 | 0 | 0 | 80950 | 819456 | 7350 | 108 | 107 | 11 | 243 / 352 | 364 | 4 / 53 | 0 / 2 / 3.73 |
| tl-p8i_b | low | pass | 1 | 0 | 0 | 62307 | 857472 | 6360 | 108 | 120 | 11 | 679 / 788 | 800 | 4 / 46 | 0 / 2 / 3.73 |
| tl-p8j_a | medium | pass | 1 | 0 | 0 | 102627 | 1112832 | 10555 | 156 | 140 | 14 | 361 / 517 | 527 | 2 / 118 | 0 / 2 / 3.68 |
| tl-p8j_b | low | pass | 1 | 0 | 0 | 88182 | 900480 | 8710 | 140 | 116 | 11 | 500 / 642 | 652 | 3 / 61 | 0 / 2 / 3.68 |

## Per-effort summary (n = 10 tasks; mean / median / sd) and paired ratios low / medium
Ratio = geometric mean of the ten per-task ratios; 95% CI from a t interval on the log ratios (shown where I computed it). "Lower" = pairs where low < medium.
| measure | medium | low | paired low / medium | lower |
|---|---|---|---|---|
| uncached input, all steps | 95.2k / 93.8k / 10.3k | 87.4k / 91.2k / 17.7k | 0.90 (0.78-1.04) | 7/10 |
| cached input | 803k / 791k / 169k | 784k / 821k / 140k | 0.98 | 5/10 |
| total input | 899k / 878k / 174k | 871k / 894k / 136k | 0.98 (0.85-1.11) | 5/10 |
| output, all steps | 6.87k / 6.77k / 1.61k | 6.63k / 6.33k / 1.04k | 0.98 | 5/10 |
| implement uncached input | 49.5k / 51.3k / 6.1k | 41.4k / 48.2k / 16.3k | 0.74 (0.48-1.15), median 0.97 | 6/10 |
| implement output | 2587 / 2503 / 750 | 2247 / 2249 / 580 | 0.87 (0.79-0.97) | 7/10 |
| implement turns (model requests) | 10.6 / 10.5 / 2.5 | 10.0 / 10.5 / 2.3 | 0.95 (0.78-1.15) | 5/10 |
| plan wall s | 109 / 107 / 22 | 113 / 108 / 17 | 1.04 (0.91-1.19) | 5/10 |
| implement wall s | 99.5 / 96.3 / 21.4 | 98.8 / 101.4 / 17.5 | 1.00 (0.92-1.09) | 5/10 |
| time to green s (includes checks) | 392 / 313 / 183 | 426 / 447 / 150 | 1.11 (sd of log ratio 0.6) | 4/10 |
| task total s | 503 / 424 / 188 | 541 / 565 / 153 | 1.10 | 4/10 |
| files changed | 2.5 / 2 / 0.7 | 2.6 / 2.5 / 0.7 | 1.04 | 0/10 (9 equal) |
| lines changed (excl. plan) | 51 / 42 / 29 | 44 / 43.5 / 17 | 0.89 | 7/10 |
Per-task ratios (low/medium, tasks a..j) for the headline measures: implement wall 0.96 0.83 1.13 1.15 0.94 1.11 1.02 0.98 1.12 0.83; total input 1.07 0.85 1.30 0.90 0.88 1.17 1.17 0.73 1.02 0.81; implement output 1.01 0.70 1.07 0.84 0.81 1.01 0.94 0.91 0.81 0.72.
The implement-uncached mean ratio is driven by two pairs (b 0.21, i 0.28: the low arm hit a much warmer prompt cache, not a smaller job); the median pair is 0.97. Time to green and task total contain the check cycle, which is host-load noise (pair a: 697 s vs 149 s check for the same diff size), so they say nothing about effort. Effort did not change the number of model requests (10.6 vs 10.0).

## Quality read (one reader, unblinded; rubric: satisfies each acceptance line, tests added, extras)
All 20 diffs satisfy the task text and passed the repo's `just check` and `just test` first time; I read only the source and test diffs, not each test body, so "satisfies" is a reading of the source plus the green checks.
| task | source change | new test functions medium / low | note |
|---|---|---|---|
| a port range | same 3 lines, different message | 2 / 3 | equal |
| b 0600 artifacts | both correct; medium shorter (opener lambda, mkdir loop), low longer (manual `fdopen` and close) | 1 / 1 | medium simpler |
| c slot bound | identical (64) | 3 / 3 | equal |
| d code-map error | near-identical | 1 / 1 | equal |
| e dashboard 500 | identical source | 1 / 0 | low edited two existing tests to assert the fixed body instead of adding a test; medium added one |
| f heading | identical source | 1 / 1 | equal |
| g policy cap | identical source | 4 / 3 | equal |
| h word cap | same logic, medium also rewrote the docstring | 2 / 2 | equal |
| i name cap | same logic; medium also rewrote the docstring | 6 / 4 | medium more tests |
| j trailer block | medium: last paragraph, accepts continuation lines; low: final paragraph must be all trailers (stricter); both cover all three call sites | 3 / 2 | designs differ, both satisfy the stated rule |
Totals: new test functions medium 24, low 20 (medium more in 4 pairs, equal in 5, low more in 1). Extras outside the task: none in either arm beyond two docstring updates (h and i, medium). Source diffs were identical or equivalent in 6 of 10 pairs. Only b and j differ in how the solution is built; neither arm was worse on the task text.

## What n = 10 pairs can and cannot show
- Noise yardstick: per-run A/A sd was 9-14% (wall) and 4-13% (input). The paired log-ratio sd here is 12% for implement wall, 19% for total input, 20% for all-step uncached input, 14% for implement output; so the standard error of the mean ratio is about 4%, 6%, 6%, 4.4%, and a 95% interval about ±9%, ±13%, ±14%, ±10%.
- Can: rule out an implement-wall difference larger than about 9% (the interval is 0.92-1.09) and a total-input difference larger than about 11-13% in either direction, for this model, these small code tasks and this host. Can say effort did not change the number of requests, the first-attempt pass rate (20/20) or the size of the diff in any way visible at this n. A 10% wall effect is at the edge of what 10 pairs resolves; a 5% one is not.
- Cannot: say anything about larger tasks (these diffs are 10-120 lines), about holds or repeats (none occurred in either arm, so the failure-rate effect of effort is unmeasured: 0 of 20, which still allows a true rate up to about 15% per arm at 95%), or about quality beyond "satisfies the task" (one unblinded reader).
- The implement-output reduction (0.87, CI excludes 1) is the single nominal signal; with about ten comparisons one of them landing at p ~ 0.02 is not surprising, so treat it as a hint to re-test, not a result. It is also about 350 tokens per run.
- Cost frame: the plan step (effort `high` in both arms) averaged 111 s and 0.40M input vs 99 s and 0.48M for the implement step: even a real implement saving would move total cost by a few percent. Pilot 7 pointed the same way (all differences inside noise).

## Decisions made
- /tmp was wiped by a host reboot after setup began: rebuilt base repo, runner and the empty bd tracker, and restarted the scout (its output also kept as a copy in the working tree of the supervising worktree). The base commit hash changed from the first build (`9d85c4ae`, never used) to `d47c2b91` (the one used for all 20 runs); contents identical.
- First launch of pair 1 failed at setup, not in the model: the rebuilt base repo had no `main` branch (it was a detached checkout), so every round answered `unavailable:git` and no agent ran (0 tokens). I stopped both rounds by confirmed pid after 30 min, filed the two infra results in `infra-attempt1/`, created `main`, and re-ran pair 1 once (counts as a setup retry, not as extra budget: the 20 reported runs are all valid and none was retried for a model reason). That is 2 infra failures from one cause, below the 3-consecutive stop.
- Meaning decisions inside two tasks (`tl-p8f` plan heading tolerance, `tl-p8j` trailer-block rule) were stated in the task text as requirements rather than asked, as the owner wanted no questions; both are tiny and not landed.
- Pair 1 had no failure to diagnose (both passed), so all other pairs were started right after it ended.
- Diffs rebuilt from each run's task branch (`git diff <base> task/<id>`); plan files `docs/design/<task>/plan*` excluded from the file and line counts.
- Never landed, pushed or committed; stopped processes only by confirmed pid (the two failed rounds); no stray pilot 8 processes remain.

## Improvements noticed
### A/B method
- The check cycle (150-700 s, two runs in flight plus other sessions) dwarfs agent time, so "time to green" is not an effort metric; report implement wall and requests, and keep the check time as its own column.
- Prompt-cache warmth swings uncached implement input by up to 5x on a pair (b, i); compare total input or output, or force one warm-up call, before reading uncached tokens.
- A blind per-run quality rating would add little here: 6 of 10 pairs had identical or equivalent source; test counts are the visible difference.
- A pass rate of 20/20 means the effort question is now only about cost; a failure-rate question needs harder tasks (a plan hold or a repeat never occurred in 32 real-task runs since #863).
### Tooling
- The runner needs a precheck that the base repo has the branch the profile targets (`main`) before starting a pair; a misnamed or missing branch cost 30 minutes and showed only as `unavailable:git` in `rounds.log` while the runner's state stayed empty. A rounds start that fails fast on an unavailable target would be better than a 5-minute backoff loop (values 9).
- The runner should write its pair order to `order.txt` only once per pair; a retry appended a second block and I moved the first aside.
- `tl attempt export` already carries everything needed except changed files and lines (L6, L61): still rebuilt from the task branch.
### Storage
- `/tmp/aa/pilot8/runs` is 3.2 GB for 20 runs (clone, venv and slot per run), 160 MB per run, far above the 3 MB of earlier pilots; durable evidence is `results/*.json`, `rows.json`, `diffs/*.patch`, `tasks/`, this report. Not deleted.
- A host reboot wiped /tmp: durable copies of results belong outside /tmp as soon as a run ends (here the repository's experiments archive).
