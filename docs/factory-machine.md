# Factory machine requirements

Status: **built** for the facts below, checked on two machines on 2026-11-16 and 2026-11-17 (an x86_64 Ubuntu container on
the sol VM and an aarch64 NixOS OrbStack machine). It describes what a machine needs to run the factory, so the factory can
run on any machine that meets it. The task tracker owns task status; this document owns machine facts.

## Requirements

| Need | Rule | Enforced by |
|---|---|---|
| Python | 3.15 or newer, from `uv` | `requires-python = ">=3.15"` in `pyproject.toml` (`uv sync` refuses an older interpreter) and `.python-version` |
| Tool pins | exact versions in `mise.toml` and `mise.lock`; in the machine's global mise list only what the tracker or the factory depends on (beads 1.3.1, uv 0.13.0, dolt 2.4.2) | `just` reads the pins; install with `mise install` |
| Agent CLIs | not pinned: Codex and Claude Code stay current by updating themselves. Codex is installed with pnpm (`pnpm add -g @openai/codex`, `global-bin-dir` set to `~/.local/bin`) so that `codex update` works; the npm install under mise cannot update itself (it runs `pnpm add -g`). Claude Code uses the native installer and `claude update` | the tool; no mise entry for either |
| Trust | `MISE_TRUSTED_CONFIG_PATHS` names the parent folders of the checkout and of the tracker root | mise itself; without it mise refuses the repo config |
| Code that runs | the installed wheel, never an editable install or `PYTHONPATH` | `just install`; run with `uv run --frozen --no-sync python -I -m taskloop ...` |
| Architecture | x86_64 and aarch64 both work; `mise.lock` and the wheels must cover both | checked on both on 2026-11-16, no gap |
| Slot paths | at most 64 bytes | slot setup |
| Git | an SSH key for GitHub in `~/.ssh` | the host login, never copied between tools |
| Logins | each tool logs in on its own (Claude Code, Codex, GitHub); never copy one tool's credentials to another | the tool |
| Docker | not needed by this repo's `just check` or `just test` | the justfile uses none. The sol container has no Docker (no socket, and no rootless daemon without user namespaces); the OrbStack machine has Docker 29.9.1. Gates that need Docker or Nix, such as the homelab repo's host checks, run on the OrbStack machine, which also has Nix 2.34 |
| Browser | none required today; dashboard scripts are tested with DOM probes only | none |
| Always on | the machine must not sleep during a run | see Sleep |

Python 3.15 is enforced at install time: an older interpreter cannot build the project environment, and the factory
runs only from that environment. There is no other guard, and none is needed.

## Machine settings, not code

| Setting | Where | Notes |
|---|---|---|
| Agent sandbox | `sandbox` under `[agents.<step>.access]` in `~/.config/task-loop/config.toml` | A real sandbox needs user namespaces: available on the OrbStack machine, not in the sol container (`unshare -U` is refused by the container's default seccomp profile), which sets `danger-full-access`. Allowing them would take a seccomp exception on the devbox, which ADR 0076 forbids. Off is acceptable only for an owner-only factory. |
| Slot count | `slot_count` in the same file (`round_seconds` is there too), and `--max-running` | 8 on sol, 6 on the OrbStack machine |
| Model and effort | the `rounds start` options | `gpt-6.1-sol`, `high` |

## Layout (the same on every machine)

| Thing | Path |
|---|---|
| Tracker root (the only place that writes beads) | `~/Workspaces/iorlas-task-loop` |
| Factory checkout (the code that runs) | `~/.local/share/task-loop/checkouts/iorlas-task-loop` |
| Slots | `~/.local/share/task-loop/slots/iorlas-task-loop/s1..sN` |
| State and logs | `~/.local/state/task-loop/` (`factory.db`, `artifacts/rounds.log`) |
| Dashboard | `127.0.0.1:8765` inside the machine; read-only |

Keep every repository and all factory state on the machine's own disk, not on a folder mounted from another operating
system. On a Mac, Microsoft Defender adds about 20 ms per file on Mac-side files.

## Start and stop

Start (one process, started by hand; nothing restarts it):

1. `cd ~/.local/share/task-loop/checkouts/iorlas-task-loop`, with `MISE_TRUSTED_CONFIG_PATHS` set.
2. `git fetch origin && git merge --ff-only origin/main`, then `just install`.
3. Bind the backlog once in `~/.config/task-loop/config.toml`:

   ```toml
   backlog = "tl"

   [backlogs.tl]
   tracker_root = "~/Workspaces/iorlas-task-loop"
   checkout = "~/.local/share/task-loop/checkouts/iorlas-task-loop"
   label = "real-run-1"
   ```

   Then run `rounds start --model gpt-6.1-sol --plan-effort high --implement-effort medium --max-running N --minutes 240`, in the
   background (`--backlog`, `--tracker-root`, `--checkout` and `--label` override the config's values), with output to
   `~/.local/state/task-loop/rounds.out`. After a `factory.db` discard, first run the same line once as `rounds once` with `--retake-lapsed`; never leave that flag on the permanent line.

Stop: send SIGTERM to the confirmed python process id held in `factory.db.rounds-tl.lock`, then wait until no attempt
entry process runs. Never stop a process by name.

Alive means a fresh last line in `rounds.log`. A quiet log is normal when nothing changes. A process in another
container cannot be seen from an agent session, so the log is the evidence.

## Moving the factory to another machine

1. Stop rounds on the old machine (above). Confirm that no attempt entry process runs and every slot is clean.
2. Publish the tracker: `bd dolt push` in the tracker root, and push every branch worth keeping. The tracker is the
   only state that moves; it syncs through the Git remote.
3. On the new machine: clone the repository, install the tools from the table above, and pull the tracker with
   `bd dolt pull`. Do not copy `factory.db`: it is disposable, and a fresh one starts from Git and the tracker.
4. Run `tl slot adopt <checkout> --slot-count N` in the factory checkout, then start rounds.
5. Leave the old machine's slots, worktrees, artifacts and old homes in place. Nothing is deleted by a move.

Only one machine writes beads at a time. A second writer needs a merge of the tracker, which is not supported.

## Sleep

A laptop that sleeps stops a run: attempts time out (`run:timeout`) when the clock jumps. A timeout after a sleep is
not a task fault. Keep the machine awake and plugged in for a run, or run on an always-on host. The sol machine never
sleeps, so there is nothing to do there.
