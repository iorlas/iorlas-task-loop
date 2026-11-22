# Pilot 5: feedback A/B on real tasks: STOPPED by the 25-minute cap, no valid terminal result

## Result in one line
The A/B is **not complete**. The first valid pair (task tl-p5c, per-step effort flags) hit the supervisor's 25-minute-per-run cap with both runs still inside check/implement (default: attempt 2 committed, checks running; attempt-budget: attempt 3 = the cap, committed, checks running). Per the stop rule everything was stopped (rounds, entry and check processes by confirmed pid). 0 conclusions about feedback can be drawn. What the pilot does show: failed-check repeats **do** happen on real tasks here (4 of 4 valid-looking runs had one or more), and a real run on this repo needs far more than 25 minutes.

## Setup (frozen, both arms identical)
- Repo base: origin/main `ae7216f8a` ("Ledger: pilot 4 trap task") + 3 local commits (`/tmp/aa/pilot5/base-src`, local bare origins per run, never pushed): `land: manual`; checks wrapped as `env BEADS_DIR=<empty external tracker> just check|test`; `.gitleaks.toml` allowlist of 3 history paths. **Final base commit `55e623ec`** (earlier: `ff53db67`, `08e5a854`).
- Engine: new worktree `ab-engine` at `ae7216f8a` (engine digest of that build; includes max_attempts, export columns, attempt-budget). Workflow digests: default `b10f912b…`, attempt-budget `7e824ba6…`. `max_attempts` = 3 in both. Codex 0.169.0, gpt-6.1-sol, plan effort high, implement effort medium (defaults). `--workflow NAME` per arm.
- Tasks (bead-style, no how-to, same id in both arms): tl-p5a (L25 `tl attempt show` artifacts dir), tl-p5b (L28 `hold_text` in export), tl-p5c (L45 per-step effort flags), tl-p5d (L10 `rework_count` failed-check only). Texts in `/tmp/aa/pilot5/tasks/`. L17 skipped: no `/bin/bash` shebang is left in the repo; L44 skipped (needs the harness's offered levels, not exposed cleanly).
- Runner `/tmp/aa/pilot5/run6.py` (from pilot 4's): 4 block pairs, one default + one attempt-budget per task, both started together (2 in flight), fresh clone/origin/tracker/db/artifacts/slot per run, caps 25 min and 3M input tokens per run, 3 consecutive infrastructure failures, land never run, diffs saved to `diffs/`.

## Per-run rows (uncached = input minus cached; agent wall = sum over steps)
| run | arm | outcome | implement attempts | failed_check repeats | uncached in | cached in | out | agent wall s (plan+impl) | elapsed s | files changed |
|---|---|---|---|---|---|---|---|---|---|---|
| tl-p5c_a | default | cap:wall (attempt 2 committed, checks running) | 2 | 1 | 148278 | 2047872 | 17894 | 461 (239+222) | 1503 | 11 |
| tl-p5c_b | attempt-budget | cap:wall (attempt 3 committed, checks running) | 3 | 2 | 215721 | 2482048 | 21560 | 576 (236+340) | 1503 | 14 |
| tl-p5d_a (INVALID, setup artifact) | default | held (incomplete at attempt 2) | 2 | 1 | 111537 | 1063040 | 10146 | 269 (123+146) | 605 | 5 |
| tl-p5d_b (INVALID, setup artifact) | attempt-budget | held (incomplete at attempt 2) | 2 | 1 | 140818 | 1051264 | 9672 | 279 (117+162) | 668 | 5 |

Not valid and not counted: the 4 setup-failed starts (`aborted_setup/`, 0 tokens: `bd init` clashed with the global `BEADS_DIR`), tl-p5d pair 1 (`pair1_invalid/`, see diagnosis), and the started-then-aborted tl-p5a pair (plan step only, `pair1_invalid/runs`). Run totals so far: 2 valid-but-capped runs + 2 invalid pair-1 runs + 2 partial pair-2 starts ≈ 6 of the 8-run budget used in spirit; 2 runs left would not make a 4-task design.
Both capped runs are non-terminal: `outcome` is a cap, not a result.

## Diagnosis of the invalid pair 1 (setup artifact)
1. `secrets` failed in check 1: the slot's task branch has no upstream, so blueprint's `secret_scan range` scans all history and hits 4 old false positives (paths absent from the checkout). Fixed with a `.gitleaks.toml` allowlist (verified: 4.6 s, clean).
2. Attempt 2 ended `incomplete` because the agent ran its own `just check`/`just test` in the Codex sandbox: no bd database (BEADS_DIR only in profile argv) and `~/.cache/gate-leases` read-only; it reported "full validation unverified". Mitigated by one identical note in every task text ("the factory runs just check/test; they cannot run in your sandbox"). In the restarted pair tl-p5c this did not recur: checks ran and produced `lint` failures.
3. Genuine failures (ruff format, pyrefly) were also in that feedback: those are implementer slips, which is what the A/B needs.

## What the restarted pair (tl-p5c) shows
- Check 1 failed on `lint` (and `test` once) in both arms: natural failed checks (stored `check-1-check.log`: `gate: failed: lint` / `lint test`), not the secret scan.
- Feedback text: in the attempt-budget arm, the stored input of attempts 2 and 3 starts with `Implement attempt N. The failed-check repeat cap is 3, including the initial attempt.`; the default arm's input has no such sentence (checked in the input files). Both then carry the same "Failed check" section with the check output.
- Behaviour after the repeat: attempt 2 / 3 took 51-70 s of agent time each against 170-225 s for attempt 1 and re-ran 5-6 minute checks. The capped runs never reached a verdict on attempt 2 (default) or 3 (attempt-budget), so "did the sentence change the next-check pass rate" is **unknown** (one capped run each).
- Directness: tl-p5c_a changed 11 files, tl-p5c_b 14 files including `.importlinter` and a new module `src/taskloop/cli_step_flags.py` plus `cli_step.py` -81/+16 (a refactor the task did not ask for). Evidence in `diffs/`, unreviewed by a human.

## Why the cap tripped, and what a real A/B costs
- One check cycle is 5-6 minutes with two runs in flight (`just check` 80-360 s, `just test` 120-360 s, 8086 tests); a run with 3 attempts needs plan 4 min + 3 x (agent 1-4 min + check 5-6 min) = 25-35 min. The 25-minute cap is below the minimum for a run that uses its cap of 3 attempts, so it measures nothing but the checks' speed.
- Tokens per run are large: 1.1-2.7M input (mostly cached), 10-22k output; tl-p5c_b reached 2.70M input in total, close to the 3M cap. 8 runs would be about 10-20M input tokens, 80-170k output, and 2-3 hours wall at 4 pairs one after another.
- Recommendation (supervisor decides): per-run wall cap of 45 minutes and token cap of 4M, fewer slow checks (set `-p no:cov` is already used; a faster sample of tests is not neutral), and 1 in flight or 2 with checks given the whole host. With those, the remaining valid budget for tasks is 3 tasks (6 runs) already spent partially; plan for 8 new runs.

## Decisions made
- Treated pair 1 as invalid (setup artifacts) after the supervisor's message and restarted from a fresh pair; reported its rows separately.
- Applied the supervisor's stop rule literally when the first run exceeded 25 minutes, even though the runs were progressing normally; did not extend the cap. Stopped the owned processes by confirmed pid (rounds, attempt_entry, check_entry, gate children, identified by `pilot5/runs` paths in their command lines).
- Neutral environment fixes only, identical for both arms and recorded as commits in `base-src` (never in the real repo): land manual, `BEADS_DIR` for checks via `env`, gitleaks allowlist, one sandbox note in the task text. Mise trust through `MISE_TRUSTED_CONFIG_PATHS`.
- Task texts name requirements and acceptance criteria only, and use the existing names (`hold_text` is the only new name, stated in the task).

## Improvements noticed
### A/B method
- Per-run wall cap must be derived from the check time, not guessed: measure one check cycle first (here 5-6 min under 2-way contention) and size cap = plan + attempts x (agent + check).
- A run whose checks are still running at the cap is not a result; the runner should stop at a step boundary (after the check verdict), not at a wall time.
- Run pairs with 1 in flight if the checks use all cores (8086 tests with xdist); concurrency inflates the check time and the wall of both arms equally, but it hides speed differences.
### Tooling
- A fresh slot cannot run this repo's own gate unattended: needs mise trust, a bd database (`bd bootstrap` downloads 168k chunks; fresh clone has none), and a branch upstream for the secret scan (`secret_scan range` scans all history without one: the factory's task branch has none). A factory run on this repo needs these three fixed in the repo or the profile.
- The agent tries to run `just check`/`just test` in the Codex sandbox, where they cannot run (no bd database, read-only gate cache), then reports `incomplete`. The default prompt should tell the agent that the factory runs the checks, or the sandbox should allow them (L14).
- `tl attempt export` gives hold_cause as a code only (L28) and no per-check failure names: the failed check names were read from `check-N-<name>.log` and `gate: failed:` lines; export should carry `latest_checks_failed_names`.
- No command to stop a run's whole process tree (rounds, entry, check, gate, pytest): five levels of processes had to be stopped one by one (L26).
### Storage
- Run trees are large here (a full clone, a venv and a slot per run: tens of MB to hundreds of MB each, plus `.venv`); results JSON and diffs are the durable evidence. Nothing deleted; clean `/tmp/aa/pilot5/runs`, `pair1_invalid/runs` when the report is read.

## What this A/B can and cannot conclude
- Can: failed-check repeats occur on real small tasks of this repo at default efforts (tl-p5c: 2 of 2 runs failed `lint` at attempt 1; tl-p5d: 2 of 2), so the feedback variable is exercised, unlike on every earlier task. The only reliably observed cause is lint/format, which the agent cannot run in its sandbox.
- Can: the attempt-budget sentence is present in the stored feedback of the b arm and absent in the default arm.
- Cannot: whether the sentence changes the next-check pass rate, repeat count, tokens or time: no run reached a terminal verdict after a repeat on the valid setup (n = 0), and with 1 run per cell per task there is no variance estimate; A/A noise from pilot 2 (wall sd 9-14%, input sd 4-13%) is far below the between-run differences seen here (461 vs 576 s agent wall, 11 vs 14 files), so any single comparison is dominated by what the agent chose to do, not by the workflow.
