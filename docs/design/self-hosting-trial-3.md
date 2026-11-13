# Self-hosting trial 3: failure routes with a real agent, odd input, a deleted task

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 against `main` at `8fe219905` (PR #736 merged: trial defects .26-.29 fixed). Linux only (OrbStack),
Codex 0.167.0, model `gpt-6.1-sol`, effort `medium`; the machine was loaded by two other trials (load average 30+).
Follow-up to [trial 1](self-hosting-trial.md) and [trial 2](self-hosting-trial-2.md); vocabulary: [glossary](../glossary.md).
Tracker epic `tl-8bh9.14`. No factory code was changed.

## 1. Setup

`~/tl-trial3`: bare `remote.git` as `origin` (every other branch removed), the person's clone `repo`, a scratch config
(`slot_count = 1`), one slot, the repository's own `.task-loop.json`. Run only as `uv run --frozen --no-sync python -I -m
taskloop --config ...`; mise trust through `MISE_TRUSTED_CONFIG_PATHS`. Hazards of the setup itself (not factory defects):

- `bd init -p t3` inside the clone **bootstrapped the real backlog** (1112 issues, some labelled `auto`) and ignored `-p`,
  and the first `tl step next` started an attempt on a real task (`tl-e5t0.10`) with a real agent. Only the scratch
  database was touched; I stopped the owned entry and agent by pid, released with `--abandon`, threw the scratch
  `factory.db` away, and moved the tracker to its own empty directory (`~/tl-trial3/tracker`, `--tracker-root`).
- The bd git hooks made two local commits on `main` (`bd init`, `clear sync.remote`), and the tracked `.beads/config.yaml`
  names the real GitHub remote as `sync.remote`; I removed the dolt remote in the scratch tracker.
- The slot path is `<slots_root>/<repo_id>/sN`; `tl slot adopt` prints the path it wants (`not_listed`), which is how I found it.

A person repeating this trial should create the scratch tracker outside any clone of this repository.

## 2. What was tried and what happened

| Scenario | Result |
|---|---|
| Impossible task (rename `list` to `ls` and keep `list`, no `src/` change, no alias) | Plan step: the agent wrote a 65-line plan saying "cannot be done, owner decides" and answered `planned`, so it was **verified, published and advanced**. Implement step (about 4 min: setup, `just check`, `just test`) answered `needs_owner`; hold recorded, comment good. Edit plus `auto` re-planned and replaced the stale plan (F5). |
| Vague task ("Make it faster"; a unicode title with no content) | Same pattern: `planned`, then `needs_owner` after a full implement attempt (F5). |
| "Do nothing" | Plan answered `unchanged` with no plan file: held `answer:schema_invalid` after 7 s (F4). |
| Hung agent (`sleep 1500` first), `--minutes 3` by hand | `run:timeout` at 3 min, worker gone. By hand, so not held: claim kept, `auto` kept, `Next: done` (F9). Under rounds with `--minutes 2`: held `failed:run:timeout` (F3). |
| Agent killed mid-edit (`kill -KILL` of the verified worker group, 3 of 12 files written) | `run:killed`, held, `hold pending abandon held:slot_dirty`: slot kept, claim kept, comment names the slot. After `git clean` of the slot (the person's step) the next round returned the claim, and because `auto` had been re-added meanwhile, replanned from scratch. Works as designed. |
| Agent asked to crash itself | It refused (`needs_owner`); no crash to observe. |
| Plan with invalid UTF-8 and NUL bytes | `rejected:plan_encoding`, held. The comment quotes the agent's cheerful "Created and verified the exact requested plan" and never says which rule or why (F3). |
| Plan of 7.6 MB (valid text) | Attempt 1 ended `unsafe`, repeated automatically (attempt 2 of 3), the agent noticed the 1 MiB limit and answered `needs_owner`; hold with `slot_dirty`; the comment is attempt 2 only. Repeat path works. |
| Empty plan | `rejected:plan_empty`, held. |
| Task with an unmet dependency (`bd dep add`) and `auto` | Never taken while the blocker was open. Correct. |
| Task closed (`bd close --force`) while implement ran | The agent ran to the end (`needs_owner`); the hold wrote nothing to the tracker (`Hold tracker: nothing written`), `Next: on_hold`. Graceful, a little wasteful. |
| Task **deleted** (`bd delete`) while plan ran | The entry finished and published; then every round fails `unavailable:tracker` with a growing wait (5, 10, 20, 40, 80 s) and **no other task is taken** (F1). `release --abandon` of the task cleared it. |
| Wrong `--checkout` | `unavailable:git`, exit 3, no reason (F7). |
| `--model bogus-model --effort ultra` | Accepted; the agent failed and the result is `run:vendor_blip` (F2). |
| Landing a 12-file task (`tl step land`, `--summary` then real) | Landed, closed; S message good. |
| Titles and descriptions: leading dash, newline, 499 and 5000 characters, empty, blank, escape codes, RTL override, 100 KB description | `bd` refuses empty, blank and over-500 titles and a `--`-led title (flag); the rest reach `tl task show` unsanitized (F8). Land messages are sanitized (`one_line`). A 100 KB description is printed whole. |
| `tl step show/list/verify/release/land` on odd ids (empty, `-x`, `../../etc`, newline, 3000 characters, wrong case) | All `refused:absent`/`not_done`, exit 1 (2 for argparse); the id is echoed back whole, so a newline or 3000 characters reach the terminal. `--json` refusals are valid JSON. |

## 3. Findings (one bead each, parent `tl-8bh9.14`)

| # | Sev | What | Bead |
|---|---|---|---|
| F1 | P2 | A task deleted from the tracker while the factory holds an attempt for it wedges rounds: every round `unavailable:tracker`, backoff, no other task starts; no line names the task. Only `release --abandon` of that task helps and nothing says so. | tl-8bh9.14.54 |
| F2 | P2 | A permanent configuration error (`--model bogus`, unsupported for the account) is classed `run:vendor_blip`, held without the vendor's message; `--model`, `--effort` are not validated before the agent starts. | tl-8bh9.14.55 |
| F3 | P2 | Hold comments carry the rule name and an evidence directory only. `run:timeout` does not say the deadline or that `--minutes` is the lever; `rejected:plan_*` does not say the rule or the limit and quotes the agent's contradictory claim; the stock advice ("edit the description, add `auto`") replans into the same failure for a timeout, `vendor_blip` and `slot_dirty` (a relabel while the slot is dirty does nothing). | tl-8bh9.14.56 |
| F4 | P2 | A well-formed `unchanged` plan answer for a task with no plan file is held as `answer:schema_invalid` though the answer matches `schema.json`; the cause is only in `diagnostics.txt`, and the comment does not say so. | tl-8bh9.14.57 |
| F5 | P3 | An impossible or empty task is accepted by the plan step as `planned` (the plan itself says "blocked on the owner") and pays a full implement attempt (about 4 min, `just check` and `just test` included) before `needs_owner`. | tl-8bh9.14.58 |
| F6 | P3 | `Deadline passed` (text and `--json`) is evaluated when read, not when the attempt ended: a plan that finished in 20 s of a 15 min deadline reads `yes` ten minutes later. | tl-8bh9.14.59 |
| F7 | P3 | A nonexistent `--checkout` gives `unavailable:git`, exit 3, no reason or path; "unavailable" reads as retry-later. | tl-8bh9.14.60 |
| F8 | P3 | `tl task show` prints title and requirements raw (escape codes, RTL override, newline in a title splits the `Title:` line, 100 KB body); `step show` echoes an unknown task id raw. The land message already sanitizes with `one_line`. | tl-8bh9.14.61 |
| F9 | P3 | A hand-started attempt that fails (`needs_owner`, `run:timeout`) is never held: claim kept, `auto` kept, `Next: done`; every later `tl step next` reprints each stale failure and the 250-character "failed:" paragraph again. A closed or landed task keeps `auto` and assignee `taskloop`. | tl-8bh9.14.62 |
| F10 | P4 | Small wording and shape: `Next: hold` text lists all 14 causes (about 1200 characters) whatever the cause; `tl step land` `not_done` prints one sentence twice; usage errors under a subcommand print the top-level usage; a TOML error names no file; `step start nonexist` leaks raw bd text (`TaskInspectionError: ... no issues found matching the provided IDs`); `tl version` prints `0`; `slot adopt --count 99` is accepted against `slot_count = 1`; a restart of an existing attempt silently ignores `--model ""`. | tl-8bh9.14.63 |

Already filed and seen again: tl-8bh9.14.31 (hold comment `task branch task/<id> at not published.`) reads that way
even when the branch **is** on origin (the plan of `t3-tgx` was published at the time of the hold).

Fixed since trial 1 and confirmed: SIGTERM to rounds logs `rounds stopped abrupt` and prints `Stopped at once.`, the
start notice says SIGINT is ignored, `report land` is logged once a task can land, and `land --summary` no longer needs
`--minutes`.

## 4. Not covered

Several slots or tasks in parallel (other trials), a rounds restart mid-hold, merge conflicts (trial 2), macOS, an
`incomplete` disposition, exhausted repeats (reached attempt 2 of 3 only), `ignored` and `uncommitted` repeat reasons, a
dependency closed while the dependent waits, deleting a task in the `check` or `land` step, and a plan that is valid but
wrong.

## 5. Verdict

The failure routes work and fail safe: a hold is recorded once, claims come back, the slot is never cleaned for the
person, killed and timed-out agents leave no process, and repeats and rejections come from real agents. What does not
yet hold up is the **explanation**: most holds tell the person a rule word and a directory, and the stock advice is wrong
for half the causes (F3, F4). One robustness defect needs fixing before unattended use: a single deleted task stops all
work (F1). F2 and F5 cost real time and money on bad input.
