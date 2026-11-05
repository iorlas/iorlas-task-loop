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

**D5. Does a filed task start work on its own?** Context: filing needs no loop, but nothing runs the filed bead until someone runs `tl factory start --repo` for that repo (no OS service installed). Options: (A) manual start, as today (recommended for now: one shelf loop you start when you want shelf work; adding a supervisor is a new moving part); (B) the factory keeps one loop alive per registered repo that has ready beads (cross-repo dependencies resolve without you, at the cost of a supervisor and unattended 10 to 17 minute shelf gates).

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

## Filing needs no running loop (Denis question, 2026-11-05)

- ✅ Filing is a store write, not a call to a process. The factory is a config folder and a CLI; only the dashboard and the per-repo loops are processes. `tl` looks the target up by name in `repos.json` and runs the create against that repo's `.beads/` (bd is embedded Dolt, no server, *read from the repo layout; a create into a store no loop has open is untested*).
- ✅ The target must be registered (`tl register`), not running. An unregistered or unknown name refuses with the fix. ❌ A filing path that starts a loop as a side effect.
- Consequence: a filed bead waits in the target's backlog until that repo's loop runs, and the filer's dependent bead stays blocked meanwhile. The dashboard board shows every registered repo's beads, so the wait is visible. Loops are started by hand (`tl factory start`; no OS service, README), so a filing to a repo with no loop starts nothing by itself.
- Open as D5: should the factory run a loop for every registered repo that has ready work, or stay manual?

## repos.json, registration and detached mode (Denis questions, 2026-11-05)

- Where: `~/.config/task-loop/repos.json`, one per machine (read).
- When it fills: automatically. `register_repo` runs on every `tl` event inside a repo (`app/track/trail.py`), so the first `tl` command, loop or task in a clone registers it; `tl register DIR` is only the manual form. A clone `tl` has never touched is unknown, so a filing to it refuses with "run tl in it once or `tl register DIR`" (design choice, not built).
- A removed folder: readers skip it (`doctor` keeps only `Path(r).is_dir()`; the reflect digest only repos with `.beads/`), but nothing deletes the entry; I found no verb or prune step that removes one (read, not run). ❌ Leave stale rows forever; ✅ `tl prune` drops an entry whose folder is gone (follow-up bead). Whether the dashboard board shows or skips a vanished repo is untested.
- Name to path for filing: repos.json holds paths only. Resolution by folder name, refusing an ambiguous one (design choice, not built).
- Detached mode: `tl factory start` starts the loop through `Spawner.start`, which detaches it into its own session with no terminal input, so closing the terminal does not stop it. It is a plain child of launchd, not a service: a pidfile (`loop/<repo>/loop.pid`) and a state file in the config folder let `tl factory status/stop` find it; `caffeinate` is attached for its life; a reboot ends it. ✅ Keep both: `tl loop` in a terminal when Denis watches it, `tl factory start` when a session starts it for him. No OS service (his rule).

## Every repo has a canonical name (Denis, 2026-11-05)

- ✅ `repos.json` v2 is keyed by name: `{"v": 2, "repos": {"iorlas/iorlas-task-loop": {"path": "...", "added": ...}}}`. The name is the origin's `owner/name` (the engine already resolves traces by origin URL, `reflect.resolve_repo`); with no remote, the folder name, refused if taken. Filing, `--repo`, the dashboard and the glossary's "repo" all use this name; a path is an attribute, never an identity.
- ✅ Registration stays automatic; it now records the name. The v1 file is converted once (names read from each folder's origin) and v1 is not read again: hard cut, no dual reader (single-path rule). A folder with no readable origin is named by folder name.
- ❌ Several clones of one repo registered under name plus role. A clone has its own `.beads/` store and the factory runs a loop and slots out of one home clone; two registered clones are two backlogs that diverge until bd syncs, and a filing lands in whichever one the name resolved to. One repo is one home clone per machine; its extra worktrees are slots. Hand clones (the `iorlas-task-loop-<name>` folders) are not registered. A second machine or a Windows executor holds its own checkout of the same name; that is an executor's checkout, not a second repo entry.
- If Denis still wants several clones of one repo, the key becomes `name#role` and filing must pick a role; I recommend against it for the reason above (untested: whether two registered clones of one repo conflict today, e.g. on the land lock, which is per repo path).
- Follow-ups: repos.json v2 and its one-time conversion; `tl register` takes the name; `tl prune` drops entries whose folder is gone.

## Every repo has a canonical name (Denis, 2026-11-05)

- ✅ `repos.json` v2 is keyed by name: `{"v": 2, "repos": {"iorlas/iorlas-task-loop": {"path": "...", "added": ...}}}`. Name = origin `owner/name` (traces already resolve by origin URL, `reflect.resolve_repo`); no remote: folder name, refused if taken. Filing, `--repo`, the dashboard and the glossary use the name; a path is an attribute. Registration stays automatic and records the name; the v1 file is converted once and not read again (single-path rule).
- ❌ Several registered clones of one repo under name plus role: each clone has its own `.beads/` store, and the factory runs its loops and slots out of one home clone, so two entries are two diverging backlogs. Extra worktrees are slots; hand clones are not registered; another machine or a Windows executor holds its own checkout of the same name. If Denis wants several clones anyway, the key becomes `name#role` and filing must pick a role (untested: whether two registered clones conflict today, e.g. on the per-path land lock).
- Follow-ups: repos.json v2 and its conversion; `tl register` takes the name; `tl prune` drops entries whose folder is gone.

## Processes (answer to Denis, 2026-11-05)

Per machine: one dashboard (port 7878, `dash ensure` is idempotent and replaces a stale one) and, per repo, up to its wanted count of loops (`tl factory start` tops up; a second call starts nothing). There is no engine server: the loops and `tl` write `factory.db` and files, the dashboard reads them, and its POST verbs (park, stop, note) go through the same typed stores. A central engine process with an API would be a new single point of failure and a new process to supervise; ❌ for now (untested alternative: only worth it when an executor runs on another machine).

## Later: more than one machine (Denis, 2026-11-05; thinking, nothing built)

- ✅ The bus is the git remote, not a new server. Code, the profile (read from the base commit) and bd's data (`refs/dolt/data`, README of the beads block) already travel through it. A factory on another PC or in the cloud (Linux is enough) is a second machine's factory registered for a repo by canonical name. Handing it a task = file a bead, push bd data; it pulls at each loop pass and picks it up. Done = the bead closes after its PR merges; the filer sees it when it next pulls (its `external:` dependency resolves then). No timers and no push channel: the existing pass-interval poll plus a sync at pass start. Untested: bd sync cadence and conflict behavior across two machines.
- ✅ Rule: one repo has one working factory at a time. ❌ Two machines looping the same repo: a claim is atomic only inside one store, and across a sync a double claim is possible (untested). Which machine works a repo is a registry fact, not a lock to race for.
- ✅ Everything another machine needs must be in the bead, not only in `factory.db`: outcome, block reason, owner-needed. This is already the rule ("everything is recorded in the bead"); the remote asks and runs panel are the exception to check.
- ✅ Dashboard stays one per machine and shows that machine's factory. ❌ A central dashboard or engine server now. A remote factory's live view is its own dashboard (it already binds the Tailscale address); a repo's registry entry can carry that URL.
- ⚠️ Accounts are per machine: one subscription used from two machines is counted by two delegates that cannot see each other's usage windows.

### Splitting one repo's stages across machines (executor affinity)

- ✅ It is the executor split of section 1, minimal form: one factory, remote executors. The first useful boundary already exists as a shape: a check with `run_in: clean` runs a committed tree, and the container backend ships tracked files as a tar on stdin and returns exit code plus `$TL_ARTIFACT_DIR`. One port: "run this argv on this commit, return result and artifacts". Backends: local (today), container (today, the one he calls hell), ssh to a Linux box (later). ❌ Add more container machinery (images, caches) meanwhile; freeze `in: container`. ✅ delete it when the ssh backend or the Defender fix below replaces it.
- The reason for the container is the endpoint scanner's per-file cost on the Mac (about 20 ms a file, bead memory 2026-10-29). Cheaper than any of the above if allowed: a Defender folder exclusion for the factory's worktree and slot folders. Untested and policy-dependent (see D6).
- Needs a server? No for one-way jobs over ssh (the engine starts the job, streams the log, collects the result). A server is only needed when the remote machine must start work on its own, which the git-remote bus already covers.

**D6 (answered 2026-11-05: no, this Mac cannot exclude folders from Defender; so the ssh Linux executor is the replacement and the container backend is frozen until it exists).** Can this Mac exclude the factory's worktree folders (`~/Workspaces/wt`, the slots dirs) from Defender?** If yes, the container checks and their images can be deleted and review/land/gate run natively; if the policy forbids it, the ssh Linux executor is the replacement and the container backend stays until it exists.

## What another machine needs that is not in the bead or git yet (read; sources named)

Today's homes (read): `factory.db` tables `ask, ask_ledger, attempt, bead, check_pass, check_round, effect, kv, lease, run, signal, source, step, wait`; files in the config folder `asks/`, `parks/`, `followups/`, `landed/`, `handoff/`, `decisions/<repo>-<hash>/ADR-n.json`, `slots/`. Bead metadata already carries `branch`, `slot`, the override and held keys (`app/track/verbs.py`, `app/asks/intake.py`, `app/reconcile/apply.py`).

| Fact | Today | Needed on another machine? | Verdict |
|---|---|---|---|
| Bead status, claim, landed sha, PR link, park reason | bead + `landed/` file | the filer and any dashboard: yes | ✅ the bead must show all four (landed sha and PR link as metadata; checked: only branch and slot are confirmed written) |
| Ask (question, choices) and the owner's answer | `ask` table / `asks/` file; an answer is a typed `AskAnswer` record, prose in a bd comment never acts | the owner may sit at another machine than the factory | ✅ the ask stays with the working factory (one repo, one factory); the bead gets a typed marker (label or metadata `asking`, ask id, dashboard URL) so any machine's `tl status` shows "2 asks waiting on <machine>". ❌ copying ask bodies to every machine (second record). Answering = that factory's dashboard |
| Owner typed decisions on a bead (`hint`, `hold`, `override`, `park`, `note`) | override is bead metadata; the others not checked | yes if the owner acts from another machine | ✅ every typed owner record about a bead is bead metadata; only machine settings stay in the config folder |
| Decisions in force (ADRs) | code writes `<config>/decisions/<repo-key>/ADR-n.json`; on this machine the folder does not exist yet (36 asks raised, 13 answered, no ADR made) | yes: a repo worked from another machine would not see them | ✅ every ADR belongs to one repo, so every ADR goes into that repo's tree (files are the unit of truth); no ADR stays in the config folder (single path). Written into the same commit as the bead whose ask made it (untested). Empty today, so the move costs nothing now. |
| Profile | git base commit | yes | ✅ already |
| Reflections, traces, run history, usage history | config files / `factory.db` | no (history of that machine; the dashboard reads it there) | ✅ stays local; ❌ syncing history |
| Slots, leases, `host.json`, `repos.json` | config folder | no: machine facts | ✅ stays local |
| Handoff notes (`handoff/`) | config folder, per session | no | ✅ stays local |

## Remote executor over ssh (Denis, 2026-11-05: "SSH Linux executor is what we actually need")

Good idea, in two phases; the second only if the first leaves a real pain.

- **Phase 1 ✅: remote checks by git, not tar, not mounts.** A new check location `"in": "linux"` replaces `"in": "container"`. The engine pushes the committed tree to a bare repo on the executor over ssh (`git push ssh://<exec>/<repo>.git HEAD:refs/tl/<run>`; only new objects travel; the Mac needs no inbound ssh and origin gets no WIP branch). The executor keeps one persistent worktree per repo, checks out that commit, runs the argv, and returns exit code and `$TL_ARTIFACT_DIR`. Dependencies (uv env, node_modules, build caches) stay in that worktree between runs, which is why this is faster than a tar that unpacks into an empty dir and reinstalls every time. ❌ tar (re-sends everything, reinstalls). ❌ any mount (every file read crosses the network, and the files still sit on the Mac where the scanner sees them). Only committed trees go: this covers gate and land checks (`run_in: clean` already runs committed HEAD); stage checks that read an uncommitted slot stay local. What stays on the Mac: anything needing the Mac or the Unity editor. A down executor fails the check loudly, never falls back to the Mac (single path).
- **Phase 2 ❌ now: remote slots.** Worker, worktree and engine git all on the remote means the Spawner and Git ports get ssh implementations, the delegate accounts must be logged in on the remote (one subscription on two machines, see above), and every engine file read crosses ssh. Worth designing only when phase 1 proves a stage that cannot be a stateless check.
- The executor term (glossary, `planned`) is this host. One more rule: the engine never runs phase-1 work in two places for one check.

**D7 (answered 2026-11-05: the OrbStack Linux machine already set up; `orbctl list` shows the machine `pix` (NixOS 25.11, arm64) running; read over `orb -m pix`: nix-ld is enabled (`NIX_LD` set), git, uv, mise and python3 are installed, `just` is not (shelf pins it as a dev dependency), home `/home/iorlas`, 220 GB free).** Which Linux host first? Options: (A) a Linux machine already running (NixOS/homelab if one is up 24/7) — cheapest, no new bill; (B) a small cloud VM — always on, a monthly cost, needs the repo's toolchain and network egress; (C) a Linux VM on this Mac, reached over ssh like the others — no network, but it shares the Mac's CPU and RAM and ends the hardware split. The check interface is the same for all three, so the first pick is reversible.

## Bead metadata, branch names, PR links (Denis, 2026-11-05)

- ✅ Park reason: bead metadata (typed), as `branch` and `slot` already are; a bd comment has no type and never acts. The `parks/` file goes.
- Landed sha: keep once, in the bead (landing provenance already goes through `bd provenance record`, integrations table; whether it carries the sha is unchecked). Why not branch name alone: the branch and worktree are deleted after landing, and `tl close` (landing must be an ancestor of base) and `tl lost` need a durable pointer. A commit trailer `Bead: <id>` gives the reverse lookup. The `landed/` file goes (single path).
- PR link: ❌ not stored. Task-loop repos land by push to main (`engine.land` default); a repo that needs a PR (shelf) derives it from the branch name (`gh pr list --head <branch>`). Branch name from the bead id by convention, so no link to keep.

## Which asks can be a problem across machines

Ask kinds: decision, stuck, ticket, budget. With the engine on one machine and only checks remote (phase 1), no ask ever crosses a machine. With a second factory working a repo, its asks stay on it (the ask and its answer are working state; the lasting result is an ADR or the bead's change). The one real cross-machine case: an ask whose evidence is a file on the factory machine (screenshots for an `owner-look`, run logs in the ask's detail), answered from another machine's dashboard; the answer path is that factory's dashboard over Tailscale, so the files are served from where they are. No ask body is replicated.

## Windows and Unity (Denis, 2026-11-05)

- ✅ The engine stays POSIX and stays where Denis works (Mac, or Linux). Windows (and any GPU or Unity host) is an executor reached the same way as Linux: OpenSSH, git push to a bare repo there, a persistent worktree, run, return result. **Withdrawn the same day (Denis: "Engine should be able to run on Windows natively. That's even not a discussion. Some people don't have Linux and Mac OS.")**: the engine runs natively on Windows; the audit items (`process_lock` fcntl, stream_proc tree kill, SIGTERM stop, symlink pid index, sh shims) are required work in the shelf packages and engine adapters, not a refusal. ❌ Running the factory in Docker or on the remote PC: the factory is where the owner is; capabilities are executors.
- Checks fit phase 1 (Unity tests on committed trees). The lifesim live scene is different: the worker must run on Windows (a GUI game it edits and runs), which is phase 2, remote slots with Claude/Codex CLIs and a delegate account logged in on Windows. Parked, not designed; the ports (Spawner, Git) stay clean so it stays possible.
- Risk, resolved by reading the machine: nix-ld is present on `pix`, so uv- and mise-installed binaries run. Still to keep: repos live on the VM's own disk, not on the shared `/Users` mount (that would put the Mac's per-file cost back).

## Mirrored executor layout, Windows factory, ADR route (Denis, 2026-11-05)

- Mirror rule (proposal, question M below): the executor keeps the same slot names, repo names and relative layout as the engine's host under one configurable root (`<root>/<repo>/<slot>`), one persistent worktree per slot, so `run_in: slot` checks and slot setup also work remotely and caches stay per slot. Identical absolute paths are possible on Linux (a created `/Users/iorlas`) and impossible on Windows, so the rule is names and layout, not absolute paths.
- Unity on a Windows executor works: the checkout is on Windows disk and Unity opens it natively; ssh and git only deliver the commit. My earlier worry was wrong.
- Two factories, one per OS, are consistent with the one-working-factory-per-repo rule when each repo has exactly one: task-loop and shelf on the Mac factory, lifesim on a Windows factory. They share tasks and results through the git remote (beads, branches); an ask stays on the factory that raised it. A repo whose work needs both OSes keeps one owner factory and sends the other OS's checks to an executor.
- Why there are no ADRs: an ADR exists only when the owner picks the "ADR" outcome ("make it stick", `app/asks/stick.py`) on an answered ask in the dashboard; 13 asks were answered here and none got that outcome. By design the engine and `tl` "never write into a checkout", so ADRs are written under the state dir. Putting them in the repo needs a landing path; see question A below.

## Decisions recorded (Denis, 2026-11-05) - these supersede earlier rows

| Id | Decision (his words where quoted) | Replaces |
|---|---|---|
| M | Executor mirrors slot names, repo names and relative layout under one configurable root, one persistent worktree per slot; setup and `run_in: slot` checks work remotely. Parity is "similar", not one-to-one between Linux and Windows. | |
| A | ADRs are landed as files through a bead; the engine reads them from the base commit. | config-folder ADR store |
| W | Linux executor (`pix`) first, rushed; Windows executor after; native Windows engine after that. | |
| D2 | A task filed from another repo is admitted by factory configuration, like an agent-proposed bead the owner approved up front: auto-admit by default, a profile setting makes a repo wait for the owner. | "his merge is the gate" |
| merge | "Things should be automatically merged unless I'll configure it to be waiting for me." Shelf PRs auto-merge; PRs stay as the review trail. A profile setting (`wait`) holds a repo for the owner. | section 2 "stops at an open PR and never merges", and the standing rule that merge approval is the owner's. Follow-up: the PR-only land mode becomes a PR-and-merge land mode with `merge: auto \| wait`. |
| D3 | Merge the shelf Article IV amendment (commit 0243ce6) before the shelf factory starts, and "the same caps for everything". The amendment as written says the limit is "per-repo, set in the repo's linter", so it does not yet give the same numbers; follow-up: name the shared numbers (task-loop's 400 SLOC per file, 80 per function, 800 per test file, no exceptions list) in the shared linting preset so shelf and task-loop use one set. | |
| D4 | "Shipped" = the shelf change is merged into main. PRs stay but never block. | |
| D5 | Yes: the loop is a continuous worker. A running loop keeps polling when the queue drains (`--wait-drained`, README) and takes any ready, unblocked bead of its repo, by priority, until nothing is ready. Starting a loop stays manual (no OS service); filing does not start one. | |
