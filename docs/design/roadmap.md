# Roadmap: speed and less code (2026-11-06)

Rule: a bead that makes checks, tests or lands faster, or deletes code, goes first. Everything else waits.
Bead ids are the source of truth; this file only orders them. Update it when a wave finishes.

## Wave 1: now (lanes running in parallel)

| Goal | Beads | Lane |
|---|---|---|
| Store on sqlite, files deleted | STORE slices (tl-sqd3.26.*), then STORE 8 (tl-sqd3.26.8, delete legacy file stores) | engine |
| Fewer tests per change | tl-wz4z AFFECTEDTESTS, tl-7i9k.23 SUITEONCE, tl-wnup.9 | gatespeed |
| Gate runs once, in the slot | tl-wxcg GATEINSLOT, tl-op26 GATEREUSE, LINUXEXEC follow-ups | linuxexec |
| No flaky reds, no hangs | tl-fmll, tl-i222, tl-eumb, tl-frrm, tl-7i9k.62, tl-m8u2, tl-7i9k.20 | reliab |
| Less code in task-loop | tl-w7lt.16, .9, .10, .8 (shelf moves); tl-7i9k.32 DEADCODE; tl-7i9k.34 | shelf, hardening |
| See where time goes | tl-9un.23 RUNSQ, tl-br2.16 LANDTIME, tl-7k8.3 | dash |

## Wave 2: after STORE run-dir state

- LAYOUT: tl-9un.40, .43, .44 (runs/<run>/ bundle, migrate), then tl-9un.45, .46, .47 (loop id, checkpoints, retention).
- tl-wnup.4 (255 temp-dir sites to the workdir fixture): wide test edit, run when no other lane has open test PRs.
- tl-wnup.2, .3 (split delegate spawner tests, procsim contract suite).
- tl-w7lt.11 SHELF-LEASE (after STORE leases settle), tl-w7lt.13, .18, .19, .7.

## Wave 3: later

- Delegate isolation: tl-hwv5.*, tl-w7lt.37 DELEGATEHOME (owner decision first).
- GATEHOST tl-7eoh.* (mostly moot while all work runs on pix), WINEXEC and WINENGINE (tl-w7lt.38.12, .38.13).
- M2 trust night tl-bxk.10.4: parked until the backlog is dealt with (owner, 2026-11-06). M3 and M4 follow it.
- A new architecture review: after wave 2 (66 review beads are still open: tl-7i9k, tl-br2, tl-3cl).
