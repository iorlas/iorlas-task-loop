# REWRITE-STAGE: one worker-stage primitive, rounds that return a StageResult (tl-7i9k.37)

Design note only; no code moves with it. Acceptance of the bead (REWRITE-07 in `docs/architecture/review-rewrite-opus.md`): `replan.md` is written in one function; rounds return `StageResult`; one run entry and one cursor. Ledger rows folded in: M-120 (effects return typed results), M-152 (two run entries, two cursors), M-153 (one `next_step(state)`), M-164 (exceptions as the step protocol), M-170 (`app/run` is a god slice), M-196 (RunFields survivability), M-387. Measured on origin/main, 2026-11-06.

## Size

| area | files | lines | tests (files / lines) |
|---|---|---|---|
| `app/plan` (planner 251, sendback 143, prompt 132, cases 144, probe 100, cap, assume, briefs, decisions) | 10 | 1,017 | 16 / 1,321 |
| `app/write` (write_round 154, check_round 96, review_round 213, stage_loop 55, state 37, handoff, newfiles, prepare, briefing) | 11 | 953 | 9 / 659 |
| `app/review` (verifier 200, routing 140, settles 194, link_check) | 4 | 604 | 11 / 1,107 |
| `app/look` (judge 189, shots 217, owner_look 143) + `app/run/reflect.py` 80 | 4 | 629 | 2 / 276 |
| **the stage nodes** | **29** | **3,203** | **38 / 3,363** |
| `app/run` (the run around them) | 60 | 6,548 | |

The nodes share one skeleton: take the host (`Any`: `StageLoop(host: Any)`, `SendBack(host: Any)`), call a worker, parse, send back once on the same thread if the answer is malformed, record, decide the next step. Five places write `replan.md` by hand (`write_round.py:107`, `check_round.py:66` and `:92`, `review_round.py:204`, `resume.py:180`), one reads it (`planner.py:105`, tail 12,500 characters). The architecture note says four; there are five.

The flow between rounds is the string sentinel `AGAIN`/`ACCEPT`/`REPLAN` (`write/state.py`), 8 modules that compare against it. The "found wrong:" prefix is a second string channel: `review/verifier.py` builds it in three places and `review/routing.py:118` tests `startswith("found wrong:")` to classify a defect. `StageState` is a 30-field bag mutated by all three rounds. The one-shot booleans `plan_decided`, `plan_assumed`, `cap_granted` appear in 9 places across `plan/planner.py`, `plan/cap.py`, `run/fields.py`.

Exceptions as protocol: `app/run/blocked.py` `Blocked(Exception)` is raised from `stage_checks.py` (2), `ask_flow.py`, `stages.py`, and caught in `stages.py:143` and `:255`; `FixFailed` is the fix-round variant. It works and the crash matrix covers it (`tests/run/test_crash_matrix.py`); it is also why no round can be called alone.

Two cursors (M-152, M-153): `select_step` (`app/run/stages.py:85`, used by the run and by `preflight.py:52`) picks the step from the manifest and checkpoint; `resume_decision` (`app/run/decide.py:106`, used by `Resume`) decides what a found checkpoint means. Two `begin`s too: `Steps.begin` (`run/steps.py:45`) and `RunOnce.begin` (`run/run_once.py:125`), neither the others' wrapper. This is a different layer from the stage primitive and the dangerous half of the bead (see cut order).

## The primitive

```
Stage(role, prompt, answer_type, validators, route)
run_stage(ctx, stage) -> StageResult
StageResult = Continue | Again(feedback) | Replan(reason, cause) | Accept(answer) | Blocked(kind, spec)
```

`run_stage` owns: the worker call (through the existing `WorkerCall`), the single send-back on the same thread, the `replan.md` write (one function, `replan(ctx, reason, cause, text)`), the counter bump and the record. A node keeps only its prompt, its validators and its router. `Blocked` as a *return value* replaces `raise Blocked` inside rounds; the exception stays at the one place that unwinds to the run's outermost handler, so the run's ending path is unchanged.

`StageState` shrinks to what really crosses rounds (`rounds`, `n`, `feedback`, the failed commands); the 20 per-round fields (`w`, `wfam`, `run`, `red_now`, `acc_first`, ...) become locals of the round.

## What is not in this bead

REWRITE-08 (the state machine with an effect outbox: `next_step`, effects returning results, M-120, M-153) is the engine core, 3,060 lines, "high risk, strangler only, after 01/03/04/05/07". This note keeps the cursor merge (M-152) inside STAGE only as far as one function: `select_step` and `resume_decision` stay separate until the engine bead; the stage primitive does not touch them. M-170 (split `app/run` by slice) is a move of files and follows the primitive (smaller `app/run` once the stage nodes no longer reach into it through `host`).

## Cut order (each a PR green on `just test`)

1. **Golden prompts for every node first.** `tests/domain/test_prompt_golden.py` has 12 cases today; extend to every node's prompt (plan, send-back, write, check feedback, review, verify, look, reflect). No behaviour change; it is the safety net (tests only).
2. **`replan()` in one function**: the five hand writes and the read in one module; `replan.md` format unchanged (golden: bytes equal). First slice of the bead and the one acceptance line that is mechanical.
3. **`StageResult` for the three write-stage rounds**: `WriteRound`, `CheckRound`, `ReviewRound` return it; `StageLoop` matches on it; `AGAIN`/`ACCEPT`/`REPLAN` strings deleted. The "found wrong:" prefix becomes a field (`Defect(kind="found_wrong")`); `routing.py` reads the field. The write-round tests (9 files) and the crash-matrix rows for write/check/review are the proof.
4. **The primitive proper, one node at a time**: verify (fits: worker call + validators + route), then look, then reflect (smallest), each deleting its own copy of the skeleton. Plan last: it has the most special cases (cap, assumptions, `plan_decided`, send-back); its one-shot booleans become `PlanState` fields carried by the checkpoint (they are in `run/fields.py` now, which is M-196's table).
5. **`host: Any` becomes a typed `StageCtx`** (the narrow Protocol of what the stage reads: run dir, checkpoints, stats, warn, stop), per node as it moves; a rules test that no `app/plan|write|review|look` class takes `host: Any`.

Size: in about 250 lines (the primitive and its types) plus the golden fixtures; out about 1,300 of the 3,203 (the architecture note's estimate; this count of the nodes agrees). About 29 src files and 38 test files change over five PRs; cuts 3 and 4 are the wide ones and each touches the same modules the engine rewrite will, so they go one at a time.

## Risks

- These stages are the product: a prompt change is a behaviour change. Cut 1 is the guard; cuts 2-5 must leave every golden file unchanged or say why.
- Resume: a checkpoint written by the old code (a `step="write"` with `rounds`, `n`, `feedback`) must resume under the new rounds. `RoundState` keeps its fields; any rename waits one release.
- The `Blocked` exception is caught at the same two places during the migration; a round that returns `Blocked` and a round that raises it must both end the run the same way (one test per kind).

## Owner decisions, with a recommendation

1. **How far does this go: stages only (cuts 1-5), or with the cursor merge?** Recommend stages only. The cursor belongs to the engine rewrite (REWRITE-08, high risk, needs this first), and merging `select_step` and `resume_decision` is a crash-resume change that `docs/design/crash-resume.md` (#275) wants proven by the kill-point tool first.
2. **`Blocked` as a return value inside rounds, exception kept at the top?** Recommend yes; deleting the exception outright is REWRITE-08's decision.
3. **Plan node last, or first (it is the most-edited prompt)?** Recommend last: most special cases, most risk, and the primitive is better shaped by the four simpler nodes.
4. **Tests: keep the 38 existing test files and add goldens, or rewrite them around `run_stage`?** Recommend keep and add; rewrite a file only when its node moves.
5. **Order against FACTLOG (#278) and READMODEL (#276):** recommend FACTLOG first (it adds the `WriteRound`/`Verified`/`Reflection` rows these nodes would otherwise carry in memory), then STAGE, READMODEL independent. Running STAGE cuts 3-4 in parallel with anything else touching `app/run` is a conflict, not a gain.
