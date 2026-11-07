# Stage isolation: hosts, roots, persistence, tests

Status: design, reviewed (opus, section 7 folds the findings in), 2026-11-06 (ARCHVERT; owner directive: isolation of tests, functionality and data, for large-scale parallel development. Installable packages and shelf are NOT goals). Extends docs/design/nodes-and-roots.md. Numbers are from the import graph and an AST scan of `src/taskloop/app` on this date.

## 0. What "isolated" means here (the acceptance test)

A stage is isolated when all five hold, each checked by a tool and not by review:

1. **Imports**: it imports only the kernel and the stages it declares; import-linter fails otherwise.
2. **Behaviour**: it reaches the rest of the run only through ports it declares (small Protocols), never through an engine object it can read any attribute of.
3. **State**: the run state it needs between calls is a type it owns, saved in its own checkpoint section.
4. **Data**: the tables and record types it persists are its own, registered by it, versioned by it.
5. **Tests**: its tests build the stage from its own fakes of those ports, import nothing of the other stages' internals, and run alone (`just test-pkg <stage>`) in seconds.

Lightweight is a number: a stage's forward import closure and the time to import it are capped per stage in the linter (ratchet; today checks 112 files, review 68, write 128, plan 158, land 247, the engine 465).

## 1. Hosts: the problem measured

The engine (`Engine`, a mix of Plumbing, RunParts, LandParts, ...) exposes **232 distinct attributes** that stage code reads as `e.x` / `self.e.x` / `host.x` (AST scan of `src/taskloop/app`). They fall in four groups:

| group | count | meaning | example |
|---|---|---|---|
| used by exactly one stage | 111 (run 68, land 15, review 7, plan 6, look 5, write 3, others 5) | **stage-owned state or handle that lives on the engine** | `look_done`, `look_notes`, `rendered_names`, `shot_cache` |
| used by 4 or more stages | 37 | **shared run context** | `log`, `warn`, `wt`, `cfg`, `run_dir`, `bead`, `steps`, `run_id`, `stores`, `checkpoints`, `comment`, `git`, `home` |
| used by 2-3 stages | ~84 | **cross-stage hand-offs written as attribute reads** | `leftovers`, `plan_data`, `briefs`, `cases`, `unverified` |

The import graph cannot see any of this. Stage code that takes `host: Any` is coupled to the whole engine, and every one of those attributes is an undeclared contract. PR #295 (LookHost) proves the point: look needs 40 members; typing them as one Protocol only makes a typed god object. It is a useful inventory, not the design.

### 1.1 Design: context, ports, owned state

Replace "the stage gets the engine" with three things, each explicit:

**(a) `RunFacts`** (kernel, frozen dataclass): `bead, wt, run_id, run_dir, evidence_dir, home, cfg, dry`, the ~8 facts nearly every stage reads and nobody writes. Built once by the root.

**(b) Ports**: each stage declares in `app/<stage>/ports.py` the verbs it needs, as small Protocols, named for the capability and not for the engine: `Narrate` (note/warn/comment), `StepBook` (begin/outcome/move), `AskAi` (one worker call -> typed answer or a typed refusal), `ChecksRunner`, `TreeView` (changed paths), `Locking`, `Bd`. Rule of thumb: a stage declares at most ~8 ports, and a port has at most ~6 methods. Shared ports that 4+ stages need (`Narrate`, `StepBook`, `RunFacts`) live in the kernel once. The 37 "shared context" attributes become these.

**(c) Owned state**: the 111 single-stage attributes become a `<Stage>State` dataclass in `app/<stage>/state.py`. The root creates it and keeps it in a map keyed by stage; the stage gets only its own. It is saved in the checkpoint as that stage's section (today `run/state.py` and `contracts/checkpoint.py` list `look_notes`, `look_done`, `rendered_names`, ... as engine fields): each stage defines `<Stage>Checkpoint`, the Checkpoint record holds `sections: dict[str, bytes-typed]` decoded by the stage that owns it. Old checkpoints read through a migration owned by the stage.

**(d) Hand-offs** (the ~84): a value one stage produces and another consumes becomes a **return value or an event**, not a field both read. `retry_after` written by look into the engine become a `Pause` value look returns and the pipeline records. `leftovers` becomes `Leftover` records returned by the stage and appended by the pipeline. The consumer's port names what it needs (`FollowupSink.add(leftover)`).

Stage entry becomes constructor injection: `Judge(facts, ports, state)`, not `Judge(engine)`. No `Any` host survives; `except e.Blocked` becomes a typed result or exception owned by the stage.

### 1.2 Look as the worked example (40 members of PR #295 classified)

| | members | goes to |
|---|---|---|
| owned state (11) | look_done, look_notes, look_filed, look_retried, look_unjudged, rendered_names, shots_skipped, shot_cache, artifact_repo, last_reqs, render_stale | `LookState` + `LookCheckpoint` |
| run facts (13) | bead, bead_parent, bead_title, wt, run_id, run_dir, evidence_dir, home, cfg, dry, at_stage, writer_family, last_flag | `RunFacts` (+ writer family passed as an argument) |
| ports (11) | log, steps, budget.labels, store, ai, comment, warn, now, sh, checkout, checkpoints, waits.locked | `Narrate`, `StepBook`, `AskAi`, `Bd`, `Locking`, `TreeView`, `Clock` |
| hand-offs (5) | cases (from plan), stage_checks, leftovers, unverified, retry_after/pause_* | arguments, return values, `Pause` |

After this, `look` takes about 7 ports and a state object; the Engine root builds them. The look test builds `Judge` with fakes of those ports (the pilot of CheckHost in #285 is this idea for checks).

## 2. Roots: making them thin, and keeping them thin

Definition: a root only **constructs and binds**. It may import any node; nothing imports a root; it holds no rule, no branching on domain data, no loop over domain data.

Today's shell is fat: `run` + `loop` + `launch` + `wire` + `prune` = 113 files / 10,157 sloc, about 4,060 wiring and about 6,100 logic. Split:

- **node `pipeline`**: `stages`, `closer*`, `steps`, `budget`, `blocked`, `waits`, `reload`, `reflect`, `requests`, `resume`, `stuck`. It sequences the stages through their ports; it owns the run's step order and the close. It imports the stage ports, never the Engine.
- **node `workers`**: `worker_call`, `worker_request`, `delegation` (the AI-call machinery and delegate glue, today about 14 app importers of `adapters.delegate`): the one node that talks to the delegate library; every stage gets it as `AskAi`.
- **node `loop`**, **node `prune`**: stay, each with its own ports (`Claim`, `Take`, ...). `loop/take.py` imports 3 stages today and is a root-shaped file inside a node: it moves to the root or takes ports.
- **roots**: `engine` (construct pipeline + stages + states, bind ports), `entry`, `run_once`, `launch/*`, `wire/*`, `cli`, `hook`, `tl.py`.

C-THIN (a), tl-e5t0.40.1: `run/ask_flow`, `bead_env`, `closer_ports`, `preflight`, `reload_ports`, `shared`, `shell` and `stage_checks` are composition files: they bind ports across slices and stay in `run/`. The proposed composition classification of `stage_rounds`, `stage_run`, `review_glue` and `running` is blocked by imports from `run.stages`, `run.state` and `prune.verb`; they remain logic sources in `nobody-imports-a-root`. `stages`, `state` and `target` keep their existing classification. No import exceptions are widened.

Keeping them thin, mechanically:

1. import-linter: nodes never import roots; roots are leaves of the graph (a `forbidden` contract per root package).
2. A change ratchet per root file (AST): branches (`if/for/while/try/match`), functions over 25 sloc, and sloc are compared with the merge base for each changed root file; new root files count from zero, so they are frozen too. A deliberate rise requires `Ratchet-allow: root +N reason`. No baseline or total is stored. Measured 2026-11-07: **78 root files, 4,471 sloc, 425 branches, 15 long functions, and 151 Engine attributes** (distinct annotated fields, self assignments and properties across Engine and its bases). The goal is under ~1,500 root sloc: 2,972 sloc must go to reach strictly under 1,500. Run `uv run python dev/root_report.py` for the current totals and 10 worst files; move rules into nodes to bring the roots down.
3. Root files may hold no class with behaviour: dataclasses and factories only.

## 3. Persistence: stages own data, the db package routes and checks

Directive: entities, DTOs and schemas belong to the stages; one db package routes to sqlite and projects; the app **fails on launch** if anything changed.

### 3.1 Ownership

Each stage owns, in `app/<stage>/store.py`: its record types (msgspec), its tables (DDL), its migration steps, its prune rule, its read API.
Examples (from the opus read of `writer_invariants` and the stores, to be verified per stage in the PRs): gate: check_pass, check_round,
durations, check_run; asks: ask, ask_ledger, park; slots: locks, tickets, worktrees, leases; release: pins, results; report: reflect state;
work: adr; land: followups; pipeline: run, attempt, effects, signals, waits, checkpoints, run log, traces; workers/lanes: status, usage;
dash: source, bead, events. `kv` stops being a shared prefix grab-bag: each user gets a table or a typed `Doc`. Parks now live in the
asks-owned `park` table, separately from pipeline `wait` rows. `ParkStore`, written by asks, loop.take and run.stages, gets one writer
(asks) and the others call its port.

### 3.2 The db package (`taskloop_db`, a kernel)

It knows nothing of any record. It provides: connection (open, WAL, `begin_immediate`, `cas_update`, quarantine), the generic doc/log primitives, a **part registry**, a migration runner, a prune runner, and **projections**. One sqlite file stays (single-transaction prune and the dashboard's joins need it).

```
Part(name, version, ddl, steps: {to_version: fn}, records: [RecordType], prune: [Predicate])
register(part)        # at import of the stage's store module
open(path)            # the launch gate below
```

### 3.3 Fail on launch

`open()` runs before anything else touches the db (engine, loop, dashboard). For every registered part it compares three things with the `schema_part` table (name, version, ddl_fingerprint, record_fingerprint):

| state | action |
|---|---|
| part not in db | create its tables, write its row |
| db version < code version | run the part's migration steps in order, in one transaction, then update the row |
| db version > code version | **refuse to start** ("this code is older than the data of part X") |
| same version, `ddl_fingerprint` differs from `sqlite_master` | **refuse** ("table T changed without a version bump") |
| same version, `record_fingerprint` differs | **refuse** ("record R changed without a version bump") |

`ddl_fingerprint` = hash of the normalised DDL of the part's tables. `record_fingerprint` = hash of `msgspec.json.schema` of the part's
registered record types. A second, earlier guard runs in the test suite: each part commits a golden `fingerprint.json` per version; a test
fails when the code's fingerprints differ from the golden of its declared version, so a schema or DTO change cannot reach `main` without a
version bump and a step. The dashboard declares which parts it reads and from which version (`needs = {"gate": 2, "pipeline": 4}`); it
refuses to start against a part below that, with no global schema read floor.

Existing database: the first launch of the new code migrates `schema_part` from `PRAGMA user_version = 5` to version 1 of every part at today's shape (a database migration, not a legacy reader); the global `user_version` is then frozen.

### 3.4 Projections

A read model that crosses stages (the dashboard's run list; `run_rows` today sits in the kernel as the engine's published read model) is a **projection** registered by its owner over the parts' public row views: it names the parts and versions it reads, so the same launch check covers it. The projection code lives with the reader (dash), not in the db package.

### 3.5 Hard parts

- Cross-part transactions (`factoryprune`: ask_ledger by run eligibility, run delete checks attempt): the prune runner takes each part's predicates plus declared dependencies (`attempt` before `run`) and runs them in one transaction.
- The single-writer ratchet (`tests/rules/writer_invariants.py`) hard-codes `taskloop.app.*` paths and wrong owners for four stores; it is rewritten with the moves, in the same PRs.
- The vendored `sqlite_store/migrate.py` keys on one version; a per-part runner is new code (here, or a shelf change if the shelf wants it).

## 4. Tests: independent bases

- Each stage has `tests/<stage>/` plus a `testing.py` shipped by the stage with fakes of **its own ports** (FakeCheckHost is the first). Other stages' tests import `testing.py` of a dependency, never its internals.
- Contract, then consumers (already the rule): one conformance test per port runs the Engine's adapter and the stage's fake through the same probes; a mutation of the fake must fail it (the #285 gate).
- `just test-pkg <stage>`: the stage's tests plus its declared dependencies' contract tests, nothing else. `dev/affected.py` stops being the only gate for stage changes: a stage change runs its own base and its dependents' contract tests. The engine/e2e base stays small (10 tests max by the existing rule).
- Per-stage budgets: closure size and import time ratcheted; a stage whose closure grows fails with a name.

## 5. Order of work (each PR small, measured, reversible; none moves `paths.py`, ids or the run layout before #219/#232 land)

1. **Inventory and conformance** (done for look, #295; checks pilot #285). Keep `host_conformance` as a ratchet.
2. **Kernel pieces**: `RunFacts`, shared ports (`Narrate`, `StepBook`), the checkpoint `sections` mechanism with old-checkpoint read, root-lint test (report only, then ratchet).
3. **Per stage, in this order: look, review, write, plan, land**: introduce ports + `<Stage>State`/`Checkpoint` section, change the stage to constructor injection, delete the stage's attributes from the engine, convert its tests to its fakes. One PR per stage, reach reported (stage closure and number of engine attributes removed).
4. **Split the shell**: `pipeline`, `workers` out of `run/`; `loop/take.py` onto ports; root-lint ratchet on. The import-linter node/root contracts land in the same PR.
5. **Persistence**: `taskloop_db` kernel with the part registry and the launch check first (behaviour-preserving: every table registered as part `legacy` v1, the golden fingerprints committed); then one stage's tables per PR (gate, asks, slots, release, report, work, land, pipeline, dash), each moving its records, DDL, steps and prune rule; `kv` decomposed last.
6. **Packages**: only now `packages/<stage>` moves, mechanical, because each stage is already closed.

## 6. Open points for the owner

- The checkpoint becoming a map of stage sections changes the on-disk format (with a read migration). OK?
- Is a 5-line "port" file per stage acceptable overhead, or should shared ports be consolidated at the cost of wider interfaces?
- Root-lint strictness: forbid all branching in roots (clean, but may force small helper nodes), or ratchet branch count? Proposed: ratchet.
- Persistence step 5 touches `paths.py`-adjacent names (`ConfigDir`, run locations): sequence after #219/#232.

## 7. Review findings (opus, checked against the code) and what changed

The first draft was wrong or incomplete in these places; the sections above are to be read with these corrections, which win.

1. **Checkpoint format is the riskiest step, so it is last, not second.** `contracts/checkpoint.py` says an old-version checkpoint "reads as absent: nothing is migrated" (`wire.load` raises `StaleRecord`). Readers of a new format: `reload.safe_point` (execs a run into a newer install mid-run), `versions.py` (rollback to the old install), a dead close (`Engine.__init__`, `ended.unfinished`). A format change drops every in-flight checkpoint, including `ended`/`applied`, so an unfinished close is lost; that is accepted (compat.md). Even so: **ports and stage-owned state first, with the checkpoint on disk unchanged** (the pipeline composes the existing `RunState` from the stage state objects); the on-disk change happens once, at the end, with no compatibility step (point 3).
2. **The close must not depend on stage sections.** One record, one fenced write (`Checkpoints.save` deep-copies `RunState` plus `review_of(e)` in one CAS write; `keep_look`/`keep_pending`/`keep_filed` amend several parts in one write). So the checkpoint stays one record. A separate typed **`CloseIntent`** (today's `EndRec`, extended to carry the `Pause`, the owner-look payload and the leftovers) is all a restart needs to finish the close; the close never decodes stage sections. Sections may hold resumable stage progress only, and each declares an explicit `restart()` keep-rule that replaces `RunState.start_again` (called from `land/restart.py:93`); `save`'s forced step `land-verify-red` while `pending_land_validation` is set moves with it. `Closer.resume -> finish -> pause` reads `retry_after`, `pause_reason`, `pause_producer`, `stats` from a fresh engine today (`closer.py:124-160`): the `Pause` value must go into `CloseIntent`, or it fixes nothing.
3. **No backward compatibility** (`docs/design/compat.md`): a format change is made directly; a foreign checkpoint or part is refused loudly (`StaleRecord`) and the run starts over; no N-1/N+1 readers, no expand-then-contract.
4. **Fingerprints are a guard, not a compatibility proof.** `msgspec.json.schema` includes descriptions, titles, `$defs` names, defaults and field order, and can change with a msgspec upgrade (false positives); `Open = dict[str, Any]` fields (`plan`, `snap`, `last_reqs`, `leftovers`) show only as "object", `EndRec.spec` is JSON in a string, and `kv`/`checkpoint` bodies are TEXT, so the DDL hash never sees them (false negatives). Changes: the golden test strips descriptions and titles; it fails when the schema changes while the record's existing **`Rec.V`** does not; persisted records may not gain new `Open` fields; the launch check compares `Rec.V` and the DDL fingerprint, not the raw schema hash.
5. **The attribute classification was by "which dirs mention it", not by who reads and who writes.** Corrections: `render_stale` is written by write (`write/write_round.py:44`) and read by the pipeline (`run/run_once.py:104`): a hand-off. `artifact_repo` is a memoised repo key used by `ask_flow`, `write_round`, `worker_request`: a run fact. `look_notes`, `look_unjudged`, `unverified` are read at land/close by `owner_look`. The counts in section 1 (111 single-stage; look 5 or 11) are unreliable: bead ATTR-MAP redoes it per slice by reads and writes before any stage is converted.
6. **`worker_call` writes other stages' state**: `writer_fallback`/`fallback_lane` (`worker_call.py:129,328`), `planner_ref` (`:398`), `last_flag` (`:399`). `AskAi` returns a **typed result** carrying session, fallback and ref updates, and the caller persists them in the same atomic write as `done_memo.keep` (`:394`), or a crash loses them.
7. **Engine wiring needs an acyclic build order first.** `RunParts` holds 36 `cached_property` parts taking `self`, only 3 with construction-time edges (measured in `engine-order.md`); `RunHost` adds `worker`/`closer`; `Checker(self, ...)` is built at `engine.py:101`; (corrected: `land_fields()` has one caller, `RunFields.__init__`, so `Checkpoints` is created once; it is not a mid-run reset) the closer needs `worker.saved`. Constructor injection needs a written build order with the lazy cycles removed (bead ENGINE-ORDER) before any stage is converted.
8. **Persistence additions**: `OWNERS` is in `contracts/factorydb.py:88` and records which *process* writes a table (index/engine/loop/owner); `tests/rules/test_dash_engine_sql.py` depends on it. Keep it and add stage ownership beside it. Also owned by a part and missing from the first list: `CallState` (`stores/call_state.py`, a receipt in `effect` with a file fallback and its own `v`), the `RunCounters` docs (`reload.py:46`), the done-memo copy (`reload.carry_done_memo`, raw SQL across runs). Threads read engine state concurrently (`ThreadFlag`, the stuck tick, `live_now`): their reads go through the same ports and get a thread-safety note per port.
9. **`just test-pkg` is a developer tool, not a second gate** (CLAUDE.md: `just test` is the only gate).

Revised order: ATTR-MAP and ENGINE-ORDER first; then RunFacts/ports; then stages (look, review, write, plan, land) with the checkpoint untouched; then the shell split; then CloseIntent and, only then, the checkpoint format and per-part persistence; then `packages/`.
