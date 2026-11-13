# Foundation implementation evidence

Status: **evidence**. Dated delivery record for the **built** minimal foundation, not a claim that the entire factory
is complete. Current capabilities and commands are in the [README](../../../README.md).

Task: tl-8bh9.8.7. Local implementation checkpoint, 2026-11-09.
This is the minimal foundation; it does not execute factory tasks or establish product cutover.
Independent review, executable smoke verification, publication and task completion are separate effects.

## Provenance and transferred evidence

The isolated managed worktree is
`/home/iorlas/.codex/worktrees/successor-foundation/iorlas-task-loop`, on
`codex/successor-foundation`, from exact baseline
`731b7c76ef214ce35229f77814f98b6e1d6d5c0f`.
The coordinator deliberately transferred the accepted uncommitted review documents and
AGENTS/CLAUDE instructions from the frozen review worktree before source construction.
The implementing agent did not edit those transferred instructions or the person's main checkout.

## Removed ownership

Only tracked baseline runtime/test/tool files in the approved roots were deleted. All
Markdown, nested docs and instruction evidence in those roots were retained, as were
root docs, task data, Git metadata and user/config files. Git's diff is the exact per-file
record; no copied historical implementation remains as a dormant runtime.

| Deleted root | Tracked paths deleted | Reason |
|---|---:|---|
| src | 237 | Baseline CLI/application/adapters/stores; package initialization is replaced directly. |
| packages | 1020 | Old stage/kernel/testkit runtime, tests and package metadata would retain the baseline graph. |
| tests | 909 | Historical behavior/composition tests and bootstrap import the retired application. |
| dev | 53 | Historical runners/release/vendor tooling imports or operates the retired runtime. |
| skills | 134 | PEP 723 launcher and vendored runtime; the skill's instruction document is retained. |
| hooks | 2 | Old task-loop hook executable and activation manifest. |
| .claude-plugin | 1 | Old plugin manifest advertised features and packaging absent from this foundation. |
| MANIFEST.sha256 | 1 | Old installed-plugin hashes describe retired files, not this wheel. |

The Beads-only .claude/.codex/.cursor activation configurations, .agents skills,
.task-loop.json and .beads data remain intact. Installed plugin caches, hooks, person
worktrees and release state were not touched. Package docs and Markdown test fixtures
remain evidence, excluded from the wheel and successor test selection.

## Retained behavior and checks

The wheel contains only `taskloop` initialization, the real CLI parser and module entry.
`tl`, `tl -h` and `tl --help` show truthful help; unsupported commands/options fail with
argparse's exit status 2 and stderr. There are no placeholder task commands, new adapters,
state, kernel, interfaces, process calls or runtime dependencies. No composition module
is needed before an application operation exists.

Both `just check` and `just test` rebuild/reinstall the current non-editable wheel in this
worktree's own .venv. Tests execute parsing and the module entry in process and compare
installed production bytes to this source tree, check non-editable distribution provenance,
and reject old package import resolution. Python isolated mode ignores PYTHONPATH and user
site packages. There is no testkit/bootstrap dependency or copied fake.

The required static checks retain pinned ruff, pyrefly and import-linter, strict production
types, the current entry-to-CLI dependency direction, and no direct network/process mechanisms.
Focused rules retain tokenize-based 400/80/800 SLOC caps and refuse Any, cast and ignore escapes.
All current tests belong to the foundation's one affected behavior/build boundary; the
historical whole/live suites and runners are absent and were not invoked.

Initial required checks passed: ruff 0.17.2, pyrefly 1.4.0 (zero errors), import-linter 2.15
(two contracts kept), and 19 focused pytest checks. The available interpreter is
CPython 3.15.0b2; uv reports that a stable 3.15 is available. No interpreter upgrade was
performed. These results alone do not claim independent acceptance or task closure.


## Independent acceptance and executable checks

Independent read-only review found no blocking correctness/scope issue. The coordinator verified both
`.venv/bin/tl --help` and `.venv/bin/python -I -m taskloop --help` return 0, and `.venv/bin/tl plan` returns
2 with an unsupported-command diagnostic. No task execution route is falsely advertised as implemented.
Required gates passed after the final source changes: `just check` and `just test` (19 focused tests).
Preserved `.task-loop.json` describes historical baseline operations; the foundation has no profile reader and
this configuration is inactive. Its bytes remain protected. The obsolete pre-commit comment was corrected;
the actual repository lint hook remains valid. Only documentation changed after the source gate results.

The adapter removal counterfactuals are recorded separately in ../tl-8bh9.4.6/removal-challenge.md.
A local checkpoint is not publication, merge, release, full factory functionality or task delivery.
