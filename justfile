set allow-duplicate-recipes
import '.blueprint/base.just'
import '.blueprint/python.just'

# `uv run` must neither re-sync an editable project nor touch the lockfile: the successor runs as an installed wheel
# (`install` below), and a gate step that resolved anything would hide a drifting lock.
export UV_FROZEN := "1"
export UV_NO_EDITABLE := "1"

# Rebuild the current project on every gate; never use an editable install or PYTHONPATH.
install:
    uv sync --no-editable --reinstall-package iorlas-task-loop

# Prepare a slot: the project environment with every pinned check tool (the factory's `setup`).
bootstrap: install

# This repo's own lint: ruff check only. `ruff format --check` has never run here and would rewrite 163 of 210 files at once, under
# every other branch in flight, so the owner schedules that one commit; until then format is not a gate (see the PR).
lint:
    uv run ruff check .

# The architecture contracts (.importlinter): the one step of this repo's gate the kit does not own.
rules:
    uv run --no-sync lint-imports --no-cache

[private]
check-extra: rules

# Compile the dashboard stylesheet with the standalone Tailwind CLI (v4.1.11, not an npm or Python dependency;
# see docs/design/dashboard-ui.md). The compiled dash.css is committed, so running the page never needs it.
css:
    tailwindcss -i src/taskloop/dash/static/dash.input.css -o src/taskloop/dash/static/dash.css --minify

# The coverage floor, a regression backstop (the gate's `test` step is selection-based and measures none).
cov:
    uv run --no-sync pytest --cov --cov-fail-under=65 tests/cli tests/steps tests/rules
