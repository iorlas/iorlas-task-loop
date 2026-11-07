# B-LAND: the land stage without the engine (tl-e5t0.36)

Follows `stage-isolation.md` and `b-plan.md`: a typed host first, owned state second, hand-offs last. Checkpoint on disk unchanged.

## Slice 1 was already done

Measured on origin/main, 2026-11-07: `app/land` holds no `Any`. All 18 parts take a small `*Host` Protocol (`commit`, `landed`, `rebase`, `recheck`, `push`, `fixer`, `sync`, `gate`, `outbound`, `pr_land`, `salvage`, `tree`, ...) and `lander_host.py::LanderHost` is the sum of them (NARROW2). The per-step fakes live in `tests/support/narrow_hosts.py`.

## Slice 2 as built: LandState

`app/land/host.py::LandState`, held as `engine.land_state`, takes the six plain engine attributes only the land and its resume rebase touch: `gate_log`, `salvage_tail`, `rebase_orig`, `rebase_pre`, `salvaged`, `remote_oid` (was `land_remote_oid`). Readers outside land: `run/state.py` (gate log for the red tail), `run/records.py` (salvaged), `run/parts_land.py` (remote oid). Left on the engine because they are checkpoint fields (`RunState`) or read by the checkpoint seams: `pending_land_validation`, `landed_sha`, `left_dirty`, `task_branch`, `branch`, `tree_memo`, `fixes`.

## Slice 3 as built: the gate tests off the engine

`tests/support/gate_rig.py::GateRig` is the checks' `FakeCheckHost` plus `land_state` and the stops, a `GateHost` with no Engine; `GateCase.checks_engine(**cfg)` builds one. `test_gate_clean.py` (7 tests) and the eight unit tests of `test_gate_run_in.py` run on it (0.4 s and 0.8 s); the one whole-run test of the second file stays an `EngineTest` class (`SlotGateFlow`). `GateHost.log` is `RunLogPort` (the gate only emits and notes), not the concrete `RunLog`. What still builds a full engine: `test_engine_land_1/2` (52 whole-flow tests), `test_wip_push`, `test_outbound`, `real/test_cleanup`, `real/test_engine_signals`: each drives `run_engine` end to end, so they are the wiring tests of the land (one per consumer), not stage tests.

## Next

- Slice 3: `restart` and the amend family wait for B-PLAN's `AmendState`.
- Slice 4: `landed_sha` and `pending_land_validation` as the land's return value (checkpoint-sensitive).
- Slice 5: the land's remaining engine tests move only if a stage-level assertion hides in them; the whole-flow ones stay.
