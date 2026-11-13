# Task-loop successor foundation

The successor task factory. Built so far: read-only inspection of Git checkouts and tasks, and the plan step end to
end, from admitting a ready task into a free slot to publishing its verified plan as `task/<id>` on `origin`; then the
implement step, advanced by each round (or by hand, `tl step start`) and published on the same branch; before an
implement agent starts, its entry resets the slot's environment and runs the repository's `setup` (Linux only), and the
agent runs offline with that environment. Not built: the checks, review and land steps, holds, and the dashboard.
Nothing merges or lands.

- `tl repo inspect PATH [--json]` reports the local repository identity, common directory, selected checkout and origin.
- `tl task show TASK_ID --backlog BACKLOG --tracker-root PATH [--json]` reads the explicitly configured Beads tracker,
  preserving requirements, acceptance and dependency relationships. The backlog key is supplied configuration; it is
  not inferred from Git. Missing, malformed and unavailable reads are distinct nonzero results; JSON errors go to stderr.
- `tl config show` prints each effective machine setting and its source.
- `tl profile show [--checkout PATH] [--at REV] [--target REF] [--json]` prints the repository profile: `setup` and
  checks at the commit `--at`, `required` and `target` from `--target` (read-only).
- `tl slot adopt CHECKOUT` adopts hand-made detached worktrees as slots and creates `factory.db`.
- `tl step start|show|list|verify|release|publish` run, inspect, verify, release (`--abandon` returns the tracker
  claim) and publish one task's current attempt, whatever its step (plan, then implement: `tl step start` on a done plan
  admits the implement step). `tl step next` runs one
  scheduling round: it settles existing attempts, advances each claimed task whose step is done (no label check), then
  admits approved ready tasks (`--label`) into the slots left while fewer than `--max-running` (default 3) of the backlog's tasks are in flight (a step running, or passed and waiting for `tl step land`); `tl step rounds` runs rounds in the foreground until Ctrl-C. `tl plan` is
  gone (an unknown command).

The machine config is `~/.config/task-loop/config.toml` or `--config FILE`; state defaults to
`~/.local/state/task-loop`. Other commands are rejected until their behavior is implemented. `tl <command> --help`
is the reference; the slice plans under `docs/design/tl-8bh9.4.3.1.*` record each step's design and acceptance.
The previous implementation remains in Git history. [docs/design/INDEX.md](docs/design/INDEX.md) lists every design folder
and document; [docs/glossary.md](docs/glossary.md) holds the vocabulary, the commit letters and the CLI flag table.

Python 3.15 and the tool versions in `mise.toml` are required. Run `mise install` after
trusting the repository configuration through normal mise setup.

```bash
uv sync --frozen --no-editable
uv run --frozen --no-sync tl --help
uv run --frozen --no-sync python -I -m taskloop --help
uv run --frozen --no-sync tl repo inspect . --json
just check
just test
```

Both required checks rebuild and install the current project as a wheel in this
worktree's `.venv`. Tests use that installed package and verify its source provenance;
no old editable install, vendored runtime or baseline source path supplies imports.
`just test` runs the CLI, step and architecture checks. `tests/steps/` holds all the factory tests, including the lock, lease and
rounds tests (the folder name is historical). No historical test bootstrap or kernel is included.
The Git, task tracker, agent, SQLite, process-lock and stream boundaries come from released
[shelf](https://github.com/yoselabs/shelf) libraries (`git-porcelain` 0.15.0, `beads-client` 0.2.0, `any-agent`
0.5.0, `sqlite-store` 0.1.0, `process-lock` 0.2.1, `stream-proc` 0.6.0), each pinned by Git tag and locked commit
and checked for portable source provenance.

[Design and acceptance](docs/design/tl-8bh9.8.7/plan.md) describe the boundary of this
foundation. Preserved design documents may describe future behavior or the historical implementation;
they are not additional executable commands.

`.task-loop.json` is this repository's profile (`setup`, `checks`, `required`, `target`), read from Git by
`tl profile show` ([tl-8bh9.14.1](docs/design/tl-8bh9.14.1/plan.md)). An implement attempt's entry runs its `setup`
(`just bootstrap`: `just install` plus every pinned check tool warmed in the uv cache) in the slot before the agent
([S5e](docs/design/tl-8bh9.4.3.1.16.2/plan.md)), on Linux only; the agent then writes three folders beside the slots
(`TMPDIR`, the uv cache and tools) with uv offline and is told to run every command under `checks` itself. The factory
does not run the checks yet. A slots root must keep `<slots_root>/<repo_id>/.t/<slot>` within 64 bytes and lie outside
the checkout, the artifacts root and factory.db's folder.
