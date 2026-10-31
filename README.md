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

Then in a repo that uses bd, say "task loop". Requirements: Python 3.15+, uv, git, bd 1.3+,
Claude Code. macOS and Linux (also inside a container); Windows is not supported.

Required: [iorlas-delegate](https://github.com/iorlas/iorlas-delegate) 0.14+ from the same marketplace
(`claude plugin install iorlas-delegate@iorlas-marketplace`). The engine runs every AI step through it
([worker-run v3](docs/contracts/worker-run-v3.md)); it picks lane and model from live plan limits. You never call it
yourself.

## What the loop does

A Claude Code session (attended mode) picks ready beads and runs the **engine** on each, watching its output:

```sh
uv run --script skills/task-loop/tl.py run-task <bead id> --worktree <dir>
```

`run-task ID [--stage STEP] [--fresh] [--force] [--dry-run]` runs the recorded next
stage unless a step is named. `--dry-run` prints the stage, worktree, slot/lease,
branch and any refusal without running a step or writing run files. A hand run
with uncommitted work lists the paths and refuses unless `--force` allows WIP
commits. `--fresh` still discards the checkpoint; it does not imply `--force`.
Land previews require a clean tree and cached gate evidence; they never execute
the repository's plan producer and conservatively require every gate step.

The engine claims the bead and runs reset → plan → per stage (write → checks run by the engine → review by the other
model family) → gate → land → close, each AI step a headless worker (Codex or `claude -p`) with a schema-checked
answer. Code routes and accepts by rule (checks green, nothing blocking in the review); close always runs. Its output is verbose with
⚠ lines for anything the watching session should react to. Settings: `.task-loop.json` → `engine`.

Or let the loop run the queue by itself, one bead after another, each in any free slot:

```sh
uv run --script skills/task-loop/tl.py loop [--max-beads N] [--until HH:MM]   # tl loop status to watch, tl stop [--now] to end
uv run --script skills/task-loop/tl.py factory start [--repo DIR]          # detached loop + dashboard; terminal may close
```

Everything is recorded in the bead (plan, review findings, reflect stats, provenance of who claimed and landed it).
The method is [`skills/task-loop/SKILL.md`](skills/task-loop/SKILL.md); each repo's specifics go in its loop profile
(`docs/agents/task-loop.md`) and `.task-loop.json`.

## Slots

For repos with a heavy setup (an engine import, a large restore), slots are persistent worktrees set up once and
reused task after task; each is a bead labelled `slot`, so holding one is a bd claim with a lease and heartbeat.
Without slots, each loop session makes one worktree at start and reuses it.

```json
{"slots": {"count": 3, "setup": ["just", "agent-setup"], "setup_inputs": ["mise.toml"], "keep": [".task/"]}}
```

## Dashboard

One read-only server per machine, started by the loop (`tl.py dash ensure`), default port 7878.
`tl factory start` starts a detached loop for the current directory's repo and ensures the dashboard; it needs no Claude Code
Desktop session or open terminal. It keeps polling when the queue drains. Repeating it reports `already running`.
Use `tl factory status`, `tl factory stop` (finish the current bead), `tl factory stop --now`, and
`tl factory logs [-n 50] [-f]`; each accepts `--repo DIR`. Start and status print the repo, version, PID, log and dashboard URL.
The loop's PID and console log are in `<config>/loop/<repo-key>/loop.pid` and `factory.log`, alongside its existing run logs.
On macOS, installed `caffeinate` prevents idle sleep while the loop lives. This installs no OS service and does not restart after reboot.

- **Board:** every bead of every registered repo by stage (backlog, working, asking, AI review, your look, landing, done),
  and the goal tree.
- **Floor:** each slot's timeline of stage passes, 2 to 8 hours back, and what is running now.
- **Decisions:** the asks waiting on you, the ledger of every ask and what it became, the decisions in force.
- **Lanes:** each delegate lane's usage and state.
- **A bead:** its passes, stage by stage, the live tail of its running worker, screenshots and files; park, stop, a note.

It works on a phone (below 600 px it switches to a phone layout).

It listens on 127.0.0.1 and on the Tailscale address when Tailscale is up, so a phone on the tailnet can open it.
In a container: `TASK_LOOP_DASH_BIND=0.0.0.0` and publish the port. `TASK_LOOP_DASH_PORT` changes the port.

It reads only local files: the records the engine and `tl.py` write (`~/.config/task-loop`) and bd. Its API is
[docs/contracts/dash-api.md](docs/contracts/dash-api.md).

## Layout

```
skills/task-loop/SKILL.md        the method (read by the orchestrating session)
skills/task-loop/tl.py           the command line only: every verb lives in src/taskloop
skills/task-loop/_vendor/        the shelf packages src/ imports by name (dev/vendor.py; never edited)
src/taskloop/                    the engine, the loop and the verbs, in layers: contracts, domain, adapters, stores, app, cli, hook
src/taskloop/app/launch/         what tl starts: loop.py (tl loop / next / stop), selftest.py (tl selftest: one bead through the
                                 engine with a scripted lane, on this install's code), dash.py (tl dash), dash_ports.py
src/taskloop/app/prune/          tl prune: run data, merged build worktrees and release branches past loop.keep_days (also run at loop start)
src/taskloop/app/report/         tl report, lost and reflect digest: the data (cli/report.py prints it)
src/taskloop_dash/               the dashboard package (imports taskloop.contracts, so msgspec; runs on the interpreter `tl dash ensure` runs on)
src/taskloop_dash/static/        the dashboard page: index.html and its ES modules (Preact + HTM vendored; no build)
src/taskloop_dash/views/         engine logs, asks and bd -> the typed snapshot and bead records (contracts/dash.py)
hooks/hooks.json                 SessionStart: index session id -> transcript path (uv run --script); PreToolUse: python3, no msgspec
tests/                           uv run pytest   (pytest + xdist, the dev group of pyproject.toml; CI: Ubuntu, Python 3.15)
dev/release.py                   the only way to release: release lock, version from origin, suite, marketplace, install
docs/design/                     design notes
docs/contracts/dash-api.md       the dashboard's HTTP API: GET /api/snapshot, /api/bead, /api/live, POST /api/<verb>
docs/dev/integrations.md         for developers: every external format read, and how delegate connects
docs/dev/runaway-process.md      for developers: capture a runaway process (/proc, py-spy, cgroup) before killing it
```

Work on this plugin is tracked with beads (`bd ready`).
