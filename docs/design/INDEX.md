# Design index

Status: **built** for this navigation inventory, updated 2026-11-13; it does not track task completion.
Every regular file below `docs/design`, including INDEX itself, has one path-sorted inventory row.
Plans stay at `docs/design/<task-id>/plan.md`; the task tracker owns requirements and task status.

**Built** identifies bounded delivered behavior and its implementation/test evidence. **Design** identifies
accepted decisions or pending proposals, without asserting completion. **Evidence** identifies dated reviews,
trials, historical behavior and supporting specimens. Mixed documents distinguish their built portions from
remaining design. A proposed decision stays proposed, and an explicit hold remains held unless superseded.
Historical command examples are preserved; use the [README](../../README.md) and `tl --help` for current commands.
Vocabulary belongs to [the glossary](../glossary.md); the [foundation plan](tl-8bh9.8.7/plan.md) bounds the successor.

## Decision records

The ten ADRs under `tl-8bh9.14.119/` record delivery/publication, ready-task selection, profile-change approval,
check results, skills/hooks, admission/host power, execution storage, land continuation, hierarchical priority
and the factory management boundary. Their individual rows below link to provenance, supersession and exact
pytest enforcement. Accepted rationale and mechanically enforced behavior are separate claims.

## Inventory

Supporting scripts, schemas and machine-readable inventories are evidence artifacts, not production tools
or additional design authority. Prototype documents describe historical experiments, not an adopted toolchain.

| Path | Purpose | Scope / status |
|---|---|---|
| [INDEX.md](INDEX.md) | Complete design-file inventory and authority guide | built: navigation only |
| [architecture-review/architecture-review-playbook.md](architecture-review/architecture-review-playbook.md) | Architecture review playbook (from the task-loop successor review, 2026-11-13) | evidence |
| [architecture-review/brief-external-sources.md](architecture-review/brief-external-sources.md) | Brief (for a bd brainstorming task): external task sources and the code host | design |
| [architecture-review/brief-review-model.md](architecture-review/brief-review-model.md) | Brief (for a bd brainstorming task): the review model, and the name that replaces `held` | design |
| [architecture-review/composition-map.html](architecture-review/composition-map.html) | Composition map — historical visual specimen | evidence: historical mockup, not operator instructions |
| [architecture-review/constitution-draft.md](architecture-review/constitution-draft.md) | Draft: additions for CLAUDE.md and AGENTS.md (mirror both) | evidence |
| [architecture-review/decision-register.md](architecture-review/decision-register.md) | Decision register (architecture review of the task-loop successor, 2026-11-13) | evidence |
| [architecture-review/docscheck-proto/REPORT.md](architecture-review/docscheck-proto/REPORT.md) | docscheck prototype - report | evidence |
| [architecture-review/docscheck-proto/docs/glossary.md](architecture-review/docscheck-proto/docs/glossary.md) | glossary — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/adr/one-owner-per-fact.md](architecture-review/docscheck-proto/docs/system/adr/one-owner-per-fact.md) | one owner per fact — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/adr/requirements-live-in-the-tracker.md](architecture-review/docscheck-proto/docs/system/adr/requirements-live-in-the-tracker.md) | requirements live in the tracker — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/adr/size-caps.md](architecture-review/docscheck-proto/docs/system/adr/size-caps.md) | size caps — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/adr/work-in-managed-worktrees.md](architecture-review/docscheck-proto/docs/system/adr/work-in-managed-worktrees.md) | work in managed worktrees — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/area/engine.md](architecture-review/docscheck-proto/docs/system/area/engine.md) | engine — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/area/storage.md](architecture-review/docscheck-proto/docs/system/area/storage.md) | storage — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/external/git.md](architecture-review/docscheck-proto/docs/system/external/git.md) | git — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/external/tracker.md](architecture-review/docscheck-proto/docs/system/external/tracker.md) | tracker — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/lifecycle/attempt.md](architecture-review/docscheck-proto/docs/system/lifecycle/attempt.md) | attempt — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/persona/implementing-agent.md](architecture-review/docscheck-proto/docs/system/persona/implementing-agent.md) | implementing agent — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/persona/owner.md](architecture-review/docscheck-proto/docs/system/persona/owner.md) | owner — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/runbook/factory-db-corrupt.md](architecture-review/docscheck-proto/docs/system/runbook/factory-db-corrupt.md) | factory db corrupt — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/system/workflow/factory-start.md](architecture-review/docscheck-proto/docs/system/workflow/factory-start.md) | factory start — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/docs/waivers.md](architecture-review/docscheck-proto/docs/waivers.md) | waivers — prototype format specimen | evidence: historical schema specimen; values preserved |
| [architecture-review/docscheck-proto/ontology/adr.yml](architecture-review/docscheck-proto/ontology/adr.yml) | adr — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/area.yml](architecture-review/docscheck-proto/ontology/area.yml) | area — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/capability.yml](architecture-review/docscheck-proto/ontology/capability.yml) | capability — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/case.yml](architecture-review/docscheck-proto/ontology/case.yml) | case — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/case_table.yml](architecture-review/docscheck-proto/ontology/case_table.yml) | case table — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/change.yml](architecture-review/docscheck-proto/ontology/change.yml) | change — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/check.yml](architecture-review/docscheck-proto/ontology/check.yml) | check — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/command.yml](architecture-review/docscheck-proto/ontology/command.yml) | command — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/evidence.yml](architecture-review/docscheck-proto/ontology/evidence.yml) | evidence — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/external.yml](architecture-review/docscheck-proto/ontology/external.yml) | external — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/failure.yml](architecture-review/docscheck-proto/ontology/failure.yml) | failure — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/gap.yml](architecture-review/docscheck-proto/ontology/gap.yml) | gap — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/glossary.yml](architecture-review/docscheck-proto/ontology/glossary.yml) | glossary — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/lifecycle.yml](architecture-review/docscheck-proto/ontology/lifecycle.yml) | lifecycle — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/limit.yml](architecture-review/docscheck-proto/ontology/limit.yml) | limit — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/operation.yml](architecture-review/docscheck-proto/ontology/operation.yml) | operation — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/outcome.yml](architecture-review/docscheck-proto/ontology/outcome.yml) | outcome — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/persona.yml](architecture-review/docscheck-proto/ontology/persona.yml) | persona — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/rule.yml](architecture-review/docscheck-proto/ontology/rule.yml) | rule — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/runbook.yml](architecture-review/docscheck-proto/ontology/runbook.yml) | runbook — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/runstep.yml](architecture-review/docscheck-proto/ontology/runstep.yml) | runstep — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/step_row.yml](architecture-review/docscheck-proto/ontology/step_row.yml) | step row — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/term.yml](architecture-review/docscheck-proto/ontology/term.yml) | term — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/transition.yml](architecture-review/docscheck-proto/ontology/transition.yml) | transition — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/waiver.yml](architecture-review/docscheck-proto/ontology/waiver.yml) | waiver — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/waivers.yml](architecture-review/docscheck-proto/ontology/waivers.yml) | waivers — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/ontology/workflow.yml](architecture-review/docscheck-proto/ontology/workflow.yml) | workflow — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/docscheck-proto/run.sh](architecture-review/docscheck-proto/run.sh) | run — supporting artifact | evidence: supporting historical artifact |
| [architecture-review/docscheck-proto/scripts/verify_ontology.py](architecture-review/docscheck-proto/scripts/verify_ontology.py) | verify ontology — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/__init__.py](architecture-review/docscheck-proto/src/docscheck/__init__.py) |   init   — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/__main__.py](architecture-review/docscheck-proto/src/docscheck/__main__.py) |   main   — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/changed.py](architecture-review/docscheck-proto/src/docscheck/changed.py) | changed — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/cli.py](architecture-review/docscheck-proto/src/docscheck/cli.py) | cli — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/code_read.py](architecture-review/docscheck-proto/src/docscheck/code_read.py) | code read — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/docs.py](architecture-review/docscheck-proto/src/docscheck/docs.py) | docs — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/generate.py](architecture-review/docscheck-proto/src/docscheck/generate.py) | generate — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/gitport.py](architecture-review/docscheck-proto/src/docscheck/gitport.py) | gitport — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/index.py](architecture-review/docscheck-proto/src/docscheck/index.py) | index — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/main.py](architecture-review/docscheck-proto/src/docscheck/main.py) | main — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/ontology.py](architecture-review/docscheck-proto/src/docscheck/ontology.py) | ontology — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/probes.py](architecture-review/docscheck-proto/src/docscheck/probes.py) | probes — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/rules_code.py](architecture-review/docscheck-proto/src/docscheck/rules_code.py) | rules code — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/rules_docs.py](architecture-review/docscheck-proto/src/docscheck/rules_docs.py) | rules docs — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/run.py](architecture-review/docscheck-proto/src/docscheck/run.py) | run — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/schema.py](architecture-review/docscheck-proto/src/docscheck/schema.py) | schema — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/values.py](architecture-review/docscheck-proto/src/docscheck/values.py) | values — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/src/docscheck/waivers.py](architecture-review/docscheck-proto/src/docscheck/waivers.py) | waivers — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/tests/support.py](architecture-review/docscheck-proto/tests/support.py) | support — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/docscheck-proto/tests/test_docscheck.py](architecture-review/docscheck-proto/tests/test_docscheck.py) | test docscheck — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/fmt/A-current.md](architecture-review/fmt/A-current.md) | A current | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/ALL-variants.md](architecture-review/fmt/ALL-variants.md) | Documentation format alternatives | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/B-diataxis-reference.md](architecture-review/fmt/B-diataxis-reference.md) | storage — reference | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/C-rfc2119-ears.md](architecture-review/fmt/C-rfc2119-ears.md) | storage | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/D-graph.md](architecture-review/fmt/D-graph.md) | storage | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/E-hybrid.md](architecture-review/fmt/E-hybrid.md) | Status: **evidence**. Historical architecture-review format/opinion specimen; its proposals are not adopted system authority. | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/ONTOLOGY-ALL.md](architecture-review/fmt/ONTOLOGY-ALL.md) | task-loop docs ontology (a2kay-format, temporary checker on shelf libs) | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/fable-opinion.md](architecture-review/fmt/fable-opinion.md) | System doc format: independent opinion | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/fable/fable-opinion-2.md](architecture-review/fmt/fable/fable-opinion-2.md) | System doc format: round 2 | evidence: format/review alternative, not adopted authority |
| [architecture-review/fmt/fable/fable-opinion-3.md](architecture-review/fmt/fable/fable-opinion-3.md) | System doc format: round 3 | evidence: format/review alternative, not adopted authority |
| [architecture-review/graph.py](architecture-review/graph.py) | graph — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/grilling-record.md](architecture-review/grilling-record.md) | Grilling record: candidate 1, the tracker seam (2026-11-13) | evidence |
| [architecture-review/impact.py](architecture-review/impact.py) | impact — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/matrix.py](architecture-review/matrix.py) | matrix — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [architecture-review/ontology/00-README.md](architecture-review/ontology/00-README.md) | task-loop docs ontology (a2kay-format, temporary checker on shelf libs) | design |
| [architecture-review/ontology/area.yml](architecture-review/ontology/area.yml) | area — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/capability.yml](architecture-review/ontology/capability.yml) | capability — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/case.yml](architecture-review/ontology/case.yml) | case — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/check.yml](architecture-review/ontology/check.yml) | check — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/external.yml](architecture-review/ontology/external.yml) | external — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/failure.yml](architecture-review/ontology/failure.yml) | failure — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/gap.yml](architecture-review/ontology/gap.yml) | gap — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/glossary.yml](architecture-review/ontology/glossary.yml) | glossary — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/lifecycle.yml](architecture-review/ontology/lifecycle.yml) | lifecycle — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/limit.yml](architecture-review/ontology/limit.yml) | limit — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/operation.yml](architecture-review/ontology/operation.yml) | operation — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/outcome.yml](architecture-review/ontology/outcome.yml) | outcome — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/persona.yml](architecture-review/ontology/persona.yml) | persona — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/rule.yml](architecture-review/ontology/rule.yml) | rule — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/step_row.yml](architecture-review/ontology/step_row.yml) | step row — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/term.yml](architecture-review/ontology/term.yml) | term — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/transition.yml](architecture-review/ontology/transition.yml) | transition — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/ontology/workflow.yml](architecture-review/ontology/workflow.yml) | workflow — supporting artifact | evidence: prototype schema or configuration specimen |
| [architecture-review/readme-direction.md](architecture-review/readme-direction.md) | Proposed database-library direction | design |
| [architecture-review/sample-system-storage.md](architecture-review/sample-system-storage.md) | storage | current date: 2026-11-13 read_when: before touching SQL, a store module, a transaction, factory.db, or a row type owns: src/taskloop/*/store.py, factory.db schema fragments, sqlite-store… |
| [architecture-review/slices.py](architecture-review/slices.py) | slices — supporting artifact | evidence: review/prototype script; not installed runtime or gate |
| [dashboard-ui.md](dashboard-ui.md) | Dashboard UI | built, slice 1 |
| [dashboard-ux-review-1113.md](dashboard-ux-review-1113.md) | Dashboard drawer and status redesign: Opus UX review (2026-11-13) | proposal from a read-only consultant review of the live dashboard data and page code (no browser was opened, so nothing about looks or layout is verified) |
| [dashboard/README.md](dashboard/README.md) | task-loop dashboard | design |
| [dashboard/dash-decisions.md](dashboard/dash-decisions.md) | Dashboard revamp decisions (owner, 2026-10-28) | evidence |
| [dashboard/dash-kit-audit-1029.md](dashboard/dash-kit-audit-1029.md) | UX consistency and UI kit audit, 2026-10-29 | evidence |
| [dashboard/dash-operator-model.md](dashboard/dash-operator-model.md) | Operator model, views, asks (draft, 2026-10-29) | design |
| [dashboard/dash-review-whole-1029.md](dashboard/dash-review-whole-1029.md) | Whole-design review, 2026-10-29 | evidence |
| [dashboard/dash-round-6b.html](dashboard/dash-round-6b.html) | task-loop round 6b — historical visual specimen | evidence: historical mockup, not operator instructions |
| [dashboard/dash-round-7b.html](dashboard/dash-round-7b.html) | task-loop round 6b — historical visual specimen | evidence: historical mockup, not operator instructions |
| [dashboard/dash-round-8b.html](dashboard/dash-round-8b.html) | task-loop round 6b — historical visual specimen | evidence: historical mockup, not operator instructions |
| [dashboard/dash-round-9-app.html](dashboard/dash-round-9-app.html) | task-loop phone — historical visual specimen | evidence: historical mockup, not operator instructions |
| [dashboard/dash-round-9.html](dashboard/dash-round-9.html) | Round 9 Phone — historical visual specimen | evidence: historical mockup, not operator instructions |
| [dashboard/dash-spec.md](dashboard/dash-spec.md) | task-loop dashboard: implementation spec | design |
| [execution-terms.md](execution-terms.md) | Execution terms: steps, actions and attempts | design |
| [factory-on-sol/design.md](factory-on-sol/design.md) | The factory on the sol devbox, driven from the phone (revision 2, 2026-11-14) | design: proposal; owner answers pending in part |
| [factory-on-sol/supervisor-brief.md](factory-on-sol/supervisor-brief.md) | Brief for the session that supervises the factory on sol: paths, loop, hard-won rules | design: operating notes, 2026-11-14 |
| [layers.md](layers.md) | Layers: which software manages which | design |
| [merge-queue.md](merge-queue.md) | Merge queue (MQUEUE): speculative, serial in meaning, parallel in execution (design only, 2026-11-07) | design |
| [roadmap.md](roadmap.md) | Roadmap: speed and less code (2026-11-06) | design |
| [self-hosting-real-run-1.md](self-hosting-real-run-1.md) | Self-hosting real run 1: the factory on a real bead, the owner watching | evidence |
| [self-hosting-real-run-2.md](self-hosting-real-run-2.md) | Self-hosting real run 2: reflection (2026-11-13) | reflection of the second real run; no decision here is implemented |
| [self-hosting-roadmap.md](self-hosting-roadmap.md) | Roadmap: the factory develops itself (self-hosting) | design with built milestones and recorded evidence identified below |
| [self-hosting-trial-2.md](self-hosting-trial-2.md) | Self-hosting trial 2: source and test change, failed checks, moved main, restart | evidence |
| [self-hosting-trial-3.md](self-hosting-trial-3.md) | Self-hosting trial 3: failure routes with a real agent, odd input, a deleted task | evidence |
| [self-hosting-trial-4.md](self-hosting-trial-4.md) | Self-hosting trial 4: concurrency and recovery | evidence |
| [self-hosting-trial-5-fixes.md](self-hosting-trial-5-fixes.md) | Trial 5 fixes: environment, evidence, settlement (tl-8bh9.14.44-.53) | evidence |
| [self-hosting-trial-5.md](self-hosting-trial-5.md) | Self-hosting trial 5: a hostile or sloppy agent against the safety boundaries | evidence |
| [self-hosting-trial-6.md](self-hosting-trial-6.md) | Self-hosting trial 6: do the trial 1-5 fixes hold on a real run? | evidence |
| [self-hosting-trial.md](self-hosting-trial.md) | Self-hosting trial 1: one real task through plan, implement, checks and land | evidence |
| [slot-grant.md](slot-grant.md) | Slot grant: deterministic prevention of the 2026-11-03 stall (design only) | design |
| [slots-carve.md](slots-carve.md) | Slots carve plan (tl-e5t0.17, and the largest root cut left in tl-e5t0.40.6) | design |
| [sqlite-store-plan.md](sqlite-store-plan.md) | One SQLite execution store: the plan (tl-sqd3.26 STORE) | design |
| [stages.md](stages.md) | Stages and their handoffs: audit of night 1 and a redesign (2026-10-23) | evidence |
| [tl-7i9k.56.1/plan.md](tl-7i9k.56.1/plan.md) | Retries, cooldowns and pauses | design |
| [tl-8bh9.1/configuration-review.md](tl-8bh9.1/configuration-review.md) | Configuration, profiles and source identity | design |
| [tl-8bh9.1/identity-store-contract.md](tl-8bh9.1/identity-store-contract.md) | Repository binding, lifecycle and STORE ownership | design |
| [tl-8bh9.1/plan.md](tl-8bh9.1/plan.md) | Repository binding and storage ownership | design |
| [tl-8bh9.1/timeouts-workspaces.md](tl-8bh9.1/timeouts-workspaces.md) | Time limits and check workspaces | design |
| [tl-8bh9.13/audit.md](tl-8bh9.13/audit.md) | Untouched files and behaviors without a complete disposition | evidence |
| [tl-8bh9.13/files.tsv](tl-8bh9.13/files.tsv) | files — supporting artifact | evidence: dated per-file source review inventory |
| [tl-8bh9.13/plan.md](tl-8bh9.13/plan.md) | Untouched-file and workflow gap analysis | evidence |
| [tl-8bh9.14.1/plan.md](tl-8bh9.14.1/plan.md) | tl-8bh9.14.1: the repository profile reader (block B3) | built for this bounded successor slice |
| [tl-8bh9.14.113/plan.md](tl-8bh9.14.113/plan.md) | Docs and CLI consistency | built, with validation limited by this execution sandbox as recorded in As built |
| [tl-8bh9.14.119/adr-01-delivery-publication.md](tl-8bh9.14.119/adr-01-delivery-publication.md) | ADR 01: Delivery and publication | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-02-ready-task-selection.md](tl-8bh9.14.119/adr-02-ready-task-selection.md) | ADR 02: Ready-task selection | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-03-profile-change-approval.md](tl-8bh9.14.119/adr-03-profile-change-approval.md) | ADR 03: Profile-change approval | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-04-check-results.md](tl-8bh9.14.119/adr-04-check-results.md) | ADR 04: Check results belong to their attempt | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-05-skills-and-hooks.md](tl-8bh9.14.119/adr-05-skills-and-hooks.md) | ADR 05: Lightweight skills and hooks | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-06-admission-and-host-power.md](tl-8bh9.14.119/adr-06-admission-and-host-power.md) | ADR 06: Admission and host power | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-07-execution-store.md](tl-8bh9.14.119/adr-07-execution-store.md) | ADR 07: Execution state ownership | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-08-land-resume.md](tl-8bh9.14.119/adr-08-land-resume.md) | ADR 08: Resume only unfinished land actions | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-09-hierarchical-priority.md](tl-8bh9.14.119/adr-09-hierarchical-priority.md) | ADR 09: Hierarchical priority | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/adr-10-factory-management-boundary.md](tl-8bh9.14.119/adr-10-factory-management-boundary.md) | ADR 10: Factory management boundary | design decision record, extracted 2026-11-13 |
| [tl-8bh9.14.119/plan.md](tl-8bh9.14.119/plan.md) | Design documentation authority and decision records | built |
| [tl-8bh9.14.127/plan.md](tl-8bh9.14.127/plan.md) | Version check on restart | built following the owner's implementation request; original specification below. |
| [tl-8bh9.14.13/plan.md](tl-8bh9.14.13/plan.md) | Time since the agent's last command | built for the sidecar-to-stream replacement: `EvidenceFiles.last_command` delegates to `activity_file.command_time`, with contracts in `tests/steps/test_last_command.py` and… |
| [tl-8bh9.14.132/plan.md](tl-8bh9.14.132/plan.md) | Default backlog for step show and expose list hold causes | built for default backlog selection and hold-cause reads |
| [tl-8bh9.14.156/plan.md](tl-8bh9.14.156/plan.md) | tl-8bh9.14.156: the factory at conventional locations | built; the cut-over ran 2026-11-13 (runbook below, as run) |
| [tl-8bh9.14.160/plan.md](tl-8bh9.14.160/plan.md) | Per-step agent settings: harness, model, effort and captured access policy | built: machine config, immutable admission choices, three harness adapters; Claude/OpenCode enforcement preflight deferred |
| [tl-8bh9.14.6/live-smoke.md](tl-8bh9.14.6/live-smoke.md) | M2 live smoke: the check step in the rounds (owner-run, after S6e) | evidence |
| [tl-8bh9.14.6/m2-smoke-findings.md](tl-8bh9.14.6/m2-smoke-findings.md) | M2 live smoke: findings (2026-11-11) | evidence |
| [tl-8bh9.14.6/plan.md](tl-8bh9.14.6/plan.md) | tl-8bh9.14.6: the checks step (block B4, milestone M2) | built for S6a–S6e; sections 21–25 record the bounded slices |
| [tl-8bh9.14.8/live-smoke.md](tl-8bh9.14.8/live-smoke.md) | M3 live smoke: land and close with `tl step land` (owner-run, after L5) | evidence |
| [tl-8bh9.14.8/m3-smoke-findings.md](tl-8bh9.14.8/m3-smoke-findings.md) | M3 live smoke: findings (2026-11-12) | evidence |
| [tl-8bh9.14.8/plan.md](tl-8bh9.14.8/plan.md) | tl-8bh9.14.8: land and close (block B6, milestone M3) | built for L0–L5; sections 25–29 record delivery and CLI behavior, with later trial repairs in sections 30–31 |
| [tl-8bh9.14.9/live-smoke.md](tl-8bh9.14.9/live-smoke.md) | M4 live smoke: holds and keep-awake in the unattended loop (owner- or authorized-agent-run, after H3 and K1) | evidence |
| [tl-8bh9.14.9/m4-smoke-findings.md](tl-8bh9.14.9/m4-smoke-findings.md) | M4 live smoke: findings (2026-11-12) | evidence |
| [tl-8bh9.14.9/plan.md](tl-8bh9.14.9/plan.md) | tl-8bh9.14.9: questions and holds, and the rest of the unattended loop (block B7 with B11 and B13, milestone M4) | built for H1–H3 and K1 (sections 24–27), and G1/G2 (section 14, including the later timeout implementation) |
| [tl-8bh9.2/lifecycle.md](tl-8bh9.2/lifecycle.md) | Workspace lifecycle and state ownership | design |
| [tl-8bh9.2/plan.md](tl-8bh9.2/plan.md) | Workspace ownership and concurrency | design |
| [tl-8bh9.3.2.1/plan.md](tl-8bh9.3.2.1/plan.md) | First one-shot plan execution | built for this bounded successor slice |
| [tl-8bh9.3/hierarchical-priority.md](tl-8bh9.3/hierarchical-priority.md) | Hierarchical priority: task first, ancestry breaks ties | built for scheduling priority as recorded in the scheduling slice |
| [tl-8bh9.3/lifecycle-review.md](tl-8bh9.3/lifecycle-review.md) | Admission, claims, execution and completion | evidence and design |
| [tl-8bh9.3/selection-review.md](tl-8bh9.3/selection-review.md) | Simple scheduling and existing queue policies | built for bounded selection behavior described by the scheduling slice; other alternatives remain design |
| [tl-8bh9.4.3.1.1/handoff.md](tl-8bh9.4.3.1.1/handoff.md) | Successor factory handover — 2026-11-09 | evidence |
| [tl-8bh9.4.3.1.1/plan.md](tl-8bh9.4.3.1.1/plan.md) | Collect one already admitted plan attempt | built for this bounded successor slice |
| [tl-8bh9.4.3.1.10/plan.md](tl-8bh9.4.3.1.10/plan.md) | Slot preparation under a custody lock: the task branch and the attempt-lifetime ProcessLock | built for this bounded successor slice |
| [tl-8bh9.4.3.1.11/plan.md](tl-8bh9.4.3.1.11/plan.md) | Release a slot reservation, and abandon an attempt | built for this bounded successor slice |
| [tl-8bh9.4.3.1.12/plan.md](tl-8bh9.4.3.1.12/plan.md) | Publish the verified plan: push `task/<id>` to the remote | built for this bounded successor slice |
| [tl-8bh9.4.3.1.13/plan.md](tl-8bh9.4.3.1.13/plan.md) | Scheduling: the factory takes ready tasks into free slots (`tl plan next`) | built for this bounded successor slice |
| [tl-8bh9.4.3.1.13/shelf-request.md](tl-8bh9.4.3.1.13/shelf-request.md) | Shelf change request: beads-client 0.2.0, a ready-set read with its owning fake | evidence |
| [tl-8bh9.4.3.1.14/plan.md](tl-8bh9.4.3.1.14/plan.md) | Trigger: rounds start by themselves (`tl plan rounds`) | built for this bounded successor slice |
| [tl-8bh9.4.3.1.15/plan.md](tl-8bh9.4.3.1.15/plan.md) | Generalize the step machinery once: plan becomes the first step kind | built for this bounded successor slice |
| [tl-8bh9.4.3.1.16.2/live-smoke.md](tl-8bh9.4.3.1.16.2/live-smoke.md) | Live smoke: the implement step's environment (S5e) and M1 end to end (owner-run) | evidence |
| [tl-8bh9.4.3.1.16.2/m1-smoke-findings.md](tl-8bh9.4.3.1.16.2/m1-smoke-findings.md) | M1 end-to-end smoke: findings (2026-11-11) | evidence |
| [tl-8bh9.4.3.1.16.2/plan.md](tl-8bh9.4.3.1.16.2/plan.md) | S5e: the environment for running checks and tests in the agent sandbox (block B2) | built for S5e-1 setup and S5e-2 access, recorded in section 16 and section 18 |
| [tl-8bh9.4.3.1.16/plan.md](tl-8bh9.4.3.1.16/plan.md) | Step sequencing and the implement step kind (slice S5) | built for S5a–S5c, recorded in sections 11–14; remaining scope is design |
| [tl-8bh9.4.3.1.16/run-s-findings.md](tl-8bh9.4.3.1.16/run-s-findings.md) | Run S: sandbox and environment spike for block B2 (2026-11-11) | evidence |
| [tl-8bh9.4.3.1.2/plan.md](tl-8bh9.4.3.1.2/plan.md) | Admit one plan attempt (admission only) | built for this bounded successor slice |
| [tl-8bh9.4.3.1.3/plan.md](tl-8bh9.4.3.1.3/plan.md) | Managed slots: the smallest slot state admission needs | built for this bounded successor slice |
| [tl-8bh9.4.3.1.4/live-smoke.md](tl-8bh9.4.3.1.4/live-smoke.md) | Live smoke: registered attempt entry (owner-run) | evidence |
| [tl-8bh9.4.3.1.4/plan.md](tl-8bh9.4.3.1.4/plan.md) | Registered attempt entry: launch an admitted attempt into a surviving process | built for this bounded successor slice |
| [tl-8bh9.4.3.1.5/plan.md](tl-8bh9.4.3.1.5/plan.md) | Plan verification: Git evidence for a returned plan answer | built for this bounded successor slice |
| [tl-8bh9.4.3.1.6/plan.md](tl-8bh9.4.3.1.6/plan.md) | Plan CLI: run the implemented plan path without a driver | built for this bounded successor slice |
| [tl-8bh9.4.3.1.7/plan.md](tl-8bh9.4.3.1.7/plan.md) | The agent chooses what to commit; the factory commits it and checks the tree is clean | built for this bounded successor slice |
| [tl-8bh9.4.3.1.8/plan.md](tl-8bh9.4.3.1.8/plan.md) | Repeat a step whose agent left the slot unsettled | built for this bounded successor slice |
| [tl-8bh9.4.3.1.9/plan.md](tl-8bh9.4.3.1.9/plan.md) | Keep the tracker claim's lease alive while a step runs | built for this bounded successor slice |
| [tl-8bh9.4.3.1/plan.md](tl-8bh9.4.3.1/plan.md) | First restart-safe agent execution | built for this bounded successor slice |
| [tl-8bh9.4.4.1/implementation.md](tl-8bh9.4.4.1/implementation.md) | Registered-start prerequisite delivery | evidence |
| [tl-8bh9.4.6/inventory.json](tl-8bh9.4.6/inventory.json) | inventory — supporting artifact | evidence: review/prototype structured inventory |
| [tl-8bh9.4.6/plan.md](tl-8bh9.4.6/plan.md) | Adapter audit: purpose, ownership and workflow consequences | design |
| [tl-8bh9.4.6/removal-challenge.md](tl-8bh9.4.6/removal-challenge.md) | Removing adapters: behavior counterfactuals | evidence |
| [tl-8bh9.4.6/settlement-probe.md](tl-8bh9.4.6/settlement-probe.md) | In-memory settlement probe | evidence |
| [tl-8bh9.4/plan.md](tl-8bh9.4/plan.md) | Runtime helpers: remove, consolidate or keep | design |
| [tl-8bh9.4/shared-interfaces.md](tl-8bh9.4/shared-interfaces.md) | Shared interfaces: available mechanisms and remaining gaps | evidence |
| [tl-8bh9.5.1/candidate-checks.md](tl-8bh9.5.1/candidate-checks.md) | One check pipeline, candidate-bound evidence | design |
| [tl-8bh9.5.1/plan.md](tl-8bh9.5.1/plan.md) | Check execution: remove repetition before choosing a cache | design |
| [tl-8bh9.6.1/balanced-design.md](tl-8bh9.6.1/balanced-design.md) | Human input: settled working design | design |
| [tl-8bh9.6.1/options.md](tl-8bh9.6.1/options.md) | Questions and decisions: backend-neutral options | design |
| [tl-8bh9.6.1/plan.md](tl-8bh9.6.1/plan.md) | Task questions, answers and local waits | design |
| [tl-8bh9.6.1/scenarios.md](tl-8bh9.6.1/scenarios.md) | Question-flow scenario walkthroughs | design |
| [tl-8bh9.6.2.1/plan.md](tl-8bh9.6.2.1/plan.md) | Read one task in its configured backlog | built for this bounded successor slice |
| [tl-8bh9.7.4/plan.md](tl-8bh9.7.4/plan.md) | tl-8bh9.7.4 plan: readable live lines of an agent attempt | built for bounded live activity recording, evidence reads and the attempt feed in `activity_file`, `evidence_files` and `dash_task` |
| [tl-8bh9.7/interaction-contract.md](tl-8bh9.7/interaction-contract.md) | Owner controls and evidence: one walkthrough | design |
| [tl-8bh9.7/owner-actions.md](tl-8bh9.7/owner-actions.md) | Owner and agent workflows | design |
| [tl-8bh9.7/plan.md](tl-8bh9.7/plan.md) | Dashboard state, evidence and task reads | design |
| [tl-8bh9.8.7/implementation.md](tl-8bh9.8.7/implementation.md) | Foundation implementation evidence | evidence |
| [tl-8bh9.8.7/plan.md](tl-8bh9.8.7/plan.md) | Minimal successor foundation | built for the minimal foundation only; see implementation evidence |
| [tl-8bh9.8/curated-replacement.md](tl-8bh9.8/curated-replacement.md) | Curated replacement and cutover | design |
| [tl-8bh9.8/operations.md](tl-8bh9.8/operations.md) | Hooks and cleanup | design |
| [tl-8bh9.9/delivery-publication.md](tl-8bh9.9/delivery-publication.md) | Delivery, publication and task completion | design |
| [tl-8bh9.9/plan.md](tl-8bh9.9/plan.md) | Git consolidation: mechanism versus factory policy | design |
| [tl-8bh9/coverage.md](tl-8bh9/coverage.md) | Final coverage and implementation sequence | evidence |
| [tl-8bh9/plan.md](tl-8bh9/plan.md) | Architecture review: discussion roadmap | design |
| [tl-sqd3.18.1/plan.md](tl-sqd3.18.1/plan.md) | Canonical repository inspection | built for this bounded successor slice |
| [tl-sqd3.26/plan.md](tl-sqd3.26/plan.md) | STORE: reconciled retained scope | design |
