# Task-loop successor foundation

The successor task factory implements plan, implement and checks, task holds, explicit land, and an optional
read-only dashboard. It admits approved tasks into free slots, publishes verified agent results as `task/<id>` on
`origin`, and runs the repository profile's checks. Before implementation and checks, it prepares the slot's
environment and runs the profile's `setup` (Linux only); the agent works offline with that environment.
Rounds advance tasks through checks and stop before land. The person delivers a checked task with `tl step land`.
Review remains future work; the retained designs describe more than the implemented factory.

- `tl repo inspect PATH [--json]` reports the local repository identity, common directory, selected checkout and origin.
- `tl task show TASK_ID --backlog BACKLOG --tracker-root PATH [--json]` reads the explicitly configured Beads tracker,
  preserving requirements, acceptance and dependency relationships. The backlog key is supplied configuration; it is
  not inferred from Git. Missing, malformed and unavailable reads are distinct nonzero results; JSON errors go to stderr.
- `tl config show [--count N]` prints each effective machine setting and its source.
- `tl profile show [--checkout PATH] [--at REV] [--target REF] [--json]` prints the repository profile: `setup` and
  checks at the commit `--at`, `required` and `target` from `--target` (read-only).
- `tl slot adopt CHECKOUT [--count N]` adopts hand-made detached worktrees as slots and creates `factory.db`.
- `tl step start|show|list|verify|release|publish` run, inspect, verify, release (`--abandon` returns the tracker
  claim) and publish one task's current attempt. `tl step start` on a done plan admits implementation; after a verified
  implementation it admits checks. Checks run the profile's commands in the factory, with results and logs available
  through `tl step show`. `tl step next` runs one
  scheduling round: it settles existing attempts, advances each claimed task whose step is done (no label check), then
  admits approved ready tasks (`--label`) into the slots left while fewer than `--max-running` (default 3) of the backlog's
  tasks are in flight (a step running, or passed and waiting for land). `--max-new` is removed and rejected.
- `tl step rounds` repeats rounds in the foreground until Ctrl-C. `--retake-lapsed` on `next` or `rounds` is for recovery
  after discarding `factory.db`: it also takes the factory's expired claims absent from that database, assuming one
  factory on the tracker. Prefer one `next` invocation for that recovery.
- `tl step land TASK --backlog BACKLOG --checkout PATH` is the person's delivery command: squash the checked commit
  onto origin's `main`, validate again when required, push without force, then close the task in the local tracker.
  Use `--summary` to inspect first. Some lands require `--minutes N` for validation. Reruns reconcile unfinished actions;
  tracker synchronization remains the person's responsibility. Publishing a task branch does not land it.

Rounds hold tasks they took when work needs a person: the approval label is removed, `held` is added, and a comment
explains the cause, evidence and claim state. `tl step list --stuck`, `tl step show` and `bd list --label held` expose
them. Answer by editing the task's description or acceptance criteria, then add its approval label back; the next
round starts it again at plan. Follow any pending cleanup instructions before reapproval. Comments alone are not answers.

`tl step rounds --dash-port PORT` serves the dashboard on `127.0.0.1` for the lifetime of rounds; 0 chooses a free port.
Without this flag nothing is served. A dashboard startup failure warns on stderr while rounds continue.
`step rounds --json` writes JSON Lines: one start record and one end record for a normal graceful session.
Dashboard notices go to stderr in this mode, as do early refusals and abrupt end results; stdout records keep their
existing shapes. Other commands' `--json` output is a single document.

Exit codes are 0 for success/already complete (including a graceful rounds stop), 1 for refusals and task/repo
inspection failures, 2 for invalid syntax, 3 for no reliable result (profile unavailable or a step classified unknown;
retry is safe), and 130 for an abrupt rounds stop or interrupted land. Task/repo inspection failures remain 1 even
when a backend read is unavailable. Continuous rounds retry unknown results themselves.

The machine config is `~/.config/task-loop/config.toml` or `--config FILE`; state defaults to
`~/.local/state/task-loop`. Other commands are rejected until their behavior is implemented. `tl <command> --help`
is the reference; the design index links each slice's plan and implementation evidence. `tl plan` is no longer a command.
The previous implementation remains in Git history. [docs/design/INDEX.md](docs/design/INDEX.md) lists every design folder
and document; [docs/glossary.md](docs/glossary.md) holds the vocabulary, the commit letters and the CLI flag table.

Python 3.15 and the tool versions in `mise.toml` are required. Run `mise install` after
trusting the repository configuration through normal mise setup.

```bash
just install
uv run --frozen --no-sync python -I -m taskloop --help
uv run --frozen --no-sync python -I -m taskloop repo inspect . --json
just check
just test
```

Both required checks rebuild and install the current project as a wheel in this
worktree's `.venv`. Tests use that installed package and verify its source provenance;
no old editable install, vendored runtime or baseline source path supplies imports.
`just test` runs the CLI, step and architecture checks. `tests/steps/` holds all the factory tests, including the lock, lease and
rounds tests (the folder name is historical). No historical test bootstrap or kernel is included.
The Git, task tracker, agent, SQLite, process-lock and stream boundaries come from released
[shelf](https://github.com/yoselabs/shelf) libraries, pinned in [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock)
and checked for portable source provenance.

[Design and acceptance](docs/design/tl-8bh9.8.7/plan.md) describe the boundary of this
foundation. Preserved design documents may describe future behavior or the historical implementation;
they are not additional executable commands.

`.task-loop.json` is this repository's profile (`setup`, `checks`, `required`, `target`), read from Git by
`tl profile show` ([tl-8bh9.14.1](docs/design/tl-8bh9.14.1/plan.md)). An implement attempt's entry runs its `setup`
(`just bootstrap`: `just install` plus every pinned check tool warmed in the uv cache) in the slot before the agent
([S5e](docs/design/tl-8bh9.4.3.1.16.2/plan.md)), on Linux only; the agent then writes three folders beside the slots
(`TMPDIR`, the uv cache and tools) with uv offline and is told to run every command under `checks` itself. The factory's
checks step independently runs the profile's setup and checks on the committed implementation. A slots root must keep
`<slots_root>/<repo_id>/.t/<slot>` within 64 bytes and lie outside
the checkout, the artifacts root and factory.db's folder.
