# Review synthesis: architecture and data flow (2026-11-01)

Inputs: [architecture.md](architecture.md) (A), [dataflow.md](dataflow.md) (D), [dashboard-backend.md](dashboard-backend.md) (B, when written),
the Mac log review (M, relayed by the owner's session). Written by Codex reviewers; merged and ordered here. A finding is real until a test refutes it.

Common root: **state moves without one owner, one identity and one atomic step.** The incidents of the last 36 h are instances:
pid as identity (hop, F06/F11), config read at several moments (profile, FF of main), a step marked done before its receipt exists
(follow-ups, noop), an error that is rewritten (delegate stop reason).

## Slices, in order of work (Codex writes, tests first, one release each)

| # | Slice (bead) | Merges | Prevents | Touches land/gate behaviour? |
|---|---|---|---|---|
| 1 | PROFILEREAD | A.F01 D.F01 | a malformed or unreadable committed profile becomes "no checks, default push" | no (fails closed before claim) |
| 2 | GATEIDENT | D.F02 | green evidence minted for a tree/base the checks never saw | **yes** |
| 3 | FOLLOWOUTBOX | D.F03 D.F08 D.F09 A.F10 | follow-ups lost on a hop, on a refusal, duplicated on a kill (incident 5, 9) | no |
| 4 | CLEANUPOWN | D.F04 A.F02 | cleanup/reset/probe mutating a worktree a live engine owns (incident 1, 8) | cleanup path only |
| 5 | FENCE | A.F03 D.F05 | stale owner accepted when bd is down; close not tied to generation | **yes** (push/close guard) |
| 6 | DRAFTPLAN | D.F06 | a restart executes a plan that never passed send-back | no |
| 7 | HOPSAFE | A.F04 A.F06 A.F05 | hop to a build that cannot read the checkpoint; loop pid identity; config snapshot per run (incident 2, 3, 9, 10) | no |
| 8 | SETTLE | D.F07 | landed + failed bd sync/close reported as complete, checkpoint deleted | **yes** (close) |
| 9 | PAUSEEPISODE | D.F11 A.F07 | owner pauses not persisted; resumed pause keeps an old deadline (incident 7) | no |
| 10 | CALLMEMO | D.F12 | consumed before memo: a kill repeats a write | no |
| 11 | ASKID | A.F09 | an answer meant for ask A applied to ask B | no |
| 12 | DELEGATECAP | A.F08 | skew between two installs that both say contract 3 (incident 4, 9) | no |
| 13 | PIDIDENT | A.F11 | pid reuse keeps a dead run "live" | no |
| 14 | LAYERS (P3) | A.F12 | effects inside contracts; alias-writable engine | no |

Dashboard slices (B) and Mac-log findings (M) are added to this table when their documents land.

## Rules for the fixes
Each slice: a bead (child of the review epic), a failing test first, Codex writes, `just check` + the suite, release alone.
Slices marked **yes** are announced to the owner's session with the version before release, because the Mac factory is running.
