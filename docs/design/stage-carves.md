# Stage carves: S3 (tl-e5t0.16 gate, .17 slots, .18 asks, .19 release, .20 land) and E1 (tl-e5t0.21 work)

Status: plan, docs only. Method: [workspace.md](workspace.md) (port-first for non-leaves, a carve is a pure `git mv` plus renames, one carve per PR, `Layout-allow:` in each). Charter: [stage-packages.md](stage-packages.md). Numbers were measured on main at 2026-11-07 with the import graph of `src/taskloop` (direct imports, lazy ones included); re-measure before a carve with the script in section 6.

## 1. What a carve has to move, and why it is more than the stage folder

A package may import `tlkernel` and other packages' api, contracts and testing, never `taskloop.*` internals. So each carve moves four things together, or the package cannot import:

1. `app/<stage>/` (files, sloc below);
2. the stage's own `domain/<x>/` (a stage-owned pure core: `domain/checks` 20 files is gate's, `domain/land` 14 is land's, `domain/asks` 8 is asks', `domain/slot_liveness` is slots');
3. the stage's `adapters/` and `stores/` pieces that nobody else uses (see "ports" per carve);
4. its tests (`tests/<stage>` to `packages/<stage>/tests`), after the tests stop importing `support.*` and sibling stages.

What is shared and must be settled first (each one is a pure move of its own, before any carve that needs it):

P1 update: the store interfaces formerly in `stores/api.py` (`stores.api`) now live in `packages/kernel/src/tlkernel/storeapi.py` (`tlkernel.storeapi`). The inventory below records the pre-carve counts. Checks now use their own `GateStores` and `GateLog` protocols in `app/checks/ports.py`; the concrete bundle and log remain in the shell.

| shared piece | users (files) | home |
|---|---|---|
| `domain/checks` (20 files) | checks 27, plan 7, write 5, land 3, domain.work 2, pipeline 2 | gate's `contracts` for the records, gate's `api` for the functions |
| `domain/asks` (8) | pipeline 9, asks 7, land 6, plan 4, write 4, run 3, review 2, workers 2 | asks `contracts` |
| `domain/lanes` (14) | workers 12, pipeline 8, asks 3, run 3, land 2 | stays in the shell/workers; asks and land see it by a port (`AskAi`, section 3 of stage-isolation.md) |
| `domain/work` (6), `domain/review` (5), `domain/prompts` (3) | review 7, write 5, plan 4, look 3 | the work package's internal kernel (E1) |
| `domain/matchers` | land 3, plan 2, pipeline 2, checks 2, loop, review, run, slots | kernel (it is a matcher table; `NetText` also, architecture-vertical.md section 1) |
| `adapters/ident` | release 11, slots 2, asks 1 | kernel (identity of the actor) |
| `stores/runlog` (30 land, 2 checks), `stores/bundle` (12 land, 10 checks), `stores/api` (8 land, 2 checks, 2 slots) | land, checks, slots | `RunLog`, `Bundle`, `Stores` Protocols become kernel ports (stage-isolation.md `Narrate`, `StepBook`); the real classes stay in the shell |

## 2. Per carve

Columns: files/sloc of `app/<stage>`; tests (files; how many import `support.case|tmpdir|paths`, which the TESTKIT-SUPPORT sweep rewrites); importers of the stage in `run/ pipeline/ wire/ launch/` (the files a carve's import rewrite touches outside the stage); outward `taskloop.*` imports that must become kernel, port or sibling-api.

| carve | files / sloc | tests (sweep-touched) | importers outside the stage (run, wire, launch) | outward imports to settle |
|---|---|---|---|---|
| artifacts (E1 part) | 7 / 365 | 5 (2) | run/ask_flow; look, write, cli/factory | none (a leaf) |
| gate (.16, `checks`) | 23 / 1949 | 49 (37) | run/{context,field_ports,engine,preflight}; launch/{staged,check_host,check}; land 6, write 2, release 1, workers 2 | `domain.checks` 73 (moves with it), `stores.bundle` 10, `tlkernel.{check_files,profile_at}, app.checks.base_tree, tlkernel.childenv` 17, `stores.{runlog,api}` 4 |
| release (.19; R1 code carve done) | 16 / 869 | 10 (8) | run/{run_once,reload_ports,parts_run,engine}; wire/{brief,doctor}; launch/{loop,loop_ops,loop_start} | `adapters.ident` 11 (kernel), `adapters.{suiteout,landlock,gitrepo,beadtools}, tlkernel.childenv` 10, `app.checks.{cache,authorization}` (gate api), `stores.real` 2 |
| slots (.17) | 16 / 1202 | 20 (17) | run/{entry,run_once,running,shared,closer_ports,bead_env,reload_ports}; wire/{doctor,slots,setup}; track/closeguard; 7 launch files; land 2 | `domain.slot_liveness` 8 (moves), `adapters.{pidcheck,ident,agent,locks}, tlkernel.profile_at` 10, `domain.matchers` 2, `stores.api` 2 |
| asks (.18) | 18 / 1273 | 28 (23) | run/{ask_flow,entry,parts_run,closer_ports}; wire/asks; launch/{loop,loop_ops,dash_ports}; land 2, plan 2, report, workers, write | `domain.asks` 15 (moves), `domain.lanes` 6 (port), `stores.real` 4, `domain.{plan,beads}` 4, `adapters.{ident,beadtools}` 2 |
| land (.20; L2a code/test carve done) | 47 / 3918 | 72 (43) | run/{sections,run_once,parts_land,parts_run,fields,closer_ports}; wire/asks; launch/{check_host,push_judge} | `domain.land` 76 (moves), `stores.{runlog,bundle,api,real}` 54, `domain.{asks,checks,lanes,matchers}` 30, `app.checks` 9 and `app.slots.{reset,engine_lock}` 8 (their apis) |
| work (E1): plan | 18 / 1253 | 22 (11) | run/{fields,sections,host} | `domain.{checks,plan,prompts,asks,work}` 55, `app.asks.intake` 4 |
| work: write | 17 / 1472 | 12 (9) | run/{host,stages,parts_land,parts_plan,fields} | `domain.{prompts,work,checks,asks,review}` 54, `app.checks.evidence` 3, `app.asks.trustroots` 2, `app.artifacts` 2 |
| work: review | 8 / 708 | 13 (9) | run/{fields,host} | `domain.{work,review,asks,matchers,checks}` 35 |
| work: look | 7 / 681 | 4 (1) | run/{fields,host,state} | `adapters.{looks,repourl,bdcreate,beadtools}` 13, `domain.{work,look}` 10, `app.artifacts` 4 |

E1 rule from the bead: plan, write, review, look and artifacts are one package `work` first (plan and review import each other; write imports review in 9 places). Its sloc is 4.2k, so it is the second biggest after land. Work imports only gate and asks (api), as the bead says; the two `app.checks.*` and `app.asks.*` imports above are what E1 turns into api calls.

## 3. Collisions

**C-PIPELINE (pix-pipeline).** R1 to R3 landed. R4a to R4f edit these files (message of the lane, 2026-11-07): R4a `run/state.py`, `run/ask_flow.py`, `pipeline/{run,lifecycle,resume,standalone}`; R4b `pipeline/run`, `run/run_once.py`; R4c `pipeline/standalone`, `run/stages.py`; R4d to R4f (after B3) `pipeline/{journal,summaries,trace,resume,reflect,reload,closing*}`, `run/reload_ports.py`, `run/closer_ports.py`. A carve rewrites its importers in `run/`, so it collides exactly where its stage appears in the R4 files:

| carve | R4 files it shares | verdict |
|---|---|---|
| artifacts | `run/ask_flow` (one import line, R4a) | low |
| gate | none in `run/` (its importers are context, field_ports, engine, preflight, launch); `pipeline` reaches gate by ports | low |
| work: plan, review | none (fields, sections, host are not in R4) | low |
| work: look | `run/state.py` (R4a) | after R4a |
| work: write | `run/stages.py` (R4c) | after R4c |
| release | `run/run_once` (R4b), `run/reload_ports` (R4d-f) | after R4b; R4d-f only a one-line import |
| asks | `run/ask_flow` (R4a), `run/closer_ports` (R4d-f) | after R4a, rerun the rewrite after R4d-f |
| slots | `run/run_once`, `run/closer_ports`, `run/reload_ports` | after R4b, rerun after R4d-f |
| land | `run/run_once`, `run/closer_ports`, `pipeline/*` | last, after R4 and after gate and slots |

**TESTKIT-SUPPORT sweep (pix-wspike).** It rewrites `support.case|tmpdir|paths` imports in about 400 test files to `tltestkit`. A package's tests cannot import `support.*` at all (workspace.md bug 4), so the sweep is a hard prerequisite for moving any test, not only a collision: the sweep-touched counts above are the files a carve's `git mv tests/...` would otherwise conflict on (gate 37, land 43, asks 23, slots 17). Rule: a carve moves its tests only after the sweep landed; the code move (`git mv src`, importer rewrite) does not depend on it and may go first as its own PR if the sweep is late. Tests that import a sibling stage (gate: doctor, land, slots; asks: land, loop, pipeline, plan; land: 11 stages) move to the sibling or to `tests/e2e` (TESTISO, tl-e5t0.66); that is the second hand step of each carve and it is where the budget goes.

**Other open lanes.** WS-MECH (#518) must land first (globs in the tools; workspace.md step 0). PATHS-B is parked (tl-1nbh), so `ConfigDir` stays a kernel import. `.importlinter`, `tests/rules/{arch_invariants,test_roots_classified,test_dash_state_paths}` and `app/parts.py` are edited by every carve (workspace.md bug 6): carves are therefore serial in those files, two at a time at most.

## 4. Order, lowest collision first

| # | carve | can start before R4 lands | needs first | notes |
|---|---|---|---|---|
| 1 | artifacts | yes | WS-MECH | the spike branch (a771b842) is the template; one line in `run/ask_flow` |
| 2 | gate (.16) | yes (code move); tests after the sweep | WS-MECH; kernel ports `RunLog`/`Bundle`/`Stores` (section 1) and the four `adapters.*` check helpers | biggest payoff: 27 + 7 + 5 + 3 consumers of `domain.checks` start using the api; unlocks work, release, land |
| 3 | work: review, then plan | yes (code move) | gate api, asks `contracts` (`domain.asks`), `domain/{work,review,prompts,matchers}` as the work-internal kernel | cycle plan/review is cut by moving the shared matchers first |
| 4 | asks (.18) | after R4a | gate api not needed; `domain.lanes` behind `AskAi` | before write and land (both import `app.asks.*`) |
| 5 | work: look, write | look after R4a, write after R4c | artifacts, gate, asks | write is the last piece of E1 |
| 6 | release (.19; R1 code carve done) | after R4b | gate api (`checks.cache`, `authorization`), `adapters.ident` in kernel | 16 files, small |
| 7 | slots (.17) | after R4b; rerun after R4d-f | `adapters.{pidcheck,agent,locks}` into slots or kernel | wire/ and launch/ importers are the long tail (11 files) |
| 8 | land (.20; L2a code/test carve done) | after R4 and after 2, 7 | gate and slots api (`checks` 9, `slots.reset`/`engine_lock` 8), `stores.*` ports | 47 files, last by size and by collision |

Can start before R4 lands: 1, 2, 3 (code moves; their `run/` importers are not R4 files). Hold until R4a: asks, look. Hold until R4b: release, slots. Hold until R4c: write. Hold until R4 and the others: land.

Each carve PR carries the numbers the charter asks for: `dev/reach.py` before and after, the closure ratchet delta (`Ratchet-allow: closure +N` for the new package modules), the four edit places of workspace.md bug 6.

## 5. What this plan does not decide

- `config.py` stays one struct; stages take views (architecture-vertical.md section 2). A carve that needs `GatePolicy.of(profile)` makes that view in the same PR.
- `tl-w7lt.37` DELEGATEHOME and the shelf dependency question (workspace.md section 7) are unchanged.
- The T-BUDGET ratchet (#512) already counts kernel files and external modules per `taskloop.app.<stage>`; after a carve it reads the package through the member list (workspace.md step 8).

## 6. Reproducing the numbers

Outward imports: for every `.py` under `src/taskloop/app/<stage>`, the distinct `taskloop.*` modules imported (AST, lazy imports included) that are not under that stage, counted per target. Importers: the files of `src/` outside the stage that import `taskloop.app.<stage>`. Test counts: files under `tests/<stage>/`, and those with `support.case|tmpdir|paths`. Selection effects: `python3 dev/affected.py --changed <file>` and `dev/reach.py --commits 60`.

Release R1 (tl-e5t0.19): code carve done in `packages/release/src/tlrelease`, flat modules with no api.py.
`ReleaseHost` supplies shell effects, bound by `app/launch/release_host.py`; tests stay in `tests/release` until R2.

Areas S1: `packages/areas` (`tlareas.policy`) owns area membership, ancestor caching and busy-area exclusion; queue delegates preserve shell wiring.
