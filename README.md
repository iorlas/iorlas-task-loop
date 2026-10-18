# iorlas-task-loop

A Claude Code plugin that runs an autonomous task loop over a [bd (beads)](https://github.com/gastownhall/beads)
backlog: several sessions at once, each in its own worktree or slot, claim a ready bead, plan, hand the code to
workers, verify, land on main and close it, then take the next. A live dashboard shows every task, the session
working on it, its workers and their logs.

## Install (any machine)

```sh
claude plugin marketplace add iorlas/iorlas-marketplace
claude plugin install iorlas-task-loop@iorlas-marketplace
```

Then in a repo that uses bd, say "task loop". Requirements: Python 3.8+ (standard library only), git, bd 1.3+,
Claude Code. macOS and Linux (also inside a container); Windows is expected to work and is untested.

Suggested, not required: [iorlas-delegate](https://github.com/iorlas/iorlas-delegate) picks the worker lane and model
for each step from live plan limits. task-loop never reads delegate's files: any launcher, delegate included, puts its
runs and lane limits on the dashboard by writing [agent-runs v1](docs/contracts/agent-runs-v1.md) records.

## What the loop does

A Claude Code session (attended mode) picks ready beads and runs the **engine** on each, watching its output:

```sh
python3 skills/task-loop/tl.py run-task <bead id> --worktree <dir>
```

The engine claims the bead and runs reset → plan → per stage (write → checks run by the engine → verify → review
when risky → judge) → gate → land → close, each AI step a headless worker (Codex or `claude -p`) with a
schema-checked answer. Code routes; the judge reads ambiguous results; close always runs. Its output is verbose with
⚠ lines for anything the watching session should react to. Settings: `.task-loop.json` → `engine`. Design:
[docs/design/coordinator-less.md](docs/design/coordinator-less.md).

Everything is recorded in the bead (plan, review findings, reflect stats, provenance of who claimed and landed it).
The method is [`skills/task-loop/SKILL.md`](skills/task-loop/SKILL.md); each repo's specifics go in its loop profile
(`docs/agents/task-loop.md`) and `.task-loop.json`.

## Slots

For repos with a heavy setup (an engine import, a large restore), slots are persistent worktrees set up once and
reused task after task; each is a bead labelled `slot`, so holding one is a bd claim with a lease and heartbeat.
Without slots, each loop session makes one worktree at start and reuses it.

```json
{"slots": {"count": 3, "setup": "just agent-setup", "setup_inputs": ["mise.toml"], "keep": [".task/"]}}
```

## Dashboard

One read-only server per machine, started by the loop (`tl.py dash ensure`), default port 7878.

- **Tasks:** what is live now, then each repo's bead tree (epics and children; live, open, blocked, done in 7 days).
- **A task:** its sessions over time and every worker under them: the orchestrating Claude session, its Agent-tool
  subagents, Codex runs (codex plugin jobs and `codex exec`), and runs any launcher publishes as agent-runs v1.
- **Live log** of any of them, following new output.
- **Workers:** every worker run on the machine in the last 24 hours.

It listens on 127.0.0.1 and on the Tailscale address when Tailscale is up, so a phone on the tailnet can open it.
In a container: `TASK_LOOP_DASH_BIND=0.0.0.0` and publish the port. `TASK_LOOP_DASH_PORT` changes the port.

It reads only local files: the records `tl.py` writes (`~/.config/task-loop`), `bd list`, and the transcripts Claude
Code (`~/.claude/projects`) and Codex (`~/.codex/sessions`, the codex plugin's job state) already write.

## Layout

```
skills/task-loop/SKILL.md        the method (read by the orchestrating session)
skills/task-loop/tl.py           helper: actor, claim/stage/worker/land/close/block, slots, worktrees, dashboard
skills/task-loop/dash/server.py  dashboard server (stdlib)
skills/task-loop/dash/index.html dashboard page (no build, no dependencies)
hooks/hooks.json                 SessionStart: index session id -> transcript path
tests/                           python3 -m unittest discover -s tests   (CI: 3 OS x Python 3.8 and 3.12)
docs/design/                     design notes
docs/contracts/agent-runs-v1.md  the format other tools use to show their workers on the dashboard
docs/dev/integrations.md         for developers: every external format read, and how delegate connects
```

Work on this plugin is tracked with beads (`bd ready`).
