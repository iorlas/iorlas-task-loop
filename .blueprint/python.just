# Rendered by `blueprint gate render` -- never edit; a recipe of the same name in the repo's justfile replaces it only through a declared override (gate.recipe-shadowing).
# The python+uv stack: its linter, type, spelling, dependency and test steps.

# `lint` over the files changed against the base (any-gate changed), for `check`; check-all runs `lint` over everything.
[group('gate')]
lint-changed:
    uv run blueprint gate lint --changed

format:
    uv run blueprint gate format

# A type warning fails the build (pyrefly's config). No slow rot.
[group('gate')]
typecheck:
    uv run pyrefly check

# `spell` over the files changed against the base, for `check`.
[group('gate')]
spell-changed:
    uv run blueprint gate spell --changed

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

# The tests the change reaches, through any-gate (`blueprint gate test`): suites that already passed on this input are skipped, the rest
# queue for one test slot. Declared test units combine cached coverage before enforcing their whole-repo floor.
[group('gate')]
test:
    uv run blueprint gate test

# Coverage report only (human view).
cov:
    uv run pytest --cov --cov-report=term-missing

sync:
    uv sync
