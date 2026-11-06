# ENGINE-ORDER: how the Engine is built today, and the order it can be built in (tl-e5t0.57)

Analysis only; no code moves with this note. It is the first deliverable of the bead, ahead of any constructor injection (stage-isolation.md, section 7, finding 7). Every number below comes from an AST scan of `src/taskloop/app` on origin/main, 2026-11-06 (method at the end), not from reading the design doc's list.

## What the scan found

1. **36 parts, and only three of them need another part to be built.** `RunParts`, `LandParts`, `PlanParts` and `RunHost` define 36 `cached_property` parts. The other 33 are built from the engine alone, or from the engine plus values set in steps 1 to 3 below (`git`, `cfg`, `wt`, `home`: `bead_env`, `lander`, `newfiles`, `planner`, `pictures`, `owner_look`, `hand`, `routing`, `settles`); they store the engine (`self.e = host`) and read its attributes later, in their methods, so they are built on first touch and can be built in any order. The construction-time edges are exactly three: `closer -> worker` (`closer_over(self, self.worker.saved)`), `worker -> records` (`Ops(..., self.records.after_call)`), `salvage -> rebase` (`Salvage(self, self.rebase)`). No construction-time cycle exists.
2. **Two cycles exist among the runtime reads**, both small:
   - `checkout <-> newfiles`: `Checkout.stage_all` asks `e.newfiles.new_file_kind(p)`; `NewFiles` asks `e.checkout.tree_hash/base_sha/slot_status`.
   - `ask_flow -> briefs -> planner -> ask_flow` (`planner -> briefs` too): `AskFlow` calls `e.briefs.export()`; `Briefs.export` calls `e.planner.cap.answered_words()`; the planner calls `e.ask_flow.raise_soft` and `e.briefs.export`.
3. **Both cycles are an accident of where a pure function sits.** `NewFiles.new_file_kind` reads only `cfg.untracked_ignore`, `accepted_new` and `plan_data`. `ReplanCap.answered_words` reads only `answered` and a text helper (`domain/asks/text.words`). Moving each to a function of its inputs removes the edge; no behaviour changes.
4. **The "land_fields() recreates Checkpoints mid-run" finding of the design doc is stale.** `land_fields()` has one caller, `RunFields.__init__` (`fields.py:125`), and no test calls it. Checkpoints is created once, before the engine's other fields exist, and holds the engine; nothing caches the object across a rebuild. The ordering that matters is in `Engine.__init__` (next section).
5. **The cost of constructor injection is not the parts' graph but their plain reads of the engine**: 22 of 36 parts read 10 or more distinct engine attributes (`records` 43, `worker` 34, `planner` 32, `closer` 30, `resume` 27, `judge` 25). That is the ATTR-MAP bead's work (232 attributes), not this one's.

## The order inside `Engine.__init__` (what must exist before what)

| # | step | needs | provides |
|---|---|---|---|
| 1 | `env`, `spawner`, `who`, `home`, `git` assigned | the edge | everything below; set before `super().__init__` because `RunFields.__init__` reads `who` |
| 2 | `RunFields.__init__` | `who`, `cfg`, `bead`, `wt` | plain fields; `store`, `router`, `stats`; `land_fields()`: `state`, `checkpoints = Checkpoints(self)`, the run's counters |
| 3 | `clock`, `reexec` (`take_reexec`), `pause` (`take_net_pause`), `stores` | `env`, `home` | `stores` (the first thing `checkpoints` reads) |
| 4 | `dead`: `self.checkpoints.read()` | `stores`, `bead` (not `run_id`: the run's id is not known yet) | a dead close's checkpoint, whose run id is taken over |
| 5 | `RunLayout.open(...)` | `git`, `home`, `clock`, `env`, `who`, the taken run id | `run_id`, `log_path`, `err_path`, `run_dir`, `live_dir`, `task_dir`, `brief_file`, `evidence_dir` |
| 6 | `RunContext.open(...)` | all of 5, `stores`, `store`, `route`, `clock`, `sessions`, `stats`, `say`, and the bound methods `now`, `step_guard`, `on_step` | `log`, `steps`, `budget`, `calls`, `checklog` |
| 7 | `checker = Checker(self, wait)` | 6 (reads `steps`, `cfg`, `checklog` when it runs) | `checker` |
| 8 | `delegation.route(quiet=True)` | 6 (`log`, `router`) | the resolved delegate install |
| 9 | `reload.restore_run(...)` / `carry_done_memo(...)` | 6, `run_id` | the exec'd or paused run's counters |

Two things in that table are order constraints no type shows: step 6 receives `self.step_guard` and `self.on_step`, which are methods of the parts layer (`requests`, `assert_tree`) used before `log` exists in the engine (they only run once a step starts, after step 9); and steps 8 and 9 are the only part calls in `__init__`, so they pin `delegation` and `reload` to be buildable with steps 1 to 7 done. Constructor injection has to keep 1 to 9 in this order, or hand the parts the steps' outputs as arguments.

## Parts, their layer and their inputs

Layer = 1 + the highest layer among the parts a part uses (construction or runtime), after the two cycles are cut as below. A part may only depend on lower layers. "Construct" is built-with; "runtime parts" are the other parts its methods read; "engine attrs" is the number of distinct plain engine attributes it reads (a size, not a list: the list is ATTR-MAP's).

| layer | part | class (file under `app/`) | construct | runtime parts | engine attrs |
|---|---|---|---|---|---|
| 0 | `bead_env` | `bead_env` (`run/bead_env.py`) | - | - | 4 |
| 0 | `briefing` | `Briefing` (`write/briefing.py`) | - | - | 3 |
| 0 | `briefs` | `Briefs` (`plan/briefs.py`) | - | planner | 10 |
| 0 | `cases` | `Cases` (`plan/cases.py`) | - | - | 9 |
| 0 | `checkout` | `Checkout` (`land/checkout.py`) | - | newfiles | 6 |
| 0 | `delegation` | `Delegation` (`run/delegation.py`) | - | - | 9 |
| 0 | `lander` | `lander_over` (`land/lander.py`) | - | - | 1 |
| 0 | `records` | `Records` (`run/records.py`) | - | - | 43 |
| 0 | `reload` | `Reload` (`run/reload.py`) | - | - | 21 |
| 0 | `requests` | `OwnerRequests` (`run/requests.py`) | - | - | 8 |
| 0 | `restart` | `Restart` (`land/restart.py`) | - | - | 19 |
| 0 | `stage_checks` | `StageChecks` (`run/stage_checks.py`) | - | - | 6 |
| 0 | `stuck` | `StuckTick` (`run/stuck.py`) | - | - | 3 |
| 0 | `waits` | `Waits` (`run/waits.py`) | - | - | 12 |
| 1 | `ask_flow` | `AskFlow` (`run/ask_flow.py`) | - | briefs | 20 |
| 1 | `newfiles` | `NewFiles` (`write/newfiles.py`) | - | checkout | 10 |
| 1 | `pictures` | `Pictures` (`look/shots.py`) | - | checkout | 20 |
| 1 | `rebase` | `Rebase` (`land/rebase.py`) | - | checkout | 15 |
| 1 | `reflector` | `Reflector` (`run/reflect.py`) | - | delegation | 21 |
| 1 | `routing` | `Routing` (`review/routing.py`) | - | checkout | 10 |
| 1 | `shared` | `Shared` (`run/shared.py`) | - | checkout | 8 |
| 1 | `shell` | `Shell` (`run/shell.py`) | - | bead_env | 9 |
| 1 | `stage_loop` | `StageLoop` (`write/stage_loop.py`) | - | checkout, reload | 7 |
| 1 | `tree` | `Tree` (`land/tree.py`) | - | briefs, checkout | 14 |
| 2 | `fixer` | `Fixer` (`land/fixer.py`) | - | cases, checkout, stage_loop | 12 |
| 2 | `hand` | `Handoff` (`write/handoff.py`) | - | briefs, cases, checkout, routing | 16 |
| 2 | `judge` | `Judge` (`look/judge.py`) | - | cases, pictures, stage_checks | 25 |
| 2 | `link_check` | `LinkCheck` (`review/link_check.py`) | - | checkout, routing | 6 |
| 2 | `owner_look` | `OwnerLook` (`look/owner_look.py`) | - | cases, pictures, waits | 13 |
| 2 | `planner` | `Planner` (`plan/planner.py`) | - | ask_flow, briefs, checkout, routing | 32 |
| 3 | `resume` | `Resume` (`run/resume.py`) | - | cases, planner | 27 |
| 3 | `salvage` | `Salvage` (`land/salvage.py`) | rebase | fixer | 9 |
| 3 | `settles` | `Settles` (`review/settles.py`) | - | cases, checkout, judge | 10 |
| 3 | `worker` | `WorkerCall` (`run/worker_call.py`) | records | bead_env, delegation, hand, waits | 34 |
| 4 | `closer` | `Closer` (`run/closer.py`) | worker | ask_flow, records | 30 |
| 4 | `verifier` | `Verifier` (`review/verifier.py`) | - | briefing, briefs, fixer, judge, routing, settles | 21 |

Parts that other parts read most: `checkout` (12 readers), `cases` (6), `briefs` (5), `routing` (4). Those four are the ports the stages will declare first.

Three engine-level members are not parts and not in the table: `checker` (built in step 7 with the engine; `Fixer(host)` and the `Checker` itself read the engine), `ctx` and its five outputs (step 6), and `checkpoints` (step 2). Four methods of the parts layer hide part reads from the scan, because they are engine methods that delegate to a part: `sh` (to `shell`), `run_checks` (to `stage_checks`), `step_guard`/`ai` (to `requests` and `worker`). A part that calls `e.sh(...)` depends on `shell` without showing it; the rule test below counts them.

## The order, and how to break the two cycles

Build order for constructor injection (a layer needs only the layers above it in this list, plus the edge values of steps 1 to 6):

1. Layer 0: `bead_env`, `briefing`, `briefs`, `cases`, `checkout`, `delegation`, `lander`, `records`, `reload`, `requests`, `restart`, `stage_checks`, `stuck`, `waits`.
2. Layer 1: `ask_flow`, `newfiles`, `pictures`, `rebase`, `reflector`, `routing`, `shared`, `shell`, `stage_loop`, `tree`.
3. Layer 2: `fixer`, `hand`, `judge`, `link_check`, `owner_look`, `planner`.
4. Layer 3: `resume`, `salvage`, `settles`, `worker`.
5. Layer 4: `closer`, `verifier`.

The two cuts that make this order exist:

- **`checkout -> newfiles`**: move `new_file_kind` (and its `planned` helper) to a pure function `new_file_kind(path, ignore_globs, accepted, plan_data)` beside the other write-stage matchers; `Checkout.stage_all` calls it with `cfg.untracked_ignore`, `accepted_new` and `plan_data`; `NewFiles.new_file_kind` stays as a one-line wrapper (the check host and its test double implement the same name). `CheckoutNewFiles` (a Protocol in `land/checkout.py`) goes.
- **`briefs -> planner`**: move `answered_words` to `domain/asks/text.py` as `answered_words(answered)`; `Briefs.export` calls it with `e.answered`; `ReplanCap.answered_words` calls it too. `briefs` becomes layer 0, `ask_flow` layer 1, `planner` layer 2.

## Slices (each lands green on its own, behaviour unchanged)

1. **new_file_kind out of the engine's part graph** (the first cut above), with a test of the pure function and the existing `NewFiles` tests unchanged.
2. **answered_words out of the planner** (the second cut), same shape.
3. **A rule test `tests/rules/test_engine_order.py`**: the same AST scan, as a ratchet. It fails on a construction-time cycle, on a runtime cycle among parts, and on a new part that reads a higher-layer part; the layer table above is its expected value, so adding a part means placing it. It also fails if `land_fields` gains a caller (the design doc's concern).
4. **Not in this bead**: replacing `cached_property(Cls)` with explicit construction in `Engine.__init__` in the order above. It needs the ATTR-MAP result (which engine attributes each part takes), and is the first step of the stage conversions.

## Method and limits

`ast`-scan of the four parts files (`parts_run.py`, `parts_land.py`, `parts_plan.py`, `host.py`) for the `cached_property` parts; each part's class (or factory function, for `bead_env` and `lander_over`) located through the imports of those files. Reads counted: an attribute of the host (the first `__init__` parameter, stored as `self.e`, `self.host` or `self.h`, or a local alias of it) whose name is a part. A read in `__init__` (or in a factory's body, or in the property body that builds the object) is a construction edge; any other method's read is a runtime edge. Not seen: reads through `getattr`, through a part the host passes along as an argument, and through the four engine methods named above. The scan script is not committed with this note; slice 3 turns it into the test.
