# REWRITE-LAND: what moves, the file count, the cut order (tl-7i9k.38)

Design note only; no code moves with it. Bead acceptance: `app/land` at most 15 files, one step-begin, the procsim land tests green. Ledger rows: M-389 (land as a phase machine over `LandPorts`, at most 15 files), M-227, M-237, M-249 (docs/architecture/review-ledger.md). The bead is ordered after PUSHBASE, R9-37, R9-38.

## Size today (origin/main, 2026-11-06)

`src/taskloop/app/land` has 35 files (34 plus `__init__`), 3,591 lines. 11 files outside the slice import it (`app/run`, `app/checks`, `app/launch`, `app/write`, `app/wire`, `cli/land.py`, `cli/land_stack.py`); 46 test files name it (tests/land holds 7,300 lines, procsim-driven). Most imported: `gate` (21 imports), `outbound` and `cmds` (15 each), `parts` (12), `state`, `lander` (9 each).

It holds two jobs that share little but the land lock:

| job | files |
|---|---|
| `tl land`, the Lander: commit, fetch, rebase, gate, push, record | lander, lander_host, state, parts, phases, gate, commit, landed, land_rebase, rebase, recheck, push, push_judge, push_evidence, outbound, fixer, fix_outside, sync, restart, salvage, tree, checkout, carry, cleanup, verified, followups, profile_change, gitcall |
| `tl land-stack` and PR mode | stack, stackgate, cmds, forge, pr_land |

## Target: 14 files plus `__init__` = 15

Merge by what changes together; every target stays under the 400 SLOC cap (line counts below are physical lines, SLOC is lower).

| target | takes | lines |
|---|---|---|
| lander.py | Lander (`finish`, `land` loop, `outside`, `emit`) | ~230 |
| tries.py | the in-lock `tries`, `placing`, `pass_for`, `settled`, `count_stale` (cut from lander.py) | ~120 |
| host.py | state, parts, phases, lander_host (Land, Phase, Placing, Next, the step Protocols, the host, the land phase timer) | ~230 |
| gate.py | gate, verified, profile_change | ~280 |
| rebase.py | rebase, land_rebase, recheck, commit, gitcall | ~290 |
| push.py | push, outbound, push_evidence | ~340 |
| push_judge.py | unchanged | 193 |
| record.py | landed, sync, salvage, restart, followups | ~360 |
| fix.py | fixer, fix_outside | ~220 |
| tree.py | tree, checkout | ~340 |
| cleanup.py | cleanup, carry | ~220 |
| stack.py | stack, cmds | ~380 |
| stackgate.py | unchanged | 152 |
| pr.py | forge, pr_land | ~240 |

35 files to 15. Merging does not touch a line of logic: it is `git mv` plus import edits in 11 src files and about 46 test files (a codemod over `taskloop.app.land.<old>` names). The arch allow table (`land` may import asks, checks, slots) is unchanged.

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
