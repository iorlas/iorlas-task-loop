# Blueprint: stack (Stack-specific)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ❌ | `stack.tool-pins` | yes | no | import-linter '2.15' is not an exact version | fix each pin in mise.toml, then `mise lock` and commit both (ADR 0024) | agent |
| ❌ | `stack.tools-installed` | yes | no | just 1.51.0 (pin 1.58.0); prek is not installed; uv 0.11.21 (pin 0.13.0) on this machine's PATH | run `just tools` (mise install --locked), then put mise first on PATH: `eval "$(mise activate zsh)"` (or bash) in the shell's rc file, or prepend ~/.local/share/mise/shims; a brew or system copy earlier on PATH wins otherwise | agent |
