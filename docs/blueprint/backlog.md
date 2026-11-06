# Blueprint: backlog (Generic: any repo)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ✅ | `backlog.tracker` | yes | yes | beads initialised (.beads/config.yaml) | - | - |
| ❌ | `backlog.strict-config` | yes | no | create.require-description=false (want true); validation.metadata.mode unset (want error) | edit .beads/config.yaml directly (a dotted key is nested YAML, `import.auto` is `import:` then `  auto: false`): create.require-description: true; validation.metadata.mode: error; not `bd config set`, which writes bd's database; unset any BD_*/BEADS_* override, then confirm `bd config show --json` lists each with "source": "config.yaml"; in a git worktree bd reads the main checkout's .beads/config.yaml (`bd where`): the row passes once this branch merges | agent |
| ✅ | `backlog.lock-ignored` | yes | yes | .beads.gate.lock is git-ignored | - | - |
| ✅ | `backlog.no-tracked-export` | yes | yes | no JSONL under .beads is tracked | - | - |
| ✅ | `backlog.no-local-override` | yes | yes | no local file or session env overrides bd | - | - |
| ❌ | `backlog.lint` | yes | no | 2 beads miss sections: Acceptance Criteria x1, Success Criteria x1; first: tl-bxk, tl-ja8t | add the missing sections (acceptance criteria, description) to each bead named | agent |
| ✅ | `backlog.no-tracker-file` | yes | yes | beads is the only backlog | - | - |
| ✅ | `backlog.hooks-spare-beads` | yes | yes | no end-of-file-fixer reaches .beads/ | - | - |
