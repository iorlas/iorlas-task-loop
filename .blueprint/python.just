# Rendered by `blueprint render` -- never edit; a recipe of the same name in the repo's justfile replaces it.
# The python+uv stack: its linter, type, spelling, dependency and test steps.

[group('gate')]
lint:
    uv run ruff check .
    uv run ruff format --check .

format:
    uv run ruff format .

# A type warning fails the build (pyrefly's config). No slow rot.
[group('gate')]
typecheck:
    uv run pyrefly check

# Typos in code, docstrings and docs.
[group('gate')]
spell:
    uv run codespell

# Dependency hygiene: the lockfile matches pyproject, then unused, missing and transitive (deptry), once per package in a workspace.
[group('gate')]
deps:
    #!/usr/bin/env bash
    set -euo pipefail
    env -u UV_FROZEN uv lock --check
    if [ -d packages ]; then
        printf '%s\n' packages/*/ | xargs -P "$(getconf _NPROCESSORS_ONLN)" -I{} bash -c \
            'p={}; imp=$(ls "$p/src"); out=$(cd "$p" && uv run deptry . --known-first-party "$imp" 2>&1) || { printf -- "-- deptry %s\n%s\n" "$p" "$out"; exit 1; }'
    else
        uv run deptry .
    fi

# The tests the change reaches, through any-gate (`blueprint test`): suites that already passed on this input are skipped, the rest
# queue for one test slot. No coverage floor: it is a whole-repo measure.
[group('gate')]
test:
    uv run blueprint test

# Coverage report only (human view).
cov:
    uv run pytest --cov --cov-report=term-missing

sync:
    uv sync
