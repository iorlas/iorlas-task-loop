# The gate is `just gate` = `just check` (static: ruff, pyrefly, import-linter) then `just test` (the tests). The suite receipt (RunKey) is written only after both.
# `uv run pytest <path>` is the inner loop while you edit, not a gate.
# TL_TEST_FULL: the landing gate keeps the cores; a lane's plain `just test` runs at nice 10 in as many workers as the load leaves free (dev/runtests.py).
gate: check
    TL_TEST_FULL=1 uv run python dev/runtests.py

# The tests this change can break (dev/affected.py picks them from the diff against origin/main; tests/rules always; all kinds, one run). Each test runs once per tree.
test:
    uv run python dev/runtests.py

# INNER LOOP ONLY, never the gate: pytest-testmon reruns what the code you edited reaches in the paths you name (docs/dev/test-inner-loop.md). It follows Python imports, not
# config or data files, so a green run here proves nothing about those: `just test` (dev/affected.py) is the gate. First run per path builds .testmondata.
test-inner +paths:
    uv run --with pytest-testmon pytest --testmon -o addopts="-p no:cacheprovider" --ignore=tests/e2e --ignore=tests/delegate --ignore=tests/live {{paths}}

# Every test of every kind, in 4 workers then the serial group. Started by a person, never by the gate, the release, a cron or a background job.
test-full:
    uv run pytest -m "not serial" -n 4
    uv run pytest -m serial

# just test-live [pytest args]: the explicit-only scenarios of tests/live (real git remote, real processes, real tl and dashboard); no default run collects them
test-live *args:
    uv run pytest -m live -s tests/live {{args}}

# The delegate tests (tests/delegate; real processes, several minutes). No other run collects them unless the change touches src/delegate, tests/delegate or the vendored packages (tests/support/scope.py).
test-delegate *args:
    TL_DELEGATE_TESTS=1 uv run pytest -m "" tests/delegate {{args}}

# Install the exact tool versions recorded in mise.lock.
tools:
    MISE_IGNORED_CONFIG_PATHS=$HOME/.config/mise mise install --locked

# Static gate: ruff + pyrefly + import-linter contracts. Seconds. The structural rules (caps, placement, ratchets) are tests/rules, run by `just test`.
check: lint types rules

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
