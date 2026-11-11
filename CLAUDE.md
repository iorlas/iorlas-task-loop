# Agent Instructions

This branch is the curated successor foundation. The reference implementation is commit
`731b7c76ef214ce35229f77814f98b6e1d6d5c0f`; its source remains in Git history and the original review worktree.
Read `docs/design/tl-8bh9.8.7/plan.md` and `docs/glossary.md`. Only implemented commands are available;
foundation completion is not completion of the task factory. Carry retained behavior in bounded tasks, not
whole old packages, test bootstraps or unused abstractions. No baseline runtime imports or fallback.

## Ownership

| what | who may write it | never |
|---|---|---|
| main checkout | the person | agent hand edits or release tooling |
| managed task worktree | its assigned implementing agent and coordinator | unrelated or competing source writers |
| installed plugin/cache | the normal installation/release operation | hand edits |
| owner pin | explicit owner operation | automatic version switching |
| task state | typed task-tracker operations through the actor | treating a comment as a state mutation |
| existing worktrees, evidence and user data | explicitly authorized owning operation | deletion based only on age or presumed staleness |

Work in a worktree. Preserve unrelated edits and task claims. Git operations follow active user/session authority;
local Git authorization does not authorize remote publication, merge, installation or release.
Never kill processes by name; act only on a confirmed owned process identity.

## Build and verification

Python 3.15+. `just check` and `just test` are the required focused gates. Read the justfile before running them.
The successor has its own declared environment and installed package; baseline editable installs or PYTHONPATH
must not supply missing code. Do not copy the old conftest/runners: they load the old application and kernel.
Do not run whole-suite/live tests as an agent. Use focused behavior/contract tests; new tests are pytest functions
or classes, never unittest. No test for every private helper or a test that merely repeats its implementation.
Retain caps: 400 source lines per file, 80 per function and 800 per test file. No new Any, cast or ignore escape.

## Architecture and design

- Use the glossary: task, task tracker, step, attempt, session, slot and land have distinct meanings.
- Task tracker owns requirements, dependencies, questions, linked answers and discussion; Git owns code,
  plans and selected design artifacts. Plans belong at `docs/design/<task-id>/plan.md`.
- factory.db owns local execution state and reservations. Deliberate discard permits normal reevaluation;
  intact-DB restart must continue unfinished work/session after liveness reconciliation. No backup/restore,
  compatibility reader, history reconstruction or file fallback for factory state.
- Logs, transcripts and execution artifacts remain files behind owning readers. Do not derive control state
  from logs. Tracker maintenance owns durable task-data protection; preserve exports until recovery is verified.
- One owner per fact and one application operation shared by CLI, dashboard and agent consumers.
- State/time/IO enter through narrow explicit ports. Use owning shelf Git/process/agent/lock APIs and semantic
  fakes. Factory source and tests have no subprocess imports/usage or direct spawn/signal/wait escape hatch. The only
  signal use is `interrupts.py`'s SIGINT handler while `tl step rounds` runs (sets a flag, signals no process), enforced
  by the import-linter contract `one-signal-owner` and the policy AST test.
- Prefer native Python even in libraries. A subprocess needs a concrete external-tool or lifecycle reason;
  moving a wrapper to shelf does not justify it. Retain safety behavior, not every existing mechanism.
- Typed inputs/results in process; validated structured interchange where needed across boundaries. No regex
  over display text/logs for workflow control and no JSON roundtrip just to make an in-process call look remote.
- No backward compatibility, dual readers or unused speculative features. Proposed decisions remain proposed.
  Explicitly held work stays held. Do not carry adapter behavior until its deletion consequences are assessed.
- Runtime version stays fixed until restart. Skills are lightweight explicit helpers, not another scheduler,
  policy/state owner or a prerequisite for factory correctness.
- Run commands non-interactively. AGENTS.md and CLAUDE.md are separate files: mirror substantive instruction edits.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
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
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
