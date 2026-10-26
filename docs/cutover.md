# Cutover protocol

Some changes migrate data or a contract that older code cannot read and that has no rollback: asks format 4, checkpoint
schema, records.db import, history version, health state, contract 3. Each is a cutover: nothing live may run across it.

## The steps (one cutover = one freeze window)

1. Tag. Both repos at the version before the change: `v<version>` on iorlas-task-loop (dev/release.py tags every release;
   a tag missing for the current version is made by hand: `git tag v<version> <sha> && git push origin v<version>`), the same
   on iorlas-delegate. The first one is `pre-substrate-2026-10-25` on both main branches.
2. Stop the loops. `tl stop --repo DIR` for each loop (after the current bead; `--now` only when a run is stuck).
   Wait until `tl cutover check` prints `CLEAR` (exit 0). It lists every live loop and every live run on the registered
   repos and exits 1 while any is live. Do not use `tl stop` on a run you did not start without the owner's word.
3. Migrate. Land the change by hand in a session, release it (dev/release.py), run the migration verb. The previous plugin
   cache dir stays on disk (nothing is deleted), so the old install can still be pinned.
4. Check. `tl cutover check` again, then one bead through `tl run-task --dry-run`.
5. Start. `tl loop --repo DIR` again. A bad cutover rolls back with `tl rollback` (pins the previous task-loop version),
   `tl pin <version> --delegate <version>` for a chosen pair, `tl pin --clear` to follow the installed version again.
   A rollback does not undo a migrated data format: that is why the window exists and why there is a tag to restore from.

`tl cutover check [--json]` is also the guard of any by-hand landing inside a freeze window.

## Freeze windows

- The loop keeps running on lifesim between cutovers. There is one freeze window per slice, not one per change.
- Inside a window: no loop, no run, no release other than the cutover's own, no `tl pin` by anyone else.
- A window ends when step 5 is done or the rollback finished and `tl cutover check` shows only what was started on purpose.

## The cutovers

| # | slice | what changes | needs |
|---|---|---|---|
| 1 | slice 2 | contract 3 (delegate stop reasons), `lane_policy` replacing the `_ai` ladder, records.db import (asks, checkpoints, run logs), release from a dedicated clone | tags on both repos, no live run, delegate and task-loop released as a pair |
| 2 | slice 3 | RunState and `resume_decision` (checkpoint reader) | cutover 1 done, no live run, no parked run waiting to resume |

Contract 3 and its consumer land together; `tl pin <tl> --delegate <dg>` holds a pair while one of them is rolled back.

## By hand or by the loop

Blast radius decides.

- By hand, in a session, in a freeze window: the engine's own run-lifecycle path, the stop protocol, checkpoints, slot reset,
  release tooling (dev/release.py), `maybe_move`, the pin files. A loop that rewrites its own engine mid-flight would run three
  generations of code at once.
- Loop-safe: delegate classifier and fixtures (a separate process, pinned per loop), lifesim docs and lint, `tl prune`,
  dashboard readers, tests, check ordering, prompt trimming behind golden tests.
- Never by the loop: `pinned.json`. Only `tl pin` and `tl rollback`, run by the owner, write it. The loop reads it when it
  picks the version to run between beads, and records nothing in it.
