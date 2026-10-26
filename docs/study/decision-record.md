# Decision record: measurement before experiments (tl-7y6.1.1)

Decided (from the bead):
- Measure first. Every experiment compares against `baselines-2026-10-25.json`, computed once on one engine version.
- Provenance is part of the number: engine version, source sha, window and scope are in the baseline file.
- Scope is lifesim only. The study's landed and slot-min figures are lifesim-only; its parked/asks figures were all-repo.
- A study figure more than 10% off the recomputed value is listed under `corrections`, not silently replaced.
- Git operations stay with the coordinator; `tl report lifecycle` only reads.

Not supplied, so not decided here: owner overrides of the council, slice order, and which 8 metrics are the experiment
metrics. The 49 study files are not in this repository, so they are not archived here (`~/Documents/Drop/arch-study-1025`).
