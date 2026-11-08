# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

> ## ⚠️ NO BACKWARD COMPATIBILITY ⚠️
>
> **WE DO NOT KEEP OLD RUNS, OLD STORED FORMATS, OLD CONFIG SHAPES OR OLD LOG LAYOUTS WORKING.**
>
> - A change to a stored format is made directly. Old data is discarded, or migrated later by a migration tool when there is one.
> - No N-1 readers, no two-release add/remove dance, no compat shims, no deprecation periods, no "legacy" code paths kept.
> - A stale or foreign-version record is refused loudly (`wire.load` raises `StaleRecord`: that is a rule, not compatibility) and the run starts over. Effects of an unfinished close may need manual cleanup; that is accepted.
> - Exceptions: data in git history, and anything Denis names.
> - Detail: `docs/design/compat.md`.

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
just test                      # THE test command: runs only the tests this change can break (dev/affected.py: the diff against origin/main followed up the import graph; tests/rules always), all kinds, once per tree, in at most 4 workers; the gate and the release run this and nothing else
uv run pytest tests/land -q    # one slice folder, module or test (tests/land/test_x.py::Class::test) while you edit; the tests are plain pytest classes: `assert`, `setup_method`, fixtures; `tltestkit.case.Case` still gives `addCleanup` and `subTest`; write new tests as pytest functions or classes, never `unittest`
just check                     # ruff on the changed .py files only (`just lint-all`: whole tree), pyrefly on the whole tree (a signature change breaks unchanged callers), then import-linter (tools pinned in mise.toml; `mise install`)
just test-pkg <stage>          # stage tests + its dependencies' contract tests; inner loop only, `just test` stays the gate. Workspace members run in their isolated package environment.
just test-delegate            # packages/delegate/tests (real processes, minutes): collected by no other run unless the change touches packages/delegate, skills/task-loop/_vendor or packages/testkit (dev/packages.py); a task-loop or dashboard change never runs them
```

Never run pytest over the whole suite; for broad coverage run `just test` (affected-only).
Whole-suite runs (`just test-full`) and `just test-live` (tests/live: scenarios that run the real pieces) are started by a person, never by an agent, the gate, a release, a cron or a background job.

Tests live in `tests/<slice>/`, mirroring `src/taskloop/app/<slice>` (a test's home is the slice whose code changes if its assertion breaks), or, for a stage that has become a package, in `packages/<stage>/tests/` (same layers, same folder names below it);
the other layers have their own folders (`contracts`, `stores`, `adapters`, `ports`, `domain`, `cli`, `hook`, `dash`, `rules` for the gate).
**Test layers. A test's layer comes from its path (tests/conftest.py, the rule itself is `packages/testkit`: `tltestkit.limits.kind_of_parts`, which reads the parts below `tests/` or `packages/<stage>/tests/`), never from a hand marker; a guard fails a test that touches more than its layer allows.**

For a converted stage, `tests/<slice>/` is its integration layer on the shell host (imports the package plus the shell); package-pure tests live in `packages/<stage>/tests/`, and the rules fail a package-pure file in the mapped `tests/<slice>/`, with no cap or kind change.

| layer | path | may touch | per test (CPU) | layer total (affected-only, 1 worker) |
|---|---|---|---|---|
| unit | `tests/<slice>/` | memory; files and sqlite only through the `workdir` fixture; git, processes and time only as fakes (gitsim, procsim, fake_clock); no `time.sleep` | 100 ms | 60 s |
| real | `tests/<slice>/real/`, `tests/ports/`, `tests/adapters/` | a real git, process or socket, because the port's real adapter is the thing under test | 1 s | 60 s |
| e2e | `tests/e2e/` | a whole flow; at most 10 tests | 10 s | 60 s |

- **Contract, then consumers.** Each port (git, process, clock, ...) has ONE contract suite, run against the real adapter (in the real layer) and against its fake (gitsim, procsim, fake_clock), so the fake cannot drift. A consumer of the port (land, run, loop, ...) is tested against the fake, with one wiring test on the real adapter per consumer. Real git is re-tested once per port, never once per consumer.
- Budget of the affected-only run: 120 s CPU on one worker; the gate runs that selection and nothing wider. `dev/runtests.py` loads `dev/testtimes.py`, prints a selection above 50% of all tests (the change reaches too far) and, at the end, the tests over 5 s CPU (10 lines, '+N more', with the fix class).
- Guards: `tests/support/procsim.py` (a unit test that spawns, forks or runs real git fails; a real test that spawns nothing fails), LIMITS_S in conftest (a test over its kind's limit fails), and the change ratchets (`layer_ratchet`, `temp_ratchet`, `needs_ratchet`, judged by `tests/rules/ratchet_change.py`: no stored baseline; the files a change touches are counted at the merge base with origin/main and now, per kind of offender, and a rise fails: a `@real_proc` / `@real_git` mark outside `real/`, a `time.sleep` in a test, a `tempfile` / `/tmp` site, a new `@needs` reason; a deliberate rise is a commit-message line `Ratchet-allow: <layer|temp|needs> +N <reason in words>`).
- `serial` stays a marker (shared clock, port or lock). A new `@real_proc` / `@real_git` or `time.sleep` outside `real/` is refused; a sleep is a bug: inject the clock and advance it.
- A table of cases is one parametrized test, never a loop of full runs inside one test; `subTest` and `setup_method` are for the legacy classes only.
- The unit layer holds no path literals, `os.fork`, signals or shell (Windows comes later); POSIX-only tests live in `real/`.

Dev and test tools (pytest, pytest-xdist) are the `dev` group of pyproject.toml, locked in uv.lock; `uv run` syncs them.
There is no hosted CI: the factory is the CI. `just check` and `just test` run on the release path (`dev/release.py`) before any push to main; each test runs once per tree.
Caps (tests/rules/gate_rules.py): 400 SLOC per file, 80 per function, 800 per test file; no exceptions table: an oversize file or function is split. No SLOC total and no `Any` count is stored (parallel releases would conflict on it): the caps are per file, and tests/rules/real/test_changed_files.py compares the files a change touches with the merge base on origin/main (no new `Any`, `cast` or ignore on net). The per-stage forward closure is a change ratchet (`tests/rules/closure_ratchet.py`); a deliberate rise is `Ratchet-allow: closure +N <reason in words>`.
Architecture (layers, app slices, dashboard, `import re` placement): the `.importlinter` contracts; lazy imports, banned modules, module docstrings: ruff (PLC0415, TID251, D100). Both run in `just rules`.

## Architecture Overview

See README.md (Layout) and docs/design/dashboard/README.md. The skill (SKILL.md) is the method; `tl.py` is the only code the
orchestrating session runs; the dashboard server reads state and takes only the owner's typed writes (`POST /api/<verb>`, `contracts.dash.WRITES`), each an in-process Port call.

## Stage packages (target layout, docs/design/stage-packages.md; only `packages/testkit` exists so far)

A stage becomes a package `packages/<stage>/{src/taskloop_<stage>/, tests/}` (a uv workspace member; the code stays importable as before until its carve). The charter of every carve:

- It owns its contracts (a `contracts/` folder with its own ruff.toml: records only, no subprocess, socket or threading), its domain and app code, its prompts and its tables; its fakes are `testing.py`, run against the same contract suite as the real adapter.
- **Its public surface is three names: `api.py` (the functions and Protocols it offers), `contracts/` and `testing.py`.** No other package imports anything else of it (one import-linter forbidden contract per package).
- It imports only the kernel (wire, ids, enums, paths, env, envvars, identity, bead) and other packages' api, contracts and testing, never their internals and never upward (no cycle).
- Its tests run alone (`just test-pkg <stage>`) on its own `testing.py` fakes plus the test kit (`packages/testkit`: case, procsim, tmpdir, paths, the layer guards); a test that needs another package's real code belongs to the shell or to `tests/e2e`.
- A carve is a history-preserving `git mv`, the caps (400/80/800) hold, `dev/reach.py` shows the package's change reach did not grow, and the PR is a pure move or a pure cut.

## Before changing the dashboard, tl.py, or the skill's Workers section

Read `docs/dev/integrations.md`: every format task-loop reads but does not own (delegate's status, OpenCode, bd), its one
reader, and how delegate connects (`delegate.api`, one table in SKILL.md).

## Conventions & Patterns

- Decisions live in docs (the design note's Decisions recorded table or the repo's ADR); beads are work only; a decision bead is closed the moment it is decided.

- "We need to use only our database": factory.db is for state, with no file fallback. Logs (engine, worker console, transcripts) stay files behind a log reader, rotated by age.

- Python 3.15+; macOS only, POSIX. Dependencies: runtime ones are declared inline in `skills/task-loop/tl.py`
  (PEP 723, the same pin as pyproject.toml's `dependencies`; tests/rules/test_pep723.py holds them equal) and run with `uv run --script`: the
  `tl` shim, the loop's own spawns, and dev/release.py. Dev and test tools live in pyproject.toml's `dev` group. The
  PreToolUse hook (every Bash call) stays on plain `python3` and imports no msgspec and no record (.importlinter, tests/hook/test_hook.py).
- The page is one HTML file, no build, no CDN.
- delegate is a library in this repo (`packages/delegate/src/delegate`). The engine imports `delegate.api` and nothing else of it, and has no launcher of
  its own; never add one back. Never read delegate's state files: ask the API (`packages/delegate/docs/contracts/delegate-api.md`).
- Never touch a transcript or another tool's state: the dashboard reads, `tl.py` writes only `~/.config/task-loop` and bd.
- Release only through `uv run --script dev/release.py "message" [--bead ID --reason R] [--from-branch B]`: it takes the
  release lock, works in its own persistent clone (`<config>/release/`; the main checkout is never touched), bumps `.claude-plugin/plugin.json` from origin/main and the iorlas-marketplace entry, runs the suite,
  pushes and installs. Never bump a version by hand. A `.task-loop.json` is an in-repo file read by the same version that ships it; a key the reader does not know is refused (`unknown field`), and a new key is added with the code that reads it, with no two-release step.
