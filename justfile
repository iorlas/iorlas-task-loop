# just test [pytest args]: the logic kind, in one process (pyproject addopts skip the real and e2e kinds); `just test tests/land -q` runs a folder, `just test -n auto` spreads it
test *args:
    uv run pytest {{args}}

# just test-live [pytest args]: the explicit-only scenarios of tests/live (real git remote, real processes, real tl and dashboard); no default run collects them
test-live *args:
    uv run pytest -m live -s tests/live {{args}}

# The inner loop: logic tests only (fakes, in process, under 200 ms each). `just test-fast tests/land -q`, `just test-fast -n auto`.
test-fast *args:
    uv run pytest -m "not real and not e2e" {{args}}

# Every kind (logic, real, e2e) in one process; `just test-all -n auto` spreads it. A release runs them all through dev/suite.py.
test-all *args:
    uv run pytest -m "" {{args}}

# The delegate tests (tests/delegate; real processes, several minutes). No other run collects them unless the change touches src/delegate, tests/delegate or the vendored packages (tests/support/scope.py).
test-delegate *args:
    TL_DELEGATE_TESTS=1 uv run pytest -m "" tests/delegate {{args}}

# Install the exact tool versions recorded in mise.lock.
tools:
    MISE_IGNORED_CONFIG_PATHS=$HOME/.config/mise mise install --locked

# The gate: ruff + pyrefly + the structural rules (import-linter contracts, then caps, placement, ratchets). Seconds, not the 35-minute suite.
check: lint types rules

# check plus the whole suite as a release runs it: xdist workers, then the serial group alone.
check-all: check
    python3 dev/suite.py

# lint and types look only at the .py files this change touches (against origin/main, plus the working tree); lint-all and types-all read the whole tree.
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    files=$(just changed)
    [ -z "$files" ] || echo "$files" | xargs uv tool run "ruff@$(just pin ruff)" check

lint-all:
    #!/usr/bin/env bash
    set -euo pipefail
    uv tool run "ruff@$(just pin ruff)" check

types:
    #!/usr/bin/env bash
    set -euo pipefail
    files=$(just changed)
    [ -z "$files" ] || { unset VIRTUAL_ENV; uv sync --frozen -q; echo "$files" | xargs uv tool run "pyrefly@$(just pin pipx:pyrefly)" check; }

types-all:
    #!/usr/bin/env bash
    set -euo pipefail
    unset VIRTUAL_ENV  # a caller under `uv run --script` (release.py) passes its script env, which has no dev group
    uv sync --frozen -q  # pyrefly resolves pytest and the dev group from .venv; a fresh clone has none
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" check

rules:
    #!/usr/bin/env bash
    set -euo pipefail
    # skills/task-loop/_vendor: .importlinter names stream_proc (the vendored process library) as a root package, so grimp must find it
    # --with msgspec: .importlinter names msgspec as a root package (the hook contract), and grimp must find it
    PYTHONPATH=src:skills/task-loop/_vendor uv tool run --with msgspec --from "import-linter@$(just pin pipx:import-linter)" lint-imports
    uv run pytest tests/rules/gate_rules.py tests/rules -q -m ""  # every invariant and ratchet runs in the gate

# The .py files this change touches: committed since origin/main, edited, or new; deleted ones, the vendored copy and fixtures left out.
[private]
changed:
    #!/usr/bin/env bash
    set -euo pipefail
    { git diff --name-only --diff-filter=d origin/main...HEAD; git diff --name-only --diff-filter=d HEAD; git ls-files --others --exclude-standard; } | sort -u | grep '\.py$' | grep -v '/_vendor/' | grep -v '^tests/fixtures/' || true

# The version mise.toml pins for a tool (one source for the pins).
[private]
pin tool:
    @python3 -c "import sys, tomllib; print(tomllib.load(open('mise.toml', 'rb'))['tools'][sys.argv[1]])" {{tool}}
