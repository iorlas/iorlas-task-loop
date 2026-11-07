# The pipeline node: what leaves run/, behind which ports, in which order (tl-e5t0.39, design slice 1)

Design only; no code moves with this note. It turns the one-line "node `pipeline`" of `stage-isolation.md` (section 2) into a module list, a port list and a slice order. Numbers are an AST scan of `src/taskloop/app/run` on origin/main (07a7e21b), 2026-11-07: sloc counts code lines (docstrings, blanks, comments left out); "host attrs" counts the distinct attributes a module reads from the host (`e.x`, `self.e.x`).

## 1. What the node is

The pipeline is the code that decides **which stage runs next and what a run is when it ends**: the step cursor, the stage loop with its replans, the verify-then-land tail, the close, the run's waits, requests, reload (exec into a newer install) and stuck rule. It calls the stages (plan, write, checks, review, look, land, asks, slots) and the workers; it is called by the roots (`entry`, `launch`). It holds no stage's rule. Its acceptance test is the one of `stage-isolation.md` section 0: **a pipeline test runs on stage fakes, with no Engine and no real git**.

## 2. Measured: what moves, what does not

`run/` is 5,050 sloc (6,759 lines; the bead's "about 6,100 sloc" is lines, and includes the workers node). By owner:

| group | sloc | files |
|---|---|---|
| **pipeline** (this bead) | 2,607 | stages 242, run_once 242, closer 161, closer_host 72, closer_notes 93, closer_record 79, closer_branch 65, closer_settle 63, closer_decide 59, resume 130, requests 116, waits 120, reload 104, reflect 67, stage_rounds 79, stage_run 73, decide 85, outcomes 58, done_memo 61, steps 52, budget 42, stage_checks 31, trace 31, summaries 33, ended 38, finish 27, stuck 26, blocked 31, crash, review_glue, state, asked |
| **workers** (C-WORKERS, tl-e5t0.37, not this bead) | 589 | worker_call, worker_request, worker_identity, worker_recovery, delegation, writer_pin |
| **root, stays** | 1,854 | entry 336, lane_acts 178, records 168, fields 136, layout 102, engine 97, shell 79, shared 82, calls 82, plumbing 62, preflight 62, parts_* 143, context 54, console 49, host 33, running 34, ask_flow 60, ... |

So the node is about **2,600 sloc**, not 6,100; after the workers node goes too, `run/` keeps about 1,850, and C-THIN (.40) takes that to construction only. `ask_flow`, `records`, `shared`, `shell`, `lane_acts`, `fields` and `layout` are neither pipeline nor workers: they are run facts and run state (FACTS, `stages.md`), listed in section 6 as the open question.

How much of the node is already free of the Engine:

- **0 host attrs, leaf modules**: steps, budget, blocked, outcomes, finish, ended, done_memo, summaries, trace, decide, stage_run, closer_host. About 520 sloc; they move first and need no port.
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

1. **`ask_flow`, `records`, `shared`, `shell`, `lane_acts`, `fields`, `layout` (about 900 sloc).** They are used by both the pipeline and the stages. `records` (run log, manifest, heartbeat) is pipeline-shaped (it is the run's own journal); `ask_flow` belongs to asks; `shell`/`shared`/`lane_acts` are run facts. The recommendation: `records` moves with the pipeline as `pipeline/journal.py` behind a `RunJournal` port the stages already see as `StepBook`/`Narrate`; the others stay in the root until their owners move them. Not decided here.
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
| `Narrate` | `say(text: str) -> None` | `say(e.storm)` (closer_decide.py:78), from `run/console.py` | already `contracts.stagefacts.Narrate` (FACTS); the root passes the console | same |
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
| **P6d** | `reflect.py` (79), `reflect_prompt.py` | `asks.trustroots.refusal(git, wt, base, bead)`; `adapters.childenv.delegate_call_env` | `TrustRefusal.refusal(wt, base, bead) -> str or None` port; `childenv` is an adapter (allowed), so no port for it | asks (`asks/closing.py`) |
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
| `live_now` (the newest delegate call's live file) | a plain string the main thread sets and the stuck tick reads without a lock; a stale read only delays a stuck episode by one beat |
| `ThreadFlag` (`killed`, `wall_hit`) | one value per thread: the lanes of a gate run checks at once, so a shared flag would be the answer of whichever lane wrote last; a port must not move the check onto another thread |
| `OwnerRequests` | `at_beat` only peeks and sets the stop flag; `at_step` takes the rows, on the main thread, at a step boundary; `drop` sets `closing` first so nothing is taken any more |
| `Closer` and its ports (`ParkBook`, `BeadClosing`, `LandCleanup`, `Slotting`) | called on the main thread inside `stop_deferred`; none may start a thread or wait for the lease thread |
| `Reexecs`, `Trail`, `HeadHistory`, `ReviewRestore`, `TrustRefusal`, `AskRules`, `FollowUps` | called on the main thread only; each is a plain function over its own store, with no state of its own |
