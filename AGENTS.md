# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [sync-concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Ownership

`tl doctor` fails when this section is missing from the installed plugin's AGENTS.md.

| what | who may write it | never |
|---|---|---|
| the main checkout of a repo | the person; `dev/release.py` never touches it | an agent's hand edit, a release |
| a plugin cache dir (`~/.claude/plugins/cache/...`) | `claude plugin update`, driven by `dev/release.py` | any edit, by anyone: a flipped byte shows in `tl doctor` against MANIFEST.sha256 |
| the release clone (`<config>/release/`) | `dev/release.py` | anything else |
| `pinned.json` | `tl pin` and `tl rollback`, the owner's override | the loop, an engine, an agent |
| ports (slots, worktrees, the dashboard server) | `tl slot`, `tl worktree`, `tl dash` | killing a process by name: no `pkill`/`killall`, only a PID you confirmed is yours |
| a bead's state | `tl` (the actor) | prose in a comment; only typed verbs act |

Work in a worktree. Fork a session only for read-only work of 4 hours or less; otherwise start a fresh one with a written brief.

## Build & Test

```bash
uv run pytest tests/land -q    # one folder or module (also tests/test_x.py::Class::test); the suite's tests are unittest TestCases
just test -n auto  # the whole suite in parallel workers (`just test` alone: one process); the `serial` group needs dev/suite.py
uv run --script dev/suite.py  # what a release runs: xdist workers, then the serial group alone; takes the host-wide suite lock
just check                     # ruff + pyrefly + the structural rules (tools pinned in mise.toml; `mise install`)
```

Dev and test tools (pytest, pytest-xdist) are the `dev` group of pyproject.toml, locked in uv.lock; `uv run` syncs them.
CI runs the suite and `just check` on Ubuntu with Python 3.12. Linux locally: `docker run --rm -v "$PWD":/src:ro python:3.12-slim ...`.
Caps (tests/gate_rules.py): 400 SLOC per file, 80 per function, 800 per test file; the KNOWN_OVERSIZE table (tests/rules_ratchet.json) may only shrink.

## Conventions

- Python 3.12+; macOS and Linux (in containers too), POSIX only. Dependencies: runtime ones are declared inline in `skills/task-loop/tl.py`
  (PEP 723, the same pin as pyproject.toml's `dependencies`; tests/test_pep723.py holds them equal) and run with `uv run --script`: the
  `tl` shim, the loop's own spawns, dev/release.py and dev/suite.py. Dev and test tools live in pyproject.toml's `dev` group. The
  PreToolUse hook (every Bash call) stays on plain `python3` and imports no pydantic and no record (.importlinter, tests/test_hook.py).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

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

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
