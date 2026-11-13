# Self-hosting trial 2: source and test change, failed checks, moved main, restart

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 against `main` at `faa9ff023` (PR #735 merged); follow-up to [trial 1](self-hosting-trial.md) section 5.
Linux only (OrbStack), Codex 0.167.0, model `gpt-6.1-sol`, effort `medium`. Vocabulary: [glossary](../glossary.md).
Tracker epic `tl-8bh9.14`. No factory code was changed; the concurrent D1-D4 fixes are not in the build under test.

## 1. Setup

Same as trial 1 section 1, in `~/tl-trial2`: bare `remote.git` as `origin` (every `task/*` ref removed), the person's
checkout `repo`, a second clone `other` (someone else pushing to `origin`), a scratch tracker (`bd init -p t2`), a scratch
`config.toml` (`slot_count = 1`), the repository's own `.task-loop.json` (`just check`, `just test`, target `main`). Run
only as `uv run --frozen --no-sync python -I -m taskloop --config ...` after `just install`. mise trust through the
environment variable `MISE_TRUSTED_CONFIG_PATHS` (no edit of the global mise config). One slot, so a task, a land
validation and a hand `start` all compete for it. Rounds ran with `nohup` (SIGINT ignored, see D3 of trial 1).

## 2. What happened

| Part | Result |
|---|---|
| (a) `src/` change plus pytest test | **Landed.** One command chain, no hand step before land. |
| (b) failed checks | Task held once, claim returned, recovery by description edit plus `auto` worked. Findings F3, F4. |
| (c) moved `main`, conflict, remote rejection | Moved main: revalidated in the slot, landed. Conflict: refused clearly, but the recovery guide does not work (F1). Race and policy rejection: both refused safely and rerun cleanly. |
| (d) SIGTERM and restart | Rounds stopped and restarted: the agent and the attempt carry on. SIGTERM to the entry itself: hold, work lost (F2). |

### (a) A real source and test change

Task `t2-cmc`: make `tl task show` print the task's labels (a trial 1 observation). Plan 1 min, implement 2 min, checks
75 s (`just test` 62 s, 2753 tests), no hand step. The agent changed `cli.py`, `task.py`, `tracker.py`, added two tests to
`tests/cli/test_task_cli.py` (text and `--json`), and fixed the one fixture that constructed the changed dataclass; the diff
was correct and minimal. Land: same tree as X, no second check run, S pushed as the person with the `Task:`, `Plan:`,
`Checked:` trailers, the task closed locally, the person's checkout unchanged (`behind 1`, as designed). `--summary`
printed the message and the diff command and recorded nothing. Note that `tl step land` needs `--checkout`, `--backlog` and
`--minutes` even for `--summary` (trial 1 D1 covered only `--minutes`).

### (b) Failing checks

Task `t2-c5k` told the agent to add a deliberately failing test and not to run it. The agent did exactly that; X failed
`check` (ruff D100 and B011) and `test`. What the person sees:

- `rounds.log`: `check hold held failed:check:failed <attempt>` once, `round moves=1`, then quiet. No repeat, no
  `needs_owner`: a failed check is a hold at once (O2).
- Tracker: `auto` removed, `held` added, claim returned, one comment with both failed checks and their log paths and the
  recovery steps (edit description, `bd label add <id> auto`).
- `tl step list`: `next on_hold`. `tl step show`: `Hold: failed:check:failed ...` and the on_hold guide, but see F4.
- `task/<id>` stays on origin with the failing commit.

Recovery as written worked: description edited, `auto` re-added, the next round logged `hold cleared`, planned again
(about 20 s), implemented on the same branch, checks passed, `Next: land`. The recovery replans each time, even for a
two-line edit.

### (c) Main moves

1. **Moved, no conflict** (`t2-c5k`): `other` pushed a README commit after the checks. `--summary` said `merged onto a
   moved main: checks run again`; the land ran both checks on S in the slot (61 s, silent until the end), pushed, closed.
2. **Conflict** (`t2-g5c`, README line): `refused:conflict`, exit 2, names the path, `Nothing was recorded`. Clear. The
   recovery it prints does not work: F1.
3. **Race during validation**: `other` pushed while S's checks ran: `unavailable:target_moved`, exit 3, `nothing was
   pushed`, `rerun`. The rerun made candidate 2 on the new main, re-ran the checks (54 s) and landed. Clear and safe.
4. **Remote policy rejection** (a `pre-receive` hook on origin): `refused:remote_rejected`, `not a race; nothing was pushed
   and the candidate stays validated`, with the hand `git push` to read the reason. After removing the hook, a rerun
   pushed the same S with no checks (2.8 s). Clear.

### (d) SIGTERM and restart

- **Rounds only** (verified pid from the `rounds started pid=` line): rounds exited with no `rounds stopped` line and no
  terminal text (D3 of trial 1 again). The entry and the Codex process survived, reparented to init, and the entry finished
  and published by itself while no rounds ran. A restarted rounds logged `rounds started`, reported the running attempt,
  and advanced the finished one to `check` in the first round (`t2-li9` landed). This path works.
- **SIGTERM to the verified entry pid** while the agent ran: the agent died with it; the next round held the task,
  `stuck:entry_lost`, claim returned, `Last entry result: failed SystemExit`. The unfinished session was not continued:
  recovery was an edit plus `auto`, then plan and implement from scratch. F2.

## 3. Findings (one bead each, parent `tl-8bh9.14`)

| # | What | Bead |
|---|---|---|
| F1 | The conflict guide (`merge main into task/<id> by hand and push it, then release --abandon and start`) is a dead end: the restart re-plans and the plan publish is refused `remote_moved` ("rerunning does not help"); after moving `task/<id>` aside on origin it republishes the same commits at the old base (the chain's earlier plan and implement attempts are reused), and the next land conflicts again. The local `task/<id>` branch deletion changed nothing. I got out only by changing origin's `main` so X merged. Several 4-minute loops. | tl-8bh9.14.30 |
| F2 | A SIGTERM that reaches the entry holds the task with no cause recorded (`failed SystemExit`), kills the agent, and needs the person; the hold comment reads `task branch task/<id> at not published.` | tl-8bh9.14.31 |
| F3 | `tl step start` by hand on a held task is accepted and plans from the unedited task; the hold is cleared as a side effect with no warning. | tl-8bh9.14.32 |
| F4 | After a failed-checks hold, `tl step show` shows the implement attempt and no failed check or log path; they are in the tracker comment only. | tl-8bh9.14.33 |

Other observations, not filed:

- A land of a source-changing task (62 s of checks) holds the only slot; rounds log `stopped=no_free_slot` meanwhile.
  Land prints nothing until it ends.
- After `release --abandon`, rounds log `implement skip abandoned` and never retake the task: `Next: start` (a hand step) is
  right but nothing in the rounds log says it waits for the person.
- `release --abandon` of a landing task prints two `released:` blocks (the check attempt, then the land candidate).
- Agent timings (plan 1 min, implement 2 min) and `just test` 48-62 s on this machine; trial 1 saw 152 s.

## 4. Not covered

Several slots or tasks in parallel, a rejected verdict and `needs_owner` from a real agent, repeats exhausted, deadline
overrun, macOS, a push race inside the push itself (only the pre-push `target_moved` check and a server hook were
exercised), and rounds killed by the terminal's SIGHUP.

## 5. Verdict

The retained happy path now holds for a task that changes `src/` and adds a test, and failed checks, a moved main, a race
and a remote policy refusal each produce a clear, safe stop with a working or one-command recovery. Two paths are not
trustworthy yet: conflict recovery (F1) and a terminated entry (F2). Do not trust unattended landing on a busy `main`
until F1 is fixed.
