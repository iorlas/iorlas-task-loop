---
name: task-loop
description: Run the autonomous task loop on a repo that tracks work in bd (beads), with several sessions in parallel worktrees or slots, taking ready beads one after another (claim, plan, delegate the code, verify, merge into main, close) until none is left, with a live dashboard of every task, session and worker. Use when the owner says "task loop", "ticket loop", "take tickets autonomously" or "do the next things on your own".
---

# task-loop

Several sessions run this at once on one repo and one shared bd database, each in its own worktree. Each session
orchestrates; workers write and verify. The project's rules come from its **loop profile**; this file is the method,
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
5. Workers: see **Workers** below (delegate when installed, else Agent-tool subagents).

## 1. Pick (before every task)

1. `tl bd reclaim --older-than 15m` (returns dead sessions' beads, slots included, to ready).
2. Candidates: the profile's pick filter over `bd ready --json`, never a bead labelled `slot`, never `in_progress`,
   never an epic.
3. Order: beads whose `## Touches` overlap no `in_progress` bead's Touches first, by priority; overlapping ones after
   them, by priority. Overlap lowers the order, never skips a bead: the sync (step 3) resolves shared files.
4. In that order: `tl claim <id> --worktree "$WT" [--slot <name>]`. `TAKEN` → next. Nothing left after a fresh
   reclaim → step 5.
5. Branch: a bead with `metadata.branch` (a reclaimed one) continues that branch, never restarts it; with
   `metadata.slot` set it continues in that slot (its commits may exist only there).
   - Slots on: `tl slot reset <name> --bead <id>`: commits any leftover work where it was (never wipes it), checks
     out `task/<id>` from origin/main, `git clean -fd` (ignored setup output stays), reruns setup if its inputs
     changed. `READY` → go; `DIRTY` → the leftover work could not be committed: block the slot's last bead with the
     output, release the slot, take another.
   - Slots off: `git -C "$WT" fetch origin && git -C "$WT" checkout -B task/<id> origin/main`.
6. Keep the claims alive: a background Bash job `tl heartbeat <id> [<slot bead>] --loop`. It beats every 60 s and
   exits when a heartbeat fails or the session's process is gone, so a dead session's leases lapse. Restart it after
   the next claim.

## 2. Work (per task)

Say where the task is with `tl stage <id> "<what>"` at every step change (analyse, plan, stage 2 write, verify, gate,
land): the dashboard shows it next to the bead.

1. **Analyse:** the bead, its acceptance criteria, linked decisions, the code it names, the AGENTS.md triggers that
   apply. Bulk reading goes to a reader worker; keep only the conclusion.
2. **Decide and plan** (never delegated): the approach as `tl bd comments add <id> "Plan: ..."`, split into stages,
   each one coherent piece its checks can judge, each marked writer or hard part. The plan names the **risks ahead of
   time**: what in this task could break something users keep or other code relies on (a saved format, a public
   member, a content number, a migration, shared files), each with the check that will prove it safe. A stage that
   touches a named risk is reviewed (3.4) whatever the verifier says.
3. **Stages,** one at a time:
   1. **Write:** the bead is the brief. Export it, `bd show <id> > "$WT/.task/<id>/brief.md"` (with the comments:
      plan, risks, review findings; `.task/` is git-ignored and per bead, because a sandboxed worker may not open the
      bd database). The prompt points at that file and adds only the stage: its goal, files, the checks it must run
      before reporting (the profile's workers), and "no commits, no pushing, no suppressions, do not weaken tests".
      Codex in a reused slot: a task's first stage starts a fresh thread, later stages of the same task resume it.
      Its report counts as nothing.
   2. **Record the worker** unless the dashboard finds it by itself (Agent-tool subagents, Codex plugin jobs, and
      runs whose launcher publishes agent-runs records): `tl worker <id> --kind codex|claude-p|other --ref <thread or
      session id> --title "<stage>"`.
   3. **Verify:** a fresh verifier gets the goal, the checks and `git diff`, never the writer's
      report. It reruns every check, then the profile's verify list, and returns only: `git diff --stat`; per check
      the exit code and last 3 lines (never "passed"); stats (lines added and removed, files, **tests added and
      removed**, counted from the diff and the test runs' totals); files outside the bead's `## Touches`; risk flags
      (a public member changed; a test deleted, weakened or filtered; a suppression added; a named risk touched; the
      profile's extra flags); ACCEPT or GAPS with the list.
   4. **Review** (on a risk flag, a named risk, a hard stage, a third round, a merge-conflict resolution, or a gate red
      twice): a fresh reviewer from another model family than the writer (a Codex writer gets a Claude reviewer, and
      the other way round) reads the diff against the bead and its named risks and returns findings, each with
      file:line, severity and the fix. Every finding goes into the bead: `tl bd comments add <id> "Review: ..."`.
   5. **Judge:** read the verifier's report and the review's findings, not the diff. Read the diff yourself only for a
      finding you must decide on.
   6. **Gaps** → back to the same writer thread: re-export the brief (it now holds the review comments) and say which
      findings to fix. Hard part → a hard worker.
   7. **Sync** (3.1) between stages, never while a worker is writing.
4. **Every problem noticed** gets a bead now: `tl bd create ... --deps discovered-from:<id>`, with acceptance criteria
   and touched paths; small and mechanical → the profile's "ready for agents" label, else unlabelled for the owner.
5. **Gate:** the profile's gate, green. A known flaky check: retry once; red again → fix it or file it, never bypass.
6. **Complete?** Walk the acceptance criteria line by line with evidence (test, log, screenshot). A line unmet → back
   to 3. Small related work in the same files: do it now rather than file it.
7. **Reflect:** `tl bd comments add <id> "Reflect: left=<what or none>; filed=<ids or none>; stats=<lines +/->,
   <tests added>, <stages>, <review rounds>"`. Not optional; the stats feed the owner's view of what delegation
   produced.
8. Commit: `<what changed> (<id>)`.

## 3. Sync and land (in your own worktree, no lock)

Each session merges main into its own work often, so landing is a fast-forward push of a tree that is already merged
and gated. Sessions never wait for each other: a push that loses the race syncs and retries.

1. **Sync:** `git -C "$WT" fetch origin && git -C "$WT" rebase origin/main`: after every stage, before the gate,
   before every push.
2. **Conflict:** keep both intents, main's and the task's; never `-X ours` or `-X theirs`, never drop main's change to
   make yours fit; rerun the checks that cover the conflicted files. Truly contradictory → `git rebase --abort`,
   `tl block <id> --why "merge conflict: <files>; <why>"`, keep the branch, pick next.
3. **Land:** the profile's land command. The gate must run on the merged tree (the pre-push hook, or run it first);
   never `--no-verify`, never a merge path that skips the gate (a PR merged on the forge's web page does).
   Rejected because main moved → sync and push again; after 5 rejections in a row, take the next task and land this
   one after it. Red because main itself is red → fix main first and file a bead. Landed → `tl land <id> --sha <sha> --worktree "$WT"`.
4. Every third landing by your session: the profile's full gate on a detached `origin/main` (two tasks green alone,
   red together); red → fix or file.

## 4. Close

`tl close <id> --reason "merged <sha>"`; stop the heartbeat job; `tl bd dolt pull && tl bd dolt push`; the profile's
close step; `git -C "$WT" checkout --detach` and `git -C "$WT" branch -d task/<id>`. Back to step 1 (the slot or
worktree stays yours).

A question only the owner can answer: `tl block <id> --why "<the question, with options and your pick>"`, stop the
heartbeat, pick next.

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

How to get them:
- **delegate installed** (suggested): ask it for each worker and run what it answers; its role names are its own
  business (today reader → `light`, writer → `worker`, verifier and reviewer → `reviewer` with the writer's family,
  hard → `hard`). If its interface changes, follow its skill; nothing in this loop depends on its internals.
- **Without it:** Agent-tool subagents in this session (never `isolation: worktree`); for the other-family reviewer,
  the Codex plugin when installed, else a different Claude model than the writer's.

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
