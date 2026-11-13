# Design index

One line per design folder, then the flat documents. Folder ids never rename: a plan is always at
`docs/design/<task-id>/plan.md`, whatever the task is later called. Status: **built** means the successor tree implements
the bounded scope identified by its status note and source/as-built evidence; **design** means proposed or
accepted scope without a completion claim; **evidence** means a dated review, experiment, delivery record or smoke
result. Mixed documents identify their built portions separately from remaining design. Historical command examples
are preserved as evidence, not current operator instructions; use the [README](../../README.md) and CLI help.
A proposed decision stays proposed. Vocabulary is in [the glossary](../glossary.md).

| Folder | Title | Status |
|---|---|---|
| [tl-7i9k.56.1](tl-7i9k.56.1/plan.md) | Retries, cooldowns and pauses | design |
| [tl-8bh9.1](tl-8bh9.1/plan.md) | Repository binding and storage ownership | design |
| [tl-8bh9.13](tl-8bh9.13/plan.md) | Untouched-file and workflow gap analysis | design |
| [tl-8bh9.14.1](tl-8bh9.14.1/plan.md) | Repository profile reader: `.task-loop.json` at a commit, `tl profile show` (block B3) | built |
| [tl-8bh9.14.6](tl-8bh9.14.6/plan.md) | The checks step: the factory runs the profile's checks on X (block B4, milestone M2) | built S6a–S6e (as-built sections 21–25); M2 smoke evidence below |
| [tl-8bh9.14.9](tl-8bh9.14.9/plan.md) | Questions and holds with keep-awake and the Git read timeout: every stop of a round-taken task held with its reason in the tracker, answered by editing the task and re-adding its label (block B7 with B11 and B13, milestone M4) | built H1–H3 and K1 (as-built sections 24–27), G1/G2 (section 14, later release/use); M4 evidence below records its checkpoint limits |
| [tl-8bh9.14.8](tl-8bh9.14.8/plan.md) | Land and close: `tl step land TASK`, one squash of X onto origin's `main`, validated when its tree changed, pushed never forced, task closed (block B6, milestone M3) | L0-L5 built (git-porcelain 0.17.0; schema v13, land store; shared validation and release; the land operation through delivery, `--withdraw`, `open_land`; the tracker close, S's message, `--summary`; `tl step land`, status and `Next` words, the abandon order, guide); M3 smoke passed 2026-11-12; `origin` trusted as configured, no push-URL guard (owner decision 2026-11-12, plan section 29.3) |
| [tl-8bh9.2](tl-8bh9.2/plan.md) | Workspace ownership and concurrency | design |
| [tl-8bh9.3.2.1](tl-8bh9.3.2.1/plan.md) | First one-shot plan execution | built |
| [tl-8bh9.4.3.1.1](tl-8bh9.4.3.1.1/plan.md) | Collect one already admitted plan attempt | built |
| [tl-8bh9.4.3.1.10](tl-8bh9.4.3.1.10/plan.md) | Slot preparation under a custody lock: the task branch and the attempt-lifetime ProcessLock | built |
| [tl-8bh9.4.3.1.11](tl-8bh9.4.3.1.11/plan.md) | Release a slot reservation, and abandon an attempt | built |
| [tl-8bh9.4.3.1.12](tl-8bh9.4.3.1.12/plan.md) | Publish the verified plan: push `task/<id>` to the remote | built |
| [tl-8bh9.4.3.1.13](tl-8bh9.4.3.1.13/plan.md) | Scheduling: the factory takes ready tasks into free slots (historical `tl plan next`, now `tl step next`) | built |
| [tl-8bh9.4.3.1.14](tl-8bh9.4.3.1.14/plan.md) | Trigger: rounds start by themselves (historical `tl plan rounds`, now `tl step rounds`) | built |
| [tl-8bh9.4.3.1.15](tl-8bh9.4.3.1.15/plan.md) | Generalize the step machinery once: plan becomes the first step kind | built; section 17 (a new task branch starts at the local `main`'s tip, M2 finding 1) built, open to veto |
| [tl-8bh9.4.3.1.16](tl-8bh9.4.3.1.16/plan.md) | Step sequencing and the implement step kind (slice S5) | design; S5a, S5b, S5c built |
| [tl-8bh9.4.3.1.16 Run S](tl-8bh9.4.3.1.16/run-s-findings.md) | Run S: sandbox and environment spike for block B2 (2026-11-11) | evidence |
| [tl-8bh9.4.3.1.16.2](tl-8bh9.4.3.1.16.2/plan.md) | S5e: the environment for running checks and tests in the agent sandbox (block B2) | design; S5e-1, S5e-2 built |
| [tl-8bh9.4.3.1.16.2 live smoke](tl-8bh9.4.3.1.16.2/live-smoke.md) | S5e and M1 end to end (plan, round advance, implement): owner-run live smoke steps | M1 passed; S5e checklist partly |
| [tl-8bh9.4.3.1.16.2 M1 smoke](tl-8bh9.4.3.1.16.2/m1-smoke-findings.md) | M1 end-to-end live smoke: plan, round advance, implement on a scratch remote (2026-11-11) | evidence |
| [tl-8bh9.14.8 live smoke](tl-8bh9.14.8/live-smoke.md) | M3 live smoke runbook: `tl step land` on a scratch bare remote and tracker (same tree, moved main, interrupts, `target_moved`, refusals) | runbook; passed 2026-11-12 |
| [tl-8bh9.14.8 M3 smoke](tl-8bh9.14.8/m3-smoke-findings.md) | M3 live smoke: `tl step land` on a scratch remote (same tree, moved main, Ctrl-C and `kill -9`, `target_moved`, `remote_rejected`, withdraw, lost answer, no change, conflict) (2026-11-12) | evidence |
| [tl-8bh9.14.9 M4 smoke](tl-8bh9.14.9/m4-smoke-findings.md) | M4 live smoke ([runbook](tl-8bh9.14.9/live-smoke.md)): holds in the rounds (needs_owner, failed check, closed, hand-started, `kill -9` entry, dirty slot, `branch_moved`, label rule, re-ingestion) and keep-awake exits on a scratch remote (2026-11-12) | evidence; holds/keep-awake passed, Git-timeout check blocked at that checkpoint; later G1/G2 implementation in the plan |
| [tl-8bh9.14.6 M2 smoke](tl-8bh9.14.6/m2-smoke-findings.md) | M2 live smoke: the check step in the rounds (pass, fail, lingering, interrupt, abandon) on a scratch remote (2026-11-11) | evidence |
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
| [tl-sqd3.18.1](tl-sqd3.18.1/plan.md) | Canonical repository inspection | built; `tl repo inspect PATH` and inspection contracts |
| [tl-sqd3.26](tl-sqd3.26/plan.md) | STORE: reconciled retained scope | design |
| [tl-8bh9.3](tl-8bh9.3/selection-review.md) | Simple scheduling and existing queue policies (no plan.md; selection, lifecycle and priority reviews) | built bounded selection/priority; historical lifecycle review and other alternatives remain design/evidence |
| [tl-8bh9.4.4.1](tl-8bh9.4.4.1/implementation.md) | Registered-start prerequisite delivery (no plan.md; implementation.md) | evidence; delivered owning-library prerequisite, not whole factory completion |
| [tl-8bh9.8](tl-8bh9.8/curated-replacement.md) | Curated replacement and cutover (no plan.md; curated-replacement.md, operations.md) | design |
| [tl-8bh9.14.13](tl-8bh9.14.13/plan.md) | Time since the agent's last command from event evidence | built; bounded stream reader and CLI display contracts |
| [tl-8bh9.14.113](tl-8bh9.14.113/plan.md) | Docs and CLI consistency | built; validation and sandbox limits in the as-built record |
| [tl-8bh9.14.156](tl-8bh9.14.156/plan.md) | The factory at conventional locations: slots by repo name, config by convention, dashboard by default, and the cut-over runbook | built (code); runbook not yet run |
| [tl-8bh9.7.4](tl-8bh9.7.4/plan.md) | Readable live activity of an agent attempt | built bounded reader/feed; full-history paging and session reuse remain design |
| [architecture-review](architecture-review/grilling-record.md) | 2026-11-13 review, [playbook](architecture-review/architecture-review-playbook.md), [decisions](architecture-review/decision-register.md), [format alternatives](architecture-review/fmt/ALL-variants.md), [ontology](architecture-review/ontology/00-README.md) and [checker prototype](architecture-review/docscheck-proto/REPORT.md) | evidence and design; prototype specimens are preserved examples, not current instructions or installed gates |
| [dashboard](dashboard/README.md) | Historical baseline dashboard specification, reviews and mocks | design/evidence; superseded for current behavior by [dashboard-ui.md](dashboard-ui.md) |

## Flat documents

| Document | Scope/status |
|---|---|
| [dashboard-ui.md](dashboard-ui.md) | built slice 1; current optional dashboard, routes and remaining design |
| [execution-terms.md](execution-terms.md) | design; historical reasoning, glossary owns current terms |
| [layers.md](layers.md) | design; proposed layer judgments and quoted owner decisions |
| [merge-queue.md](merge-queue.md) | design; explicitly held speculative queue |
| [roadmap.md](roadmap.md) | design; historical 2026-11-06 baseline roadmap |
| [self-hosting-roadmap.md](self-hosting-roadmap.md) | design with built milestones and evidence identified in the record |
| [self-hosting-real-run-1.md](self-hosting-real-run-1.md) | evidence; dated real-task run and findings |
| [self-hosting-trial.md](self-hosting-trial.md) | evidence; trial 1 |
| [self-hosting-trial-2.md](self-hosting-trial-2.md) | evidence; trial 2 |
| [self-hosting-trial-3.md](self-hosting-trial-3.md) | evidence; trial 3 |
| [self-hosting-trial-4.md](self-hosting-trial-4.md) | evidence; trial 4 |
| [self-hosting-trial-5.md](self-hosting-trial-5.md) | evidence; trial 5 |
| [self-hosting-trial-5-fixes.md](self-hosting-trial-5-fixes.md) | evidence; repairs, partial work and revisitable decisions |
| [self-hosting-trial-6.md](self-hosting-trial-6.md) | evidence; trial 6 |
| [slot-grant.md](slot-grant.md) | design; historical baseline stall-prevention proposal |
| [slots-carve.md](slots-carve.md) | design; historical baseline package carve |
| [sqlite-store-plan.md](sqlite-store-plan.md) | design; baseline migration superseded by reconciled STORE scope |
| [stages.md](stages.md) | evidence; historical baseline design and build record |

Status inventory: 136 Markdown files recursively, including 15 schema-bearing specimens under
`architecture-review/docscheck-proto/docs`. Human-facing entries identify current, proposed or historical scope;
prototype alternatives are contextualized at their collection entries and specimen contents remain unchanged.
The index itself is this scope map, not another source of task status or a completion receipt.
