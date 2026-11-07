# REWRITE-LAND: what moves, the file count, the cut order (tl-7i9k.38)

Design note only; no code moves with it. Bead acceptance: `app/land` at most 15 files, one step-begin, the procsim land tests green. Ledger rows: M-389 (land as a phase machine over `LandPorts`, at most 15 files), M-227, M-237, M-249 (docs/architecture/review-ledger.md). The bead is ordered after PUSHBASE, R9-37, R9-38.

## Size today (origin/main, 2026-11-07)

`src/taskloop/app/land` has 48 files (47 plus `__init__`), 4,651 lines. 11 files outside the slice import it (`app/run`, `app/checks`, `app/launch`, `app/write`, `app/wire`, `cli/land.py`, `cli/land_stack.py`); 46 test files name it. Most imported: `gate` (21), `outbound` and `cmds` (15 each), `parts` (12), `state`, `lander` (9 each).

The 15 files is a goal, not a rule: a file folds only when the fold makes no import cycle and stays under the 400 SLOC cap (lazy imports are banned, PLC0415). Each move PR checks that and says what it left apart.

**The first plan merged `lander_host` into `host.py`; that is a cycle.** `lander_host` imports the step modules (`commit`, `gate`, `land_rebase`, `push`, `recheck`, `sync`, `outbound`, `pr_land`, ...) for their Host Protocols, and those import `StageCheckout`, `Strays` and `LandState` from `parts` and `state`. One module would make `host` import `commit` and `commit` import `host`. So `lander_host` stays its own module (or folds into `lander.py` when that makes no cycle, checked in its own PR).

## Target

| target | takes | lines | note |
|---|---|---|---|
| host.py | state, parts, phases | ~140 | move 1; leaf types, no step imports |
| lander_host.py | unchanged | 103 | the cycle above |
| lander.py | Lander (`finish`, `land` loop, `outside`, `emit`) | 315 | then `tries.py` cut (step 2) |
| gate.py | gate, verified, profile_change | ~280 | |
| rebase.py | rebase, land_rebase, recheck, commit, gitcall | ~340 | |
| push.py | push, outbound, landed | ~400 | push_evidence stays apart: the wire closure reaches it through cmds, and folding it drags push, gate and host into wire |
| push_evidence.py | unchanged | 23 | |
| push_judge.py | unchanged | 241 | |
| record.py | sync, salvage, restart, followups | ~380 | near the cap: may split |
| fix.py | fixer, fix_outside | ~220 | |
| tree.py | tree | ~190 | checkout (156) and treecheck (76) stay apart: the tree part reads the checkout part, so one file lifts the engine layer table (tests/rules/test_engine_order.py) by one for every part above it, which is not a pure move |
| cleanup.py | cleanup, carry | ~250 | closing stays apart: it imports rebase and cleanup, so folding it makes cleanup -> push -> rebase -> cleanup, and cleanup's stores.real import widens the wire closure by 16 |
| stack.py, cmds.py | stack is 411 lines, over the cap: split, not grown | | cmds stays apart |
| stackgate.py | unchanged | 193 | |
| pr.py | forge, pr_land | ~240 | |
| stay apart | paths, store, section, lock_cmd, flake_book | 12-40 each | each has its own owner (config paths, the factory.db part, the restart section, the lock CLI, the flake book); folding buys a file and costs a reader |
| queue_* (queue, queue_enqueue, queue_land, queue_recover, queue_refs, queue_run) | **untouched** | 534 | the dark merge queue (docs/design/merge-queue.md; `stack.py`'s `queue=` stays off until the rollout); MQUEUE tl-7s2f is on hold. Not moved, not planned, not deleted here |

That is about 25 files plus the six queue files, not 15: the gap is the queue (6), the cycle (1), the over-cap pairs and the five small owners. Merging does not touch a line of logic: concatenation plus import edits in 11 src files and about 46 test files.

## One step-begin

Today `e.steps.begin("land", ...)` is called from `lander.outside` (line 196), `lander.tries` (248, skipped when `Phase.STEP_OPEN` says the outside gate left it open) and `recheck.py:62`; `push`, `tree` and `outbound` open their own steps. The change: one `Lander.begin_try(st, where)` that every try goes through, with `STEP_OPEN` as its only skip rule. Open question I did not settle from the code alone: whether the recheck's begin (a second `land` step for the same try) is wanted in `tl runs slow`; the procsim test `test_land_phases.py` pins the step names today, so the PR must change that test on purpose, not by accident.

## Cut order (each PR passes `just test` alone)

1. **Moves, no logic**: one PR per target group in this order: host, gate, rebase, push, record, fix, tree/cleanup, then stack/pr. Each is a `git mv`, the import codemod, and `just test`. Size stays inside the 400 SLOC cap or the PR does not land.
2. **tries.py split** out of lander.py (pure move of four methods).
3. **One step-begin** (above), with its test change.
4. **M-237** (push classification reads only the tail's last lines) and **M-249** as their own PRs, after 1-3; they change behavior.
5. **LandPorts** (M-389's phase machine over ports): last, only if the owner wants it (decision 2).

## Owner decisions (5), with a recommendation

1. **Scope: does `land-stack` and PR mode count in the 15?** Recommend yes (the bead says `app/land`); the table above does that.
2. **Phase machine over `LandPorts` now, or file merge now?** Recommend the merge now (steps 1-3 meet the acceptance criteria) and LandPorts only after them. A machine rewrite on a lock-and-race path is where the flaky land tests bite; do it with the file count already green.
3. **Order against PUSHBASE, R9-37, R9-38.** Recommend after them, as the bead says: they edit push.py and gate.py, and moving those first would conflict with each.
4. **M-227, already-landed by subject line** (`landed.already` matches `(<bead>)` at the end of the last subject; the ledger marks it ❓). Recommend keep as is in this bead; any other signal (a trailer, ancestry of the task branch) is its own bead with its own tests.
5. **M-237 and M-249 inside this bead or apart?** Recommend apart (step 4): they change behavior, the rest of this bead must not. M-249 (wip_push after a fix round) is in the ledger as one line only; I did not find its description in the repo, so the owner should say what it asks for.

## Unverified

Line counts of merged files are sums of today's files. The `begin` question above. No test was run for this note.
