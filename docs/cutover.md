# Cutover protocol

Some changes migrate data or a contract that older code cannot read and that has no rollback: asks format, checkpoint schema,
history version, health state, a delegate contract number. Each is a cutover: nothing live may run across it.

## The steps (one cutover = one freeze window)

1. Tag. Both repos at the version before the change: `v<version>` on iorlas-task-loop and on iorlas-delegate. dev/release.py
   tags every release that way (since R02, 0.23.41); a tag missing for the current version is made by hand:
   `git tag v<version> <sha> && git push origin v<version>`. There is no other tag to look for (`pre-substrate-2026-10-25` was
   never made on either repo).
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

| # | what changed | landed |
|---|---|---|
| 1 | contract 3 (delegate stop reasons), `lane_policy` replacing the `_ai` ladder | R21, 0.23.69, 2026-10-27; release from a dedicated clone came later in O3c, 0.23.113 |
| 2 | RunState and `resume_decision` (the checkpoint reader) | E8b, 0.23.108; the engine moved to src/ in E9b, 0.23.116 |
| 3 | Ask v3 (`v` 2 ask files read as absent: a bead parked on one is re-asked with `tl answer --rerun`), the log tags of dash v2 item 5 | with the dash v2 backend, one freeze window |
| 4 | the Mac on the converted lifesim profile (argv checks, `wall_min`), task-loop 0.23.127 → 0.23.140 | 2026-10-29 |

Records are typed file stores under src/taskloop/stores/; the records.db import was never built. Contract 3 and its consumer
landed together; `tl pin <tl> --delegate <dg>` holds a pair while one of them is rolled back.

The Mac moved from 0.23.127 to 0.23.140 on 2026-10-29, after lifesim's profile was converted on its base branch (`checks` as
argv lists, `timeout_min` → `wall_min`). The order that worked, for any machine whose checkouts lag a profile change:

1. Stop the loop (step 2 above).
2. Fast-forward every registered checkout on that machine (lifesim, and iorlas-task-loop: its own `.task-loop.json` is a
   profile too). Local edits and untracked files that block the fast-forward are reverted or moved aside first, with the
   owner's word.
3. Update the task-loop plugin. The old version cannot read the converted profile, so `tl cutover check` fails on it
   (exit 1 on the renamed keys) until the new version runs it.
4. `tl cutover check` until `CLEAR`, one `tl run-task --dry-run`, then `tl loop`.

Before the first loop on a new version, `tl lint --ready` shows which ready beads the loop will refuse and label `needs-ac`.

## By hand or by the loop

Blast radius decides.

- By hand, in a session, in a freeze window: the engine's own run-lifecycle path (src/taskloop/app/run/), the stop protocol,
  checkpoints, slot reset (src/taskloop/app/slots/), release tooling (dev/release.py, src/taskloop/app/release/), the loop's
  `maybe_move` (src/taskloop/app/loop/loop.py), the pin files. A loop that rewrites its own engine mid-flight would run three
  generations of code at once.
- Loop-safe: delegate classifier and fixtures (a separate process, pinned per loop), lifesim docs and lint, dashboard readers
  (src/taskloop_dash/), tests, check ordering, prompt trimming behind golden tests.
- Never by the loop: `pinned.json`. Only `tl pin` and `tl rollback`, run by the owner, write it. The loop reads it when it
  picks the version to run between beads, and records nothing in it.
