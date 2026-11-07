# Glossary

One canonical name per concept. A word in the "Not" column is not used for that concept in code, docs, beads or chat.
`planned` = decided, not yet in code (the rename is a hard cut, no alias, filed as beads; see docs/design/topology.md).
Each entry: one plain sentence, an example, and what it is not. Last audited against code and docs: 2026-11-07.

## Work and repos

| Term | Means | Example | Not |
|---|---|---|---|
| piece | A segregated unit: own folder or repo, own tests, one written interface, contract tests on both sides, no imports across. | task-loop, delegate, lifesim and each shelf package are pieces. | module, component |
| factory | The machine's task-loop installation: one config folder, one `factory.db`, one dashboard, one lease table, many repos. | `tl factory start` brings up the loops and the dashboard of the whole machine. | instance (per repo), server |
| repo | A registered git repository with its own backlog (`.beads/`) and profile, known by its canonical name (origin `owner/name`; folder name when there is no remote). One home clone per machine; extra worktrees are slots. | `iorlas/iorlas-task-loop`. | project, clone (as an identity) |
| profile | `.task-loop.json` as committed on the base branch: the repo's rules for the engine (checks, land mode, limits). | The `checks` list and `land_mode` live in the profile. | config (that is machine-level, in `~/.config/task-loop`) |
| bead | One task in a repo's bd store. `planned`: it becomes "task" everywhere (epic tl-lkj2, lowest priority; bd stays one backend behind a port). | `tl-7s2f.14`. | ticket, issue (in task-loop docs) |
| epic | A bead that groups child beads; its children are scheduled by their own dependencies. | `tl-7s2f` (the merge queue) has children `.1` to `.18`. | branch (an epic gets no integration branch) |
| owner | Denis. Merge approval, profile-change approval and `owner-approved` are his. | Only his label lets a bead change a trust-root file. | user, admin |
| trust root | The files whose change parks a bead unless it carries `owner-approved` (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `mise.toml`, `.codex/`, `.task-loop.json`, `githooks/`). | A bead that edits `.task-loop.json` waits for the owner. | |
| ask | A question the engine parks a bead on until the owner answers. | "Tree mismatch twice: which fix?" shows on the Decisions tab. | prompt |

## Running work

| Term | Means | Example | Not |
|---|---|---|---|
| loop | One process that takes one bead at a time into a free slot for one repo. A repo runs up to its wanted count of loops (`tl factory start` tops up to it). What `factory-lane-K.log` and "LANES running=" call a lane is a loop. | Two loops on one repo work two beads at once. | lane, worker, daemon |
| slot | A persistent worktree set up once and reused task after task; its count is the repo's own concurrency. | A repo with 3 slots runs at most 3 beads at once; a heavy setup is paid once per slot. | floor, workspace |
| run | One engine pass over one bead, step by step. | `tl run-task tl-abc --worktree DIR` is one run. | job |
| step | One thing the engine does in a run, named by the `Step` enum: reset, plan, replan, write, checks, review, verify, look, gate, land, close, reflect. | After `write` the engine runs `checks`, then `review`. | task |
| stage | The code that does a step, one folder under `src/taskloop/app/` (plan, write, review, look, land, ...). Architecture notes say "stage packages". | `app/land` is the land stage. | step (the thing done) |
| gate | The checks that must be green before land. A single run of the gate on one tree is "a gate". | The gate runs `just check` and `just test` on a clean checkout. | review |
| land | The merge or push of a finished bead to the base branch (modes `pr` and `push`). | In `pr` mode the loop opens a PR; `tl land-stack` merges it. | deploy, release |
| land-stack | The command `tl land-stack ITEM...`: it gates open PRs in parallel (prewarm), then merges them one at a time under the land lock, lowest first. The merge queue replaces its serial core. | `tl land-stack 12 13 14` gates three PRs, merges 12, then 13, then 14. | queue (a queue keeps state across calls) |
| check | One command of the gate with an id, a cache key and a verdict (`just check`, a test run). | `ruff` on the changed files. | test (a check may run many tests) |
| RunKey | The identity of one run of a check: the check, its command, settings, toolchain, tree, base, inputs, selected tests and env. Equal keys mean the same fact, so the second run is never made. | Same tree, same base, same command: the green result is reused. | cache key of a build tool |
| receipt | The stored green result of one check under its RunKey, kept with who made it and where its output is. A failure is never a receipt. | A receipt from the owner's gate lets the land gate skip that check. | log, artifact |
| Carry | The rule that keeps a receipt valid when only the base moved: if the files the check depends on (its closure) are unchanged in the branch merged into the new base, the receipt is stored again under the new key. | Main gains an unrelated file; the PR's receipt is carried, not rerun. | cache hit (a hit needs the same key) |
| worker | One headless model call, made through the `delegate.api` library. | A `write` step calls one worker; its answer is schema-checked. | agent (ambiguous) |
| role | The kind of worker job delegate routes (planner, reviewer, worker, hard, light). | The reviewer role goes to the other model family from the writer. | persona |
| facts | `RunFacts`: the frozen data every stage of a run reads and nobody changes after the engine opens it (env, config, worktree, bead). Live objects are ports, not facts. | A stage test builds `fake_facts(...)`. | state (state changes) |
| Asked | The result of one worker call: the answer's data and family, and `updates` to the run's threads that the host applies. `AskAi` is the one verb a stage uses to make the call. | `ask_ai("review", ...)` returns an `Asked`. | ask (that is the question to the owner) |

## Structure of the code

| Term | Means | Example | Not |
|---|---|---|---|
| port | A small Protocol for something outside the code: git, a process, the clock, the forge. One contract suite per port runs against the real adapter and its fake. | `Git`, `Clock`, `Spawner`. | interface (generic), API |
| adapter | The real implementation of a port (it touches git, processes, sockets). | `adapters/` holds real git and the real clock. | driver |
| host | The typed Protocol a stage takes of its caller, naming only what it needs, instead of the engine. | `CheckHost`, `LandHost`. | the machine (that is the factory or the executor) |
| node | A stage's logic: imports only the kernel, lower layers and its declared neighbours; never the engine. | `app/land`, `app/checks`. | module |
| composition root | Code that only builds nodes and hands them to each other (`launch`, `wire`, the engine's construction). Nothing imports a root. | `app/wire`. | main (it holds no rules) |
| kernel | The contracts every node shares (`src/taskloop/contracts/`). Also, in lock talk, the OS: a kernel flock is dropped when its process dies. | `RunKey` is in the kernel. | core |
| part | One small class of a stage with one job, built by the engine and handed what it needs. | The review stage has four parts (docs/design/b-review.md). | stage |
| ratchet | A rule test that counts offenders on the files a change touches and fails if the count rises. No stored baseline; the way down is free. | A new `time.sleep` in a unit test trips the layer ratchet. | threshold |
| Ratchet-allow | The commit-message line that lets a deliberate rise through: `Ratchet-allow: <layer\|temp\|needs\|root> +N <reason in words>`. | `Ratchet-allow: needs +1 uses a real git`. | `--no-verify` (forbidden) |
| lease | One held unit of a resource, in the machine's lease table; freed when the holder dies. | Two Unity checks hold two of three `unity` leases. | lock (a lock is a mutex on one thing; a lease counts units) |
| resource | A scarce machine tool a check declares it needs (`unity`); its limit is in the profile. | `resources: {unity: 1}`. | |
| executor `planned` | The machine side of a split factory: process spawn, slots, leases, `host.json`. Today the factory and the executor are one machine. | | node, agent |

## Accounts and checks

| Term | Means | Example | Not |
|---|---|---|---|
| account `planned` | A metered connection to a model vendor: a subscription or API key with usage windows, reset times and models. Delegate owns it. Dashboard panel: Accounts. | A Codex subscription and a Claude subscription are two accounts. | lane, license, supplier, provider, token source |
| track `planned` | Within one gate block, a parallel sequence of checks; the first red cancels the other tracks. Replaces the `lane` key on checks. | A `build` track and a `test` track run side by side. | lane |
| lane `planned` | Purged word (hard cut, not finished: 80 source files still use it, docs/design/lanepurge.md). It names no concept; use account, track or loop. | | everything |

## Merge queue (design: docs/design/merge-queue.md)

All `planned`. Running example: five PRs A, B, C, D, E wait to land on main (call it M0).

| Term | Means | Example | Not |
|---|---|---|---|
| merge queue | The ordered list of PRs waiting to land, tested ahead of time and landed in order, each on exactly the main it was tested on. | A, B, C, D, E in that order. | `land-stack` (one call, no memory) |
| queue depth | How many PRs are waiting. In code: `queue_depth`. | A to E waiting: depth 5. After A lands: depth 4. | gates in flight |
| gates in flight | How many PRs are being tested at the same time, each on main plus the PRs ahead of it. 1 is today's serial landing. It starts at 1, grows by 1 after each success, halves after a failure, and stays between the floor and the cap. In code and config: `in_flight`, `in_flight_floor`, `max_in_flight` (key `land.queue.max_in_flight`); tests/rules/test_queue_terms.py fails on `window` or `lookahead` in the queue modules. | At 1: A is tested on M0; B waits; when A lands, B is tested on the new main. At 3: A on M0+A, B on M0+A+B, C on M0+A+B+C all at once; D and E wait. If A fails: A is thrown out, the tests of B and C (which contained A) are dropped and redone without A, D and E keep waiting, and the number halves. | window, lookahead, depth, `--jobs` |
| floor | The fewest gates in flight: 1. | After a failure at 1, it stays 1. | the dashboard's Floor tab (becomes Slots) |
| cap | The most gates in flight. Default 4; 3 if over half of gate time was wasted in shadow mode. Config key `land.queue.max_in_flight`. | At cap 4, E waits until A lands. | slot count |
| speculative build | A PR tested on a local queue ref made of main plus the PRs ahead of it, assuming they pass. | C's build is main+A+B+C. | a PR, a branch |
| eject | Removing a PR from the queue because its own gate failed or it conflicts; only the PRs behind it are rebuilt. | B fails: A keeps its build, C and D are rebuilt without B. | revert |
| wasted gate | Gate seconds whose result was thrown away (cancelled or invalidated). The ratio wasted / useful decides whether the cap drops. | A's failure wastes the builds of B and C. | a failed gate |
| tested-tree assertion | The check, under the land lock, that the tree that landed equals the tree that was tested and its parent is the main the test assumed. Layers: before the merge, match-head, after the merge. | A lands: its tree equals the tested tree, or the queue freezes. | `--match-head-commit` (checks the head, not the base) |
| freeze | The queue stops merging and starting gates; running gates finish. Set by the owner or by a tree mismatch. | | pause |
| repair | After a tree mismatch: an agent, dispatched automatically, lands a revert, a fix-forward or a re-merge through the queue; a human is asked only after two failed repairs. | The bad commit is reverted by a normal PR that passes the same gates. | auto-revert (it is a PR, not a blind push) |
| shadow mode | The queue builds and gates in parallel and records what it would have done; the old path still lands. | Compare the predicted tree with the one that landed, at no risk. | dry run (it does real gates) |
| flake score | Per test, how often it failed and then passed on retry or on clean main. Over 3 rows a week files a fix bead; nothing is skipped or hidden. | One test with 4 rows in a week gets a bead. | quarantine (refused) |
| guard rails | The settings that keep main safe: a GitHub ruleset against force-push and deletion, and the pre-push judge. `tl doctor` fails when either drifts. | Hook missing in a worktree: doctor fails. | branch protection requiring PRs (not used: push mode would break) |

## Tests (design: docs/design/test-tiers.md)

| Term | Means | Example | Not |
|---|---|---|---|
| behavioral test `planned` | A test that runs the real thing: the `real` and `e2e` layers (a real git, process or socket, or a whole flow), plus `tests/delegate` and `tests/live`. | `tests/land/real/`, `tests/e2e/`. | unit test (fakes, in memory), integration test |
| test tier `planned` | When a set of tests runs: T1 unit + contract on every PR, T2 behavioral near the change on every PR, T3 the full behavioral suite on main and on a release candidate. | A hub change runs T1 in full, T2 by distance, and T3 later. | test layer (a layer is what a test may touch, by path) |
| distance cut `planned` | The T2 rule that runs a behavioral test on a PR only when the PR changed it, it imports a changed file directly, it sits in a changed file's slice, or it is a wiring or e2e test. The rest of the closure waits for T3. | `contracts/paths.py` changes: tests that import it run on the PR; the far closure runs in T3. | closure (the closure is every test that reaches the file) |
| main sweep `planned` | A T3 run of the full behavioral suite on the newest main tip by an idle slot, skipped for a tree that already has a green receipt. | A landing moves main; the next idle slot runs the main sweep on the new tip. | gate (a gate judges one PR before land), devbox canary (an acknowledgement for the Mac pin) |
| release candidate `planned` | The tree `dev/release.py` is about to bump: origin/main's tip before the version-bump commit. | The tree hash the release caches its gate by. | release (a candidate is not yet released) |
| release | A release candidate that passed T3 and `just check` + `just test`, then got the version bump, the tag `v<version>` and the install. | `v0.9.12` tagged and installed. | land, a merge to main |

## Dashboard

| Term | Means | Example | Not |
|---|---|---|---|
| Board | The tab with every bead by state (Flow) or by goal (Goals). | A bead waiting on an ask sits in its column with a badge. | Floor |
| Floor | The tab with time on one axis and slots on the other: what each slot is doing and where it is stuck. `planned`: it becomes "Slots". | A red segment is a stuck bead. | floor (queue's fewest gates in flight) |
| Decisions | The tab with the owner's open asks. | | |
| Landing strip | `planned`: one strip under the Floor, queue order left to right, one chip per PR with its gate state and wait. | | |

## Rename plan (hard cut, one bead each)

0. Purge: the word "lane" leaves code, docs, tests, dashboard and the delegate copy in one cut (no alias). Three meanings, three names: delegate lane -> account; check lane -> track; factory lane (a loop process) -> loop. Occurrence counts come from the naming audit (docs/design/naming-audit.md: about 1,760 lines in task-loop and 2,019 in delegate).
1. Delegate: `lane` becomes `account` in routing.json, `route.py status`/`run` output, docs, skills. The interface is the typed `delegate.api` (docs/design/topology.md), so there is no wire contract to version. 122 files in task-loop mention "lane" today, so the task-loop side is the larger edit.
2. Dashboard: the "Lanes" panel becomes "Accounts"; the "Floor" tab becomes "Slots".
3. `tl lanes` becomes `tl accounts`; `tl setup` stops asking about lanes; `checks[].lane` becomes `track` (profile key: a hard cut, shipped one release after the code that reads it, per CLAUDE.md); `tl factory status` prints loops, not lanes.

## Visuals rename (with the visuals epic, hard cut)

`shots` (ask field) becomes `artifacts`; "shot" survives only as lifesim's own `shot` request method. `earlier_pictures`, `IMAGE_NAME`, `writer_names`, `same_defect` and `words` are deleted, not renamed.
