# B-WRITE: the write stage on injected ports (tl-e5t0.34)

Design and slicing only; no code moves with it. Same pattern as docs/design/b-look.md, over the shapes of docs/design/facts.md (RunFacts, BeadInfo, Narrate, StepBook, RepoKey, CheckpointsPort, CheckerPort) and docs/design/askai.md (the `Asked`/`settle` split of `WorkerCall`). The checkpoint on disk stays unchanged. Scan of `src/taskloop/app` at origin/main, 2026-11-06.

## What `app/write` is

11 files, 931 lines: `StageLoop` (55), `WriteRound` (154), `ReviewRound` (213), `CheckRound` (96), `Prepare` (75), `Handoff` (121), `NewFiles` (90), `Briefing` (50), `StageState` (37, plain), and two helpers (`review_skip`, `show_check`). Every class takes the engine as `host: Any`, except `Prepare` (`PrepareHost`, a `CheckHost` subset: already a Protocol).

An attribute-read scan of the whole directory finds 62 engine attributes that write code reads, of which **2 are used only by write** (`handoff`, `link_check`: parts) and 60 are shared. That is the same picture as look: the weight is in what write *assigns* on the engine, not in what it reads.

## What write assigns on the engine

| engine attribute | assigned in | read by | class |
|---|---|---|---|
| `write_rounds`, `last_summary`, `account_notes`, `strays` | write_round, review_round, newfiles | the shell (`run`), land (`last_summary`) | **write-owned state** (`WriteState`) |
| `stats[...]` (writes, rounds, reviews, tests_added/removed) | stage_loop, write_round, check_round, review_round | land, run (trace) | **counters**: returned as a `StageCounts` value, summed by the pipeline |
| `stuck_why`, `last_run` | check_round, write_round, review_round | land, review | **hand-off** write -> land/close: returned in the stage result |
| `accepted_new`, `unchecked`, `leftovers` | review_round | land, run, plan | **hand-off** (checkpointed `RunState` fields); the stage returns them, the pipeline appends |
| `at_stage`, `stage_tree` | stage_loop | look, review, run | **run position** the pipeline owns; stage_loop gets them as arguments |
| `look_done = 0` | stage_loop (line 37) | look | **write -> look**: a call `look.new_stage()`, never a field write |
| `render_stale = True` | write_round (line 44) | look, run_once | **write -> look** hand-off; `RenderFlag` of b-look.md slice 2 |
| `artifact_repo` | write_round (line 120) | look, run | `RepoKey.key()` of facts.md |
| `writer_family`, `writer`, `sessions` | write_round (lines 83, 146) | look, review, run | **WorkerCall's** to write (askai.md): they move with ASKAI slice 2 |
| `cases.add_cases`, `shared.add_flakes` | write_round | plan, review | calls on the owning part, not field writes: stay as ports `CaseBook`, `FlakeBook` |

Counts are from a grep for `e.X = / += / .append / .add` in `app/write`; the table lists every assignment found (27 lines).

## Target

- `app/write/state.py` already holds `StageState` (one stage's counters, plain). Add `WriteState` next to it for the four write-owned fields; the engine holds `engine.write` as a **plain `RunFields` field** (not a `cached_property` part: ENGINE-ORDER's 36-part table stays as it is). None of the four is in `RunState`, so no checkpoint change.
- Constructor injection: `WriteRound(facts, ports, state)`, `ReviewRound(...)`, `CheckRound(...)`, `StageLoop(...)`, `Handoff(...)`, `NewFiles(...)`, each with the small Protocols it names (at most ~8 ports, 6 methods each): `Narrate`, `StepBook`, `AskAi` (askai.md's `ai`), `CheckerPort`, `CheckpointsPort`, `TreeView` (changed paths, task diff, tree hash), `CaseBook`, `FlakeBook`, `Beads`.
- Hand-offs by value: a round returns `RoundResult(answer, stuck_why, last_run, leftovers, unchecked, accepted_new, counts)`; the pipeline applies it. The seven engine assignments of the middle rows become `return` values.
- `except e.Blocked` in write becomes a typed stop owned by the stage (as in the design).

## Collisions, in the order they bite

1. **ASKAI slice 2** moves the writes of `writer`, `writer_family`, `last_flag` and `planner_ref` out of `worker_call` into the host's `ai()`. B-WRITE must not touch `write_round.py` lines 83 and 146 (`e.writer_family = ...`, `s.wfam`) before it lands; after it, those lines become `asked.session`. **B-WRITE slice 2 waits for ASKAI slice 2.**
2. **B-LOOK slice 2** edits `write_round.py:44` (`render_stale`) and `:120` (`artifact_repo`), and `stage_loop.py:37`. **B-WRITE slices touching `write_round` and `stage_loop` come after B-LOOK slice 2.**
3. **B-LOOK slice 3** changes `LookHost` to the hand-offs below (`unverified`, `leftovers`, `retry_after`, `pause_*`); B-WRITE's `leftovers` row is the same field: whichever slice lands first defines the `Leftover` return value and the other uses it.
4. **ENGINE-ORDER** (pix-hardening) edits `app/write/newfiles.py` (the new-file kind, PR #306 landed it): `NewFiles` is migrated last for that reason.
5. **FACTS** slices 1-2 (#309) must exist for `RunFacts`/`Narrate`/`StepBook`; B-WRITE slice 1 does not need them (it moves state only).

## Slices (each a PR that passes `just test` alone; behavior the same after each)

1. **WriteState.** `engine.write` (plain field) with `write_rounds`, `last_summary`, `account_notes`, `strays`; the reads in `run`/`land` go through it; no checkpoint change (a test over the fixture used for LookState round-trips, since none of the four is checkpointed it is a negative test: the dumped record's field set is unchanged).
2. **Hand-offs by value** (after ASKAI slice 2 and B-LOOK slice 2): `stuck_why`, `last_run`, `accepted_new`, `unchecked`, `leftovers`, counters returned by `ReviewRound`/`CheckRound`/`WriteRound`; the pipeline applies them. One round per PR, `CheckRound` first (smallest, 96 lines).
3. **Ports.** Each class takes `facts` and its ports; write tests build the stage from fakes (as `FakeCheckHost` did); `Any` hosts go.
4. **Report.** Closure of `app/write` and the engine attribute count before and after, in architecture-vertical.md; T-BUDGET (tl-e5t0.55) then ratchets it.

## Acceptance criteria (replacing "as B-LOOK for write")

- `app/write` classes take no `host: Any`; no write-owned attribute is left on the engine (`write_rounds`, `last_summary`, `account_notes`, `strays`).
- No `e.<field> = ...` assignment of a hand-off remains in `app/write` (a grep test in `tests/rules` lists the allowed names and fails on a new one).
- Write tests build the stage from its own fakes; the checkpoint record's field set is unchanged (golden); engine attribute count and `app/write` closure are reported.
- `just test` green after each slice; none touches `paths.py`, ids or the run layout.

## Owner decisions

1. **Counters (`stats`) returned by value, or kept as one shared dict the pipeline owns?** Recommend by value: `stats` is written by four stages today and read by land and the trace; one dict is the shared field this work removes.
2. **Does `WriteState` also hold `unchecked`/`leftovers`?** Recommend no: they are checkpointed `RunState` fields other stages read; they stay run state and write returns additions.

## Not verified

The attribute scan counts name mentions of `e.`, `self.e.`, `eng.` and `host.` and is an upper bound on shared use. No test was run for this note. The size of `RoundResult` is a first guess; slice 2 fixes it round by round.

## Decisions recorded

| Finding | Decision | Contract |
|---|---|---|
| Z11 (ENGINECMD) | Option (d): the writer requests a declared engine check; the engine runs it after normal checks and feeds its output to the next write. Requested reds are informational and consume no red tries. | `engine.checks[].requestable` (false), `engine.max_run_checks` (2), writer `run_checks` ([]). |
