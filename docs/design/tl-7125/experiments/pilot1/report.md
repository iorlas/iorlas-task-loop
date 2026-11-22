# A/A pilot 1: default workflow vs default workflow, Codex gpt-6.1-sol, harder task

Engine: aa-engine (origin/main ecb6092be, engine_digest fcbebd9c...), workflow default digest b10f912b..., base commit f72b91af (second calibration base), task aa-hard1 (same id in every run), codex 0.169.0, model gpt-6.1-sol, plan effort high, implement effort medium. 20 runs, 10 per arm, fresh clone/origin/tracker/factory.db/artifacts/slot per run, <=2 runs in flight, randomized order (order.txt), land never run. All 20 finished in 23 minutes, 0 infrastructure failures.

## Decisions made
- Both arms Codex vs Codex (supervisor decision); no Claude runs.
- Task: parse_duration(text) with the edge cases (case, whitespace, decimals, any order, duplicate units, bare numbers) NOT in the task text; judged by a second required check `accept` that lives outside the repo (/tmp/aa/pilot1/hidden/accept.py) so the agent cannot read it as part of the repo. First calibration (tests inside repo) passed first time with no repeat (too easy: agent read the tests). Second calibration held `needs_owner`. Calibration cap (2) reached, pilot started with that task. Verified by hand: hidden tests fail with no implementation and pass with a reference implementation.
- Stop timing at accepted factory checks (waiting_for_land); total task time = plan wall + implement time to green.
- Rounds per run: `rounds start --no-dashboard --max-running 1 --round-seconds 15 --minutes 40`, stopped by pid with SIGTERM when the run reached a terminal state (waiting_for_land or hold). Per-run config files for slots root/count.
- max_attempts left at default.

## Result in one line
18 of 20 runs HELD (`needs_owner`): the plan chose behavior that the hidden acceptance check contradicts (agent: acceptance requires uppercase units and whitespace and rejects repeated units, opposite to the plan). Only 2 of 20 passed (a07, b07), both after an `answer:schema_invalid` first implement answer and a repair attempt; b07 also had one failed check and a failed_check repeat. Pass rate 1/10 vs 1/10: equal, but the pilot mostly measured how often the plan contradicts hidden requirements, and it exercised failed-check repeats once in 20 runs. It does not support any A/B conclusion on feedback.

## Per-run rows (in start order)
| run | outcome | impl attempts | repeats (failed_check) | tokens in | tokens out | agent wall s | time to green s | plan+implement s |
|---|---|---|---|---|---|---|---|---|
| b05 | held | 1 | 0 | 211067 | 4667 | 126.8 | - | - |
| a09 | held | 1 | 0 | 189464 | 4209 | 111.7 | - | - |
| a01 | held | 1 | 0 | 211335 | 4679 | 121.8 | - | - |
| b01 | held | 1 | 0 | 230156 | 4585 | 118.9 | - | - |
| a10 | held | 1 | 0 | 211950 | 5204 | 134.5 | - | - |
| b08 | held | 1 | 0 | 213688 | 5305 | 135.6 | - | - |
| a04 | held | 1 | 0 | 208252 | 4108 | 109.1 | - | - |
| b03 | held | 1 | 0 | 210096 | 4505 | 118.9 | - | - |
| a08 | held | 1 | 0 | 188601 | 4082 | 110.6 | - | - |
| a06 | held | 1 | 0 | 189856 | 4345 | 114.4 | - | - |
| a05 | held | 1 | 0 | 190052 | 4509 | 118.0 | - | - |
| a02 | held | 1 | 0 | 211135 | 4607 | 122.4 | - | - |
| b07 | pass | 3 | 1 | 440298 | 7698 | 158.1 | 105.9 | 167.3 |
| a03 | held | 1 | 0 | 231920 | 5763 | 145.4 | - | - |
| b04 | held | 1 | 0 | 170110 | 4398 | 110.1 | - | - |
| b09 | held | 1 | 0 | 210472 | 4447 | 115.4 | - | - |
| b06 | held | 1 | 0 | 251862 | 4639 | 125.4 | - | - |
| b02 | held | 1 | 0 | 210887 | 4468 | 117.3 | - | - |
| b10 | held | 1 | 0 | 252371 | 4960 | 128.7 | - | - |
| a07 | pass | 2 | 0 | 414146 | 8036 | 170.3 | 99.1 | 181.0 |

## Per-arm statistics (mean / median / min / max / stdev)

### arm a: pass rate 1/10, held 9
- tokens in (all executions): 224671 / 209694 / 188601 / 414146 / 64573 (n=10)
- tokens out: 4954 / 4558 / 4082 / 8036 / 1141 (n=10)
- agent wall s (all executions): 125.8 / 119.9 / 109.1 / 170.3 / 18.3 (n=10)
- time to green s (passes only): 99.1 / 99.1 / 99.1 / 99.1 / 0.0 (n=1)
- plan+implement s (passes only): 181.0 / 181.0 / 181.0 / 181.0 / 0.0 (n=1)
- failed_check repeats: 0 / 0 / 0 / 0 / 0 (n=10)
- implement attempts: 1 / 1 / 1 / 2 / 0 (n=10)

### arm b: pass rate 1/10, held 9
- tokens in (all executions): 240101 / 212378 / 170110 / 440298 / 70383 (n=10)
- tokens out: 4967 / 4612 / 4398 / 7698 / 947 (n=10)
- agent wall s (all executions): 125.5 / 122.2 / 110.1 / 158.1 / 12.9 (n=10)
- time to green s (passes only): 105.9 / 105.9 / 105.9 / 105.9 / 0.0 (n=1)
- plan+implement s (passes only): 167.3 / 167.3 / 167.3 / 167.3 / 0.0 (n=1)
- failed_check repeats: 0 / 0 / 0 / 1 / 0 (n=10)
- implement attempts: 1 / 1 / 1 / 3 / 1 (n=10)

Held runs are tight: tokens in 170k-252k, agent wall 109-146 s in both arms; the two arms are indistinguishable at n=10 (mean tokens in 224,671 vs 240,101, driven by one pass each at 414k and 440k).

## What looked wrong or unverified
- Held dominates (90%): a plan/acceptance conflict, not a check failure. The check-failure path (feedback, repeats) ran once (b07). A usable A/B task needs the plan and acceptance to agree on ambiguous points, or hidden checks that only catch implementation slips.
- The agent ran the hidden `accept` check itself: the profile's checks are visible in `.task-loop.json` in the repo. Hiding the file contents is not hiding the check.
- Both passes needed an `answer:schema_invalid` repair: the implement answer was malformed in 2 of the ~4 attempts that got that far. rework_count (answer repairs excluded) says 0 for a07 although it took 2 implement executions; wall and tokens include the repair executions.
- `tl attempt show` prints the DEFAULT artifacts directory, not the per-run one (the run's artifacts were under its own state/artifacts), because `show` was not given --artifacts; the printed path is wrong for non-default roots.
- Final code equivalence between arms not compared (only check pass).
- Cross-run load: 2 runs shared the host and one Codex subscription; wall times carry that noise.
- Same-second host clock and 15 s round cadence quantize timings to ~15 s.
- Holds were left pending (tracker comment not written) because rounds were stopped right at the hold; the hold cause is from the factory.db export.

## Improvements noticed
### A/A method
- Require plan/acceptance agreement: have the planner see the acceptance checks, or make hidden checks implementation-only.
- Fix the base commit hash in the report header (second calibration base f72b91af; pair1 used d3163794).
- A pilot task should target ~50% first-attempt pass and a few failed-check repeats; calibrate with 3-4 runs, not 1, before 20.
- Create the task with a fixed id (done: aa-hard1) so plan input digests match across arms.
### Tooling
- `tl attempt show` should resolve artifacts from the same source as the running rounds (show the real directory).
- The export should link plan and implement into one chain or expose a task-total time to green; today plan time has to be added by hand.
- Export lacks a column for hold cause text and for the answer-repair link (answer:schema_invalid) vs failed_check repeat; `rework_count` hides repairs.
- A runner that starts `rounds start`, waits for a terminal state and stops it should be a command (`tl rounds once` loop or `until-done`), not a script; stop-by-pid and polling are workarounds for the missing `rounds stop`.
### Storage
- Per-run trees are ~3 MB each (66 MB for 20 runs); no cleanup tool for throwaway factory.db/artifacts trees (kept under /tmp/aa/pilot1/runs).
- Results JSON per run under /tmp/aa/pilot1/results is the durable evidence; exports are 2-4 rows each.
