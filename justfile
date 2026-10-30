# just test [pytest args]: the suite through pytest, one process; `just test tests/land -q` runs a folder, `just test -n auto` spreads it
test *args:
    uv run pytest {{args}}

# just test-live [pytest args]: the explicit-only scenarios of tests/live (real git remote, real processes, real tl and dashboard, docker when it answers); no default run collects them
test-live *args:
    uv run pytest -m live -s tests/live {{args}}

# Install the exact tool versions recorded in mise.lock.
tools:
    MISE_IGNORED_CONFIG_PATHS=$HOME/.config/mise mise install --locked

# The gate: ruff + pyrefly + the structural rules (import-linter contracts, then caps, placement, ratchets). Seconds, not the 35-minute suite.
check: lint types rules

# check plus the whole suite as a release runs it: xdist workers, then the serial group alone.
check-all: check
    python3 dev/suite.py

lint:
    #!/usr/bin/env bash
    set -euo pipefail
    uv tool run "ruff@$(just pin ruff)" check

types:
    #!/usr/bin/env bash
    set -euo pipefail
    unset VIRTUAL_ENV  # a caller under `uv run --script` (release.py) passes its script env, which has no dev group
    uv sync --frozen -q  # pyrefly resolves pytest and the dev group from .venv; a fresh clone has none
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" check

rules:
    #!/usr/bin/env bash
    set -euo pipefail
    # --with msgspec: .importlinter names msgspec as a root package (the hook contract), and grimp must find it
    PYTHONPATH=src uv tool run --with msgspec --from "import-linter@$(just pin pipx:import-linter)" lint-imports
    uv run pytest tests/gate_rules.py -q

# The version mise.toml pins for a tool (one source for the pins).
[private]
pin tool:
    @python3 -c "import sys, tomllib; print(tomllib.load(open('mise.toml', 'rb'))['tools'][sys.argv[1]])" {{tool}}
