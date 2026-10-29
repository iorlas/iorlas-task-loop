# just test <feature>: run only that feature's tests (see tests/feature_tests.py); no argument = the whole suite
test feature="":
    python3 tests/feature_tests.py {{feature}}

# Install the exact tool versions recorded in mise.lock.
tools:
    MISE_IGNORED_CONFIG_PATHS=$HOME/.config/mise mise install --locked

# The gate: ruff + pyrefly + the structural rules test (caps, layers, placement, ratchets). Seconds, not the 35-minute suite.
check: lint types rules

# check plus the whole unittest suite (what CI runs across its shards).
check-all: check
    python3 -m unittest discover -s tests

lint:
    #!/usr/bin/env bash
    set -euo pipefail
    uv tool run "ruff@$(just pin ruff)" check

types:
    #!/usr/bin/env bash
    set -euo pipefail
    uv tool run "pyrefly@$(just pin pipx:pyrefly)" check

rules:
    python3 -m unittest tests.gate_rules

# The version mise.toml pins for a tool (one source for the pins).
[private]
pin tool:
    @python3 -c "import sys, tomllib; print(tomllib.load(open('mise.toml', 'rb'))['tools'][sys.argv[1]])" {{tool}}
