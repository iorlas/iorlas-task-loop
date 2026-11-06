# REWRITE-DGRUN: delegate's run path, typed (tl-7i9k.45, R9-50 / RW-17)

Status: design, no code. Acceptance of the bead: `RunResult.attempts` reported; the supervisor has no pump loop of its own; `decide` pure.
Findings behind it: M-148 (stringly shell), M-182 (`app/env.py` is a locator), M-259 (retries invisible to task-loop), M-272 (supervisor
re-implements `stream_proc.run`), M-397 (this rewrite). Read from the code at origin/main; line numbers are of that tree.

## What is there

- **Retries inside one call, invisible to the caller.** `Run._launch` (`app/run.py`) runs a ladder: canary probe -> the launch -> one network
  rerun -> schema re-ask (`_schema`) -> and, in `go`, one reroute to another lane on `schema_invalid` (`_reroute`). Each leg is a launch with
  its own history row and usage, but the answer is one `RunResult`: task-loop sees `secs`/`tokens` summed, never that it paid for 3 launches
  (and then retries itself on top: "double retry", M-259).
- **A second pump loop.** `any_agent.supervisor.Supervisor` (vendored; `_pump`, `_wait`, `run`) spawns, reads stdout/stderr in two threads,
  polls watchers every 0.5 s, kills the tree. `stream_proc.runner.run` (vendored, `_pump`/`_wait`/`_release`) does the same job for the checks.
  Two implementations of "run a child, pump lines, stop it on a limit".
- **Decide as a dict.** `decide.decision(...)` returns `(d, lanes, warnings, t)` where `d` is `Router.pick.as_dict()` plus keys added in place
  (`how`, `cap`, `notice`, `warning`, `limit_reset`...). The launcher passes facts back the same way: `res["hung_words"]`, `res["hung_kind"]`
  (`launch.py:403`) popped in `settle.py:111,132`. A misspelled key is a runtime `KeyError`, not a type error. `decision` also *writes*
  (`env.update_state(mark)`, `apply_profile`) when `apply=True`: it is not pure.

## Decisions to make before code

1. **Where the pump unification lives.** `any_agent` and `stream_proc` are vendored from shelf (`skills/task-loop/_vendor`); delegate must not
   edit vendor files, and `tl-w7lt.37` (DELEGATEHOME: where delegate lives) is an open owner decision. So the supervisor change is a **shelf
   change** (make `Supervisor.run` call `stream_proc.run` with line/tick callbacks and a `should_stop` poll) and then a re-vendor.
   Recommendation: do it in shelf, not here; this repo's part is the typed result and typed decide. Until the owner decides DELEGATEHOME, the
   third acceptance item is *blocked on shelf*, say so on the bead.
2. **Shape of `attempts`.** Recommendation: additive, a list on `RunResult` (`ABSENT` when empty so the golden wire stays unchanged for a
   single launch): `Attempt(kind: "first"|"canary"|"network_rerun"|"schema_reask"|"reroute", lane, model, outcome, secs, tokens)`.
   task-loop reads the list to charge budget per launch and to stop retrying on top of a delegate that already retried. Contract stays 4
   (additive field, `Absent`); add capability `attempts` so the caller can tell "no field" from "older delegate".

## Plan (each its own PR, tests first)

1. **`Attempt` record + wire.** `contracts/wire.py` `Attempt`, `RunResult.attempts`; golden fixtures regenerated (`dev/gen_contract.py`);
   contract.json capability. Test: a run that takes the schema re-ask reports two attempts, a plain run reports none (field absent).
2. **Record attempts in the ladder.** `Run._launch`/`_canary`/`_schema`/`_reroute` append to an `Attempts` list instead of merging dicts
   (they already compute each leg's result; today they overwrite or sum). Test per rung with the existing fakes (`delegate_fakes/fake_run.py`).
3. **Typed launch result.** Replace the `res: dict[str, Json]` between `launch_worker`, `_launch` and `Settler` with a frozen `LaunchResult`
   (outcome, say, text, data, tokens, hung: Hung|None, started: bool, ...): `hung_words`/`hung_kind` become one `Hung(words, kind)` field.
   Mechanical: every `res["x"]` site becomes `res.x`; `dict` stays only at the JSON edge (`answer.py`).
4. **Pure decide.** Split `decision(..., apply)` into `decide(inputs) -> Decision` (a frozen record from `Router.pick`) and a separate
   `apply(decision)` that does `update_state(mark)` and `apply_profile`. `how(...)` becomes a field of `Decision`. `status`/`next` call only
   the pure half (this is also what tl-sqd3.11 STATUSPURE already asserts by test).
5. **Supervisor on `stream_proc.run`** (shelf; see decision 1). Not started here.

## Out of scope

`app/env.py` as a locator (M-182) is Ctx/injection work, a separate bead. Moving delegate (DELEGATEHOME). Changing any stop reason or lane
decision: this is a refactor with one additive wire field.

## Risk

Step 3 touches ~60 dict sites in `run.py`, `launch.py`, `settle.py`; the golden answer fixtures (`tests/delegate/contracts/golden/*.json`)
are the safety net and must stay byte-identical except for the added `attempts` where a ladder retried.
