# Slots carve plan (tl-e5t0.17, and the largest root cut left in tl-e5t0.40.6)

Template: the gate carve (#580, `dev/carve_gate.py`): a pure, rerunnable `git mv` plus importer rewrite, no api.py (consumers import `tlslots.<module>`, as artifacts and gate), one import-linter contract, tests stay where they are and move in a later PR (gate D1/D2). Measured on main ba990b2e.

## What the stage is

`src/taskloop/app/slots/` (16 files) + `domain/slot_liveness.py` + `domain/slot_env.py`: 18 files, 1312 sloc. Outward `taskloop` imports: `adapters.ident` (config.py: `hostname`) and `adapters.{agent, locks, pidcheck}` (engine_lock.py: `running_for`, `hold_path`, `proc_alive`, `proc_start`). No store, no other domain, no other stage. Importers: 24 files in src/taskloop/app, 3 in cli, about 70 test files, dev/race.py, dev/split_wire_slots.py.

## Three PRs, in this order

**S1. The carve (root sloc 0).** `dev/carve_slots.py` moves the 18 files to `packages/slots/src/tlslots/` (the two domain files flat as `liveness.py`, `slot_env.py`), rewrites importers in src, tests, dev, tl.py and mock.patch strings, adds `packages/slots/{pyproject,ruff}.toml`, a contract "tlslots imports the kernel and third parties only", drops `slots` from the app layers and the arch allow-table, and reads tlslots as the slots stage in the closure ratchet. Outward imports settled first, each its own tiny `git mv` PR before the carve:
- `adapters/ident.py` (59 sloc, many importers), `adapters/pidcheck.py` (16) and `adapters/locks.py` (127; 12 importers in src) go to the kernel (identity of the actor, process facts; the stage-carves table already puts ident in the kernel). They import nothing of ours.
- `adapters.agent.running_for` asks `delegate.api.agents()`, which a package may not import: `engine_busy(..., running_for)` takes it as an injected callable, bound by the roots (entry, loop, wire/slots).
Layout-allow: move (per moved module family), node (tlslots), contract. Expected Ratchet-allow closure: none (a pure move; the gate carve needed +4 for init files).

**S2. The machine-bound half of wire/slots.py (root -130).** `slot_table`, `slot_env`, `worktrees`, `take/release` move to `tlslots.machine`. Their adapter uses become one injected `SlotsHost` (a frozen dataclass of callables over kernel ports): `bd(repo) -> Beads` (bd_store, peek), `repo_root`, `hostname`, `os_lock`, `event` (track.trail), `stores(config)`. `wire/slots.py` shrinks to the ~25 sloc that build the host. Callers (entry, doctor, loop, cli/slots) keep the same function names through the binding.

**S3. entry's slot take and run/shared.py (root -118).** `take_area`, `_slot_taken`, `run_any_slot` (~48 sloc left in entry after #606) and `shared.py` (82, notes shared by the tasks of one repo) move into tlslots over the same `SlotsHost`. entry keeps run_in/run_bead/_worktree_of.

## Collisions and order

S1 waits for #608 (touches run/*), #607 (land gate move, two land importers) and any open PR naming slots importers (`gh pr diff --name-only` before starting); the rewrite is rerunnable, so a collision costs a rerun. S2 after S1; S3 after S2. Tests stay in `tests/slots` (about 14 unit files, 8 in real/) until a D-style PR moves the package-pure ones to `packages/slots/tests` against a `tlslots.testing` fake host.

## Risks

- `engine_lock` is on the run-lifecycle path (the by-hand rule of the factory's cutover protocol): S1 must be a byte-for-byte move plus the one `running_for` parameter; the slot race tests (tests/slots/real, tests/fixtures/race) are the proof.
- The kernel grows by three adapter modules (ident, pidcheck, locks); check the kernel's own contracts (no subprocess/socket in `contracts/`) before moving locks.
