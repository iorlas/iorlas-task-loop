# Blueprint: gate (Generic: any repo)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ✅ | `gate.one-command` | yes | yes | `just --dry-run check` resolves | - | - |
| ✅ | `gate.runner` | yes | yes | a justfile holds the gate | - | - |
| ⚠️ | `gate.ci` | no | - | no .github/workflows/*.yml; unmerged remote branch(es) hold gate files: origin/claude/recursing-proskuriakova-2dc97e changes justfile; origin/claude/runtests-load changes justfile; origin/claude/shelf-failure-fp changes justfile; origin/claude/shelfmoves-4e4cfe changes justfile; origin/delegatehome-pins changes justfile; origin/release/A1 changes .github/workflows/test.yml, justfile; origin/tests/under-2s changes justfile; origin/testspeed/pr8-testmon changes justfile | do not build a parallel gate: the owner decides whether to merge that branch or remediate on main (the branch is not judged here). Without the branch: add a workflow that runs `uv run just check-all` (or `just check`) on push and pull request; a repo that decided on no CI records an override of gate.ci with its reason and `adr = "NNNN"` (the accepted ADR that decided it) | owner |
| - | `gate.ci-no-manifest-edit` | - | - | no .github/workflows: gate.ci reports the missing CI | - | - |
| ⚠️ | `gate.hooks-recipe` | yes | no | bd's own hook files are tracked (5): git rm -r --cached .beads/hooks; bd events not run from .pre-commit-config.yaml: pre-commit, post-merge, pre-push, post-checkout, prepare-commit-msg; no default_install_hook_types, so `prek install` installs pre-commit only; no pre-push hook runs `just check`, so a push skips the gate (the recipe's `gate` hook); unmerged remote branch(es) hold gate files: origin/claude/recursing-proskuriakova-2dc97e changes justfile; origin/claude/runtests-load changes justfile; origin/claude/shelf-failure-fp changes justfile; origin/claude/shelfmoves-4e4cfe changes justfile; origin/delegatehome-pins changes justfile; origin/release/A1 changes .github/workflows/test.yml, justfile; origin/tests/under-2s changes justfile; origin/testspeed/pr8-testmon changes justfile | do not build a parallel gate: the owner decides whether to merge that branch or remediate on main (the branch is not judged here). Without the branch: merge the recipe into the existing .pre-commit-config.yaml, never overwrite it: `default_install_hook_types` at the top, the recipe's bd `repo: local` block first under `repos:`, and keep every hook the repo already has after it (`python3 -m blueprint recipe hooks` prints the recipe); then `prek install` | owner |
| ❌ | `gate.hooks-installed` | no | - | no pre-commit hook installed | prek install | auto |
| ⚠️ | `gate.runs-blueprint` | no | - | `just check` never runs blueprint; unmerged remote branch(es) hold gate files: origin/claude/recursing-proskuriakova-2dc97e changes justfile; origin/claude/runtests-load changes justfile; origin/claude/shelf-failure-fp changes justfile; origin/claude/shelfmoves-4e4cfe changes justfile; origin/delegatehome-pins changes justfile; origin/release/A1 changes .github/workflows/test.yml, justfile; origin/tests/under-2s changes justfile; origin/testspeed/pr8-testmon changes justfile | do not build a parallel gate: the owner decides whether to merge that branch or remediate on main (the branch is not judged here). Without the branch: copy the shelf's `blueprint` recipe into the justfile and add it to `check` (`just bootstrap` does both) | owner |
| - | `gate.guards-have-red-tests` | - | - | `just check` runs no repo-local Python script | - | - |
| ⚠️ | `gate.clean-clone` | yes | no | fresh-clone step `mise install --locked` failed: mise ERROR Run with --verbose or MISE_VERBOSE=1 for more information; unmerged remote branch(es) hold gate files: origin/claude/recursing-proskuriakova-2dc97e changes justfile; origin/claude/runtests-load changes justfile; origin/claude/shelf-failure-fp changes justfile; origin/claude/shelfmoves-4e4cfe changes justfile; origin/delegatehome-pins changes justfile; origin/release/A1 changes .github/workflows/test.yml, justfile; origin/tests/under-2s changes justfile; origin/testspeed/pr8-testmon changes justfile | do not build a parallel gate: the owner decides whether to merge that branch or remediate on main (the branch is not judged here). Without the branch: make the documented after-clone steps work on a new clone | owner |
| - | `gate.checkers-wired` | - | - | no check_*/lint_* script under tools/ or scripts/ | - | - |
| ✅ | `gate.default-branch` | yes | yes | the default branch is main | - | - |
| ✅ | `gate.git-remote` | yes | yes | origin: git@github.com:iorlas/iorlas-task-loop.git | - | - |
| - | `gate.ci-green` | - | - | no GitHub Actions workflows | - | - |
| - | `gate.lfs-binaries` | - | - | the repo declares no LFS pattern (.gitattributes has no filter=lfs) | - | - |
| - | `gate.git-config-clean` | - | - | not the main checkout of a non-bare clone (a linked worktree or no git repository) | - | - |
| - | `gate.lfs-installed` | - | - | the repo declares no LFS pattern (.gitattributes has no filter=lfs) | - | - |
