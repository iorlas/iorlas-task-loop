# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
uv run pytest tests/land -q    # one folder or module (also tests/test_x.py::Class::test); the suite's tests are unittest TestCases
just test -n auto  # the whole suite in parallel workers (`just test` alone: one process); the `serial` group needs dev/suite.py
uv run --script dev/suite.py  # what a release runs: xdist workers, then the serial group alone; takes the host-wide suite lock
just check                     # ruff + pyrefly + import-linter + tests/gate_rules.py (tools pinned in mise.toml; `mise install`)
```

Dev and test tools (pytest, pytest-xdist) are the `dev` group of pyproject.toml, locked in uv.lock; `uv run` syncs them.
CI runs the suite and `just check` on Ubuntu with Python 3.15. Linux locally: `docker run --rm -v "$PWD":/src:ro python:3.15-slim ...`.
Caps (tests/gate_rules.py): 400 SLOC per file, 80 per function, 800 per test file; the KNOWN_OVERSIZE table (tests/rules_ratchet.json) may only shrink.
Architecture (layers, app slices, dashboard, `import re` placement): the `.importlinter` contracts; lazy imports, banned modules, module docstrings: ruff (PLC0415, TID251, D100). Both run in `just rules`.

## Architecture Overview

See README.md (Layout) and docs/design/dashboard/README.md. The skill (SKILL.md) is the method; `tl.py` is the only code the
orchestrating session runs; the dashboard server only reads.

## Before changing the dashboard, tl.py, or the skill's Workers section

Read `docs/dev/integrations.md`: every format task-loop reads but does not own (delegate's status, OpenCode, bd), its one
reader, and how delegate connects (worker-run, one table in SKILL.md).

## Conventions & Patterns

- Python 3.15+; macOS and Linux (in containers too), POSIX only. Dependencies: runtime ones are declared inline in `skills/task-loop/tl.py`
  (PEP 723, the same pin as pyproject.toml's `dependencies`; tests/test_pep723.py holds them equal) and run with `uv run --script`: the
  `tl` shim, the loop's own spawns, dev/release.py and dev/suite.py. Dev and test tools live in pyproject.toml's `dev` group. The
  PreToolUse hook (every Bash call) stays on plain `python3` and imports no msgspec and no record (.importlinter, tests/test_hook.py).
- The page is one HTML file, no build, no CDN.
- The engine requires the iorlas-delegate plugin (worker-run v1) and has no launcher of its own; never add one back.
  Only the contract is shared: never read delegate's files or call anything but `route.py run` and `status`.
- Never touch a transcript or another tool's state: the dashboard reads, `tl.py` writes only `~/.config/task-loop` and bd.
- Release only through `uv run --script dev/release.py "message" [--bead ID --reason R] [--from-branch B]`: it takes the
  release lock, works in its own persistent clone (`<config>/release/`; the main checkout is never touched), bumps `.claude-plugin/plugin.json` from origin/main and the iorlas-marketplace entry, runs the suite,
  pushes and installs. Never bump a version by hand.
