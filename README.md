# Task-loop successor foundation

The successor task factory. Built so far: read-only inspection of Git checkouts and tasks, and the plan step end to
end, from admitting a ready task into a free slot to publishing its verified plan as `task/<id>` on `origin`.
Not built: the implement, checks, review and land steps, and the dashboard. Nothing merges or lands.

- `tl repo inspect PATH [--json]` reports the local repository identity, common directory, selected checkout and origin.
- `tl task show TASK_ID --backlog BACKLOG --tracker-root PATH [--json]` reads the explicitly configured Beads tracker,
  preserving requirements, acceptance and dependency relationships. The backlog key is supplied configuration; it is
  not inferred from Git. Missing, malformed and unavailable reads are distinct nonzero results; JSON errors go to stderr.
- `tl config show` prints each effective machine setting and its source.
- `tl slot adopt CHECKOUT` adopts hand-made detached worktrees as slots and creates `factory.db`.
- `tl plan start|show|list|verify|release|publish` run, inspect, verify, release (`--abandon` returns the tracker
  claim) and publish one task's plan attempt. `tl plan next` runs one scheduling round over approved ready tasks;
  `tl plan rounds` runs rounds in the foreground until Ctrl-C.

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
`just test` runs the CLI, plan and architecture checks. `tests/steps/` holds all the factory tests, including the lock, lease and
rounds tests (the folder name is historical). No historical test bootstrap or kernel is included.
The Git, task tracker, agent, SQLite, process-lock and stream boundaries come from released
[shelf](https://github.com/yoselabs/shelf) libraries (`git-porcelain` 0.13.0, `beads-client` 0.2.0, `any-agent`
0.4.0, `sqlite-store` 0.1.0, `process-lock` 0.2.1, `stream-proc` 0.5.0), each pinned by Git tag and locked commit
and checked for portable source provenance.

[Design and acceptance](docs/design/tl-8bh9.8.7/plan.md) describe the boundary of this
foundation. Preserved design documents may describe future behavior or the historical implementation;
they are not additional executable commands.

The preserved `.task-loop.json` describes baseline behavior; no successor code reads it.
