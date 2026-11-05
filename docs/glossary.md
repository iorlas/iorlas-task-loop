# Glossary

One canonical name per concept. A word in the "never" column is not used for that concept in code, docs, beads or chat.
`planned` = decided, not yet in code (the rename is a hard cut, no alias, filed as beads; see docs/design/topology.md).

| Term | Means | Never |
|---|---|---|
| piece | A segregated unit: own folder or repo, own tests, one written interface, contract tests on both sides, no imports across. task-loop, delegate, lifesim and each shelf package are pieces. | module, component |
| factory | The machine's task-loop installation: one config folder, one `factory.db`, one dashboard, one lease table, many repos. | instance (per repo), server |
| loop | One process that takes one bead at a time into a free slot for one repo. A repo runs up to its wanted count of loops (`tl factory start` tops up to it); the machine has one dashboard. What `factory-lane-K.log` and "LANES running=" call a lane is a loop. | lane, worker, daemon |
| repo | A registered git repository with its own backlog (`.beads/`) and profile, known by its canonical name (origin `owner/name`; folder name when there is no remote). One home clone per machine; extra worktrees are slots. | project, clone (as an identity) |
| profile | `.task-loop.json` as committed on the base branch: the repo's rules for the engine. | config (that is machine-level) |
| bead | One task in a repo's bd store. | ticket, issue (in task-loop docs) |
| slot | A persistent worktree set up once and reused task after task; its count is the repo's own concurrency. | floor, workspace |
| run | One engine pass over one bead, stage by stage. | job |
| stage / gate / land | A step of the engine (plan, write, review, ...) / the checks that must be green at land / the push or merge to the base branch. | |
| ask | A question the engine parks a bead on until the owner answers. | prompt |
| owner | Denis. Merge approval, profile-change approval and `owner-approved` are his. | user, admin |
| worker | One headless model call, made through the `delegate.api` library. | agent (ambiguous) |
| role | The kind of worker job delegate routes (planner, reviewer, worker, hard, light). | persona |
| account `planned` | A metered connection to a model vendor: a subscription or API key with usage windows, reset times and models. Delegate owns it. Dashboard panel: Accounts. | lane, license, supplier, provider, token source |
| track `planned` | Within one gate block, a parallel sequence of checks; the first red cancels the other tracks. Replaces the `lane` key on checks. | lane |
| lane | Purged. The word names no concept; use account, track or loop. | everything |
| resource | A scarce machine tool a check declares it needs (`unity`); its limit is in the profile. | |
| lease | One held unit of a resource, in the machine's lease table; freed when the holder dies. | lock (a lock is a mutex on one thing; a lease counts units) |
| executor `planned` | The machine side of a split factory: process spawn, slots, leases, `host.json`. Today the factory and executor are the same machine. | node, agent |
| trust root | The files whose change parks a bead unless it carries `owner-approved` (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `mise.toml`, `.codex/`, `.task-loop.json`, `githooks/`). | |

## Rename plan (hard cut, one bead each)

0. Purge: the word "lane" leaves code, docs, tests, dashboard and the delegate copy in one cut (no alias). Three meanings, three names: delegate lane -> account; check lane -> track; factory lane (a loop process) -> loop. Occurrence counts come from the naming audit (docs/design/naming-audit.md).
1. Delegate: `lane` becomes `account` in routing.json, `route.py status`/`run` output, docs, skills. The interface is the typed `delegate.api` (docs/design/topology.md), so there is no wire contract to version. 122 files in task-loop mention "lane" today, so the task-loop side is the larger edit.
2. Dashboard: the "Lanes" panel becomes "Accounts"; "floor" does not appear.
3. `tl lanes` becomes `tl accounts`; `tl setup` stops asking about lanes; `checks[].lane` becomes `track` (profile key: a hard cut, shipped one release after the code that reads it, per CLAUDE.md); `tl factory status` prints loops, not lanes.
