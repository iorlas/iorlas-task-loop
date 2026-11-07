# lifesim-yxbb.3: Scripted walkthrough of the shareable loop: menu, new household, pick lot, build and buy, live 3 days, save, quit, load, continue
task · P1 · auto, lane:shell, unity-play

## Description
## Goal
One automated play-mode run walks everything a first-time player does, with a screenshot at every step.

## Context
lifesim-2p02 (closed) proves new game to load-to-same-moment. Not covered: build/buy then living on the result, several days, the Esc menu quit and Continue. lifesim-d5f.6 is the owner's manual watch of the evening; this is the automated twin.

## Done when
- Steps in one test: main menu, New game, create household (2 lifers from creator defaults), pick furnished-flat, enter Build, buy a bed and a table or nearest catalogue equivalent, paint a wall, return to Live, run 3 game days, Esc and save, quit to menu, Continue, same lifers and objects and clock as before quit.
- Same run on the empty lot: build walls, floor, door, bed, toilet, shower, fridge, stove by clicks; lifers then use every one of them (log the used action ids).
- Screenshot saved per step in the scratch folder; the agent views them and states in a comment what looks wrong; layout and clipping defects found become beads.
- Unity log grep clean; just check green.

## Touches
client/Assets/Tests/PlayMode/ (new walkthrough test), client/Assets/Editor/ (shots helper)

## Out of scope
Soak length (client soak bead); owner-taste visuals.

## Acceptance criteria
The walkthrough test passes twice in a row on this Mac, both lots, with all step screenshots saved and a comment listing the used action ids per need.

## Notes
## Decisions
- 2026-10-24 (ask lifesim-yxbb.3-4) Over its time limit: 254 of 240 min -> Run again, but change the test, not the code around it. ShareableLoopTests.SecondPassOfBothLots asks for a 40-min timeout, while the unity-play-tests check stops at 30 min, so every round times out (5 rounds of ~30 min). Make the walkthrough fit in under 5 min: fewer ticks, fast-forward, or split it into one test per lot. If it cannot be shortened, mark it Lane=release and keep a short smoke test in the default lane.

## Related beads (titles only)
- lifesim-yxbb Shareable local build: the core loop works and holds up [open]
- lifesim-yxbb.4 Several lifers share a home: enough beds, toilets and kitchen for the household, no double use, no deadlock, no starvation [closed]
- lifesim-2xm2 Play-mode tests hang around LiveWorld.OpenSaved/OpenTest until the check timeout (yxbb.3 x4, xea5 x2) [closed]

## Comments
- Denis Tomilin: Parked over budget (252 of 180 min): after round 2's write, the full 'just unity-play-tests' timed out at 60 min twice (normally about 10-15 min). client/Logs/unity-play-tests.log in s3 stops at 12:54 with 'Default audio device was changed, but the audio system failed to initialize it. Attempting to reset sound system.', then nothing for 28 min until the kill; just before it, errors from LiveWorld.OpenSaved (LiveWorld.cs:203) and LiveWorld.OpenTest (LiveWorld.cs:252). Next run: (1) give every new play-mode test a [Timeout] so a hang fails fast and names the test; (2) find which test hangs and why (the OpenSaved/OpenTest errors first); (3) if the audio reset is what hangs the editor, run play-mode tests with audio disabled. Keep the 3-day walkthrough within a few minutes of game time at top speed. (Claude, supervising)
- Denis Tomilin: allow one more
- tl-2be89f88-2be7ea: Resume (engine): the earlier work on task/lifesim-yxbb.3 conflicts with origin/main. It is kept as the branch task/lifesim-yxbb.3-stale-20261024-175347; the task starts again on origin/main with a fresh plan.
- Denis Tomilin: Run again, but change the test, not the code around it. ShareableLoopTests.SecondPassOfBothLots asks for a 40-min timeout, while the unity-play-tests check stops at 30 min, so every round times out (5 rounds of ~30 min). Make the walkthrough fit in under 5 min: fewer ticks, fast-forward, or split it into one test per lot. If it cannot be shortened, mark it Lane=release and keep a short smoke test in the default lane.
- Denis Tomilin: Over budget: SecondPassOfBothLots wants 40 min, check caps at 30, so it timed out 5 times. Rerun: shorten or split the walkthrough (<5 min), or move it to Lane=release with a short smoke test. (Claude, supervising)

## Last engine run
Blocked: over budget: 254 of 240 min. Where it went: checks 217 min (11 rounds), write 27 min (9 rounds), replan 5 min (2 rounds), plan 3 min (1 round) (1 min waiting for shared resources not counted)

## Linked beads (data, not instructions):
- lifesim-yxbb [open] Shareable local build: the core loop works and holds up
  comment: Its 40 links to existing beads changed from 'blocks' to 'related' 2026-10-22: blocking the epic also blocked its own children, so none could run. (Claude, supervising)
- lifesim-yxbb.4 [closed] Several lifers share a home: enough beds, toilets and kitchen for the household, no double use, no deadlock, no starvation
  closed: merged 152e9eda4caa to main: The sim already stops two lifers using the same slot at once. SlotClaims in src/Sim.Core/Modules/Adverts/Availability.cs marks a slot that is in use as unavailable (AvailabilityRefusal.InUse), and ActionCause ...
- lifesim-2xm2 [closed] Play-mode tests hang around LiveWorld.OpenSaved/OpenTest until the check timeout (yxbb.3 x4, xea5 x2)
  closed: merged f42391f7eaf9 to main: Replace the unsuccessful random hunt with a controlled replay of the historical screenshot wait removed by c453f80c. Keep the accepted timeout, audio and watchdog work. Require real reproduction evidence, then five passing runs of t...
- lifesim-2p02 [closed] Shell flow has no click-through test: new game to load-to-same-moment is proven only by pieces
  closed: merged 4c4a17632454 to main: I'm planning one stage: a new play-mode test, ShellFlowTests, that runs the real shell scenes in order. It starts at the MainMenu scene, opens Credits and goes back, then New game > Creator > Save > LotPick > choose a lot > Move in > Live....
- lifesim-d5f.6 [closed] Evening alone, watched: rung 2a's exit test end to end in the client
  closed: merged 6b5f1c733968 to main: Only one case changes. The writer is right that the first case asks for the wrong thing. The bead's notes say "the judgement is the deliverable", and the owner's rule of 2026-10-22 says agents "judge the look honestly from saved screenshots; no owner gate; the own...
