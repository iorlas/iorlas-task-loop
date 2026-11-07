# Architecture review: vertical stage packages (2026-11-06)

Bead tree: epic ARCHVERT. Status: ROUND 1 (one reviewer); the second-review section at the end folds in disagreements.
Directive (Denis, 2026-11-06): every stage a well-encapsulated package with its own src, tests and public surface; contracts owned
by the stage, not spread; more vertical; split sub-packages and shelf where it pays; independent test bases instead of affected-test
selection. Verdicts: ✅ do, ❌ refuse, ⚠️ do later or only in part. All numbers are measured on 99154664 (origin/main has since moved; numbers are not re-run) by
parsing the tree with `dev/affected.py`'s own graph (`Repo`, `select`, `closure`); method at the end.

## 0. Verdict in six lines

1. The tree is **horizontal**: 5 layers (contracts, domain, adapters, stores, app) each hold a piece of every stage. Stage `checks`
   lives in `app/checks` (1816 sloc), `domain/checks` (1130), 4+ `contracts/*.py`, `tests/checks`. `import-linter` enforces the layers,
   not the stages.
2. **Contracts are the main cause of the wide test runs (75% of the wide-alone files).** Of the last 119 first-parent commits, 45 select ≥ half of the 584 test
   files. In those 45, 61 changed files alone select ≥ half; 46 of the 61 (75%) are `contracts/*.py` (`config.py` 8, `stores.py` 5,
   `paths.py` 4, `envvars/factorydb/docrows/looprows` 3 each, ...), 8 are conftests, 7 vendored/adapters/support. Not the engine, not the dashboard.
3. Selection today: median 271 of 584 tests (47%), p90 = all 584. Closure per test: median 393 files, p90 905, max 1159.

   Measured with `dev/reach.py` on 2026-11-07 across 37 commits and 774 tests: median 268, mean 333, p90 774. The median is set by
   `tests/conftest.py`, `tests/live/conftest.py`, `tests/delegate/conftest.py` and `tl.py` edits selecting half the suite, not by package
   selection; the public-surface rule changes nothing until a package has an `api.py`.

4. The stages are already nameable and mostly separable: `delegate` and `tldash` already are packages. Cutting two import edges
   (`adapters/delegate.py`, `adapters/runner.py` → `delegate.api`) drops `delegate.api`'s reach from 199 tests to 2. That is the proof of
   what a real package boundary does; it is also the proof that **one boundary alone does not move the median** (271 → 269): the hub is
   `contracts/`, so the contracts move first.
5. Do it as **vertical packages inside this repo, top-level import names, same sys.path model** (like `delegate` and `tldash`
   today), NOT separate repos, NOT a uv workspace with installs, NOT a shelf move of the stages. Shelf gets a few small leftovers only.
6. Order: kill hubs first (measure tool, config split, stores/ports split), then carve packages from the leaves inward
   (dash, delegate, gate, land, release, slots/asks, loop/engine last). Never in the middle of #189/#190/#186/#187.

## 1. Stages and what each looks like as a package

Measured sloc (non-blank, non-comment). "Today" gathers the stage across layers by folder name; the `tests` column is test files.

| stage | today (src) | sloc | tests | cross-stage imports out (direct, src) | verdict |
|---|---|---|---|---|---|
| dash | `tldash/` | 3869 | 49 | contracts only | ✅ already a package; its input is row contracts (see §2) |
| delegate | `src/delegate/` | 6746 | 74 | none of taskloop | ✅ already; only `adapters/delegate.py`, `runner.py` + `contracts/delegate*.py` bind it |
| store | `stores/` + `contracts/{*rows,stores,factorydb,docstore,factorymigrate,factoryprune,...}` + vendored `sqlite_store` | 457 + ~2500 | 7 | adapters, contracts | ✅ package `taskloop_store`; owns every row shape |
| gate (checks) | `app/checks` + `domain/checks` + `contracts/{checks,gateplan,plancheck?}` | 1816 + 1130 + ~250 | 43 | store | ✅ leaf-ish, carve early |
| land | `app/land` + `domain/land` + `adapters/{landlock,git_ops,git_pool}` + `contracts/{scratch,gitfacts?,profile_changes}` | 3014 + 44 + ~250 | 42 | asks, checks, slots, store | ✅ after slots/asks |
| release | `app/release` + `app/reconcile` + `domain/reconcile` | 874 + 391 + 295 | 8 | checks, store | ✅ |
| slots | `app/slots` + `contracts/{slots,slottable,worktree*,lockrows}` | 1039 + ~300 | 18 | land (back edge), store | ✅ after the back edge is cut |
| asks | `app/asks` + `domain/asks` + `contracts/{ask,askrows,answers}` | 800 + 323 + ~450 | 18 | domain | ✅ |
| work (plan, write, review) | `app/{plan,write,review,look,artifacts}` + `domain/{plan,review,write,prompts}` | 906+860+534+496+357 + ~1200 | ~35 | gate, asks only | ✅ **one package `taskloop_work`** (review: nothing in it imports run back; run imports it 27 times). Not split further yet: plan↔review is a cycle (review→plan 4 edges, all `domain/plan/matchers`) and write→review is 9 edges |
| shell | `app/run` (engine, 5707, imports 14 slices) + `launch` + `prune` + `wire` + `loop` | 5707+1222+188+1147+1714 | ~190 | everything (composition) | ⚠️ stays `taskloop`: it is the composition root, with the closer. The linter already orders it on top (`app-slices-acyclic`). Not a stage; `cli` and `hook` stay beside it |
| small below the shell | `track`, `doctor`, `report` | 375, 100, 561 | ~17 | asks, reconcile | ⚠️ own small packages only if a second consumer appears; else stay in the shell tree |
| kernel | `contracts/{wire,ids,enums,paths,env,envvars,identity,bead}` | ~711 | 31 | none | ✅ minimal; §2 |
| hook | `hook/` | 213 | 5 | wire (+contracts) | ✅ stays, plain python3, never imports msgspec |

Option judgments:
- ❌ **One package per current app slice (15 packages).** `track` is 375 sloc, `doctor` 100, `prune` 188: package overhead (tests dir, public
  surface, layer rule, docs) costs more than the stage. Merge into loop/engine until a second consumer or 1500 sloc.
- ❌ **Separate repos per stage.** Release is one script on one tree (`dev/release.py`, MANIFEST), the closure of a bead's change is one
  PR; N repos multiply the drift the delegate move just ended (topology.md §5).
- ❌ **uv-workspace members with `pyproject.toml` and installs** (the shelf model). The plugin ships a tree and `tl.py` puts `src/` on
  sys.path (tl.py:77); PEP 723 pins must equal pyproject (tests/rules/test_pep723.py). Installing members means a build step in the plugin
  path and a second pin table. The **import-name** boundary gives the same isolation: `delegate`, `tldash`, `stream_proc` already work this way.
- ✅ **Top-level packages under `packages/<stage>/{src/taskloop_<stage>/, tests/}`** (the multiple src folders Denis asked for), put on
  sys.path by `tl.py`, `hooks/hook.py` and `dev/*` (review: there is **no** path hook to reuse, `src/taskloop/__init__.py:11-13` only appends `_vendor`, and its lazy filter at `:16` names only `taskloop`, `tldash`, `tl`, so a new package must be added there or it imports eagerly and may surface cycles lazy-all hides); `src/taskloop` shrinks to the shell. `delegate` and `tldash` move
  there last (path change only).
  - Namespace packages (`taskloop.gate` split across dirs) are ❌: `taskloop/__init__.py` installs the lazy-import hook and the vendor path;
    a namespace package has no `__init__`.
- **Mechanics checklist** (review, all hard-code `src` or the package names today): `tl.py:77`, `hooks/hook.py:15`, `dev/release.py:40`, `dev/{dash_fixtures,dash_profile,race}.py`,
  `tests/delegate/hermetic.py:13`, `tests/support/paths.py:14-26`; runtime `app/launch/dash.py:23,160` (dash child PYTHONPATH), `app/loop/versions.py:34` (install_key sees only `src`:
  a change under `packages/` would go unnoticed), `app/release/selfupdate.py:14` (now compares all of `src`, `packages`, and `dev/release.py`); tests `tests/conftest.py:44-90,140-143` (preload walks `taskloop` only; the test kind is
  decided from the path under TESTS_DIR), `pyproject testpaths=["tests"]` (so `packages/*/tests` are not collected and get no guards); selection `dev/affected.py:48-50,171-195`,
  `dev/runtests.py:155`, `tests/support/scope.py:13`; `pyrefly.toml:3,7,20`, `ruff.toml:5` + nested ruff.toml, `justfile:70`, `.importlinter` (root_packages, `msgspec-in-contracts-only`, `hot-hook`); `tests/rules/gate_rules.py:45,132,155,278,301,310`
  (SCAN has no `packages`: **the 400/80/800 caps silently stop applying there**), `arch_rules.py:16`, `temp_ratchet.py:12`, `layer_ratchet.py:28`; ~20 tests build `ROOT/"src"/"delegate"` or `"tldash"`.
  MANIFEST needs nothing (hashes every tracked file); PEP 723 pin equality is unaffected.
- **Rule conflicts to amend in S1a:** CLAUDE.md says "Tests live in `tests/<slice>/`" and the layer-by-path guard keys on it → amend both; per-package `contracts.py` must be a **`contracts/` directory**
  with its own `ruff.toml` (the TID251 bans on subprocess/socket/threading are directory-scoped, per-file ignores are forbidden); `hot-hook` must also forbid the kernel and every package `contracts` (it names `tlkernel` only).
- ✅ **Public surface of a package = `api.py` (functions + Protocols the package offers) and `contracts.py` (records it exchanges),
  `testing.py` (its fakes).** Other packages import only these three names (`taskloop_land.api`, `.contracts`, `.testing`). Enforced by one
  import-linter `forbidden` contract per package pair set; same pattern as `taskloop-does-not-import-delegate` already in `.importlinter`.
- ❌ **One more layer (ports/) shared by all.** `contracts/ports.py` (403 sloc: Clock, Sh, Delegate, Beads, SlotGit+Git ~230 lines, Checks, Spawner) is
  exactly that grab-bag; it is why 21 contract importers see everything. Each Protocol goes to the stage that **consumes** it or the adapter
  package that provides it (§2).

### Cycles (review-corrected)

**Point zero.** The app slices are already acyclic: `.importlinter` contract `app-slices-acyclic` orders launch > prune > run > wire > loop > land >
write|review|plan|look > report > reconcile > release > checks > track|doctor|artifacts > slots > asks. My first cycle table came from grouping slices on
both sides of that order into one stage ("engine" = run+plan+...), plus `domain/*`, which the linter does not order. With the grouping above (run in the
shell, plan/write/review/look/artifacts as `work`) the engine↔land and engine↔loop cycles disappear with zero moves: land→work is 4 edges, work→land 0,
work imports only gate and asks. (An earlier draft proposed moving `closer_*` into land; refuted: the closer imports run internals, `closer_decide.py:9`,
`closer_notes.py:9`, `closer_record.py:5-7`, `closer.py:13`, and run consumes it back. The closer stays in run.)

Remaining cuts (direct src imports, re-counted by the reviewer):

| pair | edge | cut |
|---|---|---|
| land → work back edges | `land/fix.py:18-20` → `domain/prompts/land`; `land/record.py:9` → `domain/review/followups` | move those two domain files into land (2 files) |
| land ↔ slots | `slots/reset.py:16` imports `NetText`, a git network-error matcher used by land, slots and `loop/verdict.py:12` | `NetText` lives in `tlkernel.matchers` (1 file); not "slots owns matchers" |
| release ↔ report | `reconcile/commits.py:12`, `observe.py:26` → `domain/report/matchers` vs `report/card.py:12` → `reconcile/lost`; the matchers are also used by `run/records.py:27`, `domain/outcome.py:29` | matchers to a shared home (gate or kernel), not into reconcile |
| shell → release | 8 loop files import release (`loop_ops`, `loop_start`, `selftest`, `prune/verb`, `report/card`, `wire/brief`, `wire/doctor`, `launch/loop`); `run/engine.py:11`, `reload.py:13`, `entry.py:23` → `reconcile/leases` | allowed (shell is on top); `leases` is the one engine-used piece: leases belong to slots; their Part is declared in `tlkernel.factoryparts` |
| kernel → stage | `contracts/{stores,runrows,checkpoint,finish*,rundocs,adrs}` import upward through record types | records move to owners (§2) |

## 2. Contracts: owner of each, minimal shared kernel

Measured on `packages/kernel/src/tlkernel` (90 files, 7905 sloc): consumers per file counted over direct imports from other src slices.

| bucket | files | sloc | rule | verdict |
|---|---|---|---|---|
| no direct src slice importer | 7 (`attemptrows, dashenums, docstore, factorymigrate, factoryprune, row, usage`) | 285 | **not dead** (review): internal pieces of other contracts (`factorydb.py:18,111,121`, `runrows.py:87,140`, `stores.py:36`, `dash.py:13`) | ⚠️ inline candidates into their one parent, no deletion |
| exactly 1 consumer slice | 22 | 1149 | moves **into that slice**'s `contracts.py` (or the package) | ✅ mechanical. 9 of them have `tldash` as the only consumer: they are the **read model the store publishes** → owned by `taskloop_store` (writer owns the shape), dash imports `taskloop_store.contracts` |
| 2–3 consumers | 21 | 1232 | the **producer** owns, consumers import its `contracts` | ✅ by hand, one PR per stage |
| 4–8 consumers | 24 | 2734 | owner is the stage that creates the value; consumers via `api` | ✅ per stage |
| 9+ consumers | 15 | 2420 | kernel candidates; most are NOT kernel | see below |

The 9+ bucket, judged. Kernel = what has no owner stage because **every** stage speaks it:

| file | sloc | importers (contracts/src) | verdict |
|---|---|---|---|
| `wire.py` (Rec base) | 71 | 54 | ✅ kernel |
| `ids.py` | 96 | 26 | ✅ kernel (bead, run, slot ids) |
| `paths.py` | 287 | 21 | ✅ kernel **after** LAYOUT lands (#189 makes it the only naming point of the state tree); until then do not touch (§6) |
| `enums.py` | 115 | 11 | ⚠️ split (corrected by review): kernel keeps `Outcome/Result` at most; `Step`, `WhyCode`, `WaitWhat` → engine (`Step` is used by run, tl.py, dash only); `Cause` → dash read model; `LockWhat` → store; `Ask*` → asks; `CheckStatus` → gate |
| `bead.py`, `env.py`, `envvars.py`, `identity.py` | 44+44+39+15 | 13–14 | ✅ kernel (small, stable) |
| **`config.py`** (profile) | **370 nbnc** | 16 slices | ❌ **not kernel**; 8 of the 45 wide commits were this file alone. **Not splittable by moving fields** (review, config.py:187-267, 361, 388, 444-449; wire.py:38): `EngineConfig` is one flat ~75-key struct, `Rec` forbids unknown fields, and load-time validators cross sections (checks×resources, input_sets, command shape over checks/land/prepare/slots). Nesting would rename keys. Feasible form: per-stage **views** (`GatePolicy.of(profile)`) over the unchanged struct, so a stage's code stops importing the whole `config` module but the struct stays one file in a `profile` package owned by the shell. Reach drops only if consumers import the view, so this is bead-sized per stage, not one M |
| **`ports.py`** | **403** | 23 | ❌ not kernel. Clock (kernel, 7 lines) stays; `Git/SlotGit` → git adapter package; `Checks/TreeProbe/CheckSpec/CheckResult` → gate; `Beads/NewBead/BeadPatch/BeadQuery` → a `beads` adapter pair; `Delegate` → delegate; `Spawner/Child/Ran*` → procs adapter |
| **`stores.py`** | **439** | 13 | ❌ not kernel. Legal under the layer's charter ("records and their on-disk form"; file/sqlite I/O is already in `beadrows`, `factorydb`), but carries ask-workflow behaviour (`AskStore` stores.py:188-405) that belongs to asks, and imports `contracts.dash` (line 14), pointing the store at the dash read model: wrong arrow. → `taskloop_store` / `taskloop_asks`; `ReposStore` → store |
| `log.py` | 365 | 9 | ⚠️ engine owns, but land writes `CheckStart/CheckEnd/Checks/Evidence` (6 files): split the check records to gate |
| `locator.py` 169, `slots.py` 140, `runlife.py` 75, `checkpoint.py` 142 | | 9–20 | `slots` → slots (a hub: ~20 slices, adapters 9, land 8, release 7); `runlife` (run liveness rule; dash 14, run 2) and `checkpoint` (run 12, land 2, plan 2) → engine; `runrows` → store |

Minimal kernel: **8 files, ≈ 626 sloc nbnc (≈ 8% of today's contracts; 536 by the gate's SLOC rule)**; it is a leaf (imports only itself: `paths→env,ids`, `env→envvars,ids`, `identity→paths,wire`, `bead→ids,wire`), but `identity` hangs on `paths`, so it also waits for #189. Rule: a file enters the kernel only with ≥ 4 owner stages importing it and no
stage-specific field; the kernel imports nothing of taskloop (import-linter: kernel is the bottom layer; today `contracts` imports upward via
records, see cycle table). `msgspec` stays confined to kernel + `contracts.py` files of packages (the `msgspec-in-contracts-only` contract changes
from path `tlkernel` to the glob `taskloop_*.contracts` and `taskloop_kernel`).

Options judged:
- ❌ **Keep one `contracts/` folder, add owner tags.** Same hub; the reach numbers do not move (all 90 files reached by avg 304 tests, wire.py by 449).
- ❌ **Each contract duplicated in producer and consumer (wire-copy).** Two truths; drift guard needed. The vendored `any_contract` handshake already
  exists for the one true process boundary (delegate); inside one repo use import.
- ✅ **Owner package exports; consumers import `X.contracts` only (records, not logic) and test against `X.testing` fakes.** Matches the existing
  rule in CLAUDE.md ("each port has ONE contract suite run against real adapter and fake").

## 3. Shelf (yoselabs/shelf, ~/Workspaces/shelf)

Shelf bar (constitution Art. VII): *"no second consumer required"*; a generic helper is homed at writing time; Art. VI: adopt only if DEEP · STABLE · WINS.
The shelf is a uv workspace with per-package tests and **package-granular affected** (`tools/affected.py`, 238 lines) — it is already the model Denis describes.

State: 24 packages vendored in `skills/task-loop/_vendor` (≈ 15k sloc), 14 SHELF beads still open under tl-w7lt. Most generic substrate has moved.
Remaining candidates, judged:

| candidate | where | sloc | verdict |
|---|---|---|---|
| `dev/affected.py` + `importgraph.py` (file-level AST closure, ledger, string/data/discovery rules) | dev/ | 386 | ⚠️ **evolve, not duplicate**: shelf has its own `tools/affected.py` (package-level, uv graph). Two "affected" tools = Art. III redundancy. After §6 step P1 the package-level rule is trivial here too; promote the AST closure + ledger as one `any-affected` with the package layer as its coarse mode. Not before the layout stabilises |
| `adapters/locks.py`, `landlock.py` | adapters | 127 + 92 | ⚠️ read first against vendored `process_lock`/`any_lease`; if landlock is a flock wrapper, evolve `process_lock`; else keep local |
| `adapters/treehash.py`, `gitmemo.py`, `halt.py`, `links.py` | adapters | 77/100/56/154 | ❌ none is generic substrate on inspection of names; git-shaped helpers belong inside `git_porcelain` (already 6101 sloc vendored: that package is the kitchen sink to split on the shelf, not here) |
| `contracts/fence.py` (113), `rotating.py` (32), `timedrows.py` (87) | contracts | | ⚠️ look: rotating/ago/timespec are 7–32-line helpers; shelf `timefmt` and `partial-time` exist — **adopt** before writing more (grep) |
| stage packages (gate, land, release, ...) | | | ❌ they encode this factory's method; shelf holds generic substrate (Art. VI–VII; topology.md §5 already refused delegate for this reason) |
| `taskloop_store` row layer (`RowDoc`, `JsonlStore`) over `sqlite_store` | stores | ~450 | ⚠️ the generic half (revision-guarded doc rows) may belong in `sqlite-store` (it already has "revision-guarded updates"); the rest is ours. One reading bead, no code |

Verdict: **shelf is not the lever for the vertical split.** Expected gain is small; every shelf PR is a Denis-merged gate of 10–17 minutes (topology.md).

## 4. Tests: per-package, no selection

Measured today (584 test files, 1548 python nodes):
- closure per test file: min 263, median 393, p90 905, max 1159, union 1721. **The 263 floor is data**: every key includes all of `tests/fixtures` (148
  files), `tests/delegate` data (76), `tests/adapters` (23) because `closure()` adds "every non-Python file under tests/". That alone is 2/3 of the median
  and makes every key change on any fixture edit. Narrowing it to the fixture directories a test names is one change in `affected.closure` (S).
- Hubs: `tests/support/engine_case.py` (imported by 108 tests, forward 622 files, 22 src slices), `builders.py` (32 tests, 580), `looptest.py` (19, 616),
  `exchanges.py` (3, 623). Tests of checks, run, review, write, look reach a median of **20 of ~30 src slices** (support median 33 files). These are
  not unit tests of a stage; they are tests of the whole engine wearing a stage's folder.
- Source hubs: `contracts/*` mean reach 304 tests; `stores/` 226; `adapters/` 198; `domain/` 173 (`affected` counts every importer transitively).
- `tests/conftest.py` change (5 of 45 wide commits) selects everything below it.

What collapses to per-package runs, by folder (tests whose reach is within their own stage plus kernel after the carve):

| folder | tests | reaches now (median src slices) | per-package after carve |
|---|---|---|---|
| dash | 49 | 2 | ✅ already (own + contracts) |
| delegate | 74 | 2 | ✅ already |
| adapters, ports, domain, contracts, stores, hook, rules | 43+7+20+31+7+5+46 | 0–2 | ✅ already small; they follow their owner |
| asks, artifacts, track, report, release, cli | 18+4+6+5+8+9 | 2–6 | ✅ |
| slots, wire, doctor, prune | 18+14+6+6 | 7–13 | ✅ after cycle cuts |
| land | 42 | 12 | ⚠️ after engine↔land and land↔slots cuts |
| checks, plan, review, run, write, look, loop, launch | 43+13+10+53+7+1+32+5 = **164** | 16–24 | ⚠️ only after the engine tests move to `<pkg>.testing` fakes of land/gate/slots/delegate |

So about **256 test files (44%, recounted by the reviewer with layers counted as slices; my first count of 330 was too high: asks median is 7, release 8, cli 8, track 7.5, hook 15) are within ≤ 6 src slices, and only after the shared test hubs get owners**: `support/fake_beads.py:3` is `app.launch.selftest_beads.MemoryBeads` (asks tests depend on the shell), `support/slots.py:10` imports `app.wire` (`tests/slots/test_areas.py` reaches 27 slices), `engine_case` reaches 22 slices (16 land, 26 checks, 3 asks tests). `packages/*/tests` also need `support/{case,procsim,tmpdir,paths}` and the layer guards without one shared hub: those four become a small `tests_support` kernel, everything else moves to its owner's `testing`. The rest (slots, wire, doctor, prune, land, ~90) follow the cycle cuts; the **164 engine/loop-class tests (28%)** are the real work and stay engine-wide until their collaborators ship fakes.

Win, honestly bounded (I cannot give a wall-time number from this data: `dev/testtimes.py` holds per-test CPU but the engine tests dominate it, so the
number is a function of the 164, not of the carve):
- Selection: today 271/584 median per change. In the 45 wide commits the cause is a contract edit; after §2 those contracts reach their owner's tests
  plus those of packages that import the owner's `contracts` (a kernel edit stays wide: wire/ids/paths/env are few files).
  A crude model (own package + tests of packages whose `api` imports the changed one, kernel as sink) gives lower bound median ~192, upper bound
  ~all. The upper bound is what the cycle table says: **until the cycles are cut, a package's dependents are everyone**. This number is NOT a promise.
- What *is* a promise: no change to `tldash` or `delegate` selects another stage's tests; a `contracts.py` change selects its owner + importers.

Should affected selection disappear? ❌ not entirely. Per-package independence still needs "which packages does this change touch?": a path-prefix
rule over `packages/*/`, plus a dependents rule over each package's declared deps. That is what shelf's `tools/affected.py` does in 238 lines. Keep
`dev/affected.py` as the inner narrowing (file closure inside a package) and the ledger; do not rewrite it. The directive "no affected shenanigans"
is met in the strong form for every package but the engine and in the weak form (package selection) for the engine until E.

## 5. What fails (harsh)

| option | verdict | why |
|---|---|---|
| Big-bang rename `src/taskloop/*` to `packages/*` | ❌ | #189/#190 rewrite paths.py users and 36+16 files; #186/#187 delete 54 files. A move PR touching 600+ files conflicts with every open lane (pix-isolation, pix-dash-3, pix-delegate-hard, pix-lander) and is not reversible per stage |
| Carve the engine (`app/run`) as a stage | ❌ | it imports 14 slices and is imported by launch/prune/cli: it is the composition root with the closer. Stays in the shell; `work` is what splits out of it |
| Carve contracts by *file move only* (no consumer change) | ❌ | moves the hub without cutting edges; reach numbers identical |
| Splitting tests/ first, source later | ❌ | the 164 tests are wide because source imports are wide; folders mirror sources (CLAUDE.md rule) |
| Remove import-linter layers when packages land | ❌ | layers still hold *inside* a package (contracts → domain → app); packages add a second axis, they do not replace the first |
| One shared `testing` package for fakes | ❌ | `tests/support` is that and has the 4 hub files above; fakes belong to the package that owns the port (CLAUDE.md "contract, then consumers") |

## 6. Migration: small PRs, each reversible

Size S ≤ 150 changed lines, M ≤ 600, L > 600 mechanical. Every PR keeps `just check` and `just test` green and is a pure move or a pure cut; revert = `git revert`.

Held/in-flight PRs: #189 LAYOUT-2 (36 files, `paths.py` only naming point), #190 LAYOUT-3 (`tl layout migrate`, stacked), #186/#187 STORE 8 (HELD until
pix and the Mac ran a release with #184; delete RowDocs adoption, importers, loop file stores, dead path methods), #191 ISOLATION-D (design, Agent Protocol in contracts), #192/#193 test and delegate lease.

**Rule: no step edits a file named by `gh pr diff <n> --name-only` for #189, #190, #186, #187 until that PR lands.** The reviewer's overlap list: `config` is imported by
`wire/{doctor,slots}.py` (#189, #190), `release/gate.py` (#189), `stores/{bundle,real}.py` (#186, #187) → **C1 after #189/#190**; `ports` by `packages/kernel/src/tlkernel/runlayout.py`, `report/reflect.py`,
`wire/{slots,doctor}.py`, `track/verbs.py`, `tl.py` → **C2 after #189/#190**; C3 touches rows #186 (`lockrows, waitrows, worktreerows, signalrows, parks, rundocs, adrs`), #187 (`askrows, finish, receiptrows, runrows, locator`) and #189 (`locator, receiptrows, runrows`) change → **C3 per-file after those**;
`app/wire/slots.py` (#189) → **X1 after #189**; S1 touches `tl.py`, `gate_rules.py` (#190), dash readers (#186/#187), tests (#189/#186) → **S1 after all four**. What can go **now**: M0, P2, the NetText cut, the two domain moves into land.

| step | PR | size | depends | reversible because |
|---|---|---|---|---|
| M0 | `dev/reach.py`: the measurement used here (selected tests per commit, reach per file, stage cycles) as a tool + a rule that prints the median; baseline in the PR | S | none | tool only |
| P1 | inject the delegate port: the 199→2 measurement deleted the adapter's own import, which cannot be deleted (an adapter is where it belongs); the real cut is passing the port into ~14 importers of `adapters.delegate`/`runner` (`app/run/{call,delegation,worker_call,fields,…}`, `launch/loop.py`, `wire/{lanes,usage,setup}.py`); **re-measure, no promised gain** | M | none (ISOLATION-D Agent Protocol overlaps: take its shape, **do not decide DELEGATEHOME**) | injection point |
| P2 | narrow `closure()` data floor: fixtures a test names, not all of tests/ | S | none | key change only |
| C1 | `config.py` split: per-stage `*Policy` records move beside their readers; loader keeps names | M | none (profile keys unchanged) | alias re-exports for one release |
| C2 | `ports.py`: each Protocol to its consumer/provider | M | after #191 (Agent Protocol lands in `contracts/`) | |
| C3 | 7 dead contracts removed; 22 single-consumer contracts move to their slice | M | after STORE 8 for store-owned ones | |
| K1 | kernel named: `contracts/{wire,ids,enums,paths,env,envvars,identity,bead}` get an import-linter layer; nothing imports upward | S | paths after #189 | contract is a lint ✅ done (tl-e5t0.10: `kernel-core-is-a-leaf` in .importlinter) |
| X1 | the four cuts of the corrected table: 2 domain files → land; `NetText` out of slots; report matchers to a shared home; `reconcile/leases` to slots (Part in `tlkernel.factoryparts`) | 4 × S | C2 | pure moves, one pair each |
| S1a | mechanics checklist above: one empty package, conftest/rules/SCAN/caps/CLAUDE.md learn `packages/`, lazy filter extended | M (~35 files) | #189 #190 #186 #187 | revert |
| S1b | `tldash` moves in (path only; ~20 tests rebuild `ROOT/src/…`) | M | S1a | rename |
| S1c | `delegate` moves in (123 test files) | L | S1a | rename |
| S2 | carve `taskloop_store` | L | S1a | |
| S3 | carve gate, then release, slots, asks, land (one PR each) | 5 × M–L | S1a, X1, C2 | |
| E1 | `taskloop_work` (plan, write, review, look, artifacts) as one package; split plan/write/review only after the shared matchers/findings/skip/switch/visual move to a work-internal kernel (plan↔review cycle; write→review 9 edges, `write/review_round.py:15-20`). There is no 'close' package: the closer is the shell's | M | S3 | |
| T0 | test hubs get owners: `MemoryBeads`, the slots fixture, `engine_case` split per package; `tests_support` kernel | M × 3 | S1a | |
| T1 | per-package `just test-pkg <name>`; engine tests move to fakes (`<pkg>.testing`) one collaborator at a time | M each | S3 | |
| G1 | `just test` selects packages by path prefix + declared deps; `affected.py` keeps the file-level inner rule | M | S3 | selection only |
| SH1 | shelf reading beads (locks/landlock, row layer, time helpers) | S each | none | |

Order against DELEGATEHOME (tl-w7lt.37, Denis's open decision; not decided here): packages are import names under `packages/` or `src/`; delegate already
is one. Option 1 (stay as a top-level package in this repo): S1 moves it to `packages/delegate` — zero change in semantics. Option 2 (shelf): the same carve works;
`taskloop` imports only `delegate.api`, which is exactly what the linter enforces, so leaving later is `git subtree split` of one folder. P1 serves both.

## 7. Method (reproducible)

`Repo('.')` from `dev/affected.py`: forward/back graph over src, tests, dev, vendor (lazy imports included). Selection per commit =
`affected.select(repo, files_of_commit)` using the **current** graph on the last 120 first-parent commits of origin/main (119 had Python-visible files):
an approximation of what the gate selected then. Sloc = non-blank non-comment lines. Stage mapping by folder name (`PK` table in the scratch script; the
doc lists it per row). The cut experiment deletes two edges from `repo.edges` in memory and re-runs `select`.

## 8. Second review (folded in)

Three independent opus reviews, code only. What changed:
- **Cycles (reviewer 1):** the app slices are already acyclic; my engine cycles were an artifact of grouping. `run` stays in the shell, plan/write/review/look/artifacts become `taskloop_work`; closer move refuted; `NetText` and report matchers belong to a shared home, not to slots/reconcile (§1).
- **Contracts (reviewer 2):** `config.py` cannot be split by fields, only into views; 7 "dead" contracts are live internals; owners of `enums`, `runlife`, `checkpoint` corrected; kernel 626 sloc; "single cause" became "main cause, 75%" (§0, §2).
- **Mechanics (reviewer 3):** no existing path hook; the checklist of ~35 hard-coded places; caps silently skipped under `packages/`; test count 330 → 256 (44%); P1 is M with no promised gain; overlap rule widened to every file the four PRs touch; S1 split in three (§1, §4, §6).
Disagreements I keep: shelf is not the lever (§3); packages stay in this repo with import names, not workspace installs (the review found no argument against). Not re-measured after the review: the 119-commit baseline (origin/main moved).

## 9. Measured after the first hub splits (2026-11-06): why the dash/delegate path move is deferred

Method: `dev/reach.py` and the same `Repo` graph. "Stages" = distinct stage packages (`reach.stage_of`, kernel left out) in the forward import closure of a test file.

**The move gives no selection drop.** Candidates with the fewest inbound imports:

| stage | src files | inbound src files | tests importing it | selection of one edit now |
|---|---|---|---|---|
| dash (`tldash`) | 57 | 3 | 59 | median 92 (46 `tests/rules`, always, + 49 dash tests): already independent |
| delegate | 66 | 3 | 71 | 413 per delegate-only commit; wide only because 14 app files import `adapters.delegate`/`runner` (the Agent-port work of ISOLATION, #191), not because of its directory |
| hook | 6 | 0 | 6 | tiny |

A `packages/` move of dash costs S1a (~35 files of mechanics) + ~116 moved files across four live lanes and changes no edge. Dash still imports 44 contract files, 40 of them shared with other stages: its coupling is contract churn, which the contract splits (C2, C3a) address. Verdict: ❌ move now; ✅ after the contracts and test hubs are owned.

**Tests that are still wide** (before T0b; `tests/rules` left out; "within ≤ 3 stages" = own stage + 2):

| folder | tests | median stages reached | within ≤ 3 |
|---|---|---|---|
| delegate | 77 | 1 | 77 |
| adapters | 46 | 0 | 42 |
| contracts | 33 | 0 | 32 |
| dash | 51 | 1 | 40 |
| domain | 20 | 2 | 17 |
| asks | 18 | 3 | 12 |
| checks | 43 | 12 | 15 |
| land | 42 | 10 | 9 |
| run | 53 | 12 | 6 |
| loop | 32 | 14 | 0 |
| write, review, look | 18 | 12 | 3 |
| all folders | 553 | | 313 (57%) |

Cause of the wide ones: `tests/support/engine_case.py` (596 sloc, imported by 108 tests: run 32, checks 26, land 16, review 7, write 6, plan 6), `builders.make_engine` (457 src files forward through `app/run/engine.py`), `looptest`, `slots`. T0a moved `cfg_with`, `plan_of` and `argv_cfg` to `tltestkit/cfgs.py` (reaches 8 src files); of the 32 importers of `builders`, 26 only needed those. T0b is the engine harness: the 26 checks tests and 16 land tests that subclass `EngineTest` to exercise one stage through the whole engine.

## 10. Measured after T0 (2026-11-06): what is left worth doing

T0a (`tltestkit/cfgs.py`) and T0b (`tltestkit/plans.py`: PLAN, WRITE, CLEAN, BEAD and the plan/review builders out of `engine_case`, 62 importers rewritten) are done. Result on 604 tests, 108 commits: selection per commit median 273, mean 264, p90 453, max 604; tests within ≤ 3 stages 316 of 557 (was 313 of 553). **The hub split alone moved reach by ~1%.** What still reaches far is the engine harness itself (checks, land, run, review, write, loop tests subclass `EngineTest`), which is a rewrite of those tests onto the stage's own fake, not a file split.

Median stages reached per test folder: loop 14, checks 12, run 12, review 12, write 12, look 12, launch 11, land 10, wire 10, doctor 10, hook 10; dash 1, delegate 1, adapters 0, contracts 0.

Contract hubs, files that alone select at least half the suite (commits out of 108): `contracts/paths.py` 8, `stores.py` 7, `config.py` 4, `factorydb.py` 3.

| hub | verdict | number |
|---|---|---|
| `config.py` | ❌ do not split | 130 importers, 94 use EngineConfig/load/RepoProfile/CheckSpec (the composer); moving the six section classes off the other 36 drops one config edit from 419 to 401 tests (4%) for ~36 rewrites |
| `factorydb.py` | ❌ do not split | the sqlite connection layer under every store, 44 importers, no section with its own audience |
| `dash`, `delegate` path move to `packages/` | ❌ deferred | dash already selects 92 (rules + own tests); delegate is wide through 14 app importers of `adapters.delegate`, which ISOLATION addresses |
| `paths.py` | ⏳ the one open split | held until the layout migration (#219, #232) lands; it is the single naming point |

What this means for Denis's ask. Independent test bases per package are not reachable by moving directories: the width sits in two places, the engine test harness and the shared contract hubs. The contract splits that had a real audience are done (ports #217, stores #224); the rest measured at ≤ 4%. A `packages/` carve is justified only when a stage's tests stop subclassing `EngineTest`; that is the decision for Denis (below), not a mechanical step.

Decision for Denis: rewrite stage tests (checks, land, review, write, loop) off `EngineTest` onto per-stage fakes (large, the only change that cuts the 10-14 stage reach), or accept 273-median selection and keep the current layout.

## B-WRITE report (tl-e5t0.34, 2026-11-07)

| | before (b-write.md, 2026-11-06) | after slices 1 and 3 + tl-q3ma |
|---|---|---|
| write-owned engine attributes (`write_rounds`, `last_summary`, `lane_notes`, `strays`) | 4 on the engine | 0: `engine.write` (`WriteState`, not checkpointed; #376) |
| `host: Any` in `app/write` | 8 classes | 0: `app/write/host.py` Protocols (`WriteHost` and narrow hosts; #396) |
| engine attributes `app/write` reads or assigns (distinct `e.X`) | ~62 | 58 by grep; now named in `write/host.py` instead of hidden behind `Any` |
| `app/write` imports of other app slices | | `artifacts`, `asks`, `checks` |
| stage progress on the engine path | never saved: a run parked in checks or review resumed at write | `step="review"` + `StageProgress` saved when a round's checks are green (tl-q3ma, #387) |

Not done, by design of the slices: slice 2 (hand-offs by value for `accepted_new`/`unchecked`/`leftovers`, `stats`) waits for ASKAI slice 2; the write tests still build the stage on the `EngineTest` fixture, not on their own fakes (the stage-test rewrite of the Decision above). T-BUDGET (tl-e5t0.55) ratchets these numbers.

## 11. Per-slice trackers for the selection median (tl-e5t0.81, 2026-11-08)

The median is 226 of 752 tests in total and 143 beyond the 83 always-run `tests/rules` files (`dev/reach.py --commits 40` on main, 2026-11-08, 37 commits measured; it prints both numbers). Of a typical engine-touching commit's ~190–205 selected tests, 83 are the always-run rules. The target in the acceptance text is unchanged. The slices below are as seen by a typical engine-touching change: `src/taskloop/app/land/lander.py` selects 205.

| slice | selected now | owner bead | what moves it | target |
|---|---|---|---|---|
| tests/rules | 83 (always) | tl-e5t0.81 probe | the rules probe; see the bead | set by the owning bead; none invented here |
| tests/run | 48 | tl-e5t0.81 itself and the run carve | the run carve | set by the owning bead; none invented here |
| tests/land | 27 (16 for a run/engine.py change) | land carve tl-e5t0.20 | the land carve | set by the owning bead; none invented here |
| tests/review | 8 | tl-e5t0.80 (work) | the work carve | set by the owning bead; none invented here |
| tests/plan | 7 | tl-e5t0.80 (work) | the work carve | set by the owning bead; none invented here |
| tests/write | 6 | tl-e5t0.80 (work) | the work carve | set by the owning bead; none invented here |
| tests/slots | 5 | tl-e5t0.78 | the slots carve | set by the owning bead; none invented here |
| tests/asks | 3 | tl-e5t0.79 | the asks carve | set by the owning bead; none invented here |
| tests/domain | 3 | the nearest SURFACE bead | the owning SURFACE change | set by the owning bead; none invented here |

Kernel records (ids 606, config 450, checkpoint 421, answers 437) are wide by nature and set p75/p90, not the median. Moving the engine-class test files off the engine core was simulated to change the median only 225 → 221 (top 5), 218 (top 10 and 20) because the same tests reach it through kernel records and `tests/support`, so the tracker is per-slice, not a single number.
