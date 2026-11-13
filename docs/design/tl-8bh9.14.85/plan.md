# Small-model leak audit

Status: **design**. Task: `tl-8bh9.14.85`. Prepared 2026-11-13 against
`fe14d0f3a7b6a50cab00fe2f3bed7ff9599d1ac4`.

Produce a reviewable list of backend, string and lifecycle details that a small model reading the current code
could misread or copy into new work. Each finding names the file, explains the misleading pattern and proposes a
bounded fix. The owner chooses which findings to repair. This task delivers the audit report; repair work remains
with the selected owning tasks.

## Evidence and execution prerequisite

The mandate is the supplied task description, originating in architecture-review session `local_16bd6c79`,
2026-11-13. Read these sources before the audit:

- [Grilling record](../architecture-review/grilling-record.md), especially the closed-vocabulary/backend rules,
  census findings and accepted version-control/harness decisions.
- [Decision register](../architecture-review/decision-register.md), especially the tracker, version-control,
  typed-output and adapter-explanation decisions, and the current repository `AGENTS.md` and `docs/glossary.md`.
- The session scratchpad's `architecture-review-20261113.html`. It was readable during planning at
  `/tmp/claude-501/-home-iorlas-Workspaces-iorlas-task-loop-b83c5d9a3f13cb9d-sleepy-nobel-d00460/b75c53f8-b204-48ba-bfee-a0095c237e4e/scratchpad/architecture-review-20261113.html`.
  Its candidate cards supply leads, not accepted decisions or current defect counts. Later accepted decisions
  and current instructions take precedence. If that temporary report disappears, record the missing evidence
  and use the retained grilling/register material; do not imply the original was rechecked.

Run the audit only after the task tracker's vocabulary and constitution prerequisites have settled and their
accepted changes are present in the checkout. Re-read their final requirements and artifacts before scanning.
Constitution task `tl-8bh9.14.81` has landed text in this revision; vocabulary task `tl-8bh9.14.112` has a separate
managed branch. Neither observation establishes all prerequisite task statuses. During planning, `bd show
tl-8bh9.14.85 --json` failed with `database not found: tl`; the complete dependency list could not be verified.
Recheck it through the owning tracker/actor when available, preserving existing claims. Do not start the full
audit or infer completion from a plan, historical implementation commit, comment or glossary definition alone.
This prerequisite does not prevent preparing this plan.

Record the exact audited Git revision and prerequisite evidence in the report. Revalidate the leads below at that
revision: vocabulary work may remove or relocate them. Historical census counts are context, not acceptance targets.

## Scope and method

Inventory production Python under `src/taskloop`, dashboard JavaScript, agent-facing prompts and schemas, CLI
help/messages, and active documentation that directs new code. Inspect tests, semantic fakes and architecture
contracts where they demonstrate or encourage a pattern. Historical design records and dependency source provide
context; their literal backend identifiers are not automatically current-code findings.

1. Map existing boundaries by responsibility: tracker translation, Git mechanics, harness/process access, stores,
   application operations and presentation. Current adapters are named modules, not necessarily an `adapters/`
   directory. Trace a suspect value from its originating adapter or edge through its consumers before classifying it.
2. Search imports, identifiers, comments, prompt strings, commands and error messages for backend product/tool names
   and types. Inspect error-text matching, backend error-kind branching, hard-coded harness selection and raw access
   flags outside their owner. Follow explanations into CLI/dashboard output: generic typed results need adapter-supplied
   explanations; raw diagnostics can remain attached detail rather than becoming workflow control or generic prose.
3. Inspect `Literal` declarations, repeated membership lists, literal comparisons, composite reason strings and their
   parsing. Identify which strings are closed vocabularies and where definitions/codecs compete. Trace storage and
   display encoding separately from in-process decisions. Open text, task IDs, paths, opaque session references,
   command arguments and correctly owned interchange formats are not closed vocabularies merely because they are strings.
4. Follow task, step, attempt, session, entry process, agent process, claim, reservation and release through representative
   admission, launch, collection, verification, checks, repeat/relaunch, publication and land paths. Check that phase,
   status, conclusion, verdict and disposition retain their settled meanings. Explain an actual ambiguity or unsafe
   inference, such as confusing a collected result with success or publication with capture; a word search is only a lead.
5. Inspect current enforcement and tests for each confirmed finding. Record the gap and the smallest useful contract
   or behavior check a later repair needs. Cross-reference existing owning tasks so already planned work is visible
   without treating its plan as a repair or duplicating it here.

The glossary permits domain words such as commit, branch and merge. Backend tool names and commands remain adapter
details even when only one backend is enabled. Library types inside their owning adapters and intentional edge
encodings are legitimate. Read apparent exceptions in context and record why important search hits were excluded.
Do not introduce new domain terms: propose options and reasons for an owner decision if a fix would require one.

## Current leads to recheck

These examples establish that the audit is actionable; they are not a completed or exhaustive audit.

| Location at the planning revision | Lead and proposed direction |
|---|---|
| `src/taskloop/admit.py` (`BdError`, `NOT_CLAIMED`) | Admission knows backend error kinds and uncertain claim effects. Evaluate generic typed claim results supplied by the tracker adapter, preserving reconciliation and uncertain-claim safety. |
| `src/taskloop/hold.py` and `src/taskloop/step_render.py` | A hold explanation names `bd`; the release renderer constructs `bd show`. Evaluate adapter-owned explanations carried through generic results. |
| `src/taskloop/claim_lease.py` | Renewal timing/comments embed backend version and timeout assumptions. Determine which policy is generic and which timing guarantees belong to the adapter; preserve lease-loss and shutdown behavior. |
| `src/taskloop/attempt_result.py` and `src/taskloop/check_status.py` | Composite reason strings and literal lifecycle words feed results and success decisions. Check remaining ownership after vocabulary work and propose typed distinctions with encoding at the edge. |
| `src/taskloop/attempt_types.py` and `src/taskloop/attempt.py` | Shared contracts expose library types; execution selects a concrete harness. Trace the actual boundary before proposing factory-owned contracts or adapter configuration. |
| `src/taskloop/dash_model.py`, `src/taskloop/dash_task.py`, prompts and dashboard scripts | Backend wording and lifecycle labels can teach consumers the wrong abstraction. Compare them with settled terminology and observable behavior. |

`tests/rules/test_policy.py` currently limits construction/import of `Bd` to `tracker_client.py`; that narrow test
does not confine `BdError` or backend text. `.importlinter` has process, entry, step and profile boundaries, but no
general rule confining all backend names/types to adapters. Reinspect both after the prerequisites settle rather
than assuming either the present gap or a proposed architecture contract still applies.

## Deliverable and validation

Write `docs/design/tl-8bh9.14.85/report.md`, with status **evidence**, the audited revision, scope, sources,
prerequisite checks and any coverage limitations. Give every confirmed leak:

- A current file path, line number, symbol and short excerpt or reproducible search.
- The specific misreading or copyable pattern, traced producer/consumer boundary, and violated accepted rule.
- A concrete bounded fix, its owning module/adapter, affected callers and suggested focused verification. Preserve
  behavior and state ownership; identify any schema/lifecycle consequence rather than disguising it as a rename.
- Any existing task covering the repair and any decision the owner must make. Leave repair selection explicitly pending.

Group repeated occurrences only when the owner and fix are the same, listing the affected files. Distinguish
confirmed leaks from unresolved questions; include significant exclusions and reasons. Report honest coverage,
not a claim that a keyword scan proves the absence of leaks. No small-model benchmark or new audit framework is needed.

Have an independent reader check the findings against the audited source and accepted decisions. Verify file/line
references, links, proposed fixes, coverage and existing-task overlap. Review the final diff for documentation-only
scope. Do not change production code, tests, dependencies, glossary or instruction files, or create repair tasks
before the owner selects them. Audit artifacts stay under this task's design directory; retain no temporary scans.

This documentation-only audit requires no runtime changes or test run. Later selected repairs carry their own
focused tests and the repository's required `just check` and `just test` gates, with `justfile` read first and no
historical whole-suite/live runs. Completion here means a source-checked file-and-fix list is ready for owner choice,
not that its proposed fixes have been implemented.
