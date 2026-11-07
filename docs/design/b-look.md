# B-LOOK: the look stage without the engine (tl-e5t0.32)

Design and slicing only; no code moves with it. Follows docs/design/stage-isolation.md (section 1.2, the worked example). Checkpoint on disk unchanged (CKPT is last).

## What the code holds today (origin/main, 2026-11-06)

`app/look` is `judge.py` (191 lines), `owner_look.py` (151), `shots.py` (219), `host.py` (the `LookHost` Protocol of #295, 40 members). The engine builds them with itself: `Pictures(self, self.git)`, `OwnerLook(self, self.git)`, `Judge` (`app/run/parts_plan.py`).

The look-owned state is on the engine in two different ways, which decides the slicing:

| field | where it lives | read or written outside `app/look` |
|---|---|---|
| look_notes, look_unjudged, look_done, rendered_names, last_reqs, render_stale | **RunState** (the checkpoint), reached as engine attributes through `StateField` (`app/run/state.py`) | `run/state.py` (`keep_look`), `run/run_once.py` (render_stale, last_reqs, look_done), `write/stage_loop.py` (`look_done = 0`), `write/write_round.py` (`render_stale = True`) |
| look_filed, look_retried, shots_skipped, shot_cache | plain engine attributes (`run/fields.py`) | none |
| artifact_repo | plain engine attribute | `look/shots.py`, `run/ask_flow.py`, `run/worker_request.py`, `write/write_round.py` |

ATTR-MAP (stage-isolation.md) says `render_stale` is a write-to-look hand-off and `artifact_repo` a run fact, neither look state. That leaves **nine** look-owned fields (not eleven): done, notes, unjudged, filed, retried, rendered, skipped, shot_cache, last_reqs.

## Target

- `app/look/state.py`: `LookState`, a plain dataclass of those nine (`done`, `notes`, `unjudged`, `filed`, `retried`, `rendered`, `skipped`, `shot_cache`, `last_reqs`). The engine holds one (`engine.look`). Judge, OwnerLook and Pictures get it by constructor, never `engine.look_*`.
- The checkpoint stays as it is: the pipeline fills `RunState`'s six look fields from `LookState` at the two places that write the checkpoint (`Checkpoints.save`, `keep_look`) and loads them back at the one place that restores a run. Because the on-disk record does not change, no COMPAT work is needed (docs/design/compat.md applies when CKPT moves it).
- `render_stale` stays an engine hand-off: write sets it, look clears it through a one-method port (`RenderFlag`), the same shape as `Pause` in the design.
- `artifact_repo` stays an engine attribute (a plain `RunFields` field) until `RunFacts` exists: no such class is in `src` yet (it is designed in docs/design/facts.md, #309, and scheduled in stage-isolation.md section 5.2). `tests/support/check_host.py` is test support, not a home. Look reads and sets it through the one-method `RepoKey` port of that design; once RunFacts lands, slice 2 moves it there.
- The 13 run facts and 11 ports of the design's table become constructor arguments: `Judge(facts, ports, state)`.
- **`LookState` is a plain `RunFields` field** (`self.look = LookState(lambda: self.state)`), never a `cached_property` part, so ENGINE-ORDER's part table (slice 3, 36 parts) is not changed by this bead.
- **The hand-offs stay engine attributes for now**: `unverified`, `leftovers`, `retry_after`, and what `owner_look` reads at close (`unverified`, `look_unjudged`). `LookHost` therefore cannot be deleted in slice 3 as first written: it shrinks to exactly these hand-offs plus the shared run facts, and is deleted only when ASKAI slice 2 (`ai()`) and RunFacts (#309) have taken those. Until then `tests/look/test_look_host.py` keeps guarding what remains.

## Slices (each a PR that passes `just test` alone; the engine's behavior is the same after each)

1. **LookState.** Add it (with a round-trip test over a checkpoint dumped by the old code, `tests/fixtures/checkpoint_v3_look.json`); move the nine fields into it; Judge/OwnerLook/Pictures read `self.state`; `run_once`, `stage_loop` and `state.py` use `engine.look.*` for the fields that moved; the six `StateField`s become one mapping at the checkpoint seams; `tests/run/test_state.py` (StateAttrs equals RunState) learns the six names are carried by `LookState`. Engine attribute count drops by 9 plus.
2. **RenderFlag and artifact_repo as a fact.** `write_round` and `shots.render_shots` stop sharing an attribute.
3. **Ports.** `Judge`, `OwnerLook` and `Pictures` take `facts` and the small ports instead of the host; `LookHost` shrinks to the hand-offs above (deleted only after ASKAI slice 2 and RunFacts); the look tests build the stage from `FakeLookPorts` (as `FakeCheckHost` did for checks).
4. **Report.** Stage closure (forward imports of `app/look`) and the engine attribute count before and after, recorded in architecture-vertical.md (the bead's last AC clause); T-BUDGET (tl-e5t0.55) then ratchets it.

Slice 1 touches `run/fields.py`, `run/state.py`, `run/run_once.py`, `write/*`, which B-CHECKS (pix-architect) may also edit; slice order is: B-CHECKS rebases first or I do, whoever lands second merges.

## Owner decisions

1. **Nine fields, not eleven** (`render_stale` and `artifact_repo` stay outside, per ATTR-MAP). Recommend yes; the bead text says eleven, ATTR-MAP overrides it.
2. **Does `LookState` also carry `render_stale`?** Recommend no: write sets it and look clears it, so neither owns it; a port keeps the hand-off visible.

## Not verified

Counts are greps of `src/taskloop`. Nothing was run for this note. Whether `shot_cache` (a vendor-methods cache, not run data) belongs to look state or to the `Pictures` object is open until slice 1 is written; it is never checkpointed, so either is safe.

## Result (slices 1 to 3 and the fakes, measured 2026-11-07)

Method: `dev/attrmap.py --root DIR` (engine attributes) and the forward import closure of `src/taskloop/app/look/*.py` over `dev/affected.Repo` edges (files under `src/`, stage by `dev/reach.stage_of`), on the commit before B-LOOK 1 (#312) and on this branch.

| | before B-LOOK | after slice 3 |
|---|---|---|
| look files | 5 | 6 (`state.py`) |
| look closure, `src/` files | 75 | 73 |
| of which the shell (`run`, `launch`, ...) | 0 | 0 |
| of which the store layer | 3 | 0 |
| engine attributes (attrmap, all stages) | 186 | 180 |
| `LookHost` members | 40 | 13 (hand-offs only) |

- The look stage never imported the shell; what fell out of its closure is the `stores` layer (3 files: it now sees `RunFacts` and the Protocols, not `RunLog`). `app/look` itself grew by one file (`state.py`) and the closure by one `work` file.
- The engine total fell by 6, not by the nine look fields: other lanes added and removed attributes in the same window. The look-owned attributes that left the engine are exactly the nine of `LookState`; `render_stale` and `artifact_repo` stay as hand-offs (decisions 1 and 2 above).
- `tests/support/look_host.py` (`FakeLook`) builds the three parts on fake ports; `tests/look/test_look_ports.py` holds the tests that no longer need an Engine (epic walk, shot caps, before pictures). The flow tests in `tests/look/test_look.py` run the whole engine on purpose and stay.
- Left for T-BUDGET (tl-e5t0.55): the closure and import-time budget per stage. `LookHost` is deleted when the 13 hand-offs have homes (RunFacts' `artifact_repo`, WRITER/REVIEW state for `leftovers`/`review`).
