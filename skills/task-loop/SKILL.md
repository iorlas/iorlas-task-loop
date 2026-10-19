---
name: task-loop
description: Run the autonomous task loop on a repo that tracks work in bd (beads), with several sessions in parallel worktrees or slots, taking ready beads one after another (claim, plan, delegate the code, verify, merge into main, close) until none is left, with a live dashboard of every task, session and worker. Use when the owner says "task loop", "ticket loop", "take tickets autonomously" or "do the next things on your own".
---

# task-loop

Several sessions run this at once on one repo and one shared bd database, each in its own worktree. The engine
(`tl run-task`) does each task with headless workers; the session picks, starts and watches it (attended mode). The project's rules come from its **loop profile**; this file is the method,
the profile is the project.

The owner pre-approves everything here: claiming, committing, merging into main, filing beads. No plan mode, no
approval questions. Ask only for a decision the owner owns (product direction, scope, an architecture choice that is
hard to reverse, deleting large parts): block the bead with the question and take the next. Tokens are not a
constraint; time is: run independent work in parallel, and when a check is slow, file a bead to make it faster.

Read this skill and the profile in full at the start and again after every context compaction.

`tl` below means `python3 ${CLAUDE_SKILL_DIR}/tl.py` (`python` or `py -3` on Windows). It names the session for bd,
records what the loop does for the dashboard, and runs slots. Python 3.8+, standard library only.

## The loop profile

`docs/agents/task-loop.md` in the repo (or the file the repo's AGENTS.md names), plus `.task-loop.json` at the repo
root for what `tl` reads itself (slots). The profile gives:

| key | what |
|---|---|
| setup | the command a fresh worktree runs once |
| pick | the `bd ready` filter: labels, lanes, what to exclude |
| gate | the command that must be green, and whether the pre-push hook runs it |
| land | the branch to land on and any rule about how (default: `git push origin HEAD:main`) |
| workers | how workers run here (what a sandbox can and cannot run, build flags) and the checks each stage names |
| verify | what the verifier runs beyond the stage's own checks, and the project's extra risk flags |
| close | per-ticket cleanup (editors to close, caches) |
| known | flaky checks (retry once) and other standing facts |

`.task-loop.json` (optional):

```json
{"slots": {"count": 3, "dir": ".slots", "base": "origin/main",
           "setup": "just agent-setup", "setup_inputs": ["mise.toml", "client/Packages/manifest.json"],
           "keep": [".task/"]}}
```

No `slots` (or `count` 0): slots are off. No profile: say so in one line, use
`bd ready --exclude-type epic --exclude-label slot`, the gate the repo's AGENTS.md names, and land on main by push.

## Identity

Sessions share one database, and bd lets the same actor claim a bead twice silently, so every bd call names the
session: `tl bd <command>` (actor `tl-<first 8 of $CLAUDE_CODE_SESSION_ID>`; `tl actor` prints it). The lifecycle
calls below (`tl claim`, `tl close`, ...) do this themselves and also record the event for the dashboard and in the
bead's provenance.

## 0. Start (once)

1. `tl dash ensure`: starts the dashboard if it is not running (one per machine) and prints its addresses. Tell the
   owner the address in one line.
2. `git worktree prune`; `tl bd dolt pull`.
3. Where to work:
   - **Slots on:** `tl slot init` once per machine (creates the slot beads `slot <host> s1..sN` and their worktrees);
     then `tl slot take` → prints `NAME DIR SLOT-BEAD`, or `NONE` (all held: stop with that one line). Keep the
     slot bead for the heartbeat. The slot's setup runs in step 1.5, only when its inputs changed.
   - **Slots off:** `tl worktree sunset` (removes clean loop worktrees of sessions that hold no lease), then
     `tl worktree start` → prints this session's worktree, made once and reused for every task.
4. Your work directory (`WT` below) is that slot or worktree. A session cannot move its own folder: work there with
   absolute paths and `git -C "$WT"`; the shell's cwd resets between calls.
5. Workers come from the iorlas-delegate plugin (required, see **Workers**). Feed it your Claude usage now:
   `get_usage`, then `$TL usage '<plan.windows as JSON>'`.

## 1. Pick (before every task)

1. `tl bd reclaim --older-than 15m` (returns dead sessions' beads, slots included, to ready).
2. Candidates: the profile's pick filter over `bd ready --json`, never a bead labelled `slot`, never `in_progress`,
   never an epic.
3. Order: beads whose `## Touches` overlap no `in_progress` bead's Touches first, by priority; overlapping ones after
   them, by priority. Overlap lowers the order, never skips a bead: the engine's rebase before landing resolves shared files.
4. Take the first one to the engine (step 2): it claims the bead as this session (`TAKEN`, exit 1 → the next
   candidate), continues `metadata.branch` when the bead was worked before, and keeps the claim alive while it runs.
   Nothing left after a fresh reclaim → step 5.
5. Slots on: before the engine, `tl slot reset <name> --bead <id>` (commits leftover work, never wipes it; reruns the
   setup only when its inputs changed). `DIRTY` → block the slot's last bead with the output, release the slot, take
   another. A bead with `metadata.slot` set continues in that slot.

## 2. Run the engine (per task)

The engine does the task; you watch it. `tl run-task <id> --worktree "$WT" [--slot <name>]` in a background Bash job
(several at once is fine, one per slot or worktree). It claims the bead, then: reset → plan → per stage (write →
checks run by the engine → verify → review when risky → judge) → gate → land → close. Every AI step is a headless
worker with a schema-checked answer; the close step always runs; the plan, findings and a Reflect line go into the
bead. Engine settings: `.task-loop.json` → `engine` (gate, land, budgets). Every run appends one line to
`<config dir>/task-loop/traces.jsonl` (never pruned): bead, repo, branch, outcome, your session id, and every worker
session (Codex thread, `claude -p` session) with its transcript. `tl trace <id>` lists them; reflection and improvement
are done by hand from these traces for now.

Its output is verbose by default (`--quiet` for less): each step, the facts behind it (checks with exit codes, gaps,
flags, findings, the judge's reason, cost) and **⚠ lines** for what you must look at. Read the output as it comes
(the job's output file, or the dashboard's Engine run). Never do a step's work yourself; change what makes the
engine misbehave.

| ⚠ line | what to do |
|---|---|
| judge says block / an owner question | owner decision: leave it blocked, report it at the end |
| judge says replan, write round 2+, rounds exhausted | read the gaps and checks: a vague bead → sharpen its description and acceptance criteria, reopen; a wrong check in the plan → note it in the bead |
| a check fails the same way every round | the environment or the profile (setup, a missing tool, a flaky test): fix it or file it, then reopen |
| needed a retry / no valid output / engine error | an engine problem: file a bead in iorlas-task-loop with the engine log path, then reopen and rerun |
| files outside the task, tests removed, high finding, verifier changed files | read the diff; if wrong, reopen with a note saying what must not change |
| budget 50% / 80% | fine once; on every task → the beads are too big (split them) or the budget too small |
| push rejected | normal under parallel landings; five in a row → main is too busy, run fewer at once |

Reopen = `tl bd update <id> --status open --append-notes "<answer or correction>"`, then run the engine again: it
continues the task branch (its earlier work is kept) and the next plan reads the note.

## 3. After each run

- Landed: next bead (step 1).
- Blocked with an owner question: leave it; it goes in the final report.
- Blocked or failed for any other reason: act on the ⚠ table, then rerun or move on.
- Every problem you notice gets a bead (`tl bd create ... --deps discovered-from:<id>`); problems with the engine
  itself go to iorlas-task-loop.

## 4. By hand (only when the engine cannot run here)

When the engine cannot run here (delegate missing or not set up, no Codex or `claude` CLI login), do the same steps
yourself in the same order, with the same records: `tl claim`, `tl stage`, plan in the bead, write through workers, run the checks
yourself, a fresh verifier, a reviewer from another model family on risky stages, `tl land`, `tl close` or `tl block`.

## 5. Stop

No candidate left: `tl bd dolt push`, the profile's close step; slots on: `tl slot release <name>`; slots off:
`tl worktree sunset --self-too` (removes your worktree if it is clean). One report to the owner: beads closed, beads
filed, beads blocked with their question, the dashboard address. Nothing else.

## Slots

A slot is a persistent worktree, set up once and reused task after task, so a heavy setup (an engine import, a large
restore) is paid once per slot, not once per task. Each slot is a bead labelled `slot` and titled
`slot <host> <name>`: holding a slot is claiming its bead, so the lease, heartbeat and reclaim come from bd. Leases are
local to one machine, hence the host in the title.

- A held slot belongs to one session; a dead session's slot returns through `reclaim` once its lease lapses
  (about 20 minutes with `--older-than 15m`).
- `tl slot reset` never discards work: leftover changes are committed on the branch they were on (or on
  `wip/<slot>/<time>` if detached) before the next task's branch is checked out.
- Setup runs again only when a file in `setup_inputs` changed; when it is heavy and several slots could rerun it at
  once, the profile's setup command must queue itself (a lock or a slot limit of its own).
- `tl slot list` shows each slot, its bead, holder and folder.

Slots off: one worktree per loop session (`.worktrees/loop-<session>`), made at start and reused for every task;
never one worktree per task. `tl worktree sunset` removes loop worktrees whose session holds no lease, never a dirty
one, and never a worktree the loop did not make.

## Dashboard

`tl register [DIR]` adds a repo's main checkout to the dashboard before claiming a bead; DIR defaults to the current directory.

`tl dash ensure` starts one server per machine (`tl dash url` prints its addresses, `tl dash stop` stops it; it
restarts by itself when the plugin's code changes and exits after hours without a loop). It listens on 127.0.0.1 and,
when Tailscale is up, on the machine's Tailscale address; `TASK_LOOP_DASH_BIND=0.0.0.0` (e.g. in a container with a
published port) overrides; `TASK_LOOP_DASH_PORT` changes the port (default 7878).

It shows every repo the loop touched: the bead tree (epics and children; live, open, blocked, done), each task's
sessions and workers (the orchestrating session, its Agent-tool subagents, Codex runs, recorded `claude -p` runs) and
the live log of any of them. A Workers tab lists every worker run on the machine for the last 24 hours. It reads the
records `tl` writes, `bd list`, and the transcripts Claude Code and Codex already write; it changes nothing.
Finished tasks stay visible for 7 days.

## Workers

The loop needs five kinds of worker; it does not care what runs them.

| kind | does | never |
|---|---|---|
| reader | reads many files or logs, returns a conclusion | edits |
| writer | one stage's code, runs the stage's checks | commits, pushes, branches |
| verifier | reruns the checks on the diff, returns facts | sees the writer's report |
| reviewer | reads the diff against the bead and its risks; another model family than the writer | fixes |
| hard | a subtask two writers failed | |

How to get them: from the **iorlas-delegate** plugin, which every task-loop install has. You don't talk to it; the
engine does, one `route.py run ROLE` per AI step (contract: `docs/contracts/worker-run-v1.md` in this plugin's repo).
Delegate picks lane, model and effort from its role table and live plan limits, and never spends API credit for the
engine. Its role names (reader and verifier → `light`, writer → `worker`, reviewer → `reviewer` with the writer's
family, hard → `hard`) matter only in §4 by hand, where you ask delegate's skill for each worker yourself.

The one thing the engine cannot do itself: read your Claude usage. Delegate spends the Claude subscription headless only
with a reading under 30 minutes old, so before starting an engine and every 20 minutes while one runs: call
`get_usage`, then `$TL usage '<plan.windows as JSON>'`. Without it Claude steps count as out: the engine waits for a lane
(⚠ "waits for a lane"), then blocks the task.

Any launcher can put its runs on the dashboard by writing agent-runs v1 records
(`docs/contracts/agent-runs-v1.md` in this plugin's repo); otherwise record them with `tl worker`.

## Beads are the record

Everything about a task lives in its bead, so any session or worker can pick it up: the plan, the named risks, every
review's findings, the reflect line with its stats, the provenance of who claimed, handed off and landed it. Chat and
worker reports are not the record.

## Context

The session runs task after task; its context window is the scarce resource. Keep in it decisions, plans and
verdicts; everything bulky goes through a worker that returns the conclusion. The task's thinking stays in the session;
move it to a per-task hard worker only if compactions start losing tasks.
