# Nodes and composition roots

Status: assessment, 2026-11-06 (ARCHVERT, owner directive: stage packages are GO, goal is isolation, import-linter guards every edge, composition roots as thin as possible). Numbers are `dev/reach.py` / `dev/affected.py` graph facts from this date.

## Vocabulary

- **Node**: a stage's logic. Imports only the kernel, lower layers and its declared neighbours; never the engine; takes what it needs of its caller as a typed Protocol (the `CheckHost` pattern).
- **Composition root**: code that only builds nodes and hands them to each other (constructs, binds Protocols to the concrete engine, parses argv). May import everything; **nothing imports a root**. A root holds no rules.
- **Kernel**: contracts every node shares (`contracts/`, minus the stage-owned ones that move out).

## What the code is (measured)

1. **The stage nodes are already nearly clean.** Direct `app/` edges between stages (files importing a file of another stage): land -> gate 14, land -> asks 4, land -> slots 6, work -> gate 8, work -> asks 6, release -> gate 3, report -> asks 2, report -> release 2. Nothing else. gate, slots, asks, track, doctor import no other stage at all. Only the shell (`run`, `launch`, `wire`, `loop`, `prune`) imports many (asks 33, slots 45, release 33, track 29, land 27, gate 26, work 24, doctor 12, report 4).
2. **Nobody but `cli`/`hook` imports the shell.** Inbound edges to `run/launch/wire/loop/prune` from non-shell: cli 58, hook 4, no stage. So the shell already behaves as one root above the nodes.
3. **But the shell is not thin.** `run` 61 files / 5,725 sloc, `loop` 18 / 1,736, `launch` 15 / 1,243, `wire` 13 / 1,177, `prune` 6 / 276: **10,157 sloc, of which about 4,060 is wiring by name** (launch, wire, `run/entry|engine|run_once|parts_*|plumbing|stages|host|context|layout`) and about 6,100 is logic living in the root: steps, budget, blocked, closer, worker_call, shell, waits, reload, reflect. Only 17 of its 113 files import 3 or more other stages (the true roots: `wire/doctor`, `run/run_once`, `launch/loop`, `run/entry`, `launch/dash_ports`, `run/worker_request`, `run/stages`, ...).
4. **The import graph under-reports coupling.** Stage code takes the engine as a duck-typed host: files that read `e` / `host` typed `Any` or via `self.e`: write 8 of 12, plan 8 of 11, review 4 of 5, look 3 of 4, land 17 of 34 (79 Protocols already exist there), run 32 of 61; checks 0 of 22 (10 Protocols), slots, asks, release, report, track, doctor, launch, wire, loop: 0. So the work stages and half of land reach into the engine through attributes no linter sees. That, not imports, is what blocks isolating plan/write/review/look.
5. **One persistence kernel is the only real shared coupling** (see below).

## Classification

| module | class | note |
|---|---|---|
| `cli/*`, `hook/*`, `skills/task-loop/tl.py` | root | already thin by rule |
| `app/launch/*`, `app/wire/*` | root | 2,420 sloc; wire is the binding of nodes to ports |
| `app/run/{entry,engine,run_once,parts_*,plumbing,fields,host,context,layout}` | root (Engine = the binding of every Protocol) | the part that must shrink to construction only |
| `app/run/{stages,closer*,worker_*,steps,budget,blocked,waits,reload,reflect,shell,...}` | **node: the pipeline** | logic; today inside the root's folder |
| `app/loop/*`, `app/prune/*` | node (loop orchestration, prune) | loop is a node with a root-shaped `take.py` |
| checks (gate), land, slots, asks, release, report, track, doctor | node | clean already |
| plan, write, review, look, artifacts | node (**work**) | blocked by `Any` host |
| `delegate`, `tldash` | already separate top-level packages | keep; add contracts |
| `contracts/` | kernel + stage-owned contracts mixed | 22 single-consumer contracts move to their stage (C3) |

## Target

```
roots:    cli · hook · tl.py · launch · wire · engine (the Engine class and its Protocol bindings)
nodes:    pipeline · loop · prune · gate · land · slots · asks · release · report · track · doctor · work · (dash) · (delegate)
kernel:   contracts (shared records) + taskloop_db (connection, migrations runner, log/doc primitives)
```

Rules (import-linter, one contract each): roots may import nodes, nodes never import roots; `layers` among nodes from the measured edge list (land > work > gate/asks/slots, release > gate, report > asks/release; gate, slots, asks, track, doctor independent); each node imports the kernel and other nodes only through their `api` module (`forbidden` for the rest); every node's host is a Protocol in the node, never `Any`.

Documented exception: `hook/prepush.py` stays a root with its branches by design: the git hot path is stdlib-only and imports no record (see .importlinter `hot-hook-path-is-light`), so it is not folded into a node.

## Persistence (Denis: "does one store package defeat isolation?")

Opus read (this session, verified on the repo): **yes, as long as there is one schema.** `contracts/factorydb.py` is one `DDL` (16 tables),
one `SCHEMA_VERSION=5`, a global reader floor (now replaced by declared part needs) and `factorymigrate.STEPS={2,3,4}` on one `PRAGMA
user_version`. A gate column change edits the kernel DDL, bumps the global version and can break the dash's read floor. Moving store classes
into stages while keeping that file only moves the problem. Recommendation: **(b) plus a schema split**:

- kernel `taskloop_db`: open/WAL/`begin_immediate`/`cas_update`/quarantine, the doc/log primitives, a **part registry** (each stage registers `Part(name, ddl, steps, version)`; versions go in a `schema_part` table; the global `user_version` freezes), a prune registry.
- each stage owns its tables and stores: gate (`check_pass`, `check_round`, durations, `check_run`), asks (ask, ask_ledger, park), slots (locks, tickets, worktrees, leases), release (pins, release result), report (reflect state), work (adr), land (followups), engine (run, attempt, effects, signals, waits, checkpoints, run log, traces, bad-versions, repos, `run_rows` read model), dash (source, bead, events). The `Stores` bundle is the composition root.
- one sqlite file stays (single-transaction prune and the dash's joins need it); no per-stage db files.

Facts that make it harder: `kv` is a prefix grab-bag written from 6 stages; `ParkStore` has 3 writers (asks, loop.take, run.stages), which breaks single ownership under any option; `OWNERS` (`contracts/factorydb.py:88`) labels `check_pass`, `check_round`, `ask`, `ask_ledger` as "engine": that is the writing process, a different axis from the stage that owns the data (stage ownership is added beside it); `factoryprune` deletes across tables in one transaction; the ratchet hard-codes `taskloop.app.*` paths and must be rewritten in the same PR as the move. The migration runner (vendored `sqlite_store/migrate.py`) keys on one version, so part registration is code work (here or in shelf), not a file move.

## Shelf and isolation

The earlier "no second consumer, so not shelf" argument measured reuse. Under an isolation goal the criterion changes: a node with a closed Protocol surface and its own tests can be a separate distribution (own `pyproject.toml`, uv workspace member) with import-linter forbidding the rest. That is a packaging step after the packages are real; `delegate` (own top-level name, `delegate.api` only) is the first candidate and still waits on DELEGATEHOME (tl-w7lt.37, not decided here).

## Order (each one PR, none touches `paths.py` while #219/#232 are held)

1. **Protocol hosts for work** (plan, write, review, look): replace `Any` hosts by Protocols in each stage, Engine satisfies them; contract test Engine-vs-fake per Protocol (the CheckHost pilot, #285).
2. **Split `run`**: pipeline node (`stages`, `closer*`, `worker_*`, `steps`, `budget`, `blocked`, `waits`, `reload`, `reflect`, `shell`) out of the root; root keeps `engine`, `entry`, `run_once`, `parts_*` and shrinks to construction.
3. **import-linter**: node/root contract + the layers contract of the measured edge list, in the same PR as step 2.
4. **Packages**: `packages/<stage>` for gate, slots, asks, release, report, track, doctor first (zero inbound from other nodes except listed edges), then land, work; each with `api.py`, own tests, own linter contract.
5. **Persistence parts** (`taskloop_db` kernel + registry) before any stage that owns tables moves, one stage per PR.
