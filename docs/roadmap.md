# Roadmap: from a supervised engine to an unattended loop

Accepted by the owner 2026-10-21. Epic tl-bxk; one epic per milestone. `bd list --parent <epic>` shows the work left.

## Where we are (M0)

`tl run-task ID` runs one bead through the engine. A Claude session picks each bead, starts it, reviews it and
answers its asks. On 2026-10-21 this landed 16+ lifesim beads (25-90 min each, 0-2 fix rounds) and found an engine
flaw after almost every early bead (0.15.0 to 0.15.7 in one day). The engine is now steady enough that the session's
per-bead dispatch is the bottleneck, not the engine.

## Milestones

| | epic | what | done when |
|---|---|---|---|
| M1 | tl-bxk.9 | `tl loop`: one sequential loop. Each pass takes any free slot (waits if none), picks by the queue rule, claims, runs the bead, releases the slot, goes on. An ask parks the bead and the loop moves on; a lane out waits; 2 failures in a row stop it. One summary line per bead | its beads are closed and one live lifesim bead ran through it |
| M2 | tl-bxk.10 | trust run: one loop, one night, no supervisor | >=10 beads; >=7 land with no owner ask; 0 lost work; 0 engine crashes (scored by `tl report`) |
| M3 | tl-bxk.11 | concurrency: N tasks at once on N slots | one night on 3 slots with no double claims and no broken lands, scored as M2 |
| M4 | tl-bxk.12 | unattended: budgets, launch and restart without a session, asks pushed to the owner, morning digest, usage feed without a session | a week with no supervisor |

M2 blocks M3 and M4. Passing M2 is what "runs reliably" means.

## Design choices

- **A loop, not a dispatcher.** Atomic claims (`bd --claim`), `tl slot take` and the land lock already make several
  sequential loops safe; a central dispatcher (the old factory `one_pass` port) adds a reaper, events and deadlock
  detection that a sequential loop does not need.
- **Slots are taken inside the loop**, never assigned up front: the same code later runs one loop with N tasks
  (decided in M3 from M2 data, tl-bxk.11.2).
- **The queue rule lives in the repo's `.task-loop.json`** (pick label, skip labels, epic order, lowest ID), and
  `tl next` prints what the loop would pick and why, so a pick can be checked before it runs.
- **Review is async.** The loop writes a summary line per bead; a supervisor (or later the reflect step, tl-05s)
  reviews it while the next bead runs. Engine fixes still go tests first.
- **A Claude session is still needed until M4** to feed delegate the Claude usage windows (`tl.py usage`, tl-bxk.2).

## Safe by construction

Rule (owner, 2026-10-21): every shared thing is taken through a lock or lease in code, and a second taker waits in
line; a message between sessions is never the guard. Clashes may happen; they must resolve themselves.

| shared thing | guard | a second taker | gap |
|---|---|---|---|
| a bead | atomic `bd --claim` | the loop takes the next bead | |
| a slot | slot bead + `<worktree>/.task/engine.lock` (pids with start times) + `tl slot hold` | the loop waits; a hand run refuses | fair queue for waiters, tl-bxk.11.5 |
| the base branch | land lock, rebase, retry | waits | |
| Unity on the machine | the repo's OS counting locks (lifesim `tools/unity_slot.py`) | waits | |
| a model lane | delegate's leases; busy answers `retry` | waits until `retry_after` | |
| files two beads both edit | none: conflicts show at land as a rebase or fix round | | areas, tl-bxk.11.4 |
| the repo's `.task-loop.json` | read from the base branch after a fetch (`tl.profile`); the working tree only with no remote | the next fetch reads the new rule | |
| an engine release | `dev/release.py`: an OS lock, the version from origin/main, the suite, a push race retried once | waits in line, told who holds it | |
| a stopped engine's worker | engine SIGTERMs route.py, which kills the worker's group; SIGKILL after a grace | | |

All of it is proven together by one race test (tl-bxk.11.1): two loops, a hand run, a slot hold and a release at
once.

## Not on the roadmap

tl-sq8 (blueprint), tl-bl5 (improve from reflections), tl-4af (dashboard across machines), tl-65w (old transcript
index), tl-y2y (Windows live run), tl-bxk.7 (research link checks), tl-bxk.6 (screenshots on the bead), tl-4qg.
