# Self-hosting trial 1: one real task through plan, implement, checks and land

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 against `main` at `41612d71d` (PR #732 merged). Linux only (OrbStack, aarch64), Codex 0.167.0, model
`gpt-6.1-sol`, effort `medium`. Vocabulary: [glossary](../glossary.md). Roadmap: [self-hosting](self-hosting-roadmap.md);
tracker epic `tl-8bh9.14`.

**Result: the task landed.** One task went through every implemented step with no hand step in between, and a
short list of defects (section 4) came out of it. No step failed.

## 1. Setup (what the trial did, and what it needed by hand)

Everything lived under `~/tl-trial`: a bare `remote.git` as `origin` (cloned from this repository's object store, `main`
set to `41612d71d`, every `task/*` ref deleted), the person's checkout `repo` cloned from it (`git remote -v` shows only
the local path), a scratch tracker (`bd init -p trial`), a scratch `config.toml` (own `db`, `artifacts`, `slots_root`,
`slot_count = 1`) and one slot. Nothing touched the real `origin`, the real tracker, `~/.local/state/task-loop` or
any real claim. The code under test ran only as `uv run --frozen --no-sync python -I -m taskloop --config ...` from
`repo` after `just install` (1 s, warm uv cache); `tl` on `PATH` was never used.

By-hand steps (all known from the M1 to M3 runbooks, listed because a self-hosting person repeats them):

1. `mise settings add trusted_config_paths ~/tl-trial` (D14). It edits the person's global `~/.config/mise/config.toml`; I
   restored the file afterwards. Without it every `uv run` in `repo` fails `mise ERROR ... not trusted`, including the
   read-only `tl step show` (seen once after the restore). `MISE_TRUSTED_CONFIG_PATHS=<dir>` works as an env-only
   alternative.
2. `tl slot adopt` first answers `s1 not_listed <path>` with exit 1; the person makes `git worktree add --detach <path>`
   and adopts again (`s1 adopted`). The message says so; the first exit 1 reads as a failure.
3. `codex sandbox -- true` in the slot as a probe (exit 0), `bd init` of the scratch tracker, `bd create` and `bd label
   add <id> auto`. `tl task show` printed the task without its labels, so `auto` is not visible there.
4. The rounds ran in the background (`nohup`) because this session has no terminal tab; see defect D3.

## 2. Timeline (rounds every 15 s, `--minutes 60`)

| Time (UTC) | Event |
|---|---|
| 11:06:54 | `plan start started` (admission: slot, claim, entry) |
| 11:07:52 | `implement advance started` (the plan's entry had already verified and published: no `plan verify` line) |
| 11:11:23 | `check advance started` (implement took about 3 min) |
| 11:14:35 | checks released, `collected passed`: setup 1 passed, `check` 5 s, `test` 152 s (2749 tests) |
| 11:14:39 | `round moves=0`: the last line rounds ever write for this task; nothing says it can be landed |
| 11:15:06 | `tl step land` (me): same tree as X, no checks again, pushed to origin `main` as S `099d7282c` |
| 11:15:10 | task closed in the scratch tracker; rerun answers `already_landed`, nothing called |

Task: correct one sentence of the glossary row for `outcome` (the real count of comments saying "outcome" in
`src/taskloop`). The plan agent wrote `docs/design/trial-rvk/plan.md` (33 lines, verified against source: two comments, in
`attempt.py:272` and `admit.py:203`, correct) and the implement agent changed exactly `docs/glossary.md` and reported
`just check` and `just test` (2749 passed) run in its sandbox. The diff was correct. The landed S has the person as
author and committer, the branch subjects, `Task:`, `Plan:` and `Checked:` trailers, no co-author trailer. The person's
checkout (`HEAD`, `refs/heads/main`, index file digest) was bit-for-bit unchanged by the land, as designed. The slot ended
clean at the target commit, `.t/s1` empty, no leftover process with its cwd in the slot.

## 3. What worked as specified (evidence for the owner)

- The chain plan, implement, check, land with no second claim, no label re-check, no manual `tl step start` (D3).
- The agent ran the project's checks offline in its sandbox (D2) and the factory re-ran them on the host on X.
- `tl step show` and `list` told the truth at each point; `Last command: 11 s ago` worked while the entry ran, `-` after.
- `--summary` changed nothing; the land, its rerun and the person's checkout behaved as the M3 runbook says.
- Codex sandbox probe, the `setup` run (`just bootstrap`) and the per-slot environment worked on this machine.

## 4. Defects and confusing behavior (one bead each, parent `tl-8bh9.14`)

| # | What | Evidence | Bead |
|---|---|---|---|
| D1 | `tl step land --summary` (and a same-tree land) refuse without `--minutes`, though its help says the value is "unused otherwise" | `tl step land: error: the following arguments are required: --minutes`, exit 2, on the first command of the land | tl-8bh9.14.26 |
| D2 | A person who runs `tl step rounds` unattended gets no sign that a task is ready to land (or that plan and implement finished): the entry publishes first, so rounds log only `advance started`, `report running` and `round moves=0`; `Next: land` is visible only by polling `tl step list` | the log above, 11:11:38 then nothing | tl-8bh9.14.27 |
| D3 | A `rounds` started with SIGINT ignored (`nohup`, `&` in a non-interactive shell, an agent's background shell) installs no handler and prints no notice: SIGINT does nothing, `SigCgt` is empty; only SIGTERM stops it, then `rounds.log` ends without a `rounds stopped` line | `kill -INT` ignored for 30 s; `kill -TERM` stopped it, log ends at `round moves=0`; behavior is documented in `interrupts.py` but nothing is printed at start | tl-8bh9.14.28 |
| D4 | Every `tl step` help repeats the same two-line boilerplate ("steps built: plan, implement, check; publishes task/<id>; `tl step land` lands, never a round") and `start`'s help is about thirty lines, so the line that matters is hard to find | `tl step --help`, `tl step start --help` | tl-8bh9.14.29 |

Observed and not filed (already known or by decision):

- `keep_awake`: rounds logged `keep_awake started pid=609144`; the child was already `<defunct>` (`systemd-inhibit`,
  logind refuses on OrbStack, the roadmap's B11 note). The "started" line is false here, and the zombie stays until
  rounds end. [layers.md](layers.md) section 5 item 1 proposes deleting keep-awake; this trial supports it.
- A one-sentence wording fix produced a 33-line `docs/design/<id>/plan.md` that now lives on `main`. By design
  (glossary: plan), but a trivial task pays a plan attempt and a permanent file.
- A land of a docs-only change still ran `just test` (152 s of the 5 minutes). One mandatory check set, no pass cache (D9).
- `tl step list` takes no `--backlog` while `show` and `land` require it (the list is database-wide). Consistent, not a bug.
- My own slip: the task title ("agent folders row") did not match its description. The factory used the title in S's
  message verbatim; it cannot know.

## 5. Not covered by this trial

Failure routes (rejected verdict, `needs_owner`, repeats, failed checks, hold, `held` label), a moved `main` (validation
in a slot), the land's conflict and remote-rejection paths, a restart with an agent running, several slots or tasks in
parallel, an agent changing source or tests (this task was prose only: no new test was written or run by the checks
beyond the existing suite), macOS (implement refuses off Linux), and anything over about 15 minutes. The M2 and M3 live
smokes cover some of these on this same code; this trial covers none of them again. A task that changes `src/` is the
next trial.

## 6. Verdict

The happy path of the implemented chain works end to end on a real agent, a real tracker and a real Git remote, with one
caveat: the person polls. Before trusting it on real tasks overnight, the failure and hold paths (section 5) need their
own trial, and D2 and D3 decide how an unattended person learns the state.
