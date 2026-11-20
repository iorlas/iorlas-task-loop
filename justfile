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

# This repo's own lint: ruff check only. `ruff format --check` has never run here and would rewrite most files at once, under
# every other branch in flight, so the owner schedules that one commit; until then format is not a gate (see the PR).
lint:
    uv run ruff check .

# The architecture contracts (.importlinter).
rules:
    uv run --no-sync lint-imports --no-cache

# Verify successful, bounded probes using the installed project's interpreter.
tool-versions:
    #!/usr/bin/env -S uv run --frozen --no-sync python -I
    import runpy
    import subprocess
    import sys

    arguments = []
    for tool, command in (
        ("git", ["git", "--version"]),
        ("codex", ["codex", "--version"]),
        ("python", [sys.executable, "--version"]),
        ("tailwind", ["tailwindcss", "--help"]),
    ):
        try:
            result = subprocess.run(command, check=True, timeout=10, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = result.stdout
        except (OSError, subprocess.SubprocessError) as error:
            output = f"probe failed: {error}"
        arguments.extend((f"--{tool}", output))
    sys.argv = ["tools/check_tool_versions.py", *arguments]
    runpy.run_path(sys.argv[0], run_name="__main__")

# This repo's own steps of the gate, after the kit's: the architecture contracts and the external-tool pins.
[private]
check-extra: rules tool-versions

# Compile the dashboard stylesheet with the standalone Tailwind CLI pinned in mise.toml;
# see docs/design/dashboard-ui.md. The compiled dash.css is committed, so running the page never needs it.
css: tool-versions
    tailwindcss -i src/taskloop/dash/static/dash.input.css -o src/taskloop/dash/static/dash.css --minify

# The coverage floor, a regression backstop (the gate's `test` step is selection-based and measures none).
cov:
    uv run --no-sync pytest --cov --cov-fail-under=65 tests/cli tests/steps tests/rules
