# Glossary

One canonical name per concept. A word in the "never" column is not used for that concept in code, docs, beads or chat.
`planned` = decided, not yet in code (the rename is a hard cut, no alias, filed as beads; see docs/design/topology.md).

| Term | Means | Never |
|---|---|---|
| piece | A segregated unit: own folder or repo, own tests, one written interface, contract tests on both sides, no imports across. task-loop, delegate, lifesim and each shelf package are pieces. | module, component |
| factory | The machine's task-loop installation: one config folder, one `factory.db`, one dashboard, one lease table, many repos. | instance (per repo), server |
| loop | One process that picks and runs beads for one repo. | worker, daemon |
| repo | A registered git repository with its own backlog (`.beads/`) and profile. | project |
| profile | `.task-loop.json` as committed on the base branch: the repo's rules for the engine. | config (that is machine-level) |
| bead | One task in a repo's bd store. | ticket, issue (in task-loop docs) |
| slot | A persistent worktree set up once and reused task after task; its count is the repo's own concurrency. | floor, workspace |
| run | One engine pass over one bead, stage by stage. | job |
| stage / gate / land | A step of the engine (plan, write, review, ...) / the checks that must be green at land / the push or merge to the base branch. | |
| ask | A question the engine parks a bead on until the owner answers. | prompt |
| owner | Denis. Merge approval, profile-change approval and `owner-approved` are his. | user, admin |
| worker | One headless model call, made through delegate. | agent (ambiguous) |
| role | The kind of worker job delegate routes (planner, reviewer, worker, hard, light). | persona |
| account `planned` | A metered connection to a model vendor: a subscription or API key with usage windows, reset times and models. Delegate owns it. | lane (delegate), license, supplier, provider, token source |
| lane | Within one gate block, a parallel sequence of checks; the first red cancels the other lanes. After the account rename this is its only meaning. | a delegate vendor connection, a dashboard swim lane |
| resource | A scarce machine tool a check declares it needs (`unity`); its limit is in the profile. | |
| lease | One held unit of a resource, in the machine's lease table; freed when the holder dies. | lock (a lock is a mutex on one thing; a lease counts units) |
| executor `planned` | The machine side of a split factory: process spawn, slots, leases, `host.json`. Today the factory and executor are the same machine. | node, agent |
| trust root | The files whose change parks a bead unless it carries `owner-approved` (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `mise.toml`, `.codex/`, `.task-loop.json`, `githooks/`). | |

## Rename plan (hard cut, one bead each)

1. Delegate: `lane` becomes `account` in routing.json, `route.py status`/`run` output, docs, skills. Worker-run contract gets a new major version. 122 files in task-loop mention "lane" today, so the task-loop side is the larger edit.
2. Dashboard: the "Lanes" panel becomes "Accounts"; "floor" does not appear.
3. `tl lanes` becomes `tl accounts`; `tl setup` stops asking about lanes.
