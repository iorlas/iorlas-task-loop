# Task-loop successor foundation

This isolated successor currently provides CLI help and rejects unsupported commands.
It does not execute tasks. The previous implementation remains in Git history.

Python 3.15 and the tool versions in `mise.toml` are required. Run `mise install` after
trusting the repository configuration through normal mise setup.

```bash
uv sync --frozen --no-editable
uv run --frozen --no-sync tl --help
uv run --frozen --no-sync python -I -m taskloop --help
just check
just test
```

Both required checks rebuild and install the current project as a wheel in this
worktree's `.venv`. Tests use that installed package and verify its source provenance;
no old editable install, vendored runtime or baseline source path supplies imports.
`just test` selects the foundation's CLI and architecture checks. No historical test
bootstrap, kernel, process fake or runtime dependency is included.

[Design and acceptance](docs/design/tl-8bh9.8.7/plan.md) describe the boundary of this
foundation. Preserved design and instruction documents may describe future behavior
or the historical implementation; they are not additional executable commands.

Preserved `.task-loop.json` and skill/package documents describe baseline behavior and are not operational
configuration for this foundation. Their source remains reference material until each retained concern is implemented.
