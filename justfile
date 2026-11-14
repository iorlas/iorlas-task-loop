# Focused implemented CLI, admitted-plan body and successor isolation contracts.
test: install tool-versions
    uv run --frozen --no-sync python -I -m pytest -q tests/cli tests/steps tests/rules

# Rebuild the current project on every gate; never use an editable install or PYTHONPATH.
install:
    uv sync --frozen --no-editable --reinstall-package iorlas-task-loop

# Prepare a slot: the project environment and every pinned check tool in the uv cache (the factory's `setup`).
bootstrap: install
    uv tool run "ruff@$(just pin ruff)" --version
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" --version
    uv run --frozen --no-sync --with "import-linter==$(just pin pipx:import-linter)" lint-imports --help

check: install lint types rules

lint: tool-versions
    uv tool run "ruff@$(just pin ruff)" check src tests tools

types:
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" check

rules:
    uv run --frozen --no-sync --with "import-linter==$(just pin pipx:import-linter)" lint-imports --no-cache

[private]
pin tool:
    @python3 -c "import pathlib, sys, tomllib; print(tomllib.loads(pathlib.Path('mise.toml').read_text())['tools'][sys.argv[1]])" {{tool}}

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

# Compile the dashboard stylesheet with the standalone Tailwind CLI pinned in mise.toml;
# see docs/design/dashboard-ui.md. The compiled dash.css is committed, so running the page never needs it.
css: tool-versions
    tailwindcss -i src/taskloop/dash/static/dash.input.css -o src/taskloop/dash/static/dash.css --minify
