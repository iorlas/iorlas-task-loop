# Blueprint

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| layer | concern | ✅ | ❌ | ⚠️ | 🔒 | first to fix |
|---|---|---|---|---|---|---|
| Generic: any repo | gate | 4 | 1 | 4 | 0 | `gate.ci`: no .github/workflows/*.yml; unmerged remote branch(es) hold gate files… |
|  | backlog | 6 | 2 | 0 | 0 | `backlog.strict-config`: create.require-description=false (want true); validation.metadata.mode unset (want error) |
|  | knowledge | 0 | 3 | 0 | 0 | `knowledge.glossary`: no CONTEXT.md |
|  | secrets | 0 | 0 | 0 | 0 | - |
| Stack-specific | stack/python-uv | 7 | 13 | 0 | 0 | `stack.python-uv.toolchain`: uv, with a committed lockfile and a declared Python range set up, but the gate never… |
|  | stack | 0 | 2 | 0 | 0 | `stack.tool-pins`: import-linter '2.15' is not an exact version |
| Agent harness | agents | 0 | 7 | 1 | 0 | `agents.instructions`: CLAUDE.md is a second instructions file: 32 lines only in CLAUDE.md, 61 lines only in… |
