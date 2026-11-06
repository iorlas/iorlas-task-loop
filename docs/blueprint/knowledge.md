# Blueprint: knowledge (Generic: any repo)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ❌ | `knowledge.glossary` | no | - | no CONTEXT.md | write CONTEXT.md: one entry per domain term, a one-line definition and _Avoid_ names | agent |
| ❌ | `knowledge.adr-format` | no | - | no ADRs in docs/adr/ | record the repo's key decisions as docs/adr/0001-slug.md; frontmatter: id (the file's NNNN), title, statement (one line, the decision), concerns [list], status (proposed/accepted/superseded/rejected), decided_by, updated (YYYY-MM-DD); body: decision on top, `## History` below | agent |
| ❌ | `knowledge.adr-index` | no | - | no ADRs, so no docs/adr/INDEX.md | record ADRs, then PYTHONPATH=<shelf>/packages/blueprint/src python3 -m blueprint adr-index --repo . --write | agent |
