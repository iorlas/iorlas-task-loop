# Rendered by `blueprint gate render` -- never edit this file; `blueprint gate render` rewrites it and `just render` fails on any difference.
# The base of this repo's gate. The repo's own `justfile` imports it and owns everything else: a recipe defined there replaces the
# one of the same name here (`set allow-duplicate-recipes`), and `check-extra` is the extension point for one more step.
#
# No backticks anywhere: `just --dry-run` evaluates them, and blueprint's gate.one-command dry-runs `check`.

# The gate: every step at once (`steps`), one timing line, a warning for a step over its budget. A green run records the tree it
# checked (any-gate), so the pre-push hook does not run it again on that tree.
[group('gate')]
check: gate-start beads-lint (steps "guard" "preset" "render" "blueprint" "secrets" "lint" "typecheck" "spell" "deps" "test") check-extra
    uv run python -m any_gate passed --gate check

# The release gate, rare (before a tag): every step over everything (all files, all history, every test, the coverage floor).
[group('gate')]
check-all: beads-lint (steps-all "guard" "preset" "render" "blueprint" "secrets-all" "lint" "typecheck" "spell" "deps" "test-all")

# Extension point: a repo defines `check-extra` in its own justfile to run one more thing in the gate (after the steps, before the record).
[private]
check-extra:
    @:

# Notes the working tree as the gate starts, for `check` to record when it passes.
[private]
gate-start:
    uv run python -m any_gate start

# Every bead still to be started (open or blocked) carries its acceptance criteria. bd's database lives in this clone.
[group('gate')]
beads-lint:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -d .beads ] || exit 0
    command -v bd >/dev/null || { echo "beads-lint: bd is not installed -- run just tools" >&2; exit 2; }
    # A clone with no (or an uninitialized) database lints 0 beads and exits 0; that is no pass.
    if ! out=$(BD_DISABLE_METRICS=1 bd list --limit 1 --json 2>&1); then
        echo "beads-lint: bd's database does not answer in this clone -- run bd bootstrap" >&2
        exit 1
    fi
    rc=0
    for status in open blocked; do BD_DISABLE_METRICS=1 bd lint --status "$status" || rc=1; done
    exit "$rc"

# Runs the gate's steps at once (`any-gate steps`): each into its own log, then one timing line and the log of every step that
# failed. Each name is a recipe, so the gate graph still reads the edges. Budgets, in seconds: GATE_STEP_BUDGET (default 60) per
# step, GATE_BUDGET (default 180) for the whole gate.
[private]
steps +names:
    uv run python -m any_gate steps --runner {{ just_executable() }} {{ names }}

# `steps` for the release gate: every step runs, whatever changed (a step otherwise skips when `gate-inputs.toml` says its inputs did not change).
[private]
steps-all +names:
    uv run python -m any_gate steps --all --runner {{ just_executable() }} {{ names }}

# The blueprint's per-commit checkpoints: one line per one that is not passing.
[group('gate')]
blueprint:
    uv run blueprint check --repo . --brief

# Secrets in the code this branch changed: gitleaks (pinned in mise.toml) over the commits since the upstream merge-base plus the staged,
# unstaged and untracked work. The commit hook scans only the index and a hook can be skipped; this is the enforcement.
[group('gate')]
secrets:
    uv run python -m blueprint.secret_scan range

# The same over all history: for a release gate, never per commit.
[group('gate')]
secrets-all:
    uv run python -m blueprint.secret_scan full

# The commit guard as a gate, not only a hook: a hook is per-clone and silently disabled by anything that claims core.hooksPath.
# Reads HEAD (an uncommitted local override is the supported co-development workflow). Exit 2 means it could not run: never a pass.
[group('gate')]
guard:
    uv run blueprint gate guard --committed

# The linter preset: fails on a difference from the blueprint's snapshot that the repo has not declared in [tool.shelf-preset].
[group('gate')]
preset:
    uv run blueprint gate preset --repo .

# This base and the stack parts equal what `blueprint gate render` writes now, and the justfile imports them.
[group('gate')]
render:
    uv run blueprint gate render --repo . --check

# The pinned tools (mise.toml, locked by mise.lock). The user's own config is left out: its unlocked tools would make `--locked` refuse.
tools:
    mise trust --yes .
    MISE_IGNORED_CONFIG_PATHS="$HOME/.config/mise" mise install --locked
