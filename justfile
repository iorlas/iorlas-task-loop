# The foundation has one behavior slice; both test folders are affected by its build boundary.
test: prepare
    uv run --frozen --no-sync python -I -m pytest -q tests/cli tests/rules

# Rebuild the current project on every gate; never use an editable install or PYTHONPATH.
prepare:
    uv sync --frozen --no-editable --reinstall-package iorlas-task-loop

check: prepare lint types rules

lint:
    uv tool run "ruff@$(just pin ruff)" check src tests

types:
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" check

rules:
    uv run --frozen --no-sync --with "import-linter==$(just pin pipx:import-linter)" lint-imports --no-cache

[private]
pin tool:
    @python3 -c "import pathlib, sys, tomllib; print(tomllib.loads(pathlib.Path('mise.toml').read_text())['tools'][sys.argv[1]])" {{tool}}
