# The pipeline node: what leaves run/, behind which ports, in which order (tl-e5t0.39, design slice 1)

Design only; no code moves with this note. It turns the one-line "node `pipeline`" of `stage-isolation.md` (section 2) into a module list, a port list and a slice order. Numbers are an AST scan of `src/taskloop/app/run` on origin/main (07a7e21b), 2026-11-07: sloc counts code lines (docstrings, blanks, comments left out); "host attrs" counts the distinct attributes a module reads from the host (`e.x`, `self.e.x`).

## 1. What the node is

The pipeline is the code that decides **which stage runs next and what a run is when it ends**: the step cursor, the stage loop with its replans, the verify-then-land tail, the close, the run's waits, requests, reload (exec into a newer install) and stuck rule. It calls the stages (plan, write, checks, review, look, land, asks, slots) and the workers; it is called by the roots (`entry`, `launch`). It holds no stage's rule. Its acceptance test is the one of `stage-isolation.md` section 0: **a pipeline test runs on stage fakes, with no Engine and no real git**.

## 2. Measured: what moves, what does not

`run/` is 5,050 sloc (6,759 lines; the bead's "about 6,100 sloc" is lines, and includes the workers node). Historical ownership estimate before C-THIN (a):

| group | sloc | files |
|---|---|---|
| **pipeline** (this bead) | 2,607 | stages 242, run_once 242, closer 161, closer_host 72, closer_notes 93, closer_record 79, closer_branch 65, closer_settle 63, closer_decide 59, resume 130, requests 116, waits 120, reload 104, reflect 67, stage_rounds 79, stage_run 73, decide 85, outcomes 58, done_memo 61, steps 52, budget 42, stage_checks 31, trace 31, summaries 33, ended 38, finish 27, stuck 26, blocked 31, crash, review_glue, state, asked |
| **workers** (C-WORKERS, tl-e5t0.37, not this bead) | 589 | worker_call, worker_request, worker_identity, worker_recovery, delegation, writer_pin |
| **root, stays** | 1,854 | entry 336, lane_acts 178, records 168, fields 136, layout 102, engine 97, shell 79, shared 82, calls 82, plumbing 62, preflight 62, parts_* 143, context 54, console 49, host 33, running 34, ask_flow 60, ... |

C-THIN (a), tl-e5t0.40.1 supersedes the ownership estimate for these run modules:

| classification | modules |
|---|---|
| **composition, stays in run** | ask_flow, bead_env, closer_ports, preflight, reload_ports, shared, shell, stage_checks |
| **logic, move blocked by existing imports** | stage_rounds and stage_run (run.stages), review_glue (run.state), running (prune.verb) |

The four blocked modules remain source modules in `nobody-imports-a-root`; `stages`, `state` and `target` are unchanged. No file moves or new import exceptions accompany this classification.

So the node is about **2,600 sloc**, not 6,100; after the workers node goes too, `run/` keeps about 1,850, and C-THIN (.40) takes that to construction only. `ask_flow`, `records`, `shared`, `shell`, `lane_acts`, `fields` and `layout` are neither pipeline nor workers: the wiring modules `ask_flow`, `shared` and `shell` are now composition roots; the remaining ownership questions are listed in section 6.

How much of the node is already free of the Engine:

- **0 host attrs, leaf modules**: steps, budget, blocked, outcomes, finish, ended, done_memo, summaries, trace, decide, closer_host. The historical estimate was about 520 sloc; `stage_run` stays in run because `run.stages` imports it.
- **Narrow hosts already**: the close family (`closer_*`, 10 to 14 attrs each, behind `CloseHost`/`CloserHost`) and `stuck` (3), `requests` (8), `stage_checks` (6).
- **Wide**: `run_once` 67 attrs, `stages` 43, `resume` 29, `reload` 21, `reflect` 22. These are the real work; they are where the stages' hand-offs hide.

## 3. How a run flows today (the logic the node owns)

Two entries share one lifecycle (`stages.run_stages`, inside `stage_run`):

1. **Continuous** (`RunOnce.go`): `begin` (stop check, peek the bead, start the lease heartbeat, route the delegate, pin check, `tree.reset`, `ask_flow.check`, plan cap grant, acceptance) then `prepare` (resume point; rebase onto the base, salvage on a fixable conflict, a restart on a hard one; a safe point and `planner.plan` when there is no plan) then `stages` (the loop: `stage_loop.run` returns accept or replan; accepted stages are pushed as wip, the checkpoint is saved, a safe point before the land, a rebase on top of the base between stages; a replan is capped by `max_replans`) then the verify gate and `lander.finish`, then `close_out` (the close always runs; a failed close parks; one terminal state is settled).
2. **One stage** (`one_stage`): `select_step` picks the cursor (requested, fresh, manifest, checkpoint), `restore` reconciles it with the checkpoint, `refuse` checks the gate/land preconditions, `dispatch` runs one stage and saves the next cursor.
3. **The close** (`Closer`): save branch, decide the outcome by policy, record the run, file follow-ups, close or block the bead, release the slot.

The fault handling (`Blocked`, `Fenced`, `Exec`, deadline, any `Exception` into `parked_crash`) is the pipeline's too; today it is spread over `go`, `one_stage` and `close_out` with the outcome carried as five fields on the Engine (`kind`, `why`, `landed_sha`, `moved`, `fenced`, plus `asked`).

## 4. The ports the pipeline needs

Read off the calls above, named for the capability (the rule of `stage-packages.md` section 4: no `Host`, `e` or `engine`). Each is a small Protocol that lives with the **consumer** in `app/pipeline/ports.py`; the stage package implements it and the root binds it. A stage that already has a typed port (RunFacts, `CheckpointsPort`, `Narrate`, `StepBook`, `RepoKey` in `contracts/stagefacts.py`) keeps it.

| port | methods the pipeline calls today | served by |
|---|---|---|
| `Planning` | `plan(again) -> PlanData`, `cap.grant()`, `cap.blocked(why)`, `cap.answered_words()` | plan |
| `Writing` | `stage_loop.run(plan, i, state) -> "accept" or "replan"` | write |
| `Reviewing` | `verifier.run(unchecked) -> gaps` | review |
| `Looking` | `render_shots(reqs, n)`, `stale`, `file_owner_look()` | look |
| `Landing` | `finish(bead) -> sha`, `gate.green()`, `gate.run()`, `out.wip_push(i)`, `checkout.fetch()`, `rebase.onto_base(salvage, between)`, `salvage.salvage()`, `restart.again(text)` | land |
| `Slotting` | `tree.reset(bead)`, `Lease(...)` (start, stop, beat) | slots |
| `Asking` | `check()`, `raise_ask(spec, why, kind)`, the close's park/raise calls | asks |
| `Routing` | `route()`, the pin check | workers |
| `Reloading` | `safe_point(step)`, `save_net_pause()`, `Exec` | release |

The first cut is **eight to nine Protocols of 1 to 4 methods each**, not a 36-part host. Two things are not ports and must be removed, not wrapped:

- **`e.Blocked`, `e.blocked_for(...)`, `e.stuck_why`, `e.pending_land_validation`, `e.accepted`, `e.done`, `e.stage_tree`, `e.replans`**: fields that stages write and the pipeline reads (the hand-offs of `stage-isolation.md` 1.1(d)). Each becomes a return value (`StageDone(accepted, stuck_why)`), a value the pipeline owns (`replans`, `accepted`), or a stage-owned state read through its port. B-WRITE, B-REVIEW, B-PLAN, B-LOOK and B-LAND (the dependencies of this bead) decide each; the pipeline must not invent them first.
- **The outcome fields on the Engine** (`kind`, `why`, `landed_sha`, `fenced`, `moved`, `asked`) become one value, `RunEnd` (the existing `oc.RunOutcome` plus `fenced`, `moved`, `asked`), returned by `go`/`one_stage` and handed to `close_out`. `Ended` in `run_once.py` is the seed of it.

## 5. Layout, rules and tests

`src/taskloop/app/pipeline/`:

| module | holds | from |
|---|---|---|
| `ports.py` | the Protocols of section 4 | new |
| `cursor.py` | `parse_step`, `stage_kind`, `select_step`, `manifest_next`, `checkpoint_next`, `previous_run` (pure, or over `RunLocator`) | stages.py |
| `lifecycle.py` | `run_stages`, `one_stage`, `finish_stage`, `record_stage`, `restore`, `refuse`, `dispatch` | stages.py |
| `run.py` | the continuous run (`begin`, `prepare`, `stages`, `on_top_of_base`, `replan`, the verify gate, the land call) | run_once.py |
| `closing.py`, `close_*.py` | the Closer and its steps | closer*.py |
| `faults.py` | the Blocked/Fenced/Exec/deadline mapping to a `RunEnd` (today three `except` ladders) | run_once, stages, crash |
| leaves | steps, budget, blocked, outcomes, finish, ended, done_memo, summaries, trace, decide, stuck, stage_run | same names |
| `waits.py`, `requests.py`, `reload.py`, `reflect.py`, `resume.py` | as today, over ports | same names |

Rules, all written in the PR that moves the module (the HOSTBAN mechanism of #344):

- an import-linter forbidden contract: `taskloop.app.pipeline` imports no `taskloop.app.run`, no stage package (`land`, `plan`, `write`, `review`, `look`, `asks`, `slots`, `release`, `checks`) and none of `wire`/`launch`; stages are reached only through `pipeline.ports` types. `app.run` (the root) imports the pipeline, never the reverse;
- the pipeline joins the converted list of `converted-stages-take-no-host` (ANN401 per-stage ruff, the `host/e/eng/engine` name rule, the list only grows);
- `tests/pipeline/` mirrors the package; its unit tests use `support.facts.fake_facts` and one fake per port (Protocol in `ports.py`, fake in `tests/support/`), and run with no git and no process. Each port gets the contract-then-consumers treatment of CLAUDE.md only where a real adapter exists (the stage's own suite); the fake here is checked by the stage's `tests/<stage>` wiring test.

## 6. Open points (decided by the owner or by the B-* beads, not here)

1. **`ask_flow`, `records`, `shared`, `shell`, `lane_acts`, `fields`, `layout` (about 900 sloc).** They are used by both the pipeline and the stages. `records` (run log, manifest, heartbeat) is pipeline-shaped (it is the run's own journal); `ask_flow` belongs to asks; `shell`/`shared`/`lane_acts` are run facts. The recommendation: `records` moves with the pipeline as `pipeline/journal.py` behind a `RunJournal` port the stages already see as `StepBook`/`Narrate`; the others stay in the root until their owners move them. C-THIN (a) subsequently classified `ask_flow`, `shell` and `shared` as composition roots that stay in run.
2. **`e.Blocked` as an attribute of the host.** The pipeline can import the exception class itself (`contracts`-level, as `fence.Fenced` is), which removes `e.Blocked` and `e.blocked_for`. The `Blocked`/`FixFailed` classes are in `run/blocked.py` (31 sloc, 0 host attrs) and carry an outcome; they move to `contracts` or `pipeline` in slice P1. Needs the architect's kernel-rename (`tlkernel`) to be settled, so P1 does not move them yet.
3. **`reload.safe_point`** execs the process into a newer install; `Exec` is control flow. It stays a pipeline port (`Reloading`) so a test can assert "a safe point was offered before land" without exec.
4. **The checkpoint is not touched.** `CKPT` (.29) is last; the pipeline composes the existing `RunState` from the stage states through `CheckpointsPort`.

## 7. Slices (code starts after tl-e5t0.6, the delegate port, lands; each slice is one PR and lands green with behaviour unchanged)

| slice | moves | needs | size |
|---|---|---|---|
| **P1 leaves** | steps, budget, outcomes, finish, ended, done_memo, summaries, trace, decide, stage_run (0 host attrs, about 450 sloc); `app/pipeline/` and its linter contract appear with them | nothing (touches no file the B-* and delegate lanes edit) | S |
| **P2 cursor** | `cursor.py` out of stages.py, with table tests of `select_step` on plain values; `stages.py` calls it | P1 | S |
| **P3 close** | `closer*.py` as `closing`; `CloseHost` already narrow; the Closer's few `e.` reads become `CloseFacts` | P1, FACTS (done) | M |
| **P4 ports** | `ports.py`, the fakes, and `faults.py`/`RunEnd` replacing the five Engine outcome fields | B-PLAN, B-WRITE, B-REVIEW, B-LOOK, B-LAND (the hand-offs) | M |
| **P5 lifecycle and run** | `lifecycle.py`, `run.py` over the ports; `RunOnce`/`one_stage` become thin; pipeline tests on fakes | P4 | L |
| **P6 waits, requests, reload, reflect, resume** | the wide-attr ones, each with its port | P5 | M |
| **P7 journal** | `records` per open point 1 | decision | M |

P1 to P3 can run now beside the B-* lanes (they touch files only the pipeline owns); P4 on, the order is forced by the hand-offs. Files that are also in flight elsewhere: `worker_call` family (delegate-hard, C-WORKERS), `contracts/*` renames (architect, tlkernel), the stage files (B-* lanes). Each slice states, in its PR body, which of those it touches.

## 8. Decisions to record (proposed)

| decision | proposal |
|---|---|
| name | `app/pipeline` (the term of `stage-isolation.md`); not `run`, which stays the root |
| ports live with | the consumer, in `app/pipeline/ports.py` (stage-packages.md section 4) |
| outcome carrier | one `RunEnd` value instead of five Engine fields |
| P1 to P3 now, P4 on after the B-* beads | as section 7 |
| `records` | moves with the pipeline (P7), pending the owner |

## 9. P4: the close family's ports, from today's call sites (added 2026-11-07, after P3a)

P3a showed the close family (`closer.py`, `closer_notes.py`, `closer_branch.py`, `closer_settle.py`, `closer_decide.py`, with `closer_host.py` composing their hosts) cannot move to `app/pipeline` as it is: each reaches a stage through a module function. Every such call is below, with the exact signature read from the code on main (07a7e21b+), so the ports are what the close needs today, not a guess.

| port (in `app/pipeline/ports.py`) | method, taken from the call site | today's call | implemented by | bound in the root by |
|---|---|---|---|---|
| `AskRules` | `problems(spec: AskSpec) -> list[str]` | `raiser.problems(ended.spec)` (closer.py:112) | asks (`app/asks/closing.py`, a thin class over `raiser`) | `run/closer_ports.py` |
| `ParkBook` | `paused(bead: Bead, kind: Kind, run: str, now: float, *, reason, not_before, fingerprint, producer, permanence) -> Park or None` ; `ended(bead: Bead, kind: Kind, run: str, now: float) -> None` | `parks.paused(e.home, ...)` (closer.py:156), `parks.ended(e.home, ...)` (closer_settle.py:71) | asks (`ParkBook(cfg)` over `app/asks/parks.py`; `cfg` is bound at construction, so the port has no `home`) | same |
| `FollowUps` | `file() -> list[dict[str, str]]` (the leftovers bd refused) | `file_follow_ups(e)` (closer_notes.py:98); it reads the run's leftovers, filed set, stats, store and checkpoint | land (`app/land/followups.py` keeps `file_follow_ups`; the binder closes it over the run) | same |
| `LandCleanup` | `retry(repo: str) -> None` (the cleanup rows a landed run left) | `cleanup.retry_logged(e.git, e.log, is_slot, profile_slots(repo).base, cfg=e.home)` (closer_branch.py:98); `is_slot` is `wire.slots.slot_of` | land (`cleanup`) with the slot predicate from `wire.slots` | the root: it is the only place allowed to name `wire` |
| `BeadClosing` | `close(claim: Claim, reason: str) -> int` ; `block(claim: Claim, why: str, say: Callable[[str], None]) -> int` | `track.close_as(e.who, e.claim, reason, e.store, closeguard.ENGINE)`, `track.block_as(...)` (closer_settle.py:59-67) | track (`app/track/closing.py`, over `verbs`), with `closeguard.ENGINE` (a pure `lambda`) bound by the root, so the pipeline names no guard | same |
| `Slotting` | `leave_slot(outcome: Outcome, branch: str) -> None` | `e.tree.leave_slot(outcome, branch)` (closer_branch.py, a local `LeaveTree` Protocol today) | slots/land (`Tree`) | same; `fence.stale(store, claim)` is `contracts`, no port |

What is already free of a stage: `closer_record` (moved in P3a), `closer_decide` apart from `Narrate`, the branch save in `closer_branch` (git and checkpoint Protocols that are local), and `Closer` itself once its five collaborators are typed by these ports.

Rules for the slices: a port class lives in the stage that implements it (`app/<stage>/closing.py`), never in `app/pipeline`; the pipeline holds only the Protocols; the root file `run/closer_ports.py` is the one place that builds them, small enough to stay under the root ratchet (about 40 sloc, no branches).

### P4 slices (each lands green, behaviour unchanged)

| slice | content | files it touches |
|---|---|---|
| **P4a** | `pipeline/ports.py` with the seven Protocols above; stage-side classes (`asks/closing.py`, `track/closing.py`, `land` `FollowUps` and `LandCleanup` adapters) with their own small tests; fakes in `tests/support/pipeline_ports.py` | new files, plus one line each in asks, track and land; no change to `closer*.py` |
| **P4b** | `closer_settle`, `closer_decide`, `closer_notes` take the ports; they move to `app/pipeline/` (`closing_settle.py`, `closing_decide.py`, `closing_notes.py`) with tests on the fakes | those three files, `closer_host.py`, `closer.py` imports |
| **P4c** | `closer_branch` (`LandCleanup`, `Slotting`) and `closer.py` (`AskRules`, `ParkBook`) move; `closer_host.py` shrinks to the binder `run/closer_ports.py`; the pipeline joins no new exception | `closer_branch.py`, `closer.py`, `closer_host.py`, `run/host.py` |

P4a is safe beside the B-* lanes (new files and one-line additions). P4b and P4c edit files only the close family owns, plus `run/host.py`'s `closer` property. The B-LAND bead owns `app/land/followups.py`; P4a adds the adapter beside it, not inside it, to avoid a conflict.

## 10. P6: waits, requests, reload, reflect, resume, from today's call sites (added 2026-11-07, after P4)

P5 (lifecycle and run) is the large slice and waits for the rename freeze; P6 does not need it. Each file below is its own slice and its own PR, in this order (smallest port set first). The call sites were read on main (526b4eda).

| slice | file (lines) | what it reaches that a pipeline file may not | port or move | implemented by / bound by |
|---|---|---|---|---|
| **P6a** | `waits.py` (165) | `app.run.blocked.Blocked` (a pure class over `contracts`, `domain`); `e.os_lock(path, holder, waiting, timeout=, check=)` is a host method | **move** `blocked.py` to `app/pipeline/blocked.py` (every run importer follows; no shim); `OsLock` port: `__call__(path, holder, waiting, *, timeout, check) -> ContextManager[None]` | the engine already owns `os_lock`; the binder passes it. Tests on a fake lock |
| **P6b** | `requests.py` (151) | Two halves: run consumption and owner verbs using `asks.intake.Intake`, `receipt` | **split**, no port: `pipeline/requests.py` owns `OwnerRequests`, constants, `take` and `peek`, with a local narrow host Protocol and direct `pipeline.blocked.Blocked`; `asks/owner_verbs.py` owns `OwnerVerbs`, `post`, `live`, `newest_run`, using Intake and receipt in asks | run binds `OwnerRequests`; dashboard/CLI use asks owner verbs; all importers follow, no shim |
| **P6c** | `reload.py` (136) | `loop.versions.Installs`, `release.catalog/pins/reexec`, `slots.engine_lock`, `track.trail`, `adapters.halt.RUN_SLOT`, `ident` | `Reloader` port set: `NewerInstall.newer(env) -> (version, dir) or None`; `ReexecBook` (`net_pause`, `note`, `drop`); `Handoff.exec(argv, env)`; `Trail.event(...)`; the `engine_lock` slot read becomes a plain `slot: str` argument | release/loop/track classes in their stages; bound in `run/` |
| **P6d** | `reflect.py` (79), `reflect_prompt.py` | `asks.trustroots.refusal(git, wt, base, bead)`; `tlkernel.childenv.delegate_call_env` | `TrustRefusal.refusal(wt, base, bead) -> str or None` port; `childenv` is in the kernel (allowed), so no port for it | asks (`asks/closing.py`) |
| **P6e** | `resume.py` (196) | `land.gitcall.oneline`; `run.review_glue.apply_review`; `run.state.state_names` | `HeadHistory.oneline(wt, new, old, n) -> str` (land); `apply_review` and `state_names` are run-local: they move with `resume` only if their own imports are free of a stage, else `ReviewRestore.apply(review, *, unchecked, late)` port and `state_names` passed as a tuple | land (`land/closing.py`), root binder |

Rules as in section 9: a port class lives in the stage that implements it; the pipeline holds the Protocols (`pipeline/ports.py`); each moved file takes `self.host`; `.importlinter` lists and the converted-stage contracts follow the move. Each slice lands green with behaviour unchanged. Order by lowest risk: P6a, P6d, P6b, P6e, P6c.

## 11. D-PIPELINE: ownership of the tables, and the thread rules of the ports (added 2026-11-07, tl-e5t0.52)

**Who owns the pipeline's tables.** The `pipeline` Part (`run`, `attempt`, `step`, `effect`, `wait`, `checkpoint`, `timed`, `signal`, and the `ELIGIBLE` prune rule) is owned by the pipeline node but declared in the kernel (`tlkernel/factoryparts.py`), by the same rule as tl-11m4 (the slots Part): a Part the dashboard reads is declared in the kernel and owned by one stage in this design, because `taskloop_dash` imports only the kernel (`.importlinter`, the dash contract) and `DASH_PARTS` lists it. The rows modules the dashboard reads (`runrows`, `waitrows`, `signalrows`, `effectrows`, `locator`, `finish`) stay beside it. What the pipeline owns in code is the *writes*: `RunRows.carry_done_steps` (D1, tl-e5t0.52) is the one cross-run copy, so `pipeline/reload.py` holds no SQL. The checkpoint's stage sections are stored through CKPT (tl-e5t0.29), not here.

**CallState** (the vendor call in flight) is the worker call's own state: every user is in `app/workers`, and the arch table forbids workers importing the pipeline, so it lives in `app/workers/call_state.py` (D2). Its row is the pipeline's `effect` table (`call:<bead>`), written through `tlkernel.effectrows`.

**RunCounters** (`pipeline/reload.py`, `Reload.counters` / `restore_run`) are the run's cost, waited seconds, stats, sessions, write rounds and node counter; they are written by `rundocs.pause` (a network pause) or `rundocs.reexec` (a move to a newer install) and read back once by the next process, which restores them and leaves the time between neither spent nor waited.

**Thread rules per port** (the engine has three threads that touch a run: the main thread, the lease/heartbeat thread, and the close-out under `stop_deferred`):

| port or object | rule |
|---|---|
| `Lifecycle.beat` (called by the lease thread) | runs `records.heartbeat`, emits a `Beat`, calls `StuckTick.tick` and `OwnerRequests.at_beat`; a file that cannot be written must not kill the thread, so every write is suppressed on `OSError` and the thread's death goes to `beat_died` |
| `StuckTick.tick` | holds its own lock: the lease thread and the close-out may tick at once; it reads the log from its last offset, so a second tick sees nothing twice |
| `live_now` (the newest delegate call's live file) | a plain string set by `RunParts.live()` on the thread that starts a delegate call and read by the stuck tick without a lock; a stale read only delays a stuck episode by one beat |
| `ThreadFlag` (`killed`, `wall_hit`) | one value per thread: the lanes of a gate run checks at once, so a shared flag would be the answer of whichever lane wrote last; a port must not move the check onto another thread |
| `OwnerRequests` | `at_beat` only peeks and sets the stop flag; `at_step` takes the rows, on the main thread, at a step boundary; `drop` sets `closing` first so nothing is taken any more |
| `Closer` and its ports (`ParkBook`, `BeadClosing`, `LandCleanup`, `Slotting`) | called on the main thread inside `stop_deferred`; none may start a thread or wait for the lease thread |
| `Reexecs`, `Trail`, `HeadHistory`, `ReviewRestore`, `TrustRefusal`, `AskRules`, `FollowUps` | called on the main thread only; each is a plain function over its own store, with no state of its own |

## 12. State on main 8f570e25 and the closing sequence (added 2026-11-07, tl-e5t0.39 plan; supersedes the slice order of section 7 where they differ)

**What is done.** Slices P1 to P6 and D-PIPELINE landed: `app/pipeline` holds 3,500 sloc in 41 modules (cursor, lifecycle, run body, standalone step entry, the whole close family, waits, requests, reload, reflect, resume, journal, checkpoints, stuck, crash, target, stage_run, review_glue), behind the `pipeline-imports-no-stage` and `converted-stages-take-no-host` contracts. All six B-* and C-WORKERS dependencies are closed. `RunBody`, `Standalone`, `Lifecycle` and the closer are typed by small per-module Protocols, and `tests/pipeline/` (17 files) runs them on fakes (`support.pipeline_ports`).

**What is left**, measured by an AST scan of `src/taskloop/app/run` (1,643 sloc, 27 files; `dev/root_report.py`: root 4,069 sloc, 151 Engine attributes):

| item | sloc / branches | state | blocker |
|---|---|---|---|
| `stage_rounds.py` | 68 / 30 | a standalone write/look/checks/review round; reads 12 host attrs; imports `app.write.*`, so it cannot enter `app/pipeline` | none; its port (`RoundStages` in `standalone.py`) exists |
| `stage_checks.py` | 37 / 3 | `StageChecks(host: Any)`; the checks stage's own step | none |
| `running.py` | 34 / 9 | which beads run now; `prune.verb` imports it and it imports `wire.slots` (the one baseline edge) | reclassified as composition (only roots import it) |
| `stages.py`, `run_once.py` | 21 + 22 | binders (build `Standalone`, `RunBody`, `Lifecycle` over the Engine) | stay as construction |
| `state.py` | 46 / 2 | `StateField` forwards 30 `RunState` fields onto the Engine; this, not logic, is most of the 151 attributes | R4a below |
| the other `run/` files (entry 264, fields 131, layout 103, plumbing 66, parts_* 138, context 76, engine 118, host 98, shell 83, shared 85, ask_flow 60, preflight 65, closer_ports 57, facts 22, ...) | about 1,400 | construction and composition roots (C-THIN a, `.importlinter` lists them); `entry` take-area and `preflight` branches are C-THIN's (tl-e5t0.40.6), not this bead's | C-THIN |
| the pipeline's own hosts | `RunHost` (run.py) 47 members, `StandaloneHost` 41, `RecordHost` (journal) 41, `CloserHost` 31, `resume` 30, `lifecycle` 28, `reflect` 22, `reload` 21 | still "the Engine seen through a Protocol"; each module reads the run's values (`done`, `accepted`, `stage_tree`, `replans`, `stats`, `plan_data`, `pending_land_validation`) as host attributes | the PRs R4a to R4f |

So the 6,100 sloc of the bead text are gone from the root; what remains of its acceptance ("run/ holds only construction; pipeline tests run on stage fakes") is: three logic modules move out (R1 to R3), the run's values stop being Engine attributes (R4a), and each wide host becomes a port bundle the root builds (R4b to R4f), then a ratchet keeps it so (R5).

### PR sequence

Each PR is one bead (child of tl-e5t0.39, label `auto`), lands green, behaviour unchanged, and states in its body the closure delta from `dev/reach.py` (the expectation below is a direction, not a measurement: a PR whose closure rises needs `Ratchet-allow: closure +N <reason>`). A node move is one `Layout-allow: move <reason of 4+ words>` line in the commit; a new package or root is `node`; a loosened contract is `contract`. Tightening a contract (removing a source entry) needs none.

| PR | does | files | closure (expected) | Layout-allow | needs |
|---|---|---|---|---|---|
| **R1** stage_rounds to write | `round_step` and helpers move to `app/write/rounds.py`; `run/stages.py` keeps `RoundStages` as the binder; `run.stage_rounds` leaves the contract's source list | run/stage_rounds, run/stages, app/write/rounds, tests/run/test_selected_stage, test_stage_prepare, tests/write/test_round_result, tests/support/stepgraph, .importlinter | 0 to -1 (a root edge becomes an in-node one) | `move stage_rounds joins the write stage` | none; **first PR that can start now** |
| **R2** stage_checks to checks | `StageChecks` over a `CheckStepHost` Protocol into `app/checks/step.py`; `parts_run.py` binds | run/stage_checks, run/parts_run, app/checks, tests of the stoppable path | 0 | `move stage_checks joins the checks stage` | none; parallel with R1 (disjoint files) |
| **R3** running to slots | reclassified as a composition root; no code moves | run/running, app/slots, prune/verb, launch/loop, loop_ops, cli/prune, run/entry, .importlinter | -1 or 0 | contract | the `wire/slots` port design (tl-e5t0.40.6); start after that note, else R3 designs the port itself |
| **R4a** run values leave the Engine | `RunBody`, `Standalone`, `Lifecycle`, `Closer` and `stage_rounds` read and write `RunState` (the kernel record already behind `StateField`) passed as a value, not `host.done / accepted / stage_tree / replans / extra / stats / plan_data / pending_land_validation`; `run/state.py` forwards only the fields the stages still read through the Engine, the rest are deleted | pipeline/run, standalone, lifecycle, closing*, run/state, run/fields, tests/run/test_state | 0 | none | R1 (stage_rounds touches the same fields); not B3 (it does not touch parks, pauses or pause_reasons) |
| **R4b** `RunBody` ports | `RunHost` becomes separate role Protocol arguments (at most 16 members each), with the Engine passed for every role by `run/run_once.py`; roles preserve lazy cached-property access and read the current `RunState` rather than eagerly constructing a frozen ports dataclass | pipeline/run, pipeline/run_roles, run/run_once, tests/pipeline/test_run | 0 | none | R4a |
| **R4c** `Standalone` ports | `StandaloneHost` becomes separate role Protocols (at most 16 own members each), with the Engine passed for every role by `run/stages.py`; inherited journalling members remain exempt until R4d; `once`, `lease`, `rounds` stay as constructor arguments | pipeline/standalone, run/stages, tests/pipeline/test_standalone | 0 | none | R4b |
| **R4d** journal ports | `RecordHost` (41) in `pipeline/journal.py` is cut into `RunLog` (heartbeat, manifest, log lines) and `RunLedger` (stats, trace) ports; the rows modules stay | pipeline/journal, summaries, trace, tests/pipeline/test_journal | 0 | none | B3-4 (transcript kinds leave trace/journal); after it lands |
| **R4e** resume, reflect, reload | `ResumeHost`, `ReflectHost`, `ReloadHost` become separate role Protocols (at most 16 own members each), with the Engine passed for every role by `run/parts_run.py` | pipeline/resume, reflect, reload, run/reload_ports | 0 | none | B3-1 and B3-2 (they delete `resume` machinery: land first, then narrow what is left) |
| **R4f** closer host | `closing_host.py` (89 sloc, 31 members) is replaced by the ports of section 9 given to `Closer` directly; `run/closer_ports.py` stays the one binder | pipeline/closing*, run/closer_ports | 0 | none | B3 parks / pauses / pause_reasons / policy rows (touches `closing.py`, `closing_settle.py`); after B3-5 |
| **R5** run is construction | a rules test: no `app/run` module outside the composition list defines a class with logic (names from `.importlinter`), no host Protocol in `app/pipeline` over 16 members (ratchet: the list only shrinks), the `run.*` source entries of `nobody-imports-a-root` are gone; docs: `stage-isolation.md` section 2 marks the node done; `dev/root_report.py` numbers recorded | tests/rules, .importlinter, docs | -N | none (a contract entry is removed, not added) | R1 to R4f |
| **R6** pipeline package | carve to `packages/pipeline/{src/taskloop_pipeline, tests}` per the charter: public surface `api.py`, `contracts/`, `testing.py` (the fakes of `support/pipeline_ports.py`); `git mv`, no code change | packages/pipeline, pyproject, .importlinter | measured by `dev/reach.py`; must not grow | `node pipeline becomes a workspace package` | pix-wspike's layout decision (tl-e5t0.65), R5 |

### Order against the other lanes

- **B3 (pix-deleg-iso, tl-hwv5.3.1 to .5, and C-b/C-c).** It touches `app/asks/parks.py`, `pipeline/closing*.py`, `pauses.py`, `pause_reasons.py` and the policy rows, and deletes resume, transcript and context machinery in `pipeline/resume.py`, `journal.py`, `trace.py`. R1, R2, R3 and R4a to R4c touch none of these files and run now; **R4d, R4e, R4f wait for B3-4, B3-1/2 and B3-5** (narrowing code that B3 is deleting would only conflict). Sibling PRs share `.importlinter` only in different list lines.
- **Package split (pix-wspike, tl-e5t0.65).** R6 is the last PR and the only one the layout spike gates; R1 to R5 are layout-neutral (they move code between existing `app/<node>` folders, which a later `git mv` carries). The package's public surface needs R4 first: a package whose ports are the Engine seen through a 47-member Protocol cannot offer `api.py`.
- **C-THIN (tl-e5t0.40.5/.6).** R1 to R3 and R5 take the `run.stage_rounds`, `run.stage_checks`, `run.running` entries out of `nobody-imports-a-root`; they are the same items as tl-e5t0.40.5's first two criteria, so those two close with R3 and R1. The remaining `run/` root sloc (entry, preflight, shell, shared) is C-THIN's.
- **CKPT (tl-e5t0.29).** Untouched: `Checkpoints` already lives in `app/pipeline`; R4a keeps `RunState` as is.

### Decisions (proposed)

| decision | proposal |
|---|---|
| a standalone round belongs to | the write stage (it owns `StageState`, `Prepare`, progress); the pipeline reaches it through `RoundStages` |
| the run's values | one `RunState` value passed to the pipeline; the Engine's `StateField` forwarders are removed as callers stop using them |
| host replacement | a frozen dataclass of ports per entry (`RunPorts`, `StandalonePorts`), built in the existing binder files; no new root file (a new root needs `Layout-allow: node`) |
| the 16-member ceiling | a ratchet in `tests/rules` (R5), list only shrinks |

Beads (children of tl-e5t0.39): R1 tl-e5t0.39.1, R2 .2, R3 .3, R4a .4, R4b .5, R4c .6, R4d .7, R4e .8, R4f .9, R5 .10, R6 .11.

## 13. R6 is not a pure move: what the package imports today (added 2026-11-07, after docs/design/workspace.md)

`workspace.md` section 2 sets the rule: a stage package may import only `tlkernel` (and third parties); a stage that imports `taskloop.adapters`, `stores` or `domain` is not a leaf and its outward imports are settled first. Measured on main (AST of `src/taskloop/app/pipeline`, 41 modules): the pipeline imports **no other `app` stage** (the `pipeline-imports-no-stage` contract holds) but reaches the three layers below it:

| layer | modules and who imports them (pipeline files) | settle by |
|---|---|---|
| `taskloop.stores` (11 files) | `stores.runlog.RunLog` (7: closing_branch, closing_host, closing_record, stage_run, standalone_roles, steps, waits), `stores.bundle.Stores` (5), `tlkernel.storeapi` `Log` / `Doc` / `AmendDoc` (3; now in kernel), `stores.real.real_stores` (stage_run) | **R6a**: the pipeline owns the Protocols it needs (`RunLog`, `Stores` slices) in `pipeline/ports.py` or the kernel record modules; `stores` implements them; `stage_run` receives `real_stores` from the binder |
| `taskloop.adapters` | R6b done (#542 and this PR): app/pipeline imports no taskloop.adapters |
| `taskloop.domain` (24 files) | `domain.outcome` (14 files: the run's outcome vocabulary), `domain.asks.spec/specs` (6), `domain.effects` (4), `domain.lanes` (`caps`, `pauses`, `pin`, `liveness`, `pause_reasons.Producer`), `domain.plan.*` (`brief`, `matchers`), `domain.followups`, `domain.checks`, `domain.interpret`, `domain.stuck`, `domain.work`, `domain.review.kinds`, `domain.land.matchers`, `domain.lifecycle`, `domain.matchers.clip` | **R6c**: the run-end vocabulary (`outcome`, `effects`, `asks.spec`, `pause_reasons`) is shared with stages and the dashboard, so it goes to the kernel by the precedent of WORKKERNEL (tl-e5t0.70, `domain/work`); pipeline-only rules (`stuck`, `interpret`, `lifecycle`) move into the package; the plan/review/land matchers become values passed in |

**R6a done (#537 and this PR): app/pipeline imports no taskloop.stores**

Order and collisions:

1. **R6a (stores) and R6b (adapters)** touch import lines and constructor arguments in pipeline files plus the binders in `run/`; they run now, apart from `closing*.py` lines that B3-5 edits (the lead sequences B3 first for those four files; the rest of each PR does not collide).
2. **R6c (domain)** moves files other stages and the dashboard import; it waits for B3-5 (`domain.lanes.pauses`, `pause_reasons`, policy rows are B3's) and for the kernel-rename lane (`tlkernel`, ENUMS, tl-e5t0.71 landed).
3. **R5** needs R4d to R4f (the 16-member ceiling is real only when no module holds a wide host); only the `.importlinter` cleanup part (the `run.field_ports` source entry) can go earlier.
4. **R6** is then the pure `git mv` it was planned to be, now with `tlpipeline -> tlkernel` as its only edge, plus the four edits per carve of `workspace.md` bug 6 (host_ban converted list, `arch_invariants.SLICE_IMPORTS`, the layers contract, `test_dash_state_paths`), the test move rule (a pipeline test that imports a sibling stage belongs to the sibling or `tests/e2e`; today 77 test files outside `tests/pipeline` mention the pipeline), and the vendored-shelf `pythonpath` decision (the pipeline imports `atomic_io` through `adapters`, check in R6b).

Beads: R6a `tl-e5t0.39.12`, R6b `.13`, R6c `.14`; R6 (`.11`) depends on all three.

R6b part 1 done: stuck.py, reload.py, reflect.py, waits.py, run.py, run_roles.py, standalone.py; remaining: closing*.py, lifecycle.py, journal.py

## 14. R6c split: the domain imports of the pipeline, measured (added 2026-11-07, after R6a and R6b)

Pipeline files import 22 `taskloop.domain` modules (section 13). Consumers outside the pipeline (src, tests, packages) and the module's own `taskloop`/`tlkernel` imports decide where each goes. A module goes to the kernel (`packages/kernel`, by a history-preserving `git mv` plus an import rewrite over src, tests and docs (the pattern of `dev/move_kernel.py` and `dev/split_enums.py`), no shim) when other stages or the dashboard also use it; into `app/pipeline` when only the pipeline does; the pipeline takes a value instead when it only needs a constant.

| cluster | modules (consumers outside pipeline) | destination | PR |
|---|---|---|---|
| pipeline-only | stuck only; interpret is also imported by app/land/sync.py, so it is not pipeline-only and goes with effects in R6c5 | `app/pipeline` (their only deps are `tlkernel`) | **R6c1** |
| small pure helpers | `lanes.caps` (5), `lanes.liveness` (4), `followups` (5), `work.switch` (4), `checks.trim` (3) + `checks.matchers` (18), `review.kinds` (3) | kernel (no `taskloop` deps beyond each other) | **R6c2** |
| the plan/land matchers | `plan.brief` (7), `plan.matchers` (5, needs `domain.checks`), `land.matchers` (9) | kernel, or the pipeline receives the three values it uses (`COMMENTS_ONLY`, `AcceptanceText`, `without_prefix`) as constructor arguments if a move drags more than two further modules | **R6c3** — done: plan.brief (planbrief), land.matchers (landmatchers) and AcceptanceText (acceptancetext) moved to the kernel; plan.matchers stays in the domain (gate_only_criteria needs domain.checks.lint) |
| the run-end vocabulary | `outcome` (27), `lifecycle.matchers` (11), `asks.spec` (19), `asks.lint`, `asks.text`, `asks.specs` (27) | kernel (the WORKKERNEL precedent, tl-e5t0.70); `outcome` needs `asks.spec`, `lifecycle` and `tlkernel.reconcile`, so they move together | **R6c4** |
| pause and effect words | `effects` (9), `interpret`, `lanes.pauses` (13), `lanes.pause_reasons` (11), `beads.park` | kernel; B3-5 (#554, merged) edited `pauses` and `pause_reasons`, so this is free to start | **R6c5** |

Order: R6c1 and R6c2 first (small, independent); R6c3 after R6c2 (`plan.matchers` needs `checks`); R6c4 and R6c5 are the large sweeps (27 and 13 consumers) and run one at a time, each as one PR with `Layout-allow: move` and a closure line. Each PR ends with `grep taskloop.domain` of its modules empty in `app/pipeline`. R6c (`tl-e5t0.39.14`) closes when the last of them lands; R6 (`.11`) follows.

Beads: R6c1 `tl-e5t0.39.15`, R6c2 `.16`, R6c3 `.17`, R6c4 `.18`, R6c5 `.19`.
