# CRASHMATRIX slice 6: do lost runs resume by themselves? (tl-7i9k.13, R9-15)

Status: design note, 2026-11-06. Nothing here is built. It says what already happens, what the crash matrix has shown, and what is left to decide.

## What happens today when an engine dies

1. **The run is marked lost.** `runlife.reconcile` (contracts/runlife.py) writes `LOST` on every run `is_lost` finds. It is called by tl processes only: loop start, `tl doctor`, `tl wait`, `tl report` and the owner-request gate. The dashboard only reads.
2. **The claim and the slot go back.** On every pass the loop calls `release_dead` (app/loop/loop.py) before the next pick: the claim and slot of an engine actor that no run is on and whose lease ended are given back, so the bead is ready again.
3. **The next run picks up where the records say.** `select_step` (app/run/stages.py) reads the dead run's manifest `next_step` and the checkpoint. The matrix tests (tests/run/test_crash_matrix.py) show that at every edge of the step graph and every kill point it answers the same step or its successor, never an error for a lost run. A close that died inside its effects is finished from the stored outcome (tests/run/test_interpret.py, tests/land/test_crash_after_push.py, dev/killpoints.py).

So a lost run resumes through the ordinary loop: lost, claim released, bead ready, next run resumes. "Auto-resume" is not a missing mechanism.

## What is not known yet (to measure, not to build)

- **Does every lost run get its bead back to ready?** The 36 lost runs of tl-br2.20 are the sample. A lost run whose bead stays claimed, blocked or parked never resumes without the owner. The check is a read: for each LOST run, the bead's state a few minutes later (ready, claimed again, or neither). `dev/census.py` already reads the run table; add a "lost runs, and where their beads went" count.
- **Is a repeated loss counted?** A bead whose engine dies every time at the same step would resume forever. The pause history (`parks`) and the crash fingerprint (`ENGINE_CRASH`) cover a crash the engine reports; a kill from outside (OOM, power) leaves no report. Whether such a loop is bounded is not shown by any test I read.

## Proposal

1. Measure the two questions above with a read-only count (a small addition to `dev/census.py`), on a week of runs.
2. Only if the measure shows lost runs whose beads do not come back, or a kill loop with no bound: one rule, in the loop's `release_dead` pass, that counts consecutive LOST runs of a bead and, past N (default 3), asks the owner (an ask of the existing `stuck` kind) instead of resuming. The matrix then gets a case for it.

## Decisions recorded

| Decision | Date |
|---|---|
| Open: whether the measure justifies the bound (item 2). | - |
