# Depth

Small: one audit produces a file-and-fix report in this task's documentation directory;
backend, string and lifecycle leaks are dimensions of the report, not separate runtime
behaviours. No missing owner decision or explicitly unlanded dependency is stated.
Evidence budget: 6 model calls total for planning. Repair selection follows the report
and does not prevent preparing it.

## Size

- Estimated changed files: 2, including this revised plan and new `report.md`; no source,
  test, dependency, schema, glossary or instruction-file changes.
- Independent behaviours: 1, delivery of an evidence report. Acceptance: at the recorded
  revision, every confirmed leak names an existing file and line, demonstrates a misleading
  producer-to-consumer pattern, cites an effective rule, and proposes a bounded fix with
  its owning module, affected callers and focused verification. The report addresses all
  three requested dimensions, records exclusions and coverage limits, and leaves repair
  selection pending. A keyword hit without a traced misreading is not a confirmed leak.
- Estimated model calls for one implement attempt: 70, including discovery, tracing,
  writing and a second verification pass. This is distinct from the planning evidence budget.

Task: `tl-8bh9.14.85`. Status: design. Revised 2026-11-14 against
`cf7f10f90acb93dbb84601211c2bb5ee6d86797f` in its assigned managed worktree.

## Current evidence and prerequisites

The supplied task and discussion are the complete requirements. Tracker access is unavailable
by instruction; do not invoke `bd`, reconstruct tracker state, or repeat the previous attempt's
requirement to restore tracker access. This revision supersedes the old plan; no audit is
claimed complete.

The effective constitution is the supplied AGENTS.md, including backend isolation, closed
vocabulary, lifecycle, ownership and naming rules. Historical grilling/register proposals
remain proposals where they conflict with current instructions, including CLAUDE.md mirroring,
alternate scheduler names and configuration arrangements.

Vocabulary prerequisite `tl-8bh9.14.112` now has an implemented artifact in this checkout.
Its accepted scope is canonical command conclusions and an ID port; step and claim vocabularies
are separate follow-ups. `command_conclusion.py` contains the enum and edge codec. Audit
remaining literals against that bounded settlement; do not demand every deferred migration
finish first. These are local artifact/source observations, not queried task status. The
supplied constitution and implemented vocabulary scope provide the baseline. Describe any
actual conflicting requirement discovered later, rather than treating lack of tracker access
as an owner decision.

The old scratchpad path is no longer readable:
`/tmp/claude-501/-home-iorlas-Workspaces-iorlas-task-loop-b83c5d9a3f13cb9d-sleepy-nobel-d00460/b75c53f8-b204-48ba-bfee-a0095c237e4e/scratchpad/architecture-review-20261113.html`.
Record this limitation and use the retained grilling record/register. Do not imply the HTML
report was reviewed or search other session data to reconstruct it.

The worktree was initially clean. History inspection found no WIP trailer for this task.
The visible trailer embedded in `78696b90` belongs to integrated task `.160`; that commit
has no changes under this task's directory. Preserve its agent settings.

## Read list

- `docs/design/tl-8bh9.14.85/plan.md:1-23` — report scope and independently testable acceptance.
- `docs/design/architecture-review/grilling-record.md:6-113` — original accepted rules and subsequent decisions; distinguish proposals.
- `docs/design/architecture-review/decision-register.md:66-116` — tracker, Git, harness and vocabulary decisions.
- `docs/design/tl-8bh9.14.112/plan.md:1-24` — settled vocabulary scope and deferred migrations.
- `docs/design/tl-8bh9.14.112/plan.md:177-208` — implemented prerequisite evidence and handoff boundaries.
- `docs/glossary.md:98-143` — missing lifecycle definitions, claims, reservations and holds; supplied definitions remain primary.
- `src/taskloop/command_conclusion.py:1-47` — canonical vocabulary and codec; legitimate edge strings.
- `src/taskloop/tracker.py:1-42` — task facts and error boundary consumed by application operations.
- `src/taskloop/tracker_client.py:1-90` — originating backend contracts in the concrete tracker adapter.
- `src/taskloop/admit.py:210-270` — claim call, backend error branching and uncertain-effect handling.
- `src/taskloop/hold.py:155-181` — label-failure messages and backend wording outside the adapter.
- `src/taskloop/step_render.py:130-187` — release/status presentation and actionable consumer messages.
- `src/taskloop/claim_lease.py:1-38` — backend timing assumptions and lease renewal inputs.
- `src/taskloop/attempt_result.py:1-54` — composite reasons, result construction and success predicate.
- `src/taskloop/check_status.py:1-57` — check-result producer and shared attempt-result consumer contract.
- `src/taskloop/attempt_types.py:275-340` — session capture, collection and disposition contracts.
- `src/taskloop/attempt.py:180-306` — launch/collection callers and answer-to-verification lifecycle.
- `src/taskloop/agents/launch.py:1-122` — harness translation and settings consumers; establish adapter ownership first.
- `src/taskloop/agents/settings.py:107-174` — harness/settings model and policy encoding boundary.
- `src/taskloop/step_guide.py:1-80` — agent-facing instructions that could teach a copyable pattern.
- `src/taskloop/dash_model.py:163-240` — attempt/session read models and dashboard-facing contracts.
- `src/taskloop/dash/static/words.js:1-69` — dashboard lifecycle words and displayed meanings.
- `tests/rules/test_policy.py:226-241` — current backend import enforcement and its limits.
- `.importlinter:123-159` — mechanism, lock, signal and step ownership contracts.
- `tests/steps/test_admit.py:322-399` — semantic evidence for claim uncertainty and effect preservation.

## Implementation

Create **new** `docs/design/tl-8bh9.14.85/report.md`; this plan is its documentation
integration point. The listed producers, callers, presentation models and contracts are
existing integration points for findings. No runtime registration or audit framework is needed.

1. Record the exact audited revision, effective instructions, prerequisite observations,
   retained review sources and missing scratchpad. Apply supplied glossary definitions;
   collect missing terms into at most one targeted glossary read. Introduce no terms.
2. Inventory production Python, dashboard JavaScript and agent-facing text using bounded
   searches for backend identifiers, Literal declarations, repeated comparisons, composite
   reasons/parsing and lifecycle words. Active documentation supplies context; historical
   proposals and correctly owned interchange are not defects by default. Additional targeted
   searches may identify missed producers/callers or changed source. Follow concrete matches
   rather than reading every module or dependency package.
3. Trace candidates through tracker/admission, lease, attempt, check and presentation paths.
   Distinguish backend mechanisms from defined domain words, closed vocabulary from open
   text, and collection from verified success. Establish harness adapter ownership before
   classifying library types or configuration as leaks. Preserve uncertain claims, explicit
   holds, reconciliation and session capture in proposed fixes. Publication is not capture
   or task completion.
4. Group repeated occurrences only when the owner and fix coincide, listing affected files.
   Each confirmed group needs file:line, symbol, short excerpt, producer/caller trace,
   actual small-model misreading, effective rule, bounded fix, owning module and focused
   verification. Flag schema/lifecycle consequences explicitly. Note repair-task overlap
   only from supplied or inspected artifacts; unknown ownership remains unknown. Separate
   unresolved leads, exclusions and unreviewed coverage from confirmed findings.
5. Recheck each finding against source in a separate reading pass, including line references,
   ownership and caller consequences. Ensure all three audit dimensions are addressed and
   leave a selectable file-and-fix list. Do not implement repairs or create repair tasks.

## Validation and completion

Validate Read-list paths/ranges and final report references; review the documentation diff
and Git status. Report coverage honestly: representative traces do not prove absence of
other leaks. Missing historical evidence remains an explicit limitation. Keep only the plan
and report under this task's directory; retain no temporary scans.

This documentation-only result needs no runtime tests or whole-suite/live checks. Available
implementation gates are `just check` and `just test`; selected repair tasks carry their
focused behaviour/contract tests and required gates. Completion means the verified report
meets the acceptance criterion and is ready for owner selection, with repairs still pending.
