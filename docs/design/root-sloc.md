# Root sloc: what stays in `src/taskloop` roots and why (tl-e5t0.40.6)

Measured on main ddfe6729 with `dev/root_report.py` and `tests/rules/root_ratchet.py`: 77 root files, 4030 sloc, 340 branches, 12 long functions, 150 engine attributes. Design goal: under 1500 sloc (gap 2531). A root is what the `nobody-imports-a-root` contract in `.importlinter` names (launch, wire, run's composition files) plus the `cli` and `hook` packages and `tl.py`.

## Result in one line

Everything in the table that has a destination can leave: **1650 sloc**. That lands at **about 2380**, not 1500. The 880 left over is not a missing move: it is run/* construction (fields, engine, host, parts_*, context, state, plumbing, closer_ports: about 600 sloc, bound to the Engine's 150 attributes), the small cli/hook argparse files (693 sloc in 36 files, roots by definition) and `prepush.py` (documented stdlib exception). 1500 needs either the Engine attributes to fall (R4 landed; the attribute count has not moved: 150) or the goal to count cli argparse wiring as not-root.

## Status (2026-11-07)

| move | PR | root sloc |
|---|---|---|
| setup, setup_apply, lanes to app/doctor (route, config dir, host store and slot facts injected; bindings in app/launch) | #603 | -223 net |
| closeguard rules, preflight admission and entry sequencing to tlpipeline over ports | #606 | -57 (closeguard 78 -> ~35, preflight 62 -> 22, entry admission only -2: those rules already lived in app/asks/admission; entry keeps ~48 slot-take sloc for the slots carve) |
| run/layout.py to tlkernel.runlayout | #608 | -98 |

Net root 4030 -> about 3650. The slots carve is the largest cut left (docs/design/slots-carve.md); gate moves wait for the land-gate move.

## Destination map

Packages that exist: `kernel`, `gate`, `artifacts`, `pipeline`, `testkit`. Not carved yet (their rows wait on the carve in `stage-carves.md`): slots (tl-e5t0.17), asks (.18), release (.19), land (.20), work. `app/doctor`, `app/report` and `app/land` are ordinary slices that exist now.

| root file | sloc | br | leaves | disposition | why / blocker |
|---|---|---|---|---|---|
| `skills/task-loop/tl.py` | 341 | 6 | 10 | v_ask's sweep into app/asks; the rest stays | 172 sloc are argparse parser builders, 50 the VERBS table, 84 about 25 two-line bindings. cli/* is root too, so moving parsers or handlers into cli modules leaves the total unchanged. Option (c): verbs as data (~150 sloc) waits for Denis on whether cli wiring counts as root (bead tl-e5t0.40.6 follow-up) |
| `app/run/entry.py` | 261 | 45 | 150 | slots package (_slot_taken, run_any_slot decision logic, net ~35; take_area is area policy and stays until an areas carve); pipeline (admission, blocked reopen ~50) | run_in/run_bead/_worktree_of stay. Needs the slots carve (tl-e5t0.17) and a slots port; the pipeline half is free now (packages/pipeline exists) |
| `app/launch/dash.py` | 191 | 41 | 170 | tldash (its launch module); stays a ~20 sloc binding | dashboard lane work, wait until pix-dash is quiet |
| `app/wire/slots.py` | 155 | 19 | 130 | slots package (machine-bound half: slot_table, slot_env, worktrees, take/release) | slots carve (tl-e5t0.17) with a slots port that wire binds; callers: entry, doctor, loop |
| `app/run/fields.py` | 131 | 0 | 0 | stays | construction: the plain fields of a run; shrinks only when the Engine's 150 attributes fall |
| `app/launch/loop.py` | 122 | 0 | 0 | stays | builds the LoopEnv: pure binding |
| `app/launch/dash_ports.py` | 110 | 4 | 0 | stays | binding of the dashboard's ports (4 branches) |
| `app/wire/setup.py` | 106 | 12 | 100 | app/doctor (new `setup` module) | `tl setup --plan` is a rule set (checks, fixes, questions), not a binding; no blocker |
| `app/run/layout.py` | 98 | 13 | 60 | kernel (paths/locator: the run's file names) | pure naming; the manifest stays the authority; no blocker |
| `app/run/engine.py` | 97 | 3 | 0 | stays | the Engine construction; its 150 attributes are the lever for run/* |
| `hook/prepush.py` | 91 | 18 | 0 | stays | documented exception: stdlib-only hot path (18 branches) |
| `app/wire/doctor.py` | 86 | 8 | 0 | stays | multi-stage root: doctor.run imports release, which sits above doctor in the layers contract (corrected after the first move) |
| `cli/factory.py` | 86 | 15 | 40 | app/launch factory verbs | argparse + exit mapping stay (~45); start/inspect/stop/tail rules move |
| `app/run/host.py` | 83 | 2 | 0 | stays | run construction |
| `app/run/parts_run.py` | 82 | 3 | 0 | stays | run construction |
| `packages/slots/src/tlslots/shared.py` | 82 | 10 | 70 | moved to tlslots in S3a (notes shared by the tasks of one repo) | done: tlslots/shared.py over SharedHost |
| `app/run/shell.py` | 80 | 10 | 70 | gate package (a command of the run recorded in the engine log) or kernel proc helper | gate package exists; the engine-log recording needs the log port |
| `app/wire/closeguard.py` | 78 | 10 | 70 | pipeline (closing) | one function `refusal` decides every close; packages/pipeline exists; callers are tl close, tl task close |
| `app/launch/loop_ops.py` | 77 | 0 | 0 | stays | binding; pix-dataown's PRs in flight |
| `app/launch/loop_start.py` | 75 | 9 | 60 | release package (installs on the machine, loop identity) | release carve (tl-e5t0.19) |
| `app/wire/brief.py` | 73 | 5 | 0 | stays | imports app.loop (above report) and the wire roots, so it cannot sit in app/report (corrected) |
| `app/wire/setup_apply.py` | 73 | 11 | 70 | app/doctor | same slice as setup.py; do both in one PR |
| `app/run/plumbing.py` | 64 | 6 | 0 | stays | run construction (stop flag, poster, clock) |
| `app/launch/check_host.py` | 63 | 0 | 50 | gate package (CliHost) | gate exists; needs its runner/cache/evidence ports |
| `app/run/preflight.py` | 63 | 14 | 55 | pipeline (read-only admission and plans) | packages/pipeline exists; no blocker |
| `app/wire/lanes.py` | 60 | 8 | 50 | app/doctor or a new app/lanes slice | files delegate's status as the snapshot; rules, not binding |
| `app/run/ask_flow.py` | 59 | 7 | 50 | asks package | asks carve (tl-e5t0.18) |
| `app/run/context.py` | 54 | 0 | 0 | stays | run construction |
| `app/run/closer_ports.py` | 50 | 0 | 0 | stays | binding |
| `cli/asks.py` | 48 | 5 | 0 | stays | argparse wiring |
| `app/run/parts_land.py` | 47 | 2 | 0 | stays | run construction |
| `app/run/state.py` | 44 | 1 | 0 | stays | engine attributes bound to RunState |
| `app/wire/asks.py` | 44 | 6 | 35 | asks package (throttled passes over the inbox) | asks carve (tl-e5t0.18) |
| `app/launch/check.py` | 42 | 0 | 0 | stays | binding |
| `cli/land_stack.py` | 42 | 1 | 30 | land package / app/land | argparse stays (~12); shell bindings move with the land carve (tl-e5t0.20) |
| `cli/land.py` | 40 | 1 | 30 | app/land | records a direct-push land and cleans refs: a rule; land carve (tl-e5t0.20) |
| `app/launch/selftest.py` | 39 | 1 | 0 | stays | builds an Engine; a converted stage may not import app.run (corrected) |
| 36 smaller files (each under 48 sloc: cli verbs, hook entry points, run/running, parts_plan, stages, facts, run_once, sections, ...) | 693 | | 0 | stay | argparse wiring and bindings; the definition of a root |


## Order (lowest blocker first)

1. tl.py handler groups (200 sloc), `app/doctor` (setup, setup_apply, doctor, selftest, lanes: about 320), `app/report` (brief 60), pipeline (closeguard 70, preflight 55, entry admission ~50), kernel (layout 60): about 800 sloc, no carve needed, each its own PR.
2. gate (shell 70, check_host 50): the gate package exists; needs ports.
3. After the slots carve: slots.py 130, entry's slot take ~100, shared 70.
4. After asks / release / land carves: ask_flow, wire/asks, loop_start, land, land_stack (about 235).
5. dash.py 170 when the dashboard lane is quiet.
