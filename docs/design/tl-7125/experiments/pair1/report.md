# A/A pair 1 (frozen engine, Codex gpt-6.1-sol both arms)

Engine: aa-engine worktree at origin/main ecb6092be (incl. #855), engine_digest fcbebd9c...1d16 (identical in both arms).
Workflow default, digest b10f912b...2919 (both). Base commit d3163794 (both). Task: "Add slugify" (aa-gnt in arm a, aa-4c8 in arm b).
Method: `rounds start --no-dashboard --max-running 1 --minutes 40`, one process per arm, land: manual, not landed. Arm b started first (random), arm a 20 s later.
Agents: codex 0.169.0, model gpt-6.1-sol, plan effort high, implement effort medium (machine defaults; reported = asked, ran_model_differs 0).

| | arm a plan | arm b plan | arm a implement | arm b implement |
|---|---|---|---|---|
| wall_seconds | 67.2 | 84.2 | 36.7 | 39.0 |
| turns | 5 | 6 | 6 | 7 |
| tokens in (cached) | 93,155 (86,656) | 115,040 (96,128) | 111,890 (92,416) | 131,080 (91,776) |
| tokens out | 2,535 | 3,311 | 1,015 | 1,106 |
| verdict | committed | committed | committed | committed |
| rework_count | 0 | 0 | 0 | 0 |
| setup_seconds | - | - | 0.03 | 0.03 |
| check_seconds (test) | - | - | 0.06 | 0.08 |
| latest checks | - | - | passed | passed |
| time_to_green_seconds | - | - | 38.9 | 41.0 |

Totals (plan+implement): arm a 205,045 in / 3,550 out, 103.9 s agent wall; arm b 246,120 in / 4,417 out, 123.2 s. Difference ~20% in input tokens, ~19% in wall: one pair says nothing about variance.

## Looked wrong or unverified
- Task ids differ per arm (tracker-generated), so plan input_digest differs by construction (0803d8da... vs b5d868d4...). For a clean A/A the arms should share the task id (bd create --id).
- time_to_green_seconds on the implement row counts from the implement attempt only (chain_id = its own id; plan is not linked by previous_attempt_id), so plan time is not in it. Total task time needs plan + implement.
- Task trivially small: 2 agent steps, no repeat, no check failure; cannot exercise feedback, max_attempts or attempt_budget. Pick a task that sometimes fails checks for the A/B.
- Concurrent arms on one host and one subscription: cross-arm load not controlled.
- Rounds stopped by pid (SIGTERM) after both were waiting_for_land; nothing landed; arms kept in /tmp/aa/pair1.
- rounds cost/token figures: c_* are cumulative tokens, no dollars.
- Not checked: whether the two arms' final code is equivalent (diff not compared).
