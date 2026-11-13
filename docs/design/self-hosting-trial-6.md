# Self-hosting trial 6: do the trial 1-5 fixes hold on a real run?

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 against `main` at `c9c60e30c` (PR #745 merged, so PRs #732-#745 are all in the build under test). Linux
only (OrbStack, aarch64), Codex 0.167.0, model `gpt-6.1-sol`, effort `ultra` for the unattended rounds. Vocabulary:
[glossary](../glossary.md). Fixes under test: [trial 5 fixes](self-hosting-trial-5-fixes.md) and the findings of
[trial 1](self-hosting-trial.md) to [trial 5](self-hosting-trial-5.md). Tracker epic `tl-8bh9.14`. No factory code was
changed.

**Result: the fixes hold and the happy path did not regress.** Of the ten scenarios, eight behave as the fixes say and
two do not fully: a deleted task still wedges rounds (scenario 8) and a land makes a parallel task's checks hold
(new, found while testing 5). Five new defects, none of them a safety defect, are beads (section 3).

## 1. Setup

`~/tl-trial6`: a bare `remote.git` as `origin` (only `main`, at `c9c60e30c`), the person's checkout `repo`, a second
clone `other` (someone else pushing to `origin`), a scratch tracker in its own directory (`bd init -p t6`, no sync
remote: the trial 5 trap of `bd init` inside a clone is avoided), a scratch `config.toml` (own `db`, `artifacts`,
`slots_root`, `slot_count = 2`), the repository's own `.task-loop.json`. `just install`, then only `uv run --frozen
--no-sync python -I -m taskloop --config ...`; mise trust through `MISE_TRUSTED_CONFIG_PATHS`. Processes were stopped by
the pid the `rounds started pid=` line gave, after reading `/proc/<pid>/cmdline`. Nothing touched the real `origin`,
tracker or `factory.db`. The first `slot adopt` answered `not_listed` for both slots (the known two-step setup; I made a
path mistake once, not the factory's).

For scenarios 10 (and the `head_moved` part of 3) a scripted `codex` wrapper (copied from trial 5, kept in the scratch
directory) was put first on the PATH of one rounds process: it runs a scenario named in the task title and passes every
other prompt through to the real Codex. The real agent did everything else.

## 2. The ten scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | `src/` + test task lands end to end, environment allow-list, `--effort ultra` | **Works.** `t6-1bp` (`tl version --json` gains a `python` key, one test): plan 1 min, implement 1.5 min, checks 2 min (`check` 4 s, `test` 111 s). The agent and the checks ran under mise shims with the allow-listed environment: `codex`, `uv` and `just` resolved through the mise shims on `PATH` and nothing needed a name outside the list. `--effort ultra` accepted by `rounds` and `start`, the agent ran with `model_reasoning_effort="ultra"`. Same-tree land, no second check run; S authored by the person, branch commits by `task-loop <task-loop@localhost>`. |
| 2 | Conflict recovery, including a second conflict | **Works, slow.** `t6-8lv` conflicted twice (`other` pushed a change to the same `.task-loop.json` line). Both times the printed guide (`git switch main && git pull --ff-only`, `git branch -m`, `git push origin --delete`, `release --abandon`, `start`) worked verbatim: the restart replanned on the new main and the task landed on the third chain (trial 2 F1 is fixed). Cost: three full plan/implement/check chains (about 8 min each). The agent noticed the changed base: its first replan answered `needs_owner` because the description said 1800 and `main` said 900 (see D3). |
| 3 | Unattended rounds | **Works.** `nohup` rounds print `Ctrl-C is ignored in this process (started with SIGINT ignored); only SIGTERM stops these rounds, abruptly.`; `report land` is logged (`t6 t6-1bp check report land <attempt>`, then `stopped=slot_for_land`); `kill -TERM` (verified pid) logs `rounds stopped abrupt` and prints `Stopped at once.`; seen three times. Note: identical `report running` lines are not repeated, so a quiet log is not a hang (a 4-minute setup run left the log silent). |
| 4 | Gate-changing land | **Works.** `t6-8lv` (the agent set the `test` timeout and deleted one test): `--summary` shows `Check changed: test: just test (1800 s) -> just test (1200 s)`, `Configuration changed: .task-loop.json`, `Test weakened: tests/cli/test_cli.py: tests 8 -> 7`, the file list with stats, and says how to proceed. A plain `tl step land` answers `refused:gate_changed` (exit 1, nothing recorded, same lines). `--accept-gate-changes` pushes and repeats the accepted lines in the output. |
| 5 | Land waiting is not starved; guide text | **Works.** With `t6-1bp` at `Next: land`, two new `auto` tasks were not started (`stopped=slot_for_land`) while `t6-8lv` took the other slot for its checks; they started right after the land. The guide's claim ("rounds leave the last free slot for it") is true. A land that needs validation ran in the reserved slot (3 min, silent until the end, as in trial 2). New defect found here: D1. |
| 6 | Hand-added `held` pauses an `auto` task | **Works.** `t6-1bt` carrying `auto` and `held`: `t6-1bt skip paused` every round, never started; `tl step next` explains the label and how to remove it. |
| 7 | `factory.db` discard re-takes lapsed claims | **Works for the claim rule, one rough edge (D4).** After moving `factory.db*` aside and `slot adopt`: `next --retake-lapsed` started `t6-7tt` (taskloop's, lease expired 17 minutes ago) and did **not** take `t6-v3d` (taskloop's, fresh lease, its old entry still running) nor `t6-llr` (claimed by `someoneelse`). A task without the `auto` label is not read at all (by design: retake reads the ready set; my first attempt used a hand-started task and saw nothing). |
| 8 | Deleted task does not wedge rounds | **Fails.** See D2. |
| 9 | Hostile task title | **Works.** Title with ESC colour codes, an OSC title sequence, BEL, a right-to-left override, backticks, `$(id)`, `</task>` and markdown: `tl task show`, `tl step list`, the land summary, the squashed commit message (`git log` and `cat -v` on origin) and the hold comments contain no control characters, no injection, the visible text otherwise intact. |
| 10 | `head_moved` never offers the person's `main` | **Works.** A scripted agent committed in the slot, tagged and branched its own commit, and also created a branch and a tag at `origin/main`: `tl step verify` listed only `refs/heads/agent-branch-<id>` and `refs/tags/agenttag-<id>`; the person's `main`, the branch and the tag at `origin/main` were not offered. (My first run listed nothing: the ref names collided with an earlier abandoned attempt's, which the rule excludes correctly. Not a defect.) |

## 3. Defects and confusing behavior (one bead each, parent `tl-8bh9.14`)

| # | Sev | What | Evidence | Bead |
|---|---|---|---|---|
| D1 | P2 | A plain, correct land of task A holds task B when B's checks run at that moment: `failed:main_moved`, `auto` removed, claim returned. The comment names no cause and the recovery (edit the description, re-add `auto`) replans and re-implements from scratch, though only the checks need to run again. Parallel work makes this routine. | `t6-rqv` after `t6-48y` landed: `check hold held failed:main_moved`; re-adding `auto` logged `hold cleared` and a fresh `plan` | tl-8bh9.14.64 |
| D2 | P2 | A task deleted from the tracker while it has an attempt at `Next: advance` makes every round answer `advance unavailable:tracker`; rounds back off 15, 30, 60, 120 s and start nothing else; the glossary says this case is `skip task_missing`. Only `release --abandon <task>` unwedged it (rounds were running again within 15 s), and nothing names that. | `t6-a9u`, `bd delete`d during plan; `tl step next` printed `Stopped: unavailable:tracker`; a new `auto` task did not start | tl-8bh9.14.65 |
| D3 | P3 | A hand-started step that answers `needs_owner` shows no question: `Next: done` with guidance about the check step, no comment, the claim lapses. The explanation is only in `answer.txt`. (A round-taken one quotes it in the hold comment, which works.) | `t6-8lv` plan 1 | tl-8bh9.14.66 |
| D4 | P3 | After a `factory.db` discard with an entry still running, a slot left dirty on `task/<id>` is silently unusable: absent from the `no_free_slot` detail, no `unusable` line in `rounds.log` (0 lines in the whole run), the retaken task logs `start refused:branch_held` with no fix. Capacity is one slot short. | `t6-v3d`, slot `s1`; `tl slot adopt` printed the `git switch --detach` hint once | tl-8bh9.14.67 |
| D5 | P4 | `head_moved`'s ref listing is printed by `tl step verify` only (not by `step show` nor the round line); `unsettled:branch` is not in the verify guide. | `t6-6yq`, `t6-1pn` | tl-8bh9.14.68 |

Observed and not filed:

- `tl step land` is silent for the whole validation (3 min here), as in trial 2. Known.
- Replans after a hold or conflict run the whole chain again (about 8 min with a real agent). By design (the plan is
  part of the chain), but it is the real cost of D1 and of every conflict.
- After a discard the first admissions ran `just bootstrap` again: one setup took about 5 minutes in a slot whose
  `.env/` caches were gone; the log stayed quiet and `tl step show` said `Phase: admitted` meanwhile.
- A hand-started step is never held and never retaken after a discard (no label); the glossary says so.
- Abandoned scripted tasks left local `task/<id>` branches in the person's checkout; `start` for them answers
  `refused:branch_unpublished` (the trial 5 .52 rule: unpublished commits without an attempt trailer look like the
  person's work). Correct, and a person who abandons an agent that committed must delete the branch.
- `release --abandon` of a landed task's earlier attempts prints two `released:` blocks. Known (trial 2).
- The land of a docs task still ran `just test` (about 2 min) when main had moved. One check set, by decision.

## 4. Not covered

macOS; several landing tasks racing the push itself; a rejected verdict and `repeats_exhausted` from a real agent;
deadline overrun with a real agent; a host reboot; the escaping-process, credential-read and shared-git-config items the
trial 5 fixes list as open owner decisions; anything over about 90 minutes; the dashboard.

## 5. Verdict

**Yes, the owner can run the factory on a real task on their own PC while watching it.** The retained chain (plan,
implement, check, land) went through five real tasks to land, two of them with conflicts or a gate change, with no hand repair
that the printed text did not already name, and the trial 1 to 5 fixes I could reproduce are fixed. What the owner must
know first:

1. **Land one task at a time while others check.** Landing moves `main`; a task whose checks are running at that moment
   is held and replans from scratch (D1). With one task, or with all other tasks idle at `Next: land`, nothing is lost.
2. **Do not delete a task in the tracker while the factory has an attempt for it.** Close it, or `tl step release
   --abandon <task>` first; otherwise rounds stall with growing backoff (D2). If rounds go quiet with
   `unavailable:tracker`, that is the first thing to check.
3. **Expect a conflict to cost a whole chain.** Follow the printed guide exactly; it works, including the second time.
4. **Read `tl step land --summary` before the first land of a task that touches `.task-loop.json`, `justfile` or tests.**
   The gate now refuses without `--accept-gate-changes` and says what changed; accept only what is meant.
5. **After deleting or moving `factory.db`, run `tl slot adopt`, then `git switch --detach` in any slot it names, and run
   `tl step next --retake-lapsed` once** (D4); the log will not tell you a slot is unusable.
6. Run rounds under `nohup` or a terminal that keeps SIGINT; stop it with `kill -TERM <pid from the first log line>`. A quiet
   `rounds.log` means nothing changed, not a hang.
7. The agent's `needs_owner` explanation appears in the tracker comment only for round-taken tasks; for a hand-started
   step read `answer.txt` in the attempt directory (D3).
8. Known and accepted from earlier trials: the checks run on the host with the person's rights (decision Q1), the Codex
   sandbox can read `~/.ssh` and `~/.codex`, and `bd init` inside a clone of this repository restores the real tracker.
   Do not run the owner's first real task on a machine whose keys matter without reading
   [trial 5 fixes](self-hosting-trial-5-fixes.md) "Open owner decisions".
