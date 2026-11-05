# Topology: factory instances, the shelf factory, cross-repo work, lanes, delegate's home (design only)

Bead tl-w7lt.38 (TOPOLOGY); also answers tl-w7lt.37 (DELEGATEHOME) and the lanes/Unity questions of tl-m5pw (SETUPFLOW).
Verdicts: ✅ do, ❌ refuse. Evidence tags: *read* = read in code or docs, *help* = read from `--help` only, *untested* = no run exists.
Premise (Denis): Mac only, no Docker, Windows later; one constitution (shelf `docs/constitution.md`); task-loop never knows which harness is underneath; delegate owns processes and lanes.

## What exists today (read)

- One config folder per machine, `~/.config/task-loop`: `repos.json` (registered repos), one `factory.db`, `leases/`, `loop/<repo>-<hash>.<pid>.json`, `asks/`, `slots/`, `locks/`.
- One loop per repo (`tl factory start --repo DIR`), one read-only dashboard per machine (port 7878) over every registered repo.
- Each repo owns its backlog (`.beads/` in the repo) and its rules (`.task-loop.json` on the base branch).
- Delegate owns lanes and plan limits; task-loop reads `route.py status --json` and calls `route.py run`, nothing else.
- Machine-scarce things are leased in `leases/` (`any_lease`, a flock per unit); `host.json` says which resources the machine has.

So the topology is already "one factory per machine, one loop per repo". The questions below decide whether to keep it and what to add.

## 1. Unit of a factory instance

| Option | Verdict | Why |
|---|---|---|
| One factory per machine, one loop per repo | ✅ | Everything scarce is per machine: lane usage windows, the Unity limit, disk, RAM, the land lock's host, the dashboard port. Two factories on one machine would each count the same lane budget and the same Unity unit and have to coordinate: a second copy of the lease table. A new repo costs `tl register` plus one loop, no new state. |
| One factory per repo | ❌ | Duplicates factory.db, dashboard, lease table and lane accounting per repo, and the shelf factory would need its own copy of all of them next to task-loop's. |
| One factory per executor | ❌ | An executor is a place where processes run, not a place where decisions are kept. Making it a factory moves queue, asks and landing state onto every machine. |

State owners (single path, constitution: one owner per fact):

| State | Owner | Scope |
|---|---|---|
| Backlog (beads) | the repo (`.beads/`) | per repo |
| Profile, gate definition | the repo (`.task-loop.json` on the base branch) | per repo |
| factory.db (runs, asks, slots, landings) | the factory | per machine, rows keyed by repo |
| Loop (one process, its pidfile and command file) | the factory | per repo, per machine |
| Dashboard | the factory, read-only | per machine |
| Lane status, plan limits, worker processes | delegate | per machine |
| Resource leases (Unity, ...) and `host.json` | the machine's executor side (today the config folder) | per machine |

**Windows later (executor split): ✅ keep it a boundary, ❌ no code now.** The boundary exists: the engine reaches the machine only through `route.py run/status`, the Spawner port, and `any_lease`. In a split, the engine (factory.db, loops, dashboard) stays on one machine and each executor node owns exactly: process spawn and tree kill, worktrees and slots on its disk, the lease table and `host.json`. The Windows backends the audit listed (`process_lock` fcntl, `stream_proc` tree kill, SIGTERM stop, symlink pid index, sh shims) are shelf packages plus a few shims, so the Windows work lands in shelf, which is a reason to have the shelf factory first. Acceptance of the original bead ("executor port contract, backends list") is met by this paragraph; the port contract itself is written when the migration starts, not before.

## 2. A factory instance for the shelf

The shelf does not get a second factory. ✅ It is a third registered repo of the machine's factory: `tl register ~/Workspaces/shelf`, a loop started with `tl factory start --repo ~/Workspaces/shelf`, shown on the same dashboard. A separate instance would repeat section 1's ❌.

| Piece | Verdict | Detail |
|---|---|---|
| Profile | ✅ a `.task-loop.json` in shelf, landed as a PR with Denis's profile-change approval (`land-stack --profile-change`). Nothing in this note lands a profile. | `pick_label: auto`, `owner_author: Denis Tomilin`. |
| Gate | ✅ one check, `["uv","run","just","check"]`, `"run": "gate"`, `"run_in": "slot"`, `SHELF_HOST_CHECK=1`, `wall_min` at least 30. | `just check` is the shelf's Definition of Done and already narrows tests to the changed packages (`tools/affected.py`). No Docker, so the shelf's own comment applies: the host run took 10 to 17 minutes under the endpoint scanner (2026-10-10, shelf justfile, *read*). Expect that per gate run and per land. |
| Slots | ✅ `count` 2, `setup` = `mise trust --yes && mise install --locked && uv sync --locked && bd bootstrap` as a recipe called `["just", ...]` (argv only), `setup_inputs`: `mise.toml`, `uv.lock`. | A clean checkout per gate would redo the sync every time; `run_in: slot` needs the slot's tree to equal `HEAD^{tree}` (*read*). |
| Lanes | ✅ none of its own. Shelf work draws on the machine's delegate lanes like every repo. | Lanes are delegate's (section 4). |
| Landing | ✅ the shelf loop stops at an open PR and never merges. ❌ `land: git push origin HEAD:main` for shelf. | Denis's rule: he merges shelf PRs. Needs a PR-only land (profile `land` as a PR open + bead waits in "your look" until the PR is merged, then closes with the PR's merge sha). Today `land` is one argv and `land-stack` merges (*read*), so this is a **new engine feature, untested**; one bead, filed after Denis answers D1. Until it exists, the shelf loop does not start. |
| Trust-root files | ✅ as is. | Changes to `AGENTS.md`, `CLAUDE.md`, `mise.toml`, `.claude/`, `.task-loop.json` park the bead unless it carries `owner-approved` (*read*). Shelf beads touching `AGENTS.md` will park; that is the rule working. |
| Git hooks | ⚠️ untested. | Every tl-spawned process gets `core.hooksPath` = tl's dispatchers (SETUPFLOW report). The shelf runs its own pre-push gate through prek (`.pre-commit-config.yaml`, ADR 0027). If tl's dispatcher does not chain to the repo's hooks, shelf pushes from the factory skip the shelf gate; if both run, the gate runs twice (10 to 17 min each). First trial before the loop starts: push from a slot and read which hooks ran. |
| Size caps | ⚠️ see D3. | Shelf main's Article IV says "structure controls size, not caps". The hard-limit amendment (commit 0243ce6, "Article IV made a hard code limit") is on an unmerged branch. A factory that writes shelf code under the old text has no cap to hit. |

## 3. Cross-repo filing

Verdicts: one store per task, in the repo that does the work. ❌ a central inbox repo or a mirrored bead in the filing repo (two records of one task, the redundancy the constitution refuses).

| Question | Verdict |
|---|---|
| Which store | ✅ the target repo's own `.beads/`. A task filed on the shelf is a shelf bead. |
| Which command | ✅ one verb on the existing wrapper: `tl task create --repo <registered repo> ...` is the intent (bd 1.3.1 has `bd create --repo`, "target repository for issue", *help*; whether it reaches a second embedded Dolt store without routing config is **untested**). If bd's flag cannot, a thin `tl file --to <repo>` that runs bd with that repo as cwd. Either way one entry point, and no session edits another repo's `.beads/` files. Trial first, then pick; both end at the same user-visible command. |
| Who may write | ✅ any session on the machine, **create only** (title, description, acceptance, `from:<repo>` label, creator actor recorded). ❌ update, claim, close, or relabel of a foreign bead from outside its repo. The target repo's own loop and owner are the only claimers and closers. |
| Who admits it to the queue | See D2. |
| Concurrency with the target's loop | ⚠️ untested: bd's embedded Dolt takes a gate lock (`embeddeddolt.gate.lock`) per store; a create while the shelf loop claims should serialize, not corrupt. The trial includes a create during a claim. |
| The filer's side | ✅ the filing bead gets a dependency on the filed one (section 3b), so it leaves the ready list until the shelf work is done. |

### 3b. Dependencies and ordering

- ✅ The dependency edge is the only ordering. A bead that needs shelf work declares `external:shelf:<capability>` (bd's cross-project edge: "block the issue until the capability is shipped in the target project", resolved through `external_projects` config, *help*). A blocked bead is absent from `bd ready`, so the loop's next pick skips it; the existing per-pass re-read of ready beads is the wake. ❌ timers, sleeps, "retry in an hour" on a dependency, and any loop code that special-cases a dependency.
- ✅ "Shipped" means the shelf bead closed, which happens when its PR is merged (section 2). The consumer's first step after wake is to vendor the shelf commit (`dev/vendor.py`), so the pin moves in the consumer's own diff.
- ❌ A shelf bead depending on a consumer's bead. The shelf knows no consumers (constitution: owners plus injection); the edge only points from consumer to shelf, so cross-repo cycles cannot exist.
- ⚠️ untested: that `bd ready` evaluates `external:` edges across two embedded stores and which label or state marks "shipped" (the help text says "shipped", not how). One trial settles it; if bd cannot, the fallback is the consumer's bead naming the shelf bead id as a plain `blocks` edge on a local stub, which is the redundancy ❌ above, so prefer fixing the config.

## 4. Where lanes and the Unity lease live

| Thing | Verdict | Reason |
|---|---|---|
| Lanes (count, models, windows, accounts) | ✅ delegate, machine-wide. Task-loop reads status only. | Constraint from Denis: delegate owns lanes and emits events; task-loop does not know the harness. |
| `tl setup` question `lanes (default 4)` | ❌ remove it from `tl setup`. | A lane setting asked by task-loop is a second owner of delegate's setting. `tl setup` points to `iorlas-delegate:init` instead. |
| Unity: presence on the machine | ✅ `host.json` (`{"resources": ["unity"]}`), written by `tl setup --apply` from the `unity-lease` answer. Machine fact, belongs to the executor side. | Missing file means "has every declared resource", which is wrong on a machine without Unity; setup writes it explicitly. |
| Unity: the limit number | ✅ the repo profile (`engine.resources: {"unity": {"limit": N}}`). | One declared number, reviewed with the profile. Changing it is a profile change, so it goes through Denis's approval flow. |
| Unity: the lease mechanism | ✅ `any_lease` only. ❌ the second, repo-side counting lock (`lifesim tools/unity_slot.py`, named in the roadmap's safe-by-construction table; `unity-slot: got slot N` lines are still parsed in check output). | Two mechanisms for one scarce thing. The check's `needs: ["unity"]` already holds the lease. Not verified here whether lifesim's check still takes both; one bead in lifesim to confirm and delete the script. |
| Under an executor split | ✅ lease table and `host.json` move with the executor that has the tool. | A lease only means something on the machine it protects. |

## 5. DELEGATEHOME recommendation

✅ **Option 1: the task-loop repo, delegate as an isolated top-level package.** ❌ Option 2: shelf.

| | Task-loop repo | Shelf |
|---|---|---|
| Release drift between two repos | ends: one `dev/release.py` path, one version stream, one contract test pair | stays or worsens: a third release path |
| Contract (`worker-run v3`, `route.py run/status` only) | stays JSON-only; enforce with an import-linter contract (no `taskloop` import of delegate and back) plus a stdlib-only test for delegate's folder | same |
| Constitution fit | a product with lanes, skills and onboarding living next to the product that needs it | ❌ shelf holds generic, ownable packages (Articles VI to VII). Delegate is not generic substrate; it would need a new Kind (Denis's own note on the bead) |
| Who may change it | the factory itself: the factory releases its own executor through `dev/release.py` | ❌ every delegate fix becomes a shelf PR that only Denis merges, behind a 10 to 17 minute host gate, for the component the factory cannot run without |
| Direction of dependency | task-loop already vendors shelf; delegate inside task-loop adds none | task-loop would depend on shelf for its executor, and shelf's factory would work the executor's beads |

What it costs (so it is not a free move):
- `route.py` is 2383 lines in one file (and `onboard.py` 554). Task-loop's gate caps files at 400 SLOC and functions at 80, with no exceptions table (CLAUDE.md). The move cannot pass `just check` until route.py is split. **Split first, in the delegate repo, then move.**
- Two plugins from one repo: `dev/release.py` bumps one `plugin.json` and one marketplace entry today; it needs to bump both (or ship delegate as a second entry from the same version). One change to that script, tested by the existing release path.
- Delegate runs stdlib-only on whatever `python3` the plugin host has; task-loop wants Python 3.15 and uv. Keep the delegate folder's own interpreter floor and enforce stdlib-only by test, not by convention.
- Move with history (`git subtree` or equivalent), delete the old repo's content in the same step: no mirror, no stub (no redundancy).
- Not verified: delegate's current Python floor and whether its vendored shelf copies are byte-checked by a test. Read both before the move.

Order: (1) split route.py in the delegate repo, (2) extend release.py for two entries, (3) move with history, (4) archive the old repo. Nothing moves before D1.

## Owner amendment, 2026-11-05 (later): delegate is a library, imported

Denis: "When we use delegate inside of task loop, it should always be proper import. [...] we could forget about the use case when AI runs delegate directly. For task loop, the delegate is abstraction over all the harnesses, which encapsulates all the experiences and guarantees stability of running things based on inputs."

This replaces the process-boundary reading above (the `route.py run/status` rows and "stays JSON-only"). Verdicts:

| Point | Verdict | Reason |
|---|---|---|
| Interface | ✅ one public module, `delegate.api`: run(request) -> result, status() -> snapshot, cancel(handle); typed (msgspec) request, result and snapshot. task-loop imports only that module (import-linter: nothing else from `delegate`, and `delegate` imports nothing from `taskloop`). | A thin, designed interface, as he asked; internals can change without touching the engine. |
| `route.py` command line, the three delegate skills (`delegate`, `init`, `status`), the iorlas-delegate plugin and its marketplace entry | ❌ retire, hard cut. | The only reason for a command line was a model calling it directly; that use is dropped. Keeping it is a second path to the same function. Account setup and status become `tl setup` and `tl accounts`, which call the API. |
| worker-run v3 JSON contract | ❌ retire as a wire format; its fields become the typed api structs. | No process boundary, no JSON to parse. |
| stdlib-only and Python 3.8 floor | ❌ drop. Delegate runs on task-loop's interpreter and may use msgspec and the shelf packages directly. | Both only existed so a script could run anywhere without install. |
| Crash and kill isolation | ✅ keep, inside the library. Workers are still child processes (process group, SIGTERM then SIGKILL after a grace) behind `run`/`cancel`; a delegate fault returns a typed failed result, never an exception through the engine. | Each loop is its own process, so a bug still costs one loop, not the factory. |
| Several loops import delegate at once | ⚠️ account state (usage windows, leases, ledger) must stay safe across processes (file locks as today). Not re-verified; the move's tests cover two processes. | |
| Packaging | The plugin check below is now mandatory: `src/delegate` must be in what the installed plugin ships. | |

## Owner answers, 2026-11-05 (after the first PR)

| Point | Verdict | Reason |
|---|---|---|
| Concurrency is per repo | ✅ already so: `slots.count` is the repo's own profile key; each repo has its own slot line. | Nothing to build. Gap, untested: no cap across repos except the RAM/disk thresholds (`loop.min_ram_mb`, `loop.min_free_gb`). Two long gates at once (lifesim, shelf) are bounded only by those. If it bites, declare one `engine.resources` entry for "heavy gate"; no new monitor. |
| Slots are reused, tracked by an index | ✅ already so: a slot is a persistent worktree, a bead labelled `slot` with a lease, plus `slot-state`; `tl prune` and `tl worktrees clean` remove owned merged clean ones. | Growing storage would be a bug in prune, not a missing index. Observation, not verified as factory-owned: `~/Workspaces` holds dozens of `iorlas-task-loop-<name>` clones; if the factory made them, prune misses them. |
| Cross-repo filing: direct bead or through tl | ✅ through tl, always. ❌ a session writing another repo's `.beads` itself. | One entry point sets the actor, the `from:<repo>` label and refuses anything but create. |
| Ordering | ✅ pick every ready bead not blocked by a dependency, by bd's native priority (0 to 4, P0 first), then `epic_order`, then lowest id. | That is already the pick rule (SKILL.md, "Order: priority first..."). bd's priority is the native one; use no second scale. |
| Names | ✅ rename (canonical list: docs/glossary.md); ❌ keep "lane" for three things. | Today "lane" means (1) a delegate vendor connection with usage windows, (2) a parallel track of checks in one gate block, (3) a swim lane on the dashboard. "Floor" exists only in conversation; the engine's word is **slot** (a persistent worktree), so use slot. Delegate's lane is a subscription or API key with limits: call it **account**. "License" is wrong (a license permits, this meters); "supplier" and "provider" name the vendor, not the metered thing. After the rename "lane" keeps only the check-track meaning. The rename is a hard cut in delegate's contract (worker-run version bump, no alias). |
| Pieces: delegate, task-loop, lifesim, shelf packages all segregated, tests included, thin designed interfaces | ✅ as the rule for every piece. | Each piece owns its tests, publishes one interface document and contract tests that both sides run, and imports nothing of the other. Delegate already has that interface (`worker-run v3`: `route.py run` and `status`). |
| Delegate into shelf | ❌ still. See D1: segregation does not need the shelf. | Shelf pieces are imported or vendored; delegate is called as a process. Putting it there adds Denis's manual PR merge and a 10 to 17 minute gate to every executor fix, and it makes "one piece among pieces" mean "one repo" for lifesim too, which cannot follow. |

## Decisions Denis must make

**D1 (decided 2026-11-05: option A, delegate moves into this repo as `src/delegate`; Denis: "I don't mind if you would move delegate inside of it as a new folder in SRC then.") What is a piece's boundary: a folder or a repo, and so where does delegate live?** Context: bead tl-w7lt.37; his words: "I wouldn't mind merging Delegate into Task Loop repo, but keeping it isolated as a package. Maybe move it to Shelf, potentially, I don't know." and, 2026-11-05, every piece (delegate, task-loop, lifesim, shelf packages) segregated with its own tests and a thin interface. Options: (A) delegate stays a separate piece in the task-loop repo: its own folder, its own tests, its own pyproject or stdlib-only test, an import-linter contract both ways, the interface doc, so moving the folder to any repo later is a `git mv` (recommended: segregation is the same, release drift ends, route.py is split first); (B) its own repo as today, with the contract versioned and a contract test in each repo (most segregated; the two release paths and the drift remain, which is the pain that opened this bead); (C) shelf (refused above). Under A the folder is movable on purpose, so A does not close off B or C.

**D2. Who admits a task filed from another repo into the shelf queue?** Context: the loop only picks beads with the `auto` label, and every shelf PR waits for his merge anyway. Options: (A) the filer sets `auto`, his merge is the single owner gate (recommended: no double gate; cost is that shelf slots and 10 to 17 minute gates run for any filing, even a bad one); (B) he labels each filing by hand (a second gate in front of the PR gate, and every filing waits on him); (C) a triage pass labels (a new moving part).

**D3. Merge the shelf Article IV amendment (commit 0243ce6, "hard code limit") before the shelf factory starts?** Context: shelf main still says no caps; task-loop's own gate has 400/80/800 caps with no table. Options: (A) merge it first so the shelf profile can state the cap (recommended: the constitution he described is the amended one, and factory output under the old text has no size limit to hit); (B) start the shelf factory under the old text. Merging is his action.

**D4. What does "shipped" mean for a shelf dependency?** Options: (A) the shelf bead is closed, i.e. its PR merged to shelf main; the consumer vendors that commit (recommended: no release step in the way; matches how task-loop vendors today); (B) a tagged shelf release, which his standing rule says needs him each time and slows every consumer.

Not decisions (settled by existing rules, listed so they are not re-asked): merge approval for shelf PRs stays his; shelf profile lands through his profile-change approval; Mac only, no Docker; no force-push.

## Follow-ups (beads to file after the picks; not created here)

1. PR-only land mode for a repo profile (engine; blocks starting the shelf loop).
2. Trial: cross-store `bd create --repo` and `external:` dependency resolution across two embedded stores, including a create during a claim. Decides `tl task create --repo` vs `tl file`.
3. Trial: hooks on a shelf slot push (tl dispatchers vs the shelf's prek gate).
4. Shelf `.task-loop.json` plus slot setup recipe (PR, profile-change approval).
5. `tl setup`: drop the `lanes` question, write `host.json` from the `unity-lease` answer.
6. lifesim: confirm `unity_slot.py` is redundant with `needs: unity`, then delete it.
7. DELEGATEHOME steps 1 to 4 after D1.
8. Executor port contract and the Windows backends (shelf packages first): when the migration starts.
9. Glossary rename (docs/glossary.md): delegate `lane` to `account`, `tl lanes` to `tl accounts`, dashboard panel; worker-run major bump.

## D1 move: open check before it starts

The README says a plugin install ships `skills/` and `hooks/`; delegate's `route.py` runs from `skills/delegate/` in its plugin. Before moving code to `src/delegate`, read what the installed task-loop plugin actually contains (is `src/` present?). If it is not, delegate keeps a thin `skills/delegate/route.py` entry that only calls into `src/delegate`, or release.py copies it; either way the interface stays `route.py run/status`. Order stays: split route.py (400 SLOC cap) first, then move with history.

## Correction from the move session (2026-11-05)

My size facts came from a stale local delegate checkout (0.39.1, dirty). Delegate origin/main (0.56.1) already has `route.py` as a 144-line launcher, the code in `src/delegate`, and no file over 400 SLOC or function over 80; so "split route.py first" is void. The installed task-loop plugin does ship `src/`, so the packaging check passes. Real costs found instead: delegate carries about 100 ruff per-file ignores, a 201-error pyrefly baseline and 53 unittest files, none of which task-loop's gate allows; and delegate is still released daily with about 30 open branches, so a copy drifts until the cutover.

## Cutover decision (Denis, 2026-11-05)

"Yeah, we need to fix those RAF and Pyrefly issues. And we need to migrate to PyTest. And I think we need to deprecate our previous delegate skill. Not deprecate, like remove it and forget about that. [...] Yeah, uninstall the delegate skill, copy code base and move on."

Verdict: ✅ plain copy of delegate origin/main into `src/delegate` (no history, no overlap, no ask to its open branches); fix the ruff ignores and the pyrefly baseline to task-loop's gate; unittest to pytest; retire `route.py`, the three skills, the wire contract and the iorlas-delegate plugin in one release with `tl accounts`; uninstall the plugin after that release is installed. The old repo is left untouched.
