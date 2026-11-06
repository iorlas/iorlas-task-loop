# Blueprint: stack/python-uv (Stack-specific)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ✅ | `stack.python-uv.profile` | yes | yes | evidenced profile: toolchain: uv, with a committed lockfile and a declared Python range · formatter: ruff format · linter: ruff check, the shelf's rule set · types: pyrefly, strict preset · spelling: codespell · dependencies: deptry (unused, missing, transitive) · tests: pytest, strict markers · coverage: pytest-cov with a floor · architecture: import-linter (layers, forbidden, independence, acyclic_siblings, protected) for import edges; ruff TID251 banned-api for banned APIs; both read pyproject.toml, one declaration each · hooks: prek runs ruff check and ruff format --check on staged Python files · agent-guidance: docs/agents/python.md: tools per role, placement, naming, comments, traps; python-uv detected from pyproject.toml, uv.lock | - | - |
| ❌ | `stack.python-uv.toolchain` | yes | no | uv, with a committed lockfile and a declared Python range set up, but the gate never runs `uv lock --check` | run `uv lock --check` from `just check` | agent |
| ❌ | `stack.python-uv.formatter` | no | - | ruff format not set up (missing pyproject.toml with '[tool.ruff') | uv add --dev ruff; copy [tool.ruff] from the shelf (just bootstrap) | agent |
| ❌ | `stack.python-uv.linter` | no | - | ruff check, the shelf's rule set not set up (missing pyproject.toml with '[tool.ruff.lint]') | copy [tool.ruff.lint] from the shelf (just bootstrap) | agent |
| ❌ | `stack.python-uv.types` | no | - | pyrefly, strict preset not set up (missing pyproject.toml with '[tool.pyrefly]'; pyproject.toml with 'preset = "strict"'; pyproject.toml with 'use-ignore-files = false') | uv add --dev pyrefly; copy [tool.pyrefly] from the shelf (just bootstrap) | agent |
| ❌ | `stack.python-uv.dependencies` | no | - | deptry (unused, missing, transitive) not set up: nothing in the repo configures it, and the gate never runs `deptry` | uv add --dev deptry | agent |
| ❌ | `stack.python-uv.tests` | yes | no | pytest, strict markers set up, but the gate never runs `pytest` | run `pytest` from `just check` | agent |
| ❌ | `stack.python-uv.coverage` | no | - | pytest-cov with a floor not set up (missing pyproject.toml with 'pytest-cov' or pyproject.toml with '[tool.coverage' or justfile with 'coverage run' or Makefile with 'coverage run' or justfile with '--cov' or Makefile with '--cov') | uv add --dev pytest-cov; run pytest with --cov-fail-under=<just below current> | agent |
| ❌ | `stack.python-uv.spelling` | no | - | codespell not set up (missing pyproject.toml with '[tool.codespell]') | uv add --dev codespell; copy [tool.codespell] from the shelf | agent |
| ✅ | `stack.python-uv.architecture` | yes | yes | import-linter (layers, forbidden, independence, acyclic_siblings, protected) for import edges; ruff TID251 banned-api for banned APIs; both read pyproject.toml, one declaration each, run by the gate (`lint-imports`) | - | - |
| ❌ | `stack.python-uv.hooks` | no | - | prek runs ruff check and ruff format --check on staged Python files not set up (missing .pre-commit-config.yaml with 'ruff check'; .pre-commit-config.yaml with 'ruff format') | add ruff-check and ruff-format local hooks (types: [python]) to .pre-commit-config.yaml after bd's entries | agent |
| ❌ | `stack.python-uv.agent-guidance` | no | - | docs/agents/python.md: tools per role, placement, naming, comments, traps not set up (missing docs/agents/python.md) | PYTHONPATH=<shelf>/packages/blueprint/src python3 -m blueprint template --repo . | agent |
| ✅ | `stack.python-uv.python-pin` | yes | yes | .python-version 3.15 | - | - |
| ✅ | `stack.python-uv.python-range` | yes | yes | .: >=3.15 | - | - |
| ✅ | `stack.python-uv.python-range-tested` | yes | yes | every lower bound is the pin 3.15 or has a CI run | - | - |
| ✅ | `stack.python-uv.python-ci` | yes | yes | no .github/workflows; nothing to read the pin | - | - |
| ❌ | `stack.python-uv.uv-version` | no | - | no [tool.uv] required-version | add [tool.uv] required-version = ">=<the uv you run>"; setup-uv v5.2.0 and later read it when `version:` is omitted | auto |
| ✅ | `stack.python-uv.uv-ci` | yes | yes | no setup-uv step and no image copies uv; a mise-action CI installs the mise.toml pin | - | - |
| ❌ | `stack.python-uv.cli-parse` | yes | no | lenient parsing swallows unknown flags, --help included: src/taskloop_dash/cli/dash.py:46, src/taskloop_dash/cli/dash.py:48 | use parse_args and keep add_help (ADR 0025: every command answers --help with its usage and changes nothing); only a two-stage pre-parser, whose rest goes to a parser that keeps --help, is excused: an [[override]] id = "stack.python-uv.cli-parse" with scope = "<file>" (or "<file>:<line>") in docs/blueprint/blueprint.toml | agent |
| ❌ | `stack.python-uv.cli-help-tested` | yes | no | no test runs dev/affected.py, dev/check_move.py, dev/dash_check.py, dev/dash_fixtures.py, dev/dash_profile.py, dev/flakes.py, dev/reach.py, dev/record_exchange.py, dev/testtimes_report.py, skills/task-loop/_vendor/any_lease/__main__.py, skills/task-loop/_vendor/shelf_vendor/__main__.py with --help (only tracked test files are read: `git add` a new one) | add a scenario per console script and per directly run script: `<script> --help` exits 0, prints its usage and changes nothing (no server started, no file written); an unknown flag exits 2 (ADR 0025) | agent |
| - | `stack.python-uv.uv-tool` | - | - | no [project.scripts] entry point: nothing is installed as a uv tool | - | - |
