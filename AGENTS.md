# Agent Instructions

This branch is the curated successor foundation. The reference implementation is commit
`731b7c76ef214ce35229f77814f98b6e1d6d5c0f`; its source remains in Git history and the original review worktree.
A factory attempt's input text is its whole spec: read `docs/glossary.md` only for a term the text does not explain,
and `docs/design/tl-8bh9.8.7/plan.md` only when the task's own plan cites it. Only implemented commands are available;
foundation completion is not completion of the task factory. Carry retained behavior in bounded tasks, not
whole old packages, test bootstraps or unused abstractions. No baseline runtime imports or fallback.

## Ownership

| what | who may write it | never |
|---|---|---|
| main checkout | the person | agent hand edits |
| managed task worktree | its assigned implementing agent and coordinator | unrelated or competing source writers |
| task state | typed task-tracker operations through the actor | treating a comment as a state mutation |
| existing worktrees, evidence and user data | explicitly authorized owning operation | deletion based only on age or presumed staleness |

Work in a worktree. Preserve unrelated edits and task claims. Git operations follow active user/session authority;
local Git authorization does not authorize remote publication or merge.
Never kill processes by name; act only on a confirmed owned process identity.

## Build and verification

Python 3.15+. `just check` and `just test` are the required focused gates. `just check` = install (rebuilds the package), ruff,
pyrefly, import contracts; `just test` = tests/cli, tests/steps, tests/rules. Run gates as `just check 2>&1 | tail -60` and
`just test 2>&1 | tail -40`. Never run ruff or pytest directly except
`uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`.
The successor has its own declared environment and installed package; baseline editable installs or PYTHONPATH
must not supply missing code. Do not copy the old conftest/runners: they load the old application and kernel.
Run the code under test with `uv run --frozen --no-sync python -I -m taskloop ...` after `just install`, or through the tests.
No live tests. A factory attempt runs `just check` and `just test` once each, last, as its step text says; a session
runs them once before a pull request. Use focused behavior/contract tests; new tests are pytest functions
or classes, never unittest. No test for every private helper or a test that merely repeats its implementation.
Retain caps: 400 source lines per file, 80 per function and 800 per test file. No new Any, cast or ignore escape.

## Architecture and design

- Use the glossary: task, task tracker, step, attempt, session, slot and land have distinct meanings.
- Land is one application operation (`land.land`) shared by the CLI, a round and the dashboard's reads. A round runs it only
  under the profile's `land: auto` (read from Git at origin's `main`; `manual` is the default), one task per round; a refusal
  about the task's change holds it with the typed cause, so the same refusal is never tried again each round. The factory
  never asks the owner to run a CLI command: a message on these paths states the situation and the decision in words.
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
  signal use is `interrupts.py`'s SIGINT handler (sets a flag) and SIGTERM and SIGHUP handlers (the abrupt stop) while `tl step rounds` runs (signals no process), enforced
  by the import-linter contract `one-signal-owner` and the policy AST test.
- Prefer native Python even in libraries. A subprocess needs a concrete external-tool or lifecycle reason;
  moving a wrapper to shelf does not justify it. Retain safety behavior, not every existing mechanism.
- Typed inputs/results in process; validated structured interchange where needed across boundaries. No regex
  over display text/logs for workflow control and no JSON roundtrip just to make an in-process call look remote.
- No backward compatibility, dual readers or unused speculative features. Proposed decisions remain proposed.
  Explicitly held work stays held. Do not carry adapter behavior until its deletion consequences are assessed.
- Runtime version stays fixed until restart. Skills are lightweight explicit helpers, not another scheduler,
  policy/state owner or a prerequisite for factory correctness.
- Names: a new term borrows the industry-standard word for the same concept first (GitHub; OpenTelemetry GenAI
  conventions; the Claude Agent SDK and OpenAI Agents SDK: a turn is one request to the model and its reply, an
  agent invocation is one whole run); otherwise it chains defined terms (retry attempt, check suite). Where a
  vendor's word differs from the standard (Codex calls the whole run a turn), the glossary states both.
  Before a term enters the glossary or the code, put the options and reasons to a human and wait for the decision.
  Delete a term that is plain English or derivable from defined terms.
- Decide every name, meaning and structure as if starting from scratch. An existing column, name, code or earlier
  work is never a reason to keep a wrong name or meaning (sunk cost): rename or redefine and delete the old, as
  'No backward compatibility' requires. Example: execution.turns stayed 1 because it stored the harness's whole
  run; the fix is to redefine turns as the model-request count, not to add 'model_calls' beside it (tl-8bh9.14.187).
- Closed vocabularies (outcomes, phases, reasons, step and check names) are enums or classes, never string literals.
  A string appears only at the edge that stores or prints it, through one codec per vocabulary.
- A backend's (task tracker, Git, harness) tool names, commands, error text and types stay inside its adapter. The
  factory's outcome types and messages are generic; the adapter supplies the explanation per outcome. A missing
  explanation fails a test.
- Models at the edges (database rows, agent answers, configuration) are pydantic v2 models. Enums stay stdlib. Another
  third-party library needs a stated reason that tests get smaller, not larger.
- A schema-changing upgrade drains running attempts first: old entry processes cannot write to the new schema, and the
  old database is discarded.
- External actions (Git, tracker, process spawn) follow transactional outbox with reconciliation: a short transaction
  records the intent, the action runs outside any write transaction and is idempotent or observable, a second short
  transaction records the result; after a crash, reconciliation asks the world (does the ref exist, is the claim ours)
  and finishes or releases. No compensation chains; adopt what already happened. No new glossary term.
- Layout is vertical: one folder per feature, one module per use case (a transition with a typed outcome). A store or
  service module exists only where it hides something (deletion test). Only a slice's own store touches its tables; SQL
  and `sqlite3.Connection` never leave the store modules. One composition root per process.
- Test impact is a design goal: a use case's test imports only its slice and the small shared kernel, so a change runs
  only the tests its import closure reaches.
- Run commands non-interactively. AGENTS.md is the only instruction file; there is no CLAUDE.md.

## Environment facts

- Flat layout: `src/taskloop/*.py` plus `agents/`, `drain/`, `check_repeat/`, `dash/`; tests in `tests/steps`, `tests/cli`, `tests/rules`.
- Test helper modules live in `tests/steps` (pytest pythonpath, importlib mode).
- Ruff limits: 140 columns, at most 6 returns, no function-local imports.
- Project interpreter: `.venv/bin/python` or `uv run --frozen --no-sync python -I`; bare `python3` is the host's 3.12.
- shelf (pinned in pyproject.toml/uv.lock) is read-only for agents: read it at `~/Workspaces/shelf` with
  `git -C ~/Workspaces/shelf show <sha>:<path>` (sha from uv.lock) or in `.venv`. A need for a shelf change means stop and
  answer needs_owner with a shelf proposal.
- Make edits with apply_patch, not scripts.

Factory attempts have no bd and no beads skill: ignore the Beads sections below; the task text in your input is complete.

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
