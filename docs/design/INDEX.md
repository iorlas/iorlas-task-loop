# Design index

One line per design folder, then the flat documents. Folder ids never rename: a plan is always at
`docs/design/<task-id>/plan.md`, whatever the task is later called. Status: **built** means the successor tree implements
it (the as-built sections at the end of the plan say how); **design** means a plan, review or proposal only, and a
proposed decision stays proposed. Vocabulary is in [the glossary](../glossary.md).

| Folder | Title | Status |
|---|---|---|
| [tl-7i9k.56.1](tl-7i9k.56.1/plan.md) | Retries, cooldowns and pauses | design |
| [tl-8bh9.1](tl-8bh9.1/plan.md) | Repository binding and storage ownership | design |
| [tl-8bh9.13](tl-8bh9.13/plan.md) | Untouched-file and workflow gap analysis | design |
| [tl-8bh9.14.1](tl-8bh9.14.1/plan.md) | Repository profile reader: `.task-loop.json` at a commit, `tl profile show` (block B3) | built |
| [tl-8bh9.2](tl-8bh9.2/plan.md) | Workspace ownership and concurrency | design |
| [tl-8bh9.3.2.1](tl-8bh9.3.2.1/plan.md) | First one-shot plan execution | built |
| [tl-8bh9.4.3.1.1](tl-8bh9.4.3.1.1/plan.md) | Collect one already admitted plan attempt | built |
| [tl-8bh9.4.3.1.10](tl-8bh9.4.3.1.10/plan.md) | Slot preparation under a custody lock: the task branch and the attempt-lifetime ProcessLock | built |
| [tl-8bh9.4.3.1.11](tl-8bh9.4.3.1.11/plan.md) | Release a slot reservation, and abandon an attempt | built |
| [tl-8bh9.4.3.1.12](tl-8bh9.4.3.1.12/plan.md) | Publish the verified plan: push `task/<id>` to the remote | built |
| [tl-8bh9.4.3.1.13](tl-8bh9.4.3.1.13/plan.md) | Scheduling: the factory takes ready tasks into free slots (`tl plan next`) | built |
| [tl-8bh9.4.3.1.14](tl-8bh9.4.3.1.14/plan.md) | Trigger: rounds start by themselves (`tl plan rounds`) | built |
| [tl-8bh9.4.3.1.15](tl-8bh9.4.3.1.15/plan.md) | Generalize the step machinery once: plan becomes the first step kind | built |
| [tl-8bh9.4.3.1.16](tl-8bh9.4.3.1.16/plan.md) | Step sequencing and the implement step kind (slice S5) | design; S5a, S5b, S5c built |
| [tl-8bh9.4.3.1.16 Run S](tl-8bh9.4.3.1.16/run-s-findings.md) | Run S: sandbox and environment spike for block B2 (2026-11-11) | evidence |
| [tl-8bh9.4.3.1.16.2](tl-8bh9.4.3.1.16.2/plan.md) | S5e: the environment for running checks and tests in the agent sandbox (block B2) | design; S5e-1, S5e-2 built |
| [tl-8bh9.4.3.1.16.2 live smoke](tl-8bh9.4.3.1.16.2/live-smoke.md) | S5e and M1 end to end (plan, round advance, implement): owner-run live smoke steps | not run |
| [tl-8bh9.4.3.1.2](tl-8bh9.4.3.1.2/plan.md) | Admit one plan attempt (admission only) | built |
| [tl-8bh9.4.3.1.3](tl-8bh9.4.3.1.3/plan.md) | Managed slots: the smallest slot state admission needs | built |
| [tl-8bh9.4.3.1.4](tl-8bh9.4.3.1.4/plan.md) | Registered attempt entry: launch an admitted attempt into a surviving process | built |
| [tl-8bh9.4.3.1.5](tl-8bh9.4.3.1.5/plan.md) | Plan verification: Git evidence for a returned plan answer | built |
| [tl-8bh9.4.3.1.6](tl-8bh9.4.3.1.6/plan.md) | Plan CLI: run the implemented plan path without a driver | built |
| [tl-8bh9.4.3.1.7](tl-8bh9.4.3.1.7/plan.md) | The agent chooses what to commit; the factory commits it and checks the tree is clean | built |
| [tl-8bh9.4.3.1.8](tl-8bh9.4.3.1.8/plan.md) | Repeat a step whose agent left the slot unsettled | built |
| [tl-8bh9.4.3.1.9](tl-8bh9.4.3.1.9/plan.md) | Keep the tracker claim's lease alive while a step runs | built |
| [tl-8bh9.4.3.1](tl-8bh9.4.3.1/plan.md) | First restart-safe agent execution | built |
| [tl-8bh9.4.6](tl-8bh9.4.6/plan.md) | Adapter audit: purpose, ownership and workflow consequences | design |
| [tl-8bh9.4](tl-8bh9.4/plan.md) | Runtime helpers: remove, consolidate or keep | design |
| [tl-8bh9.5.1](tl-8bh9.5.1/plan.md) | Check execution: remove repetition before choosing a cache | design |
| [tl-8bh9.6.1](tl-8bh9.6.1/plan.md) | Task questions, answers and local waits | design |
| [tl-8bh9.6.2.1](tl-8bh9.6.2.1/plan.md) | Read one task in its configured backlog | built |
| [tl-8bh9.7](tl-8bh9.7/plan.md) | Dashboard state, evidence and task reads | design |
| [tl-8bh9.8.7](tl-8bh9.8.7/plan.md) | Minimal successor foundation | built |
| [tl-8bh9.9](tl-8bh9.9/plan.md) | Git consolidation: mechanism versus factory policy | design |
| [tl-8bh9](tl-8bh9/plan.md) | Architecture review: discussion roadmap | design |
| [tl-sqd3.18.1](tl-sqd3.18.1/plan.md) | Canonical repository inspection | design |
| [tl-sqd3.26](tl-sqd3.26/plan.md) | STORE: reconciled retained scope | design |
| [tl-8bh9.3](tl-8bh9.3/selection-review.md) | Simple scheduling and existing queue policies (no plan.md; selection, lifecycle and priority reviews) | design |
| [tl-8bh9.4.4.1](tl-8bh9.4.4.1/implementation.md) | Registered-start prerequisite delivery (no plan.md; implementation.md) | design |
| [tl-8bh9.8](tl-8bh9.8/curated-replacement.md) | Curated replacement and cutover (no plan.md; curated-replacement.md, operations.md) | design |

## Flat documents

| Document | Title |
|---|---|
| [execution-terms.md](execution-terms.md) | Execution terms: steps, actions and attempts |
| [merge-queue.md](merge-queue.md) | Merge queue: speculative, serial in meaning, parallel in execution (held) |
| [roadmap.md](roadmap.md) | Roadmap: speed and less code (2026-11-06) |
| [self-hosting-roadmap.md](self-hosting-roadmap.md) | Roadmap to self-hosting: the factory develops itself (2026-11-11, proposed) |
| [slot-grant.md](slot-grant.md) | Slot grant: deterministic prevention of the 2026-11-03 stall |
| [slots-carve.md](slots-carve.md) | Slots carve plan (baseline code carve) |
| [sqlite-store-plan.md](sqlite-store-plan.md) | SQLite store plan (baseline migration; STORE slices reconciled in tl-sqd3.26) |
| [stages.md](stages.md) | Stages and their handoffs: audit of night 1 and a redesign (baseline) |
| [dashboard/README.md](dashboard/README.md) | Task-loop dashboard (design only; not in this tree) |

The flat documents mostly describe the baseline implementation or earlier reviews; they are not executable commands.
