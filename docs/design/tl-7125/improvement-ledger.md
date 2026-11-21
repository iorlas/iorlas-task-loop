# Experiment improvement ledger (A/A, A/B, tooling, storage)

Status: living log, started 2026-11-21. One row per observation that could make the experiments, the tooling or the
stored evidence better. Append; never delete a row: change its status and say why. Evidence points at a run, a PR or a
file. Owner of each fact stays where the glossary puts it; this file only records what we learned and what we might do.

Areas: **A/A** (same workflow in both arms, measures noise), **A/B** (two workflows, measures a difference), **tool**
(commands, scripts, gates, supervision), **store** (what `factory.db` and exports keep). Status: `open`, `decided`
(owner picked it, not built), `done` (with PR), `dropped` (with reason).

| id | date | area | observation | evidence | idea | status |
|---|---|---|---|---|---|---|
| L1 | 2026-11-21 | A/A | Task ids differ per arm (tracker-made), so the plan input digest differs by construction | pair 1 report: 0803d8da vs b5d868d4 | create the experiment task with a fixed id in both arms | decided (pilot 1 does it) |
| L2 | 2026-11-21 | store | `time_to_green_seconds` counts from the implement attempt only: plan is not linked to implement by `previous_attempt_id` | pair 1 report; export columns of #855 | a task-level total (plan + implement) in the export, or link the chain across steps | open |
| L3 | 2026-11-21 | A/A | The first task was trivial: two agent steps, no failed check, no repeat; it cannot exercise feedback, `max_attempts` or `attempt_budget` | pair 1 report | a frozen task that sometimes fails its checks; keep a small library of frozen tasks with known pass rates | decided (pilot 1) |
| L4 | 2026-11-21 | A/A | One pair differed by ~20% in input tokens and wall time: single pairs say nothing about variance | pair 1 report | sample size from the pilot's stdev before any A/B (rule of thumb: runs per arm ~ (2 * stdev / smallest effect worth acting on)^2 * 4) | open |
| L5 | 2026-11-21 | A/A | Both arms ran concurrently on one host and one subscription; cross-arm load is uncontrolled | pair 1 report | cap runs in flight (pilot: 2) and record the order; note host load in the report | decided (pilot 1) |
| L6 | 2026-11-21 | A/B | Final code of two arms was never compared; passing checks is the only quality signal | pair 1 report | a blind review of the diffs per run (directness), or at least a diff-size column in the export | open |
| L7 | 2026-11-21 | store | Cost is tokens only; no dollars and no rate table. Codex and Claude price cached input differently | export docs (#855) | a versioned external rate table, dollars labelled "estimated", failed-arm spend counted | open |
| L8 | 2026-11-21 | store | `factory.db` is disposable and a schema bump discards it: the old arm databases (v34) could not be read by the v36/v37 build, so arm 1's evidence is history only | A/A restart | `tl attempt export` to a dated file before every drain-and-upgrade; keep exports with the experiment report | open |
| L9 | 2026-11-21 | store | The final launched-input digest is not stored; only the admitted one is | export worker report (#855) | store it on the execution row at launch if a later input change matters | open |
| L10 | 2026-11-21 | store | `rework_count` counts every repeat except answer repairs, not only failed-check repeats, because the export slice may not import the check-repeat reason | #855 | expose the reason through the slice's public door, or a neutral vocabulary module, then count failed-check repeats only | open |
| L11 | 2026-11-21 | store | The agent's reported model and CLI version are stored per execution (schema v36, #850); the duplicate `execution.harness` was dropped (#852) | #850, #852 | none; watch whether a harness that reports nothing (opencode) shows up as NULL | done |
| L12 | 2026-11-21 | A/B | The agent is not told its attempt number or cap; the `attempt_budget` section now exists as a variant file | #854 | A/B `default.toml` against `attempt-budget.toml`, same model, effort and cap; measure next-check pass rate after feedback, repeats, tokens, time | decided (after pilot 1) |
| L13 | 2026-11-21 | tool | Setting up one experiment arm by hand took a whole session (origin named `aa.git`, slot paths <= 64 bytes, separate tracker, DB, artifacts, slots per arm) | A/A restart | one command or script that builds an arm from a frozen task and base commit and prints the arm's digests | open |
| L14 | 2026-11-21 | tool | Codex workers run in a sandbox with no network and no project tooling: they cannot run `just` or pytest, so three defects per task (format, import contract, missing caller) reached me | #854, #855 | a gate step run by the supervisor right after a worker returns (script exists in the session; make it a recipe), or a worker lane with the cached environment | open |
| L15 | 2026-11-21 | tool | After `git rebase`, the installed package is stale and the pre-push gate fails on imports; `just install` must run after every rebase and after every source edit | #855 push | document it in AGENTS.md or make the push recipe install first | open |
| L16 | 2026-11-21 | tool | The pre-push hook takes more than two minutes and a branch with no upstream makes the secrets gate scan all history | fix-display session | set the upstream to `origin/main` when creating a branch; run pushes in the background | decided (practice) |
| L17 | 2026-11-21 | tool | NixOS has no `/bin/bash`: scripts with that shebang fail; use `#!/usr/bin/env bash` or run through `bash` | gate script, this session | use `env bash` in repo scripts | open |
| L18 | 2026-11-21 | tool | Subsessions were refused `gh pr create` / `gh pr merge` by the permission classifier even with the owner's standing authority, and one session could not start sessions from an automated turn | fix-schema session | give a worker only the edit step; the supervisor commits, pushes, opens and merges | decided (practice) |
| L19 | 2026-11-21 | A/A | The default workflow's digest and the engine digest are identical across arms only because both arms use one engine worktree; a different machine would differ | pair 1 report | record both digests in every report; refuse to compare runs with different engine digests | decided |
| L20 | 2026-11-21 | A/B | Directness (does the agent do only what the task asks) has no metric yet | Codex brainstorm | a blind per-run rating, or changed-files-outside-the-plan count | open |

Update rule: after each experiment run, add the rows it taught us, mark rows it answered, and link the report.
