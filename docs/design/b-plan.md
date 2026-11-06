# B-PLAN: the plan stage without the engine (tl-e5t0.35)

Design and slicing only; no code moves with it. Follows `stage-isolation.md`, `attr-map.md` (the amend family is the one open design question there), `engine-order.md`, `facts.md`, and `b-review.md` / `b-look.md` as the method: **a typed host first, owned state second, hand-offs last**. Checkpoint on disk unchanged. Measured on origin/main, 2026-11-07 by an AST scan of `src/taskloop/app/plan` (reads and writes off the host) and a grep of every writer; nothing was run.

## What the stage is today

`app/plan` is ten files, 1,019 lines. Eight parts are built by the engine; seven take `host: Any` and one (`AcProbe`) already has a typed `ProbeHost`:

| part | file (lines) | distinct engine members read | writes to the engine |
|---|---|---|---|
| `Planner` | `planner.py` (251) | 35 | `leftovers`, `amended`, `plan_visual_back`, `plan_summary` x2, `plan_data` x3, `planned` x3, `amend_text`, `plan_decided`, `plan_assumed` |
| `Prompt` | `prompt.py` (132) | 16 | `old_plan`, `amend_text`, `amend_why` |
| `SendBack` | `sendback.py` (143) | 12 | none |
| `Cap` (`ReplanCap`) | `cap.py` (71) | 11 | `cap_granted`, `extra` |
| `Cases` | `cases.py` (144) | 9 | none (appends to `leftovers` once) |
| `Decisions` | `decisions.py` (48) | 9 | none |
| `Briefs` | `briefs.py` (60) | 8 | `snap`, `brief_hash` |
| `AcProbe` | `probe.py` (100) | 6 | none (typed already) |
| `adrsync.py`, `assume.py` | 21, 49 | 2, 0 | none |

58 distinct engine members in all. That is more than look (40) and review (41), and `Planner` alone reads 35; `planner` is layer 2 in `engine-order.md` (it reads `ask_flow`, `briefs`, `checkout`, `routing`), so it is built after those and cannot be the first part converted.

## The 58 members, classified

By reads and writers (attr-map method), not by directory:

| class | members | goes to |
|---|---|---|
| **owned state, private (4)** | `cap_granted`, `plan_assumed`, `plan_decided`, `plan_visual_back` (each written only by plan) | `PlanState` |
| **the amend family (5 + 2)** | `amend_text`, `amend_why`, `amended`, `old_plan`, `plan_summary`; with `last_summary` and `unchecked` they are the 7 "shared" attributes of attr-map. Writers: plan (`planner`, `prompt`), `run/resume.py` (`amend_text`, `amend_why`, `plan_summary`, `extra`), `run/run_once.py` and `land/restart.py` (`amended`, `plan_summary`) | `AmendState`, owned by plan; resume and restart set it through two methods (`resume_into`, `restart_clear`), not by assignment |
| **hand-offs plan produces (3)** | `plan_data` (written in `planner` x3 and `run_once`/`stages` x2), `planned`, `leftovers` (written by plan, look, review, write) | `plan_data` and `planned` become the return value of `Planner.plan` that the pipeline stores; `leftovers` is the review stage's `LedgerSink` (b-review.md), shared |
| **plan's own bookkeeping (3)** | `snap`, `brief_hash` (written by `Briefs.export`), `extra` (the cap's counter, also reset by resume) | `PlanState` (they feed the owner-changed check at a rerun) |
| **run facts (21)** | `bead`, `cfg`, `wt`, `run_id`, `run_dir`, `task_dir`, `brief_file`, `evidence_dir`, `dry`, `scope`, `kind`, `now`, `git`, `store`, `stores`, `steps`, `log`, `checkpoints`, `checker`, `answered`, `verify_answer` | `RunFacts` + ports (`Narrate`, `StepBook`, `Clock`, `Git`, `Stores`, `CheckpointsPort`, `CheckerPort`); `answered`, `verify_answer` are inputs of the call |
| **other stages' parts and methods (27)** | `ai` (`AskAi`), `ask_flow`, `briefing`, `briefs`, `cases`, `checkout`, `hand`, `pictures`, `routing`, `shared`, `shell_probe`, `comment`, `warn`, `move_host`, `blocked_for`, `publish_plan`, `plan_log`, `planner_ref`, `assumed`, `done`, `path`, ... | one small port each, defined by this stage |
| **hand-off in (1)** | `landed_sha` (land writes, plan reads for the amend text) | an argument of the amend call |

So the stage has **seven fields of its own** (`PlanState`: the four flags `cap_granted`, `plan_assumed`, `plan_decided`, `plan_visual_back`, plus `snap`, `brief_hash`, `extra`), **one shared family** (`AmendState`) and two outputs (`plan_data`, `planned`). Everything else is a run fact, a shared port, or another stage's verb.

## The cycles this stage was in

`engine-order.md` removed `ask_flow -> briefs -> planner -> ask_flow` (slice 2 of ENGINE-ORDER, #308). What is left is `planner -> {ask_flow, briefs, checkout, routing}`: all lower layers, so a constructor can take them as arguments. `Cases` is read by `resume`, `settles`, `fixer`, `hand`, `judge`, `owner_look` (six stages), so `CaseBook` is the shared port that matters most: it is also in b-review.md's list, and B-LOOK's. Define it once.

## Slices (each a PR that passes `just test` alone; behaviour unchanged)

1. **Typed host.** `app/plan/host.py` with `PlanHost` (and a narrower view per part where a part reads 12 or fewer members: `CapHost`, `BriefsHost`, `CasesHost`, `DecisionsHost`, `SendBackHost`), built from small capability Protocols the way `look/host.py` and `review/host.py` are; the seven `Any` hosts become typed; `tests/plan/test_plan_host.py` is the conformance test (the Engine has every member; a deleted member fails it). This is where the amend writes become visible to the type checker. No state moves.
2. **PlanState.** The seven private/bookkeeping fields move to `engine.plan_state` (`app/plan/state.py`); `Planner`, `Cap`, `Briefs`, `Prompt` read and write it; `run/fields.py` builds it. `snap` and `brief_hash` are read at a rerun by `run/reload.py`: it reads `plan_state` too. Same mechanical rename as B-REVIEW 1; the checkpoint seams are untouched.
3. **AmendState.** The five amend attributes and their two outside writers: `resume` and `restart` call `AmendState.resume_into(ck)` / `.clear()` instead of assigning. `old_plan` is assigned by tuple (so a grep for `.old_plan =` shows no writer): the slice starts by finding all of them with the type checker, not grep. B-LAND's restart code is the other caller, so this lands after or with B-LAND's host slice.
4. **Hand-offs.** `Planner.plan` returns `Planned(plan_data, summary, planned)` and `run_once` / `stages` store it; `leftovers` goes through the review stage's sink. This is the one behaviour-sensitive slice: `plan_data` is read by `routing.ledger()` between plan writes, so the pipeline must store it before the first read. It needs its own ordering test.
5. **Ports and fakes.** Constructor injection with `facts`, `ports`, `FakePlanPorts` for `tests/plan` (1,000+ lines of engine-built setup). After B-LOOK 3, B-REVIEW 3b and B-WRITE, so `CaseBook`, `TreeView`, `FixRound` are defined once.

## Owner decisions, with a recommendation

1. **Typed host before state (slice order 1 then 2).** Recommend yes: the 58-member host is the inventory that tells slices 2-4 which writes exist; look and review did it this way.
2. **`AmendState` owned by plan, set by resume/restart through two methods.** Recommend yes (attr-map's open question): the alternative, a pipeline-owned object, moves the seven attributes without removing any outside write.
3. **Slice 4 (`Planned` return) in this bead or split off?** Recommend split off as its own bead after slice 3: it changes when `plan_data` is stored, and deserves a separate review.
4. **`CaseBook` defined once in the kernel (`contracts`), used by plan, review and look.** Recommend yes, before slice 5; today three stages each declare their own one-method copy.

## Not verified

Counts are an AST scan of the ten files (reads off `e`, `host`, `h`, `eng`, `engine`, `self.e`, `self.host`) plus a grep of writers; a write by tuple assignment, `setattr` or a local alias is not counted (`old_plan` is one). `ProbeHost` was read, not changed. Whether `extra` is plan's or the cap's alone was read from `cap.py` and `resume.py` only. The slice order assumes B-WRITE (architect, #330) does not move `stage_loop`'s calls into `Planner`; if it does, slice 4 changes.
