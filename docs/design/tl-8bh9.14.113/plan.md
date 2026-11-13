# Docs and CLI consistency

Status: **design**. Proposed implementation plan, prepared 2026-11-13 against
`521597c90645e397edf5bcf4e47284f403600b70`. This document does not authorize implementation or assert completion.
Task: `tl-8bh9.14.113`.

The result should be an accurate README, explicit status on retained design documents, one owner of application
exit policy, and CLI behavior tests for the reported flags. This attempt changes only this plan. Implementation
waits for the owner's yes.

## Current evidence and interpretation

The task cites the 16 read-only censuses from session `local_16bd6c79` on 2026-11-13. The repository's
[architecture review record](../architecture-review/grilling-record.md) retains the review summary. The evidence
below comes from direct source inspection; recheck claims rather than treating the original counts as an
acceptance target.

| Reported concern | Current tree and consequence |
|---|---|
| README says features are unbuilt | Its opening denies checks, land, holds and dashboard; its closing paragraph says the factory does not execute checks. Current code implements these. Review remains unbuilt. |
| 17 design documents lack status | Before adding this plan, the inventory contained 135 Markdown files below `docs/design`, including 40 plans and 19 flat documents. Fifteen flat documents lack an introductory explicit status marker. Other headers and the index contradict appended as-built sections. Inventory the current documents; do not manufacture a set of 17. |
| Designs name unimplemented commands | Some describe the baseline, proposals or superseded CLI names such as `tl plan`. Those records need context and current links; their historical examples must retain their meaning. |
| Checkout has four forms | `repo inspect PATH` and `slot adopt CHECKOUT` use positionals; `profile show --checkout` defaults to `.`; `step start/next/rounds/land --checkout` is required. The glossary incorrectly lists `slot adopt` under `--checkout`. |
| Exit 3 has different descriptions | `profile.Unavailable` means no verdict was possible and another read is safe. Steps use 3 for unknown results. These can share a documented retry-safe interpretation without reclassifying existing results. |
| `rounds --json` emits two documents | `tests/cli/test_step_cli.py` deliberately asserts a start record and an end record, one JSON object per line. With a dashboard, `cli_step._rounds` additionally prints an unstructured URL on stdout. |
| Four flags lack CLI tests | `--dash-port`, explicit `--count`, and `--retake-lapsed` need CLI coverage. `--max-new` no longer exists; the current option is `--max-running`. |

The removal of `--max-new` is an existing decision, recorded in
[the land plan's intake section](../tl-8bh9.14.8/plan.md#rounds-intake-and-the-land-title-tl-8bh91476-tl-8bh91473).
Cover its rejection and the replacement's actual behavior; do not restore it or add an alias. This makes the
reported flag concern actionable on the current code without reversing the owner’s decision.

## 1. Make current documentation accurate

Update `README.md` from the registered parsers and implemented use cases, not from old plans. Describe:

- Plan, implement and checks, including the factory running the profile's checks and setup.
- `tl step land` as the person's explicit delivery command, with rounds stopping before land. Publishing a task
  branch is distinct from landing it; do not claim rounds merge or land automatically.
- Holds and their existing answer/reapproval flow, and the optional dashboard served by
  `tl step rounds --dash-port PORT` for the lifetime of rounds. Without the flag nothing is served; 0 selects a port.
- Review as future work. Keep other limitations tied to the current implementation rather than claiming the
  entire target factory or all preserved designs are built.

Check the remaining README claims while editing, including its pinned library descriptions against
`pyproject.toml` and `uv.lock`. Prefer links to the dependency declaration over a second hand-maintained version
list. Use the installed-module invocation from `AGENTS.md` for executable examples.

Correct the CLI flag table in `docs/glossary.md`, including land's checkout/tracker context, and document the four
checkout forms above. Preserve their current syntax and required/default behavior. Add the current scheduling
and dashboard flags if absent. These are corrections to existing descriptions, not new glossary terms.

## 2. Put status at each design document's entry

Inventory Markdown documents recursively under `docs/design`. Inspect existing headers before adding one;
an existing accurate marker need not be reformatted. Every retained human-facing design document should identify
its scope near its title, using the existing index concepts **built**, **design**, and **evidence**. Mixed documents state which portions
are built and point to the relevant as-built sections. A proposed or accepted design alone is not evidence of code.
Use ordinary explanatory prose for historical records, partial implementation and runbooks rather than a new
machine-readable status vocabulary.

The known flat documents missing an explicit marker are `execution-terms.md`, `merge-queue.md`, `roadmap.md`,
`self-hosting-roadmap.md`, `self-hosting-real-run-1.md`, `self-hosting-trial.md`, `self-hosting-trial-2.md`,
`self-hosting-trial-3.md`, `self-hosting-trial-4.md`, `self-hosting-trial-5.md`, `self-hosting-trial-5-fixes.md`,
`self-hosting-trial-6.md`, `slot-grant.md`, `slots-carve.md`, and `sqlite-store-plan.md`. The recursive inventory also
includes task plans, runbooks, findings, architecture review material and prototype collections. Mark prototypes
and alternatives as design/evidence at their collection entry, never as current operator instructions merely
because their examples contain commands. Preserve schema-bearing specimens, including frontmatter-only files
inside `architecture-review/docscheck-proto/docs`; add context to the prototype's report/entry rather than altering
the specimen contents.

For retained documents naming commands absent from the current parser, make the header say whether they are
proposed or historical, and link to the current README/help or the design that superseded them. Preserve dated
decisions, evidence and original examples; do not mechanically rewrite a historical `tl plan` example to `tl step`.
Current operator instructions must use implemented commands.

Reconcile `docs/design/INDEX.md` with this inventory. In particular, checks S6e is built, the M4 smoke has recorded
findings, and the current dashboard documentation and missing task folders need entries. Distinguish partial
implementation from completed milestones. Correct the misleading opening headers in the checks, land and holds
plans without erasing their original proposal sections. Clarify in `docs/design/dashboard/README.md` that it
describes the historical dashboard design, and link to `../dashboard-ui.md` for the built slice.

This is a metadata and accuracy pass. No document relocation, new documentation framework, prototype adoption,
generated task state, or inference of completion from tracker closure belongs here.

## 3. Give exit policy one owner

Keep `src/taskloop/exit_codes.py` as the sole owner of application CLI exit values and result classification.
Define the closed set with a stdlib integer enum there, and make its existing result mapper return those members.
Keep the current result types and add a typed mapper for `profile.Resolved | profile.Refused | profile.Unavailable`.
Have `cli.py` use the shared values/mappers for task/repo inspection, profiles, version and root help;
`cli_step.py` continues to use the result mapper. Do not construct a synthetic step failure to map a profile,
introduce a generic operation hierarchy, or convert typed results through JSON.

Preserve current observable codes and stream routing:

| Code | Existing command contract |
|---|---|
| 0 | Success/already complete; also a graceful rounds stop. |
| 1 | Existing refusals and task/repo inspection failures. Task/repo inspection errors remain 1 even when the adapter reports an unavailable read. |
| 2 | Invalid CLI syntax, supplied by argparse. Keep argparse's own behavior. |
| 3 | No reliable result: profile unavailable, or a step result classified as unknown by the existing policy; retry is safe. Preserve the current single-round aggregation rules. |
| 130 | Abrupt rounds stop or interrupted land, with existing reconciliation behavior. |

Remove literal application exit assignments/returns from `cli.py`, including its hard-coded 1 and 3. Document
the shared interpretation of 3 and the command-specific distinctions in current CLI documentation/help, without
promising that every unavailable backend error has the same code. Keep existing operation explanations and
interruption handling. The legacy parsing of step display words inside the existing mapper is outside this slice;
do not add another parser or broaden it to classify inspection/profile errors.

## 4. Specify structured output and test the flags through the CLI

Document `step rounds --json` as JSON Lines, retaining the existing start/end record shapes. A normal graceful
session has two stdout records; an early refusal or abrupt ending retains its existing stderr result behavior.
Move the dashboard address notice to stderr when JSON output is selected so every nonempty stdout line remains
JSON. Human output keeps its current notice. A dashboard startup failure remains a warning on stderr and does
not stop rounds. No new output envelope or event kind is needed.

Add focused pytest CLI tests, using `main(argv)`, captured streams and typed semantic fakes at the existing
composition/operation boundaries. Assert user-visible results and the actual requests reaching those boundaries.
Do not launch a harness, create a real listener, spawn a process, or exercise a live tracker for these tests.

| Flag/surface | Required behavior coverage |
|---|---|
| `step rounds --dash-port` | Omission yields no dashboard request; 0 and an explicit positive port reach the serving context with the selected backlog, tracker, label, DB and artifacts. The context encloses rounds execution and closes on exit. A failed startup warns but rounds run and determine the exit. JSON stdout contains only the existing records, with the URL on stderr. |
| `config show --count` and `slot adopt --count` | An explicit count overrides the config value and reaches effective settings/adoption. Omission retains the configured/default value. Invalid numeric bounds refuse before adoption; a noninteger is a usage error. |
| `step next/rounds --max-new` | Reject the removed flag with usage exit 2 before opening execution ports. Pair this with `--max-running` default 3 and explicit-value forwarding on both commands, including the rounds start record. Existing scheduler tests retain ownership of scheduling semantics. |
| `step next/rounds --retake-lapsed` | Omission passes false and the flag passes true in `NextRequest.retake` on both surfaces. Preserve the existing recovery-only warning/help and round announcement. Existing recovery tests own lease and tracker effects. |

Retain and extend existing public CLI tests to demonstrate profile success/refusal/unavailable and representative
step/land/round exit behavior after centralization, in human and structured modes where routing matters. Existing
task/repo failure tests protect their unchanged mapping. Verify checkout examples/defaults against existing parser
tests; add a missing public contract case only where needed to support the corrected table.

Put new flag scenarios in `tests/cli/test_cli_flags.py` or small files split by command. The existing
`tests/cli/test_step_cli.py` is close to the 800-line cap; do not exceed it or copy its entire bootstrap. Reuse
owning fakes and small typed fixtures without importing another test module or testing private helpers directly.

## Implementation order and verification

1. Recheck the parser, source and document inventory at implementation time, then update current docs and markers.
2. Centralize exits while retaining existing public result behavior.
3. Add the flag scenarios and keep JSON stdout structured when the dashboard is enabled.
4. Run focused tests, then the required gates, and review documentation against the resulting CLI/help.

Expected source scope is `src/taskloop/exit_codes.py`, `src/taskloop/cli.py`, and `src/taskloop/cli_step.py`.
Tests stay under `tests/cli` with existing focused step contracts reused for verification. Documentation scope is
the README, glossary CLI descriptions and the design status/index pass above. No application schema, scheduling,
claim recovery, Git action or dashboard domain behavior changes are needed. The separately recorded future
`--format`/CLI-library migration remains separate.

Before validation, read `justfile` and run `just install`. Run the affected CLI tests and representative existing
step/round/land exit contracts with `uv run --frozen --no-sync python -I -m pytest ...`; invoke CLI help through
`uv run --frozen --no-sync python -I -m taskloop ...`. Finish with `just check` and `just test`, the repository's
declared focused successor gates. Do not run historical whole-suite or live tests. Keep the source/function/test
caps and add no `Any`, casts, ignores, runtime dependencies or process escape hatches.

Review all README command examples and links, the status inventory and index consistency, plus searches for
application exit literals in CLI modules. Review historical command mentions in context rather than demanding
their deletion. No additional documentation enforcement tool or test for every header is required.

## Acceptance

- README capabilities and examples match the implemented CLI, including checks, explicit land, holds and the
  optional dashboard; review and other remaining gaps are accurately described.
- Design documents have accurate introductory status/scope, historical or proposed commands cannot be mistaken
  for current instructions, and INDEX/current dashboard links agree with the recorded implementation evidence.
- The checkout table matches all four existing forms. `--max-new` stays removed and `--max-running` is documented.
- Application exit values/classification have one owner, with no observable numeric reclassification and tests
  protecting profile, inspection, step, rounds and land behavior.
- The four reported flag concerns have CLI behavior coverage as specified above. Dashboard-enabled JSON output
  remains JSON Lines with the current record shapes.
- Required focused gates pass. No implementation is claimed from this plan alone.
