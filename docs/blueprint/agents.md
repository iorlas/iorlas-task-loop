# Blueprint: agents (Agent harness)

Written by `blueprint check --write` on 2026-11-06; rewritten on every run.

kind: application · stacks: python-uv (from pyproject.toml, uv.lock) · surfaces: - · traits: - · tracker: beads · checkpoint set: `e93599a25bdc`

engine: shelf `76f31d6cd` · blueprint 0.1.0

concerns checked: stack, gate, backlog, knowledge, secrets, agents · not run: framework · audit-only checkpoints included

## Overrides

none

| | checkpoint | set up | working | evidence | remediation | fixed by |
|---|---|---|---|---|---|---|
| ❌ | `agents.instructions` | yes | no | CLAUDE.md is a second instructions file: 32 lines only in CLAUDE.md, 61 lines only in AGENTS.md, so agents reading one get different rules than agents reading the other | move what only CLAUDE.md holds into AGENTS.md (`diff AGENTS.md CLAUDE.md`), then `ln -sf AGENTS.md CLAUDE.md` | agent |
| ❌ | `agents.bd-metrics-off` | no | - | BD_DISABLE_METRICS is not "1" in .claude/settings.json env | add "env": {"BD_DISABLE_METRICS": "1"} | auto |
| ❌ | `agents.session-hooks` | no | - | missing a Stop hook listing beads left in_progress, so no session ends with work silently open | copy both hooks from the shelf's .claude/settings.json | auto |
| ❌ | `agents.pocock-skills` | yes | no | no extraKnownMarketplaces.mattpocock from github mattpocock/skills; enabledPlugins["mattpocock-skills@mattpocock"] is not true in .claude/settings.json | claude plugin marketplace add mattpocock/skills --scope project && claude plugin install mattpocock-skills@mattpocock --scope project (writes .claude/settings.json; commit it) | agent |
| ❌ | `agents.worktrees` | no | - | not ignored by a .gitignore in the repo (.git/info/exclude and the global excludes do not count): .claude/worktrees/ | printf '.claude/worktrees/\n' >> .gitignore | auto |
| ⚠️ | `agents.worktrees-in-sync` | yes | no | foreign-repo-push: work unmerged since 25h ago; hardening/bypass: work unmerged since 25h ago; hardening/execallow: work unmerged since 27h ago; hardening/hooktl: work unmerged since 25h ago; claude/lockout: work unmerged since 25h ago; claude/jolly-dhawan-700632: work unmerged since 24h ago; pr61: work unmerged since 24h ago | each named worktree belongs to a session; ask the one working there to land its work into main or take main's changes, and remove worktrees whose work is done | owner |
| ❌ | `agents.culture-files` | no | - | missing docs/agents/: constitution.md, working-with-agents.md, gate.md, testing.md, architecture.md, domain.md, issue-tracker.md, python.md | PYTHONPATH=<shelf>/packages/blueprint/src python3 -m blueprint template --repo . | auto |
| ❌ | `agents.managed-block` | no | - | AGENTS.md has no blueprint block | PYTHONPATH=<shelf>/packages/blueprint/src python3 -m blueprint template --repo . | auto |
