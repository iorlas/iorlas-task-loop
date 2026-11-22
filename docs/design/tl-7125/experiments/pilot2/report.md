# A/A pilot 2 (task v4, Codex gpt-6.1-sol vs Codex gpt-6.1-sol, default workflow): 5+5 runs

Engine aa-engine (origin/main ecb6092be, engine_digest fcbebd9c...), workflow default digest b10f912b..., base commit 97c7b318c6dd7810d284d16c2e6ffc24696bf2b1, task aa-hard1 (task v4: sharpened ASCII/Unicode rules, hidden check outside the repo), codex 0.169.0, gpt-6.1-sol, plan effort high, implement effort medium. 10 runs (5 per arm), 3 pairs + 4 solo in random group order (pilot/order.txt), fresh clone/origin/tracker/factory.db/artifacts/slot per run, land never run, no repo commits, nothing deleted. Host: 14 CPUs, 24 GB.

## Result in one line
All 10 runs passed on the first implement attempt (0 failed_check repeats, 0 answer repairs, 0 plan holds, 0 infrastructure failures). A/A on this task measures noise only: nothing exercised feedback or repeats.

## Per-run table (in start order)
| pos | run | arm | in-flight | outcome | tokens in | tokens out | cached ratio | agent wall s (plan+implement) | elapsed s | load1 start/end |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | a04 | a | 1 | pass | 215373 | 5128 | 0.874 | 132 | 151 | 0.34/0.24 |
| 2 | a02 | a | 1 | pass | 216879 | 5780 | 0.737 | 144 | 161 | 0.24/0.95 |
| 3 | a01 | a | 1 | pass | 217582 | 5752 | 0.819 | 147 | 160 | 0.95/0.31 |
| 4 | a05 | a | 2 | pass | 238161 | 5116 | 0.884 | 133 | 150 | 0.31/0.75 |
| 5 | b01 | b | 2 | pass | 263283 | 8086 | 0.941 | 194 | 203 | 0.31/0.57 |
| 6 | a03 | a | 1 | pass | 217668 | 6796 | 0.876 | 168 | 181 | 0.57/0.41 |
| 7 | b03 | b | 2 | pass | 242043 | 6810 | 0.936 | 172 | 182 | 0.41/1.10 |
| 8 | b04 | b | 2 | pass | 263665 | 5852 | 0.812 | 151 | 161 | 0.41/1.54 |
| 9 | b05 | b | 2 | pass | 194973 | 5236 | 0.863 | 134 | 152 | 1.10/2.38 |
| 10 | b02 | b | 2 | pass | 195350 | 5639 | 0.862 | 143 | 152 | 1.10/2.38 |

## Per-arm and per-concurrency statistics (mean / median / min / max / stdev)
| group | n | tokens in | tokens out | cached ratio | agent wall s |
|---|---|---|---|---|---|
| arm a | 5 | 221133 / 217582 / 215373 / 238161 / 8554 | 5714 / 5752 / 5116 / 6796 / 613 | 0.838 / 0.874 / 0.737 / 0.884 / 0.056 | 144.7 / 143.6 / 132.0 / 168.4 / 13.2 |
| arm b | 5 | 231863 / 242043 / 194973 / 263665 / 30972 | 6325 / 5852 / 5236 / 8086 / 1021 | 0.883 / 0.863 / 0.812 / 0.941 / 0.049 | 158.8 / 151.1 / 133.7 / 194.1 / 21.6 |
| solo | 4 | 216876 / 217230 / 215373 / 217668 / 920 | 5864 / 5766 / 5128 / 6796 / 598 | 0.826 / 0.847 / 0.737 / 0.876 / 0.057 | 147.7 / 145.1 / 132.0 / 168.4 / 13.2 |
| paired | 6 | 232912 / 240102 / 194973 / 263665 / 28371 | 6123 / 5746 / 5116 / 8086 / 1036 | 0.883 / 0.873 / 0.812 / 0.941 / 0.045 | 154.5 / 147.2 / 132.9 / 194.1 / 22.0 |

Arm a is 4 solo + 1 paired and arm b is 5 paired: the random assignment confounded arm with concurrency in this sample (see side effects #1). Arm b: +14 s wall (+10%), +10.7k input tokens (+5%) over arm a; solo vs paired: +6.8 s (+4.6%) wall. With sd 13-22 s at n=5 none of these differences is distinguishable from noise.

## Decisions made
- Supervisor: 5 per arm, no extra calibration, no reruns, holds count as results (none occurred), stop after 3 consecutive infrastructure failures (none).
- Concurrency is a controlled variable: groups run one after another; a pair group runs two runs at once, a solo group one. 3 pairs + 4 solos, random group order and random run-to-group assignment (pilot/order.txt). In-flight count is the planned group size; host load average and MemAvailable sampled at each run's start and end (results/*.json).
- Same engine, workflow digest, task id, base commit; per-run config files for slot root; rounds stopped by pid with SIGTERM at the terminal state (waiting_for_land).
- Total plan+implement time reported as agent wall (sum of execution wall seconds of both steps) and as elapsed (start to terminal state, includes setup, checks and the 10 s polling).

## Uncontrolled side effects, ranked by how much they could bias an A/B (evidence, mitigation)
1. **Arm/concurrency confounding by chance (HIGH for a small n).** Evidence: arm a 4 solo + 1 paired, arm b 5 paired; arm b +10% wall. Mitigation: block-randomize (balance each arm across solo/paired) or run arms in strictly alternating pairs so every pair is one a + one b.
2. **Prompt-cache warmth (HIGH).** Evidence: cached-input ratio 0.74-0.94 (mean 0.84 arm a, 0.88 arm b); corr(position, ratio) +0.25 and corr(ratio, tokens in) +0.28 at n=10; identical prompt prefix across runs within minutes. Cached tokens are billed and timed differently. Mitigation: compare uncached input (in minus cached) and cached separately; alternate arms so warmth is symmetric; discard a warm-up run.
3. **Run order and time of day (MEDIUM, not measurable here).** Evidence: all runs within 19 min (23:19-23:39); corr(position, wall) +0.13. Provider load varies by hour; one 20-minute window cannot show it. Mitigation: interleave arms across at least two time windows.
4. **Concurrency on one host and one subscription (MEDIUM).** Evidence: paired wall mean 154.5 s vs solo 147.7 s (+4.6%, within noise); host load1 at run end up to 2.38 vs 14 CPUs, MemAvailable ~11.3 GB constant; no rate-limit/retry/overload text in the harness events or stderr of any of the 10 runs. Mitigation: keep pairs balanced across arms (#1); sample load at run start/end (done).
5. **Plan variance and plan holds (MEDIUM).** Evidence: committed plan 3388-3789 bytes (mean 3597, sd ~150, range 11%); plan hold rate 0/10 here but 2/8 in the calibrations of the same task family and 18/20 with a conflicting hidden check in pilot 1 (the planner's depth gate `Depth: large` is a coin flip at >3 behaviours). Same prompt, same model: plan text differs run to run. Mitigation: count plan holds as outcome, report plan length; for implement-only A/B freeze the plan (`--from implement` from one committed plan).
6. **Agent can see the check, not the answer (LOW for this task).** Evidence: all 10 agents ran `python3 /tmp/aa/pilot2/hidden/accept.py` (path is in the profile `.task-loop.json`); 0 of 10 event streams mention `accept_cases` (the file with the cases) and 0 reference other runs' trees, pilot 1, calibration trees, `~/.codex/sessions` or `~/.codex/memories`; no global `~/.codex/AGENTS.md`, `~/.codex/skills` empty. Caveat: only the harness event stream was grepped, not Codex's own session history in ~/.codex, and `~/.codex/memories_1.sqlite` exists. Mitigation: run experiments with CODEX_HOME pointed at an empty directory; keep hidden checks out of the profile argv.
7. **Shared state between runs (LOW).** Evidence: same task id aa-hard1 but one tracker per run (separate .beads databases); no dashboard (no ports); locks are per factory.db; nothing was written to the default `~/.local/state/task-loop` (no files newer than the pilot start). Not measured: uv/git/pip caches under ~/.cache, `bd`/dolt state, Codex installation id and logs (shared). Mitigation: per-experiment HOME/XDG_CACHE_HOME if cache sharing matters.
8. **Clock and cadence quantization (LOW).** Evidence: rounds every 15 s and my polling every 10 s: elapsed exceeds agent wall by 9-22 s (mean 12 s) and hides sub-15 s differences; agent wall comes from the harness. Mitigation: compare agent wall and tokens, not elapsed; lower round_seconds for experiments.
9. **Disk/IO (NEGLIGIBLE).** Evidence: /tmp is tmpfs (19 GB, 53% used); each run tree ~3 MB.

## Improvements noticed
### A/A method
- The task still cannot produce a failed-check repeat (0 in 18 runs across calibration and pilot for task v3/v4, 1 repeat in pilot 1); a feedback A/B needs a task where implementers fail (see the calibration findings below) or a weaker model/effort for the A/A.
- Use block randomization (one a + one b per pair, order randomized within the pair) so arm is never confounded with concurrency or position.
- Report uncached input tokens next to total input; cached ratio ranges 0.74-0.94 and is arm-correlated by chance at n=5.
- Add plan text length and plan hold to the standard A/A row.
### Tooling
- The export has the fields needed (repeat_reason, answer_kind, terminal_result, hold cause, harness_version, ran_model); add a task-level total (plan+implement) so it need not be summed by hand, and the plan-size `Depth: large` hold as its own cause.
- The harness event stream is the only place to grep reads outside the checkout; a normalized read/write path list per attempt would make the leak check one query.
- A command to run a task to a terminal state and stop rounds (replaces the start/poll/SIGTERM script).
### Storage
- 10 run trees ~30 MB under /tmp/aa/pilot2/pilot/runs plus calibration trees (27 MB); results JSON and rows.json are the durable evidence; nothing deleted per the supervisor.


---
# Earlier stage of pilot 2 (calibration), kept verbatim below

# A/A pilot 2: calibration did not land; pilot NOT run

Engine: aa-engine (origin/main ecb6092be, engine_digest fcbebd9c...), default workflow digest b10f912b..., base commit for pilot 2 = see base-commit.txt (profile with a required second check `accept` outside the repo), task id aa-hard1 in every run, codex 0.169.0, model gpt-6.1-sol, plan effort high, implement effort medium. Both arms identical (A/A). Fresh clone/origin/tracker/factory.db/artifacts/slot per run, <=2 in flight, land never run, no repo commits.

## Decisions made
- Supervisor brief: acceptance only if first-attempt pass rate is 25-75% AND at least one run exercises a failed_check repeat; max 2 calibrations x 4 runs; otherwise stop and report. Followed exactly.
- Task v3 (calibration 1): parse_duration with EVERY judged behavior in the task text (5 numbered rules incl. exact arithmetic, case, whitespace, repeated units, 365d cap, int/float result). Hidden check stays outside the repo (/tmp/aa/pilot2/hidden/accept.py). Verified by hand: a reference implementation passes it; an empty one fails.
- Task v4 (calibration 2): rules 1-3 sharpened in the TEXT (ASCII digits only, unit letters exactly ASCII d/h/m/s either case, whitespace only space/tab/newline) and 12 more invalid inputs (Arabic-Indic and fullwidth digits, long s, Kelvin sign, no-break space, CR, VT, Arabic decimal, em space). Verified by hand: a careful ASCII reference passes; a naive implementation (re.I, \d, str.strip) fails 8 cases.
- Stopped after calibration 2 (cap reached) and did not run the 20-run pilot.

## Calibration results (8 runs, Codex vs Codex, same default workflow)
| set | run | outcome | implement attempts | failed_check repeats | tokens in | agent wall s |
|---|---|---|---|---|---|---|
| cal1 | a01 | pass | 1 | 0 | 193,438 | 129 |
| cal1 | a02 | pass | 1 | 0 | 260,663 | 154 |
| cal1 | b01 | HELD at plan (needs_owner) | 0 | 0 | 17,804 | 18 |
| cal1 | b02 | pass | 1 | 0 | 214,824 | 135 |
| cal2 | a01 | pass | 1 | 0 | 213,548 | 116 |
| cal2 | a02 | HELD at plan (needs_owner) | 0 | 0 | 17,863 | 25 |
| cal2 | b01 | pass | 1 | 0 | 260,571 | 153 |
| cal2 | b02 | pass | 1 | 0 | 260,885 | 153 |

First-attempt pass rate (of the 6 runs that reached implement): 6/6. Of all 8 runs: 6 pass, 2 hold, 0 failed_check repeats, 0 answer repairs. The criterion "at least one failed_check repeat" was met 0 times in 8 runs, so the task is rejected.

## Why it did not land
- Plan-size gate: the planner holds a task as `Depth: large` ("more than three independently testable behaviours: ...") and asks for a split. 2 of 8 holds, both at plan, ~18-25 s and ~18k tokens each. This is a factory behavior, not noise: a task with >3 listed behaviours is at risk of holding before any implementation.
- Implementation is too easy for the model once the spec states every rule: even the Unicode traps (ASCII-only digits, no case folding) were handled in all 6 implement runs. The hidden check never failed.
- The two forces conflict: more rules in the text -> plan-size hold; fewer rules -> trivial pass. The window between "planner accepts" and "agent still slips" did not appear in 8 samples.
- Pilot 1 (previous task) held 18/20 on plan/acceptance conflict. Pilot 2 tasks hold 2/8 on plan size and pass 6/8: the opposite failure mode. Neither task produced a measurable A/B signal on feedback.

## Not run, so no A/A noise numbers
No 20-run pilot was run (budget rule: stop if calibration fails after 2 rounds). Token cost of this stage: 8 calibration runs, ~1.9M tokens in total across both arms, ~15 min wall.

## Improvements noticed
### A/A method
- A feedback A/B needs failures that come from the implementer, not the plan. Pick a task whose acceptance needs a fact the agent cannot derive from the text (e.g. a repo convention in a file the agent must find, a flaky-looking interaction between two modules, or a check on behavior of existing code), and keep the described behaviours <=3 to stay under the plan-size gate. Alternatively inject failure: a check that is deliberately strict about style/lint output the task text names.
- Alternatively, lower the model/effort for the A/A (a weaker model fails checks more) instead of making the task harder; failed-check feedback is the variable under test, so a high first-attempt failure rate is a feature of the experiment design.
- Calibrate against the planner's size gate first (does the plan hold?) before tuning implementation difficulty.
- Record per-run plan+implement total for every run that reached checks (done in the rows above) and separate answer repairs from failed_check repeats (the export has repeat_reason and answer_kind; both were 0 here).
### Tooling
- `tl attempt show --artifacts <run artifacts dir>` is needed for non-default roots (it prints the default directory otherwise); I used the runs' own artifact dirs for evidence.
- A command that runs a task to its terminal state and then stops rounds would replace the start/poll/SIGTERM script (and the missing `rounds stop`).
- The plan-size gate (`Depth: large` hold) should be visible in the export as its own hold cause rather than generic `failed:needs_owner`.
### Storage
- Calibration trees: /tmp/aa/pilot2/cal1/runs, /tmp/aa/pilot2/cal2/runs (~3 MB each); results JSON per run under */results; delete after the report is read.
