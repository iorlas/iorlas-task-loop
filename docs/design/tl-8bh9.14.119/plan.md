# Design documentation authority and decision records

Status: **design**. Implementation proposal prepared 2026-11-13; awaiting the owner's yes.
Task: `tl-8bh9.14.119`. This attempt writes only this plan. It does not authorize the documentation
rewrite, test additions, runtime changes, task closure or publication described below.

## Requirements and current evidence

Make INDEX complete, give every design document an explicit status, and extract the ten cited decision
candidates into ADRs that name enforcing tests. Preserve the distinction between an owner decision, a
proposal and implemented behavior. The requirements come from the supplied task; local `bd show` found
no record for this ID, so no tracker mutation was attempted.

Read the [foundation boundary](../tl-8bh9.8.7/plan.md), [glossary](../../glossary.md), README,
justfile, current CLI registrations and relevant source/tests. Repository inspected at
`2e7850344255097b0efe42b650d792c6723db01e` in the assigned slot worktree.
The originating review is session `local_16bd6c79`, round 4, 2026-11-13, preserved in
[grilling-record.md](../architecture-review/grilling-record.md#haiku-round-4-stop-yield-is-docs-packaging-and-refinement-no-new-structural-risk).
[slices.py](../architecture-review/slices.py) is review evidence, not a runtime dependency or an installed gate.

The census numbers are historical observations, not acceptance counts:

- The current design tree has 220 files, including 141 Markdown documents. A direct relative-link census
  finds 62 Markdown documents without their own INDEX link, excluding INDEX itself. Collection links do
  not satisfy the requested complete inventory. The index's stated count of 136 is already stale.
- [tl-8bh9.14.113](../tl-8bh9.14.113/plan.md#as-built) already refreshed README, many introductory markers
  and collection entries. Preserve accurate corrections instead of repeating its implementation scope.
  Some markers occur after introductory paragraphs; lack of a particular header spelling is not proof
  that a document has no status. Read each document and its appended evidence.
- `layers.md` now says **design**, distinguishing quoted owner decisions from proposed judgments.
  Its keep-awake deletion is recorded as done. Promoting its entire layer table to accepted/built would
  misrepresent the source.
- README describes plan, implement, checks, explicit land, holds and the default dashboard. It still
  describes land chiefly as the person's command, while the CLI and `round_land.py` also support the
  profile's `land: auto`. Check it against current code, including later default-backlog changes.
- Old line numbers drifted when headers were added. Identify the cited paragraphs by their decision
  text and date. In particular, SQLite's old migration/compatibility plan is superseded; keep-awake was
  subsequently deleted; the original rejection of profile-specific approval precedes the later
  `--accept-gate-changes` land behavior. These are history to reconcile, not features to restore.

## Scope and authority

After approval, change documentation and only the focused tests needed to substantiate the ADRs.
No production behavior, command registration, schema, scheduler, adapter, package dependency or vocabulary
rename belongs to this task. Do not implement the unbuilt commands found in designs. Do not delete evidence,
move existing task plans, rewrite task status from comments, or revive historical migration paths.

Keep README as the current operator overview, the glossary as the vocabulary owner, the task tracker as
requirements/status owner, and Git as the owner of plans and design records. INDEX is a navigation and
document-scope inventory, not a second task tracker. The newer documentation framework and generator
proposals in the architecture review remain outside this task; this work does not adopt the docscheck
prototype, a system-document hierarchy, or a new documentation toolchain.

## 1. Complete the index and status pass

Inventory all regular files recursively below `docs/design`, including this task's plan, the ten eventual
ADRs, supporting artifacts, dashboard HTML, review alternatives and nested prototype specimens. Enumerate
with `rg --files` or a native read-only directory walk; do not use the old 106-file denominator.

Retain the useful overview, then provide deterministic path-sorted tables with one explicit relative link
per file. Each entry gives its purpose and scope/status; distinguish documents from supporting artifacts
using ordinary descriptions. Collection summaries may remain, but cannot replace member entries. Include
INDEX itself explicitly in the inventory convention. Compare discovered paths with indexed paths in both
directions: no missing files, duplicate inventory rows or dangling local file links. Resolve fragments
separately; external links are not filesystem paths. Remove the stale hand-maintained total or update it
from the final inventory, including newly added files.

Use the existing **built**, **design**, and **evidence** concepts, with explanatory prose:

- Built notes identify the bounded behavior and link to its implementation record and relevant tests.
  A task plan can be partly built; its original proposal is not a delivery receipt.
- Design notes distinguish accepted decisions, pending proposals and explicitly held work. A proposal
  remains proposed even when adjacent paragraphs quote an accepted owner decision.
- Evidence notes identify dated trials, reviews, historical behavior and supporting specimens. A later
  decision can supersede an earlier one without erasing its record.

Every human-facing Markdown/HTML design document gets a nearby explicit status/scope note. Preserve an
already accurate note. For HTML mocks use a brief visible note consistent with their historical role.
For schema-bearing prototype Markdown whose schema forbids body text and additional fields, place a YAML
comment such as `# Status: evidence; historical format specimen, not current system authority` inside the
existing frontmatter. Preserve all parsed values and the body. This gives each specimen its own marker
without changing the prototype schema or turning the prototype into production tooling. Non-document
scripts, YAML schemas, JSON inventories and other supporting files receive individual evidence/design
context in INDEX; do not inject prose into executable or structured artifacts.

Review each occurrence of `tl plan`, `tl report`, `tl slot list/release/hold`, `tl repo register`, and
`tl task create` in context. Historical and proposed examples stay intact with an introductory warning
and a link to current README/help or their replacement design. Current operator instructions use only
implemented commands. Do not mechanically rename historical commands. Check the same distinction in
`layers.md`, old trial instructions, old SQLite migration notes and dashboard mockups.

Refresh README only where current implementation warrants it, especially manual/default versus auto land,
the default dashboard and show-backlog selection. Explain auto land as the same application operation,
at most one task per round, enabled by the target profile; record typed task-change refusals as holds.
No owner-facing recovery message should require an invented command. Preserve current executable invocation
guidance, and link to INDEX, the ADR entries and glossary without duplicating their detailed rules.

## 2. Extract ten bounded ADRs

Put the records alongside this plan as `adr-01-<topic>.md` through `adr-10-<topic>.md`; the topic names below
are file descriptions, not new factory terms. Every ADR contains context, the decision and original date/
authority, considered alternatives and rationale grounded in the source, consequences, current implementation
scope, supersession links, and enforcement. Link to source headings/quoted opening text rather than relying
on line numbers alone. Never invent a rejected alternative or an owner approval absent from the evidence.

The two priority references overlap. Use the accepted manual-queue/epic-order removal in the execution-terms
paragraph for ADR 02, and the precise hierarchy comparator contract for ADR 09. Cross-link them; do not create
two competing definitions of priority or claim that two identical paragraphs are independent decisions.

| ADR / topic | Cited source, identified by text | Decision and current boundary |
|---|---|---|
| 01 delivery-publication | `execution-terms.md`, formerly 721, “Owner approved delivery/publication strategy 2026-11-09”; `tl-8bh9.9/delivery-publication.md` | Append-only task publication and resumable squash land with typed internal results. Current direct-push behavior is built; PR waiting and other target possibilities remain design. |
| 02 ready-task-selection | `execution-terms.md`, formerly 680, “Owner subsequently approved manual-queue/epic-order removal”; `tl-8bh9.3/selection-review.md` | Select approved ready work without a manual queue, epic order or area exclusion; eligibility precedes ADR 09 ordering. Claims, dependency checks, holds and current in-flight limits remain. |
| 03 profile-change-approval | `execution-terms.md`, formerly 685, “Owner decision, 2026-11-09: remove the whole profile-change-specific approval mechanism”; configuration review | Record retirement of the former special authorization mechanism. Explicitly qualify it with the later built land acceptance of changes to checks/configuration (`tl-8bh9.14.42`/`.43`, `land_gate.py`). Preserve `--accept-gate-changes`; do not claim all profile edits land without acceptance. |
| 04 check-results | `execution-terms.md`, formerly 713, “Owner decision 2026-11-09: accepted ... check-pipeline simplifications”; candidate-checks contract | No historical pass cache/carry exemptions; required failures block. Current-attempt results and idempotent continuation of unfinished land are required state, not a forbidden cross-attempt cache. |
| 05 skills-and-hooks | `execution-terms.md`, formerly 751, “Owner clarified lightweight skill purpose”; `tl-8bh9.8/operations.md` | Skills provide explicit help rather than scheduling or state ownership. Distinguish the owner's skill intent from Astra's hook-removal recommendation; preserve repository Git/LFS hooks and ordinary agent mechanisms. |
| 06 admission-and-host-power | `execution-terms.md`, formerly 777, “Owner accepted ... remove proactive RAM-threshold admission initially”; later roadmap B11 and layers section 5 | No proactive RAM threshold. Record keep-awake's original acceptance, trial failure and later owner-directed deletion; current factory does not manage host power. In-flight bounds and slot availability still constrain admission. |
| 07 execution-store | `sqlite-store-plan.md`, formerly 12, original SQLite owner decision and supersession notes; reconciled STORE/identity contract | SQLite owns local execution state/reservations, tracker owns task data, Git owns code/plans; logs remain evidence files. No old import/export, dual read, file fallback or automatic discard. Intact compatible restart retains progress/session after liveness reconciliation. |
| 08 land-resume | `tl-8bh9.14.8/plan.md`, formerly 109, “The latest land candidate ... decides where to resume” | Retry a held release first; a delivered candidate proceeds to close; a closed candidate returns already landed without external actions. Do not revalidate/re-push finished work. |
| 09 hierarchical-priority | `tl-8bh9.3/hierarchical-priority.md`, formerly 3, owner-accepted ordering contract | Own priority, nearest ancestor outward, P2 padding/defaults, then natural task ID. No inherited writes, weighted score or root-first substitution. Distinct from eligibility in ADR 02. |
| 10 factory-management-boundary | `layers.md`, formerly 8, quoted 2026-11-12 owner decision | Package managers own installs/versions/pins/releases; factory owns tasks/steps/slots/agents and reports its running version. Only the quoted decision and evidenced deletions are accepted/built; the detailed layer judgments and proposed import contracts remain proposals. |

At each source decision paragraph add a short link to its ADR and a qualification where later decisions
supersede it. Preserve original dates and trial evidence. INDEX links all ten individually. An ADR's status
separates acceptance from enforcement and implementation; the existence of the record does not make its
entire historical scope built. If inspection finds another superseding owner decision, cite it and narrow
the record instead of changing runtime behavior to match the old prose.

## 3. Name real enforcement and close only documentation-sized gaps

Each ADR names exact pytest node IDs, states which part each enforces, and links to the test source. Existing
tests below are starting evidence, not claims that every sentence of an ADR is mechanically enforced:

| ADR | Existing enforcement to inspect and cite |
|---|---|
| 01 | `tests/steps/test_publish.py::test_a_verified_released_plan_is_pushed_from_the_checkout_and_recorded_once`; `tests/steps/test_land_close.py::test_a_crash_between_the_push_and_the_close_is_finished_by_the_rerun_without_git` |
| 02 | `tests/steps/test_selection.py::test_eligibility_skips_attempted_abandoned_and_another_actors_task_but_keeps_the_factorys`; `tests/steps/test_round_bound.py::test_a_backlog_starts_only_up_to_the_default_bound_not_every_ready_task` |
| 03 | `tests/steps/test_land_gate.py::test_a_land_that_changes_a_check_argv_is_refused_and_a_land_changing_nothing_of_it_lands_as_before` (the later qualification, not proof of the earlier blanket statement) |
| 04 | `tests/steps/test_checks.py::test_every_check_runs_in_order_after_its_identity_is_committed`; `tests/steps/test_checks.py::test_the_conclusion_reads_the_required_names_and_any_stopping_result` |
| 05 | Existing public start/round/check contracts establish ordinary execution; a direct no-skill/no-hook-prerequisite assertion is a gap to close as specified below. |
| 06 | `tests/steps/test_round_bound.py::test_running_tasks_count_towards_the_bound_and_a_full_one_reads_no_tracker`; the deleted host-power behavior needs the explicit boundary test below. |
| 07 | `tests/rules/test_policy.py::test_every_sql_write_has_its_one_owner`; `tests/steps/test_restart.py::test_compatible_restart_keeps_progress_sessions_and_reservation_and_reconciles_the_same_attempt`; `tests/cli/test_factory_restart.py::test_missing_or_unreadable_database_is_never_initialized` |
| 08 | `tests/steps/test_land_resume.py::test_a_held_release_is_retried_first_by_every_rerun_and_the_land_still_pushes`; `tests/steps/test_land_resume.py::test_a_crash_after_the_validation_before_the_push_pushes_on_the_rerun_without_checking_again`; `tests/steps/test_land_close.py::test_a_closed_land_is_already_landed_with_no_git_or_tracker_call` |
| 09 | `tests/steps/test_selection.py::test_every_scenario_of_the_contract`; `tests/steps/test_selection.py::test_missing_levels_pad_with_p2_to_the_deepest_chain`; `tests/steps/test_selection.py::test_the_non_transitive_trap_gives_one_total_order` |
| 10 | `tests/cli/test_cli.py::test_version_prints_the_running_package_version`; `tests/rules/test_policy.py::test_nothing_forks_execs_or_spawns` (process boundary only) |

For ADRs 05/06/10 add focused regression coverage after approval, reusing existing semantic fakes and policy
machinery. Proposed test names are not yet enforcing tests and must be labelled as proposed until passing:

- `tests/steps/test_decision_boundaries.py::test_normal_work_needs_no_skill_or_managed_hook_installation`:
  execute normal admission/advancement with an empty optional-helper environment and assert expected typed
  outcomes/effects without installing chat hooks or modifying the repo's hook configuration. Use the existing
  owning fakes; do not invent a skill service port just to test its absence.
- `tests/rules/test_decision_boundaries.py::test_factory_does_not_manage_host_power_or_ram_admission`:
  protect the concrete removed module/dependency paths and host-power/system-memory APIs using the existing
  AST policy approach, scoped to runtime source. Do not ban ordinary words in docs, forbid unrelated memory
  use, or treat lease renewal as power management. Pair it with the actual bound/admission behavior tests.
- Extend the public invalid-command parameter table for `install`, `pin`, `report`, `repo register`,
  `task create`, and slot `list/release/hold`, alongside the existing `plan` rejection. This enforces ADR 10's
  removed management commands and guards documentation's unimplemented-command claims.

If ADR 04's existing cases do not prove isolation from previous attempts, add
`tests/steps/test_checks.py::test_a_new_checks_attempt_runs_commands_despite_a_previous_pass` using stored
results and the existing fake command port. It must observe commands actually run, not just inspect a helper.
If the skill boundary cannot be expressed without a new runtime abstraction, use a narrow source contract
against the concrete retired hook/skill dependencies and state its limited coverage in the ADR instead.
No speculative runtime mechanism is justified by missing enforcement. Human approval/rationale remains
review evidence; a test cannot prove that the owner agreed.

## Sequence and verification

1. After the owner's yes, repeat the inventory/source check, then write the ten ADRs with the provenance and
   supersession distinctions above. Add source cross-links, status notes and README corrections.
2. Complete INDEX last so it includes every final path. Verify set equality, link targets and all document
   markers with a native read-only check. Keep any temporary checking code in memory; no extra tool/framework
   artifact is required. For specimen edits verify that only YAML comments changed, preserving parsed data
   and body byte-for-byte. Do not execute or install the historical prototype.
3. Add the bounded missing enforcement cases, verify every cited node exists and exercises the claim, and
   run those tests plus the existing cited behavior contracts. Avoid duplicate tests for already proven rules.
4. Read `justfile` again, run `just install`, and use the declared installed package via
   `uv run --frozen --no-sync python -I -m pytest ...` for the focused files. Render relevant CLI help with
   `uv run --frozen --no-sync python -I -m taskloop ...`; no unsupported command is made available.
5. Finish with required `just check` and `just test` gates as declared, with no historical whole-suite or live
   harness/tracker/process tests. Record exact sandbox failures if a gate cannot run; do not weaken the gate.
   Respect 400/80/800 caps and add no type escapes or runtime dependencies.

Implementation files are README, INDEX, the affected documentation/status/source-decision files under
`docs/design`, the ten ADRs here, and the narrowly justified test changes above. Update this plan with the
actual validation and changed-file inventory only after implementation; do not mark it built from planning.

## Acceptance

- Every file under the final design tree has its own inventory entry; discovered/indexed path sets match,
  local targets resolve and any displayed totals match. Every design document has an explicit status, including
  individual prototype specimens without schema changes; supporting artifacts have explicit index context.
- README agrees with implemented behavior. Historical/proposed command examples have clear scope markers,
  and held/unimplemented designs remain so. No production feature is implemented by this task.
- Ten ADRs cover the ten cited locations through the explicit eligibility/comparator split. Every record has
  decision provenance, consequences, current scope and precise enforcement tests, with supersession and any
  remaining coverage limits stated honestly. Source links point readers to the records.
- Keep-awake is not resurrected, `--accept-gate-changes` is not removed, no old STORE migration/fallback is
  authorized, and proposed layer judgments do not become accepted by association.
- Focused contracts and required gates have recorded results. Documentation and tests are reviewable before
  completion is claimed; implementation starts only on the owner's explicit yes.
